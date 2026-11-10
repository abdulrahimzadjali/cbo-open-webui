"""Admin API for the Prompt Guardian.

Lives under ``/api/v1/cbo/guardian`` and is mounted from ``main.py`` with a
single ``include_router`` line, so the CBO surface stays isolated from upstream
routers.

Endpoints:

* ``GET  /config``  -- current settings (admin only)
* ``POST /config``  -- update settings (admin only)
* ``GET  /rules``   -- the deterministic rule catalogue, for the UI
* ``POST /test``    -- dry-run a prompt against the live config (admin only)
* ``GET  /stats``   -- verdict counters since process start (admin only)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from open_webui.models.config import Config
from open_webui.utils.auth import get_admin_user

from open_webui.cbo.guardian.engine import evaluate, get_counters, reset_classifiers
from open_webui.cbo.guardian.normalize import coverage, has_arabic
from open_webui.cbo.guardian.rules import ALL_RULES
from open_webui.cbo.guardian.scope import DEFAULT_DOMAINS, match_scope
from open_webui.cbo.guardian.settings import (
    KEY_BLOCKLIST,
    KEY_BYPASS_ROLES,
    KEY_DISABLED_RULES,
    KEY_DOMAINS,
    KEY_ENABLED,
    KEY_ENABLE_CLASSIFIERS,
    KEY_ENFORCE,
    KEY_FAIL_OPEN,
    KEY_HARM_MODEL,
    KEY_HARM_THRESHOLD,
    KEY_INJECTION_MODEL,
    KEY_INJECTION_THRESHOLD,
    KEY_MAX_CHARS,
    KEY_MESSAGE_AR,
    KEY_MESSAGE_EN,
    KEY_SHADOW,
    KEY_STRICT_SCOPE,
    BYPASSABLE_ROLES,
    MAX_MAX_CHARS,
    MIN_BLOCKLIST_PHRASE,
    MIN_MAX_CHARS,
    load_settings,
)
from open_webui.cbo.guardian.rules import RULE_IDS

log = logging.getLogger(__name__)

router = APIRouter()

#: Process start time for the admin "since" label. Counters themselves live in
#: ``engine`` so the request path can bump them without importing the router.
_stats_since = time.time()


class GuardianConfigForm(BaseModel):
    enabled: bool = False
    enforce: bool = True
    shadow: bool = True
    fail_open: bool = True
    max_chars: int = Field(12000, ge=MIN_MAX_CHARS, le=MAX_MAX_CHARS)
    strict_scope: bool = False
    enable_classifiers: bool = False
    disabled_rules: list[str] = []
    blocklist: list[str] = []
    domains: list[dict[str, Any]] | None = None
    injection_model_path: str = ''
    injection_threshold: float = Field(0.85, ge=0.0, le=1.0)
    harm_model_path: str = ''
    harm_threshold: float = Field(0.85, ge=0.0, le=1.0)
    bypass_roles: list[str] = ['admin']
    block_message_en: str = Field('', max_length=2000)
    block_message_ar: str = Field('', max_length=2000)

    @field_validator('disabled_rules')
    @classmethod
    def _known_rules(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - RULE_IDS)
        if unknown:
            raise ValueError(f'unknown rule ids: {", ".join(unknown)}')
        return sorted(set(value))

    @field_validator('blocklist')
    @classmethod
    def _blocklist_phrases(cls, value: list[str]) -> list[str]:
        phrases = [phrase.strip() for phrase in value if phrase.strip()]
        short = [phrase for phrase in phrases if len(phrase) < MIN_BLOCKLIST_PHRASE]
        if short:
            raise ValueError(
                f'blocklist phrases must be at least {MIN_BLOCKLIST_PHRASE} characters: '
                + ', '.join(repr(phrase) for phrase in short)
            )
        return phrases

    @field_validator('bypass_roles')
    @classmethod
    def _known_roles(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - BYPASSABLE_ROLES)
        if unknown:
            raise ValueError(f'roles cannot bypass the guardian: {", ".join(unknown)}')
        return sorted(set(value))


class GuardianTestForm(BaseModel):
    prompt: str
    role: str | None = None


@router.get('/config', response_model=GuardianConfigForm)
async def get_guardian_config(request: Request, user=Depends(get_admin_user)):
    settings = await load_settings()
    from open_webui.cbo.guardian.settings import DEFAULT_MESSAGE_AR, DEFAULT_MESSAGE_EN

    return GuardianConfigForm(
        enabled=settings.enabled,
        enforce=settings.enforce,
        shadow=settings.shadow,
        fail_open=settings.fail_open,
        max_chars=settings.max_chars,
        strict_scope=settings.strict_scope,
        enable_classifiers=settings.enable_classifiers,
        # Drop ids of rules that no longer exist so a stale entry cannot make
        # the next save fail validation.
        disabled_rules=sorted(settings.disabled_rules & RULE_IDS),
        blocklist=settings.blocklist,
        domains=[
            {
                'id': d.id,
                'label_en': d.label_en,
                'label_ar': d.label_ar,
                'terms_en': list(d.terms_en),
                'terms_ar': list(d.terms_ar),
            }
            for d in settings.domains
        ],
        injection_model_path=settings.injection_model_path,
        injection_threshold=settings.injection_threshold,
        harm_model_path=settings.harm_model_path,
        harm_threshold=settings.harm_threshold,
        bypass_roles=sorted(settings.bypass_roles),
        block_message_en=settings.message_en or DEFAULT_MESSAGE_EN,
        block_message_ar=settings.message_ar or DEFAULT_MESSAGE_AR,
    )


@router.post('/config', response_model=GuardianConfigForm)
async def set_guardian_config(
    request: Request, form_data: GuardianConfigForm, user=Depends(get_admin_user)
):
    payload = form_data.model_dump()
    await Config.upsert(
        {
            KEY_ENABLED: payload['enabled'],
            KEY_ENFORCE: payload['enforce'],
            KEY_SHADOW: payload['shadow'],
            KEY_FAIL_OPEN: payload['fail_open'],
            KEY_MAX_CHARS: payload['max_chars'],
            KEY_STRICT_SCOPE: payload['strict_scope'],
            KEY_ENABLE_CLASSIFIERS: payload['enable_classifiers'],
            KEY_DISABLED_RULES: payload['disabled_rules'],
            KEY_BLOCKLIST: payload['blocklist'],
            KEY_DOMAINS: payload['domains'],
            KEY_INJECTION_MODEL: payload['injection_model_path'],
            KEY_INJECTION_THRESHOLD: payload['injection_threshold'],
            KEY_HARM_MODEL: payload['harm_model_path'],
            KEY_HARM_THRESHOLD: payload['harm_threshold'],
            KEY_BYPASS_ROLES: payload['bypass_roles'],
            KEY_MESSAGE_EN: payload['block_message_en'],
            KEY_MESSAGE_AR: payload['block_message_ar'],
        }
    )
    # Model paths, thresholds or the on/off switch may have changed; drop any
    # cached pipelines so the next request loads the new configuration.
    reset_classifiers()
    log.info(
        'Prompt Guardian config updated by %s (enabled=%s shadow=%s enforce=%s)',
        getattr(user, 'email', getattr(user, 'id', '?')),
        payload['enabled'],
        payload['shadow'],
        payload['enforce'],
    )
    return await get_guardian_config(request, user)


@router.get('/rules')
async def get_guardian_rules(request: Request, user=Depends(get_admin_user)):
    """Catalogue of deterministic rules and default business domains."""
    return {
        'rules': [
            {
                'id': rule.id,
                'category': rule.category,
                'description': rule.description,
                'pattern': rule.pattern.pattern,
            }
            for rule in ALL_RULES
        ],
        'domains': [
            {
                'id': d.id,
                'label_en': d.label_en,
                'label_ar': d.label_ar,
                'terms_en': list(d.terms_en),
                'terms_ar': list(d.terms_ar),
            }
            for d in DEFAULT_DOMAINS
        ],
    }


@router.post('/test')
async def test_guardian(request: Request, form_data: GuardianTestForm, user=Depends(get_admin_user)):
    """Dry-run a prompt. Never enforces and never advances the counters.

    This is the tool IT uses during rollout to calibrate the allowlist against
    real prompts without blocking anyone.
    """
    settings = await load_settings()
    decision = await evaluate(form_data.prompt, settings, user_role=form_data.role)
    return {
        'decision': decision.to_dict(),
        'signals': coverage(form_data.prompt),
        'language': 'ar' if has_arabic(form_data.prompt) else 'en',
        'scope_matches': [m.domain_id for m in match_scope(form_data.prompt, settings.domains)],
        'would_block': decision.verdict.hit,
        'enforced': decision.verdict.hit and not settings.shadow,
        'message': settings.message(prefer_arabic=has_arabic(form_data.prompt)),
    }


@router.get('/stats')
async def get_guardian_stats(request: Request, user=Depends(get_admin_user)):
    return {
        'since': _stats_since,
        'counters': get_counters(),
    }
