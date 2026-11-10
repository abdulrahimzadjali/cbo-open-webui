// CBO Prompt Guardian API client.
//
// Kept in its own module (not src/lib/apis/configs) so the upstream API client
// file stays untouched and `git merge upstream/main` has nothing to conflict
// with here.

import { WEBUI_API_BASE_URL } from '$lib/constants';

const BASE = `${WEBUI_API_BASE_URL}/cbo/guardian`;

export type GuardianDomain = {
	id: string;
	label_en: string;
	label_ar: string;
	terms_en: string[];
	terms_ar: string[];
};

export type GuardianConfig = {
	enabled: boolean;
	enforce: boolean;
	shadow: boolean;
	fail_open: boolean;
	max_chars: number;
	strict_scope: boolean;
	enable_classifiers: boolean;
	disabled_rules: string[];
	blocklist: string[];
	domains: GuardianDomain[] | null;
	injection_model_path: string;
	injection_threshold: number;
	harm_model_path: string;
	harm_threshold: number;
	bypass_roles: string[];
	block_message_en: string;
	block_message_ar: string;
};

export type GuardianRule = {
	id: string;
	category: string;
	description: string;
	pattern: string;
};

export type GuardianTestResult = {
	decision: {
		verdict: { action: string; category: string | null; layer: number | null; score: number; rule: string | null; detail: string };
		shadow: boolean;
		degraded: boolean;
		blocked: boolean;
		trace: Array<Record<string, unknown>>;
	};
	signals: Record<string, boolean>;
	language: 'ar' | 'en';
	scope_matches: string[];
	would_block: boolean;
	enforced: boolean;
	message: string;
};

const request = async (token: string, path: string, init: RequestInit = {}) => {
	let error = null;

	const res = await fetch(`${BASE}${path}`, {
		...init,
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`,
			...(init.headers ?? {})
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err?.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getGuardianConfig = async (token: string): Promise<GuardianConfig | null> =>
	request(token, '/config');

export const setGuardianConfig = async (token: string, config: GuardianConfig): Promise<GuardianConfig | null> =>
	request(token, '/config', {
		method: 'POST',
		body: JSON.stringify(config)
	});

export const getGuardianRules = async (
	token: string
): Promise<{ rules: GuardianRule[]; domains: GuardianDomain[] } | null> => request(token, '/rules');

export const testGuardianPrompt = async (
	token: string,
	prompt: string
): Promise<GuardianTestResult | null> =>
	request(token, '/test', {
		method: 'POST',
		body: JSON.stringify({ prompt })
	});

export const getGuardianStats = async (
	token: string
): Promise<{ since: number; counters: Record<string, number> } | null> => request(token, '/stats');
