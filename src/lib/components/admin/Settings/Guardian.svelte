<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Switch from '$lib/components/common/Switch.svelte';
	import AdminSettingField from './AdminSettingField.svelte';
	import AdminSettingRow from './AdminSettingRow.svelte';
	import AdminSettingSection from './AdminSettingSection.svelte';

	import {
		getGuardianConfig,
		setGuardianConfig,
		getGuardianRules,
		testGuardianPrompt,
		type GuardianConfig,
		type GuardianRule,
		type GuardianTestResult
	} from '$lib/apis/cbo/guardian';

	const i18n: any = getContext('i18n');

	export let saveHandler: Function = () => {};

	let config: GuardianConfig | null = null;
	let rules: GuardianRule[] = [];
	let defaultDomains: any[] = [];

	let blocklistText = '';
	let disabledRules: string[] = [];

	let testPrompt = '';
	let testResult: GuardianTestResult | null = null;
	let testing = false;

	const inputClass =
		'w-full h-7 rounded-lg border border-gray-100/50 bg-gray-50/40 px-2 text-xs text-gray-700 outline-hidden transition-colors placeholder:text-gray-300 focus:border-blue-400 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:placeholder:text-gray-700 dark:focus:border-blue-500';
	const textareaClass =
		'w-full rounded-lg border border-gray-100/50 bg-gray-50/40 px-2 py-1.5 text-xs text-gray-700 outline-hidden transition-colors placeholder:text-gray-300 focus:border-blue-400 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:placeholder:text-gray-700 dark:focus:border-blue-500';

	// FastAPI returns a string detail for HTTPException and a list of
	// {loc, msg} objects for request validation errors (e.g. a threshold > 1).
	const errorText = (error: any): string => {
		if (Array.isArray(error)) {
			return error
				.map((item) => {
					const field = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : '';
					return field ? `${field}: ${item?.msg ?? item}` : `${item?.msg ?? item}`;
				})
				.join('; ');
		}
		return typeof error === 'string' ? error : JSON.stringify(error);
	};

	const load = async () => {
		try {
			const res = await getGuardianConfig(localStorage.token);
			if (res) {
				config = res;
				blocklistText = (res.blocklist ?? []).join('\n');
				disabledRules = res.disabled_rules ?? [];
			}

			const catalogue = await getGuardianRules(localStorage.token);
			if (catalogue) {
				rules = catalogue.rules ?? [];
				defaultDomains = catalogue.domains ?? [];
			}
		} catch (error) {
			toast.error(errorText(error));
		}
	};

	/** Returns true only when the backend accepted the new configuration. */
	const submitHandler = async (): Promise<boolean> => {
		if (!config) return false;
		const payload: GuardianConfig = {
			...config,
			blocklist: blocklistText
				.split('\n')
				.map((line) => line.trim())
				.filter(Boolean),
			disabled_rules: disabledRules
		};
		try {
			const res = await setGuardianConfig(localStorage.token, payload);
			if (!res) return false;
			config = res;
			blocklistText = (res.blocklist ?? []).join('\n');
			disabledRules = res.disabled_rules ?? [];
			return true;
		} catch (error) {
			toast.error(errorText(error));
			return false;
		}
	};

	const runTest = async () => {
		if (!testPrompt.trim()) return;
		testing = true;
		try {
			testResult = await testGuardianPrompt(localStorage.token, testPrompt);
		} catch (error) {
			toast.error(errorText(error));
		} finally {
			testing = false;
		}
	};

	const restoreDefaultDomains = () => {
		if (config) {
			config.domains = null;
		}
	};

	const toggleRule = (id: string, enabled: boolean) => {
		disabledRules = enabled ? disabledRules.filter((r) => r !== id) : [...disabledRules, id];
	};

	onMount(load);
</script>

<form
	class="flex h-full flex-col justify-between text-sm"
	on:submit|preventDefault={async () => {
		// saveHandler (SettingsModal) shows the success toast; only call it
		// when the save actually succeeded.
		if (await submitHandler()) {
			saveHandler();
		}
	}}
>
	<h2 class="text-sm font-medium text-gray-900 dark:text-white mb-4">
		{$i18n.t('settings.admin.guardian.title')}
	</h2>

	<div class="flex-1 min-h-0 overflow-y-auto scrollbar-hover pr-1.5">
		{#if config}
			<AdminSettingSection title={$i18n.t('settings.admin.guardian.sections.rollout.title')} first>
				<AdminSettingRow
					label={$i18n.t('settings.admin.guardian.enable.label')}
					description={$i18n.t('settings.admin.guardian.enable.description')}
					let:labelId
				>
					<Switch bind:state={config.enabled} ariaLabelledbyId={labelId} />
				</AdminSettingRow>

				{#if config.enabled}
					<AdminSettingRow
						label={$i18n.t('settings.admin.guardian.shadow.label')}
						description={$i18n.t(
							'settings.admin.guardian.shadow.description'
						)}
						let:labelId
					>
						<Switch bind:state={config.shadow} ariaLabelledbyId={labelId} />
					</AdminSettingRow>

					{#if config.shadow}
						<div
							class="rounded-lg border border-amber-200/60 bg-amber-50/60 px-2.5 py-2 text-[0.6875rem] text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300"
						>
							{$i18n.t(
								'Shadow mode is on: prompts are evaluated and logged, but nothing is blocked. Use this to measure false positives before enforcing.'
							)}
						</div>
					{/if}

					<AdminSettingRow
						label={$i18n.t('settings.admin.guardian.failOpen.label')}
						description={$i18n.t('settings.admin.guardian.failOpen.description')}
						let:labelId
					>
						<Switch bind:state={config.fail_open} ariaLabelledbyId={labelId} />
					</AdminSettingRow>
				{/if}
			</AdminSettingSection>

			{#if config.enabled}
				<AdminSettingSection title={$i18n.t('settings.admin.guardian.sections.rules.title')}>
					<AdminSettingField
						label={$i18n.t('settings.admin.guardian.maxChars.label')}
						description={$i18n.t('settings.admin.guardian.maxChars.description')}
					>
						<input
							type="number"
							min="500"
							max="200000"
							required
							class={inputClass}
							bind:value={config.max_chars}
						/>
					</AdminSettingField>

					<AdminSettingField
						label={$i18n.t('settings.admin.guardian.blocklist.label')}
						description={$i18n.t('settings.admin.guardian.blocklist.description')}
					>
						<textarea rows="4" class={textareaClass} bind:value={blocklistText}
						></textarea>
					</AdminSettingField>

					<AdminSettingField
						label={$i18n.t('settings.admin.guardian.bypassRoles.label')}
						description={$i18n.t('settings.admin.guardian.bypassRoles.description')}
					>
						<Switch
							state={config.bypass_roles.includes('admin')}
							on:change={(e) =>
								(config.bypass_roles = e.detail
									? [...config.bypass_roles.filter((r) => r !== 'admin'), 'admin']
									: config.bypass_roles.filter((r) => r !== 'admin'))}
						/>
					</AdminSettingField>
				</AdminSettingSection>

				<AdminSettingSection title={$i18n.t('settings.admin.guardian.sections.builtinRules.title')}>
					<p class="-mt-1 text-[0.6875rem] text-gray-400 dark:text-gray-600">
						{$i18n.t(
							'Deterministic bilingual rules. Every rule is high-precision: it only matches phrases with no legitimate business reading.'
						)}
					</p>
					{#each rules as rule (rule.id)}
						<AdminSettingRow
							label={rule.id}
							description={rule.description}
							let:labelId
						>
							<Switch
								state={!disabledRules.includes(rule.id)}
								on:change={(e) => toggleRule(rule.id, e.detail)}
								ariaLabelledbyId={labelId}
							/>
						</AdminSettingRow>
					{/each}
				</AdminSettingSection>

				<AdminSettingSection title={$i18n.t('settings.admin.guardian.sections.scope.title')}>
					<AdminSettingRow
						label={$i18n.t('settings.admin.guardian.strictScope.label')}
						description={$i18n.t('settings.admin.guardian.strictScope.description')}
						let:labelId
					>
						<Switch bind:state={config.strict_scope} ariaLabelledbyId={labelId} />
					</AdminSettingRow>

					<AdminSettingField
						label={$i18n.t('settings.admin.guardian.domains.label')}
						description={$i18n.t('settings.admin.guardian.domains.description')}
					>
						<button
							type="button"
							class="text-xs text-gray-500 underline hover:text-gray-900 dark:text-gray-400 dark:hover:text-white"
							on:click={restoreDefaultDomains}
						>
							{$i18n.t('Restore built-in CBO domains')}
						</button>
					</AdminSettingField>

					{#if defaultDomains.length}
						<div
							class="rounded-lg bg-gray-50/60 px-2.5 py-2 text-[0.6875rem] text-gray-500 dark:bg-white/[0.03] dark:text-gray-400"
						>
							{#each defaultDomains as domain (domain.id)}
								<div class="py-0.5">
									<span class="font-medium text-gray-700 dark:text-gray-200"
										>{domain.label_en}</span
									>
									<span dir="rtl" class="ms-1">— {domain.label_ar}</span>
								</div>
							{/each}
						</div>
					{/if}
				</AdminSettingSection>

				<AdminSettingSection title={$i18n.t('settings.admin.guardian.sections.classifiers.title')}>
					<AdminSettingRow
						label={$i18n.t('settings.admin.guardian.enableClassifiers.label')}
						description={$i18n.t('settings.admin.guardian.enableClassifiers.description')}
						let:labelId
					>
						<Switch bind:state={config.enable_classifiers} ariaLabelledbyId={labelId} />
					</AdminSettingRow>

					{#if config.enable_classifiers}
						<AdminSettingField
							label={$i18n.t('settings.admin.guardian.injectionModel.label')}
							description={$i18n.t('settings.admin.guardian.injectionModel.description')}
						>
							<input class={inputClass} bind:value={config.injection_model_path} />
						</AdminSettingField>

						<AdminSettingField
							label={$i18n.t('settings.admin.guardian.injectionThreshold.label')}
							description={$i18n.t('settings.admin.guardian.injectionThreshold.description')}
						>
							<input
								type="number"
								step="0.01"
								min="0"
								max="1"
								class={inputClass}
								bind:value={config.injection_threshold}
							/>
						</AdminSettingField>

						<AdminSettingField
							label={$i18n.t('settings.admin.guardian.harmModel.label')}
							description={$i18n.t('settings.admin.guardian.harmModel.description')}
						>
							<input class={inputClass} bind:value={config.harm_model_path} />
						</AdminSettingField>

						<AdminSettingField
							label={$i18n.t('settings.admin.guardian.harmThreshold.label')}
							description={$i18n.t('settings.admin.guardian.harmThreshold.description')}
						>
							<input
								type="number"
								step="0.01"
								min="0"
								max="1"
								class={inputClass}
								bind:value={config.harm_threshold}
							/>
						</AdminSettingField>
					{/if}
				</AdminSettingSection>

				<AdminSettingSection title={$i18n.t('settings.admin.guardian.sections.messages.title')}>
					<AdminSettingField
						label={$i18n.t('settings.admin.guardian.messageEn.label')}
						description={$i18n.t('settings.admin.guardian.messageEn.description')}
					>
						<textarea rows="3" class={textareaClass} bind:value={config.block_message_en}
						></textarea>
					</AdminSettingField>

					<AdminSettingField
						label={$i18n.t('settings.admin.guardian.messageAr.label')}
						description={$i18n.t('settings.admin.guardian.messageAr.description')}
					>
						<textarea
							rows="3"
							dir="rtl"
							class={textareaClass}
							bind:value={config.block_message_ar}
						></textarea>
					</AdminSettingField>
				</AdminSettingSection>

				<AdminSettingSection title={$i18n.t('settings.admin.guardian.sections.test.title')}>
					<p class="-mt-1 text-[0.6875rem] text-gray-400 dark:text-gray-600">
						{$i18n.t(
							'Dry-run a prompt against the current configuration. Nothing is blocked and no counters change.'
						)}
					</p>
					<textarea
						rows="3"
						class={textareaClass}
						placeholder={$i18n.t('Type a prompt to evaluate…')}
						bind:value={testPrompt}
					></textarea>
					<button
						type="button"
						class="mt-1 self-start rounded-lg bg-black px-2.5 py-1 text-xs text-white disabled:opacity-50 dark:bg-white dark:text-black"
						disabled={testing || !testPrompt.trim()}
						on:click={runTest}
					>
						{$i18n.t('Evaluate')}
					</button>

					{#if testResult}
						<div
							class="mt-2 rounded-lg border px-2.5 py-2 text-[0.6875rem] {testResult.would_block
								? 'border-red-200/60 bg-red-50/60 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300'
								: 'border-green-200/60 bg-green-50/60 text-green-700 dark:border-green-500/20 dark:bg-green-500/10 dark:text-green-300'}"
						>
							<div class="font-medium">
								{testResult.would_block
									? $i18n.t('Would be blocked')
									: $i18n.t('Would be allowed')}
								{#if testResult.decision.shadow && testResult.would_block}
									— {$i18n.t('shadow mode, not enforced')}
								{/if}
							</div>
							{#if testResult.decision.verdict.category}
								<div>
									{$i18n.t('Category')}: {testResult.decision.verdict.category}
									{#if testResult.decision.verdict.rule}
										· {testResult.decision.verdict.rule}
									{/if}
								</div>
							{/if}
							<div>{$i18n.t('Language')}: {testResult.language}</div>
							{#if testResult.scope_matches.length}
								<div>{$i18n.t('Domains')}: {testResult.scope_matches.join(', ')}</div>
							{/if}
							{#if testResult.decision.degraded}
								<div class="font-medium">
									{$i18n.t('Classifiers unavailable — evaluated with rules only.')}
								</div>
							{/if}
						</div>
					{/if}
				</AdminSettingSection>
			{/if}
		{:else}
			<div class="text-xs text-gray-400">{$i18n.t('Loading...')}</div>
		{/if}
	</div>

	<div class="flex justify-end pt-3">
		<button
			class="rounded-lg bg-black px-3 py-1.5 text-xs text-white transition hover:bg-gray-800 dark:bg-white dark:text-black dark:hover:bg-gray-200"
			type="submit"
		>
			{$i18n.t('Save')}
		</button>
	</div>
</form>
