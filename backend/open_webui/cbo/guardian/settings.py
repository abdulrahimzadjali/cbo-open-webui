"""Runtime settings for the Prompt Guardian.

Read through the same per-key ``Config`` store the rest of the fork uses, so
IT can change settings from Admin Settings without a restart and without a
release. Every key is registered in ``DEFAULT_CONFIG`` (see config.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from open_webui.models.config import Config

from open_webui.cbo.guardian.scope import DEFAULT_DOMAINS, ScopeDomain, parse_domains

#: Config key prefix. Keeping every key under ``cbo.guardian.`` means the
#: admin API can read/write the namespace in one query.
PREFIX = 'cbo.guardian'

KEY_ENABLED = f'{PREFIX}.enabled'
KEY_ENFORCE = f'{PREFIX}.enforce'
KEY_SHADOW = f'{PREFIX}.shadow'
KEY_FAIL_OPEN = f'{PREFIX}.fail_open'
KEY_MAX_CHARS = f'{PREFIX}.max_chars'
KEY_STRICT_SCOPE = f'{PREFIX}.strict_scope'
KEY_ENABLE_CLASSIFIERS = f'{PREFIX}.enable_classifiers'
KEY_DISABLED_RULES = f'{PREFIX}.disabled_rules'
KEY_BLOCKLIST = f'{PREFIX}.blocklist'
KEY_DOMAINS = f'{PREFIX}.domains'
KEY_INJECTION_MODEL = f'{PREFIX}.injection_model_path'
KEY_INJECTION_THRESHOLD = f'{PREFIX}.injection_threshold'
KEY_HARM_MODEL = f'{PREFIX}.harm_model_path'
KEY_HARM_THRESHOLD = f'{PREFIX}.harm_threshold'
KEY_BYPASS_ROLES = f'{PREFIX}.bypass_roles'
KEY_MESSAGE_EN = f'{PREFIX}.block_message_en'
KEY_MESSAGE_AR = f'{PREFIX}.block_message_ar'

#: Bounds for admin-supplied values. Enforced by the admin API on save and
#: re-applied on load, so a value written straight to the database (or by an
#: older build) cannot make the guardian block everything or nothing.
MIN_MAX_CHARS = 500
MAX_MAX_CHARS = 200_000
#: A blocklist phrase shorter than this ("a", "of") would match almost every
#: prompt as a substring.
MIN_BLOCKLIST_PHRASE = 3
#: Roles that may be exempted. "pending" users cannot chat at all.
BYPASSABLE_ROLES = frozenset({'admin', 'user'})


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


DEFAULT_MESSAGE_EN = (
    'Your message could not be processed because it falls outside the permitted '
    'use policy for CBO AI. If you believe this is an error, please contact the IT Service Desk.'
)
DEFAULT_MESSAGE_AR = (
    'تعذر معالجة رسالتك لأنها خارج نطاق الاستخدام المسموح به لنظام الذكاء الاصطناعي '
    'في البنك المركزي. إذا كنت تعتقد أن هذا خطأ، يرجى التواصل مع مكتب خدمة تقنية المعلومات.'
)


@dataclass
class GuardianSettings:
    """Snapshot of guardian configuration for one request."""

    enabled: bool = False
    #: Deprecated and ignored. It used to switch evaluation (and logging)
    #: off entirely while "enabled" stayed on, which read like "log only"
    #: but was "do nothing". ``enabled`` is the on/off switch and ``shadow``
    #: is log-only. Kept so stored configs and API clients still load.
    enforce: bool = True
    shadow: bool = True
    fail_open: bool = True
    max_chars: int = 12000
    strict_scope: bool = False
    enable_classifiers: bool = False
    disabled_rules: set[str] = field(default_factory=set)
    blocklist: list[str] = field(default_factory=list)
    domains: tuple[ScopeDomain, ...] = DEFAULT_DOMAINS
    injection_model_path: str = ''
    injection_threshold: float = 0.85
    harm_model_path: str = ''
    harm_threshold: float = 0.85
    bypass_roles: set[str] = field(default_factory=lambda: {'admin'})
    message_en: str = DEFAULT_MESSAGE_EN
    message_ar: str = DEFAULT_MESSAGE_AR

    @property
    def classifiers_configured(self) -> bool:
        return bool(self.injection_model_path or self.harm_model_path)

    def message(self, prefer_arabic: bool = False) -> str:
        """Pick the refusal text. Arabic is used when the prompt is Arabic."""
        if prefer_arabic and self.message_ar:
            return self.message_ar
        return self.message_en or self.message_ar


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == 'true'
    if value is None:
        return default
    return bool(value)


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str_list(value) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.replace(',', '\n').splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


async def load_settings() -> GuardianSettings:
    """Load the full guardian configuration in one database round trip."""
    values = await Config.get_many(
        KEY_ENABLED,
        KEY_ENFORCE,
        KEY_SHADOW,
        KEY_FAIL_OPEN,
        KEY_MAX_CHARS,
        KEY_STRICT_SCOPE,
        KEY_ENABLE_CLASSIFIERS,
        KEY_DISABLED_RULES,
        KEY_BLOCKLIST,
        KEY_DOMAINS,
        KEY_INJECTION_MODEL,
        KEY_INJECTION_THRESHOLD,
        KEY_HARM_MODEL,
        KEY_HARM_THRESHOLD,
        KEY_BYPASS_ROLES,
        KEY_MESSAGE_EN,
        KEY_MESSAGE_AR,
    )
    defaults = GuardianSettings()
    return GuardianSettings(
        enabled=_as_bool(values.get(KEY_ENABLED), defaults.enabled),
        enforce=_as_bool(values.get(KEY_ENFORCE), defaults.enforce),
        shadow=_as_bool(values.get(KEY_SHADOW), defaults.shadow),
        fail_open=_as_bool(values.get(KEY_FAIL_OPEN), defaults.fail_open),
        max_chars=int(
            clamp(
                _as_int(values.get(KEY_MAX_CHARS), defaults.max_chars),
                MIN_MAX_CHARS,
                MAX_MAX_CHARS,
            )
        ),
        strict_scope=_as_bool(values.get(KEY_STRICT_SCOPE), defaults.strict_scope),
        enable_classifiers=_as_bool(
            values.get(KEY_ENABLE_CLASSIFIERS), defaults.enable_classifiers
        ),
        disabled_rules=set(_as_str_list(values.get(KEY_DISABLED_RULES))),
        blocklist=[
            phrase
            for phrase in _as_str_list(values.get(KEY_BLOCKLIST))
            if len(phrase) >= MIN_BLOCKLIST_PHRASE
        ],
        domains=parse_domains(values.get(KEY_DOMAINS)),
        injection_model_path=str(values.get(KEY_INJECTION_MODEL) or ''),
        injection_threshold=clamp(
            _as_float(values.get(KEY_INJECTION_THRESHOLD), defaults.injection_threshold), 0.0, 1.0
        ),
        harm_model_path=str(values.get(KEY_HARM_MODEL) or ''),
        harm_threshold=clamp(
            _as_float(values.get(KEY_HARM_THRESHOLD), defaults.harm_threshold), 0.0, 1.0
        ),
        # Unset (None) falls back to the admin default, but an explicitly
        # saved empty list means "nobody bypasses" -- otherwise the admin
        # bypass toggle in the UI could never be switched off.
        bypass_roles=(
            set(defaults.bypass_roles)
            if values.get(KEY_BYPASS_ROLES) is None
            else set(_as_str_list(values.get(KEY_BYPASS_ROLES))) & BYPASSABLE_ROLES
        ),
        message_en=str(values.get(KEY_MESSAGE_EN) or defaults.message_en),
        message_ar=str(values.get(KEY_MESSAGE_AR) or defaults.message_ar),
    )
