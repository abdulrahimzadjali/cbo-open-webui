"""L1: deterministic bilingual rules.

Rules here are *high precision only*. A match blocks the request, so every
pattern must be something that has no legitimate reading in a central-bank
chat. That is why the injection patterns require an explicit override verb
*aimed at the assistant* ("ignore your instructions", "ignore all previous
instructions") rather than bare keywords -- see the over-defence failure mode
documented in PIGuard.

Words that are everyday regulatory vocabulary at CBO are never enough on their
own: "override" / "تجاوز" (also "exceed"), "الغاء" (cancel), "guidelines",
"directives", "تعليمات" and "ضوابط" (CBO issues instructions and controls to
banks), and security-team topics such as "ransomware". Those only block when
the phrasing targets the assistant itself (second person: "your", "ـك") or
asks for a working artefact ("write ransomware").

Rules run on text already normalised by L0 (Arabic diacritics stripped,
alef/teh-marbuta/alef-maqsura folded, digits folded, invisible characters
removed). Patterns are folded with the same letter fold at compile time, so
they can be written in ordinary Arabic spelling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from open_webui.cbo.guardian.normalize import fold_arabic_letters, normalize
from open_webui.cbo.guardian.types import Category, Layer, Verdict


@dataclass(frozen=True)
class Rule:
    """A single deterministic rule."""

    id: str
    category: str
    pattern: re.Pattern[str]
    description: str


# --- Shared vocabulary -------------------------------------------------------

#: English nouns for "the assistant's instructions". ``rules``, ``guidelines``
#: and ``directives`` are deliberately *not* here: they are CBO business words
#: and only count when explicitly addressed to the assistant (see _EN_POLICY).
_EN_INSTR = r'(?:instructions?|prompts?)'
_EN_POLICY = (
    r'(?:rules?|guidelines?|directives?|guardrails?|restrictions?|safeguards?|'
    r'polic(?:y|ies)|filters?|programming)'
)
_EN_QUALIFIER = r'(?:previous|prior|above|earlier|preceding|original|initial|system)'

#: Arabic nouns for instructions/rules/controls. Every one is also normal CBO
#: vocabulary, so they only block with a qualifier aimed at the assistant.
_AR_N = r'(?:تعليمات|قواعد|توجيهات|ضوابط|قيود|اوامر|ارشادات)'
#: Second-person possessive suffix ("your ...") -- the attack signal.
_AR_YOUR = r'(?:ك|كي)(?!\w)'
#: Arabic word start (Python's \b works for Arabic, but a lookbehind is
#: clearer and also stops "انس" matching inside a longer word).
_AR_START = r'(?<!\w)'

#: Bilingual jailbreak / prompt-injection phrases.
_INJECTION_PATTERNS: list[tuple[str, str, str]] = [
    # --- English: instruction override -------------------------------------
    (
        'inject.ignore_instructions',
        # ignore/disregard/forget + (all|any|your|the + qualifier) + instructions
        # "ignore my previous instructions" (the user correcting themself) and
        # "ignore the previous figures" do not match.
        r'\b(?:ignore|disregard|forget)\s+'
        r'(?:(?:all|any)\s+(?:of\s+)?(?:the\s+|your\s+)?(?:' + _EN_QUALIFIER + r'\s+)?'
        r'|your\s+(?:' + _EN_QUALIFIER + r'\s+)?'
        r'|(?:the\s+)?' + _EN_QUALIFIER + r'\s+'
        r')?' + _EN_INSTR + r'\b',
        'English: instruction override',
    ),
    (
        'inject.ignore_rules',
        # Policy nouns need an assistant-directed qualifier: "your rules",
        # "all previous rules", "the system rules". "Ignore the previous
        # guidelines" from a supervisor is business language and passes.
        r'\b(?:ignore|disregard|forget)\s+'
        r'(?:(?:all|any)\s+(?:of\s+)?(?:the\s+|your\s+)?(?:' + _EN_QUALIFIER + r'\s+)?'
        r'|your\s+(?:' + _EN_QUALIFIER + r'\s+)?'
        r'|(?:the\s+)?system\s+'
        r')' + _EN_POLICY + r'\b',
        'English: rule override',
    ),
    (
        'inject.override_your_rules',
        # override/bypass are only injection when aimed at the assistant.
        # "Does the new circular override the previous guidelines?" passes.
        r'\b(?:override|bypass|circumvent|disable|turn\s+off)\s+(?:all\s+|any\s+)?(?:of\s+)?'
        r'(?:your|the\s+system(?:\'s)?)\s+(?:\w+\s+)?(?:' + _EN_POLICY + r'|' + _EN_INSTR + r'|safety)\b',
        'English: override the assistant\'s rules',
    ),
    (
        'inject.ignore_previous',
        r'\b(?:ignore|disregard|forget)\s+(?:everything\s+)?(?:above|before\s+this|previous\s+turn|prior\s+context)\b',
        'English: context reset',
    ),
    # --- Arabic: instruction override --------------------------------------
    (
        'inject.ignore_instructions_ar',
        # تجاهل/اهمل/انس + (كل|جميع) التعليمات | تعليماتك | التعليمات السابقة
        # Only imperative ignore/forget verbs. "الغاء" (cancel) and "تجاوز"
        # (exceed) are everyday CBO words and live in the next rule instead.
        _AR_START + r'(?:تجاهل|تتجاهل|تجاهلي|اهمل|تهمل|اهملي|انس|تنس|انسي)\s+'
        r'(?:(?:كل|جميع|كافة)\s+(?:ال)?' + _AR_N + r'|(?:ال)?' + _AR_N + _AR_YOUR + r'|'
        r'(?:ال)?' + _AR_N + r'\s+(?:السابقة|الاصلية|اعلاه|النظام|المعطاة\s+لك))',
        'Arabic: instruction override',
    ),
    (
        'inject.override_your_rules_ar',
        # تجاوز/الغ/اكسر + تعليماتك / قيود النظام. Requires "your" or "the
        # system", so "تجاوز الضوابط المتعلقة بالسيولة" and "إلغاء التعليمات
        # السابقة الصادرة للبنوك" pass.
        _AR_START + r'(?:تجاوز|تتجاوز|تجاوزي|الغ|الغي|اكسر|اكسري|اخترق)\s+(?:كل\s+|جميع\s+)?'
        r'(?:(?:ال)?' + _AR_N + _AR_YOUR + r'|(?:ال)?' + _AR_N + r'\s+النظام)',
        'Arabic: override the assistant\'s rules',
    ),
    (
        'inject.ignore_previous_ar',
        _AR_START + r'(?:تجاهل|تجاهلي|اهمل|اهملي|انس|تنس|انسي)\s+(?:كل\s+|جميع\s+)?(?:ما\s+)?'
        r'(?:سبق|السابق|اعلاه|فوق)',
        'Arabic: context reset',
    ),
    # --- Persona / jailbreak framing (both languages) ----------------------
    (
        'inject.dan_persona',
        r'\b(?:do\s+anything\s+now|\bdan\b\s*(?:mode|prompt)|\bdeveloper\s+mode\b\s*(?:enabled|on)?)',
        'English: unrestricted persona',
    ),
    (
        'inject.persona_unrestricted',
        r'\byou\s+are\s+(?:now\s+)?(?:an?\s+)?(?:unrestricted|unfiltered|uncensored|jailbroken)\b',
        'English: unrestricted persona',
    ),
    (
        'inject.unrestricted_ar',
        r'(?:انت|انتي)\s+(?:الان\s+)?(?:ذكاء\s+اصطناعي\s+)?'
        r'(?:غير\s+مقيد|بدون\s+قيود|غير\s+محدود|مطلق\s+الصلاحيات)',
        'Arabic: unrestricted persona',
    ),
    # --- System-prompt / configuration exfiltration ------------------------
    (
        'inject.reveal_system_prompt',
        r'\b(?:reveal|print|show|repeat|output|display|leak)\s+(?:me\s+)?(?:your\s+)?'
        r'(?:system\s+prompt|initial\s+prompt|hidden\s+prompt|system\s+instructions|pre-?prompt)\b',
        'English: system prompt exfiltration',
    ),
    (
        'inject.reveal_system_prompt_ar',
        # "التعليمات الأساسية" alone is "the basic instructions" (of a
        # circular, an account opening...) and must say "of the system".
        _AR_START + r'(?:اظهر|اعرض|اطبع|كرر|اكشف|اطلعني\s+على)(?:\s+لي)?\s+(?:ال)?'
        r'(?:موجه\s+النظام|تعليمات\s+النظام|التعليمات\s+(?:الاساسية|الاولية)\s+للنظام|'
        r'التعليمات\s+المخفية|البرومبت|موجهك|تعليماتك)',
        'Arabic: system prompt exfiltration',
    ),
]

#: Words that make a "write ... ransomware" request a request for a working
#: artefact. Kept to articles/adjectives/artefact nouns so that
#: "create a policy on ransomware" (policy is not in the list) passes.
_EN_MAKE = r'(?:write|create|build|develop|make|code|generate|craft|program|produce)'
_EN_FILLER = (
    r'(?:\s+(?:a|an|the|some|me|us|my\s+own|own|working|functional|simple|basic|new|custom|'
    r'undetectable|fud|polymorphic|python|powershell|c|c\+\+|code|script|program|tool|for)){0,5}'
)
_EN_MALWARE = (
    r'(?:ransomware|keylogger|botnet|rootkit|reverse\s+shell|exploit\s+kit|'
    r'credential\s+stealer|malware|trojan)'
)

#: Content that has no legitimate reading in CBO business use.
#:
#: The malware rules require a "make it" verb: CBO IT security staff discuss
#: ransomware, keyloggers and botnets daily and must not be blocked for it.
#: The real harm coverage comes from the optional on-prem classifier (L3).
_HARM_PATTERNS: list[tuple[str, str, str]] = [
    (
        'harm.malware',
        r'\b' + _EN_MAKE + r'\b' + _EN_FILLER + r'\s+' + _EN_MALWARE + r'\b',
        'English: malware creation',
    ),
    (
        'harm.malware_ar',
        _AR_START + r'(?:اكتب|اكتبي|انشئ|اصنع|برمج|طور|صمم)\s+(?:لي\s+)?'
        r'(?:كود\s+|برنامج\s+|سكربت\s+)?'
        r'(?:فيروس|برمجية\s+خبيثة|كيلوجر|بوت\s+نت|روت\s+كيت)',
        'Arabic: malware creation',
    ),
    (
        'harm.weapons',
        r'\b(?:pipe\s*bomb|pressure\s+cooker\s+bomb|ied|molotov\s+cocktails?|napalm|'
        r'improvised\s+explosive|nerve\s+agent\s+synthesis)\b',
        'English: weapons',
    ),
    (
        'harm.weapons_ar',
        r'(?:عبوة\s+ناسفة|صناعة\s+القنابل|صنع\s+متفجرات|تصنيع\s+سم\s+الاعصاب)',
        'Arabic: weapons',
    ),
]


def _compile(pattern: str) -> re.Pattern[str]:
    # Apply the L0 letter fold to the pattern so "ة"/"أ"/"ى" written in a
    # pattern can actually match normalised input (which never contains them).
    return re.compile(fold_arabic_letters(pattern), re.IGNORECASE)


_INJECTION_RULES = [Rule(rid, Category.INJECTION, _compile(pat), desc) for rid, pat, desc in _INJECTION_PATTERNS]
_HARM_RULES = [Rule(rid, Category.HARM, _compile(pat), desc) for rid, pat, desc in _HARM_PATTERNS]

ALL_RULES: list[Rule] = [*_INJECTION_RULES, *_HARM_RULES]

#: Rules that can be toggled off per-deployment without code changes.
RULE_IDS: frozenset[str] = frozenset(rule.id for rule in ALL_RULES)


def evaluate_rules(
    text: str,
    *,
    disabled_rules: set[str] | frozenset[str] = frozenset(),
    extra_blocklist: list[str] | None = None,
) -> Verdict:
    """Run every deterministic rule against *text*.

    Returns the first match. Injection is checked before harm so that a
    jailbreak attempt is reported as an injection rather than as the harm it
    tries to elicit -- that distinction drives the audit and the user message.

    ``extra_blocklist`` lets IT add literal, case-insensitive phrases at
    runtime (for example a new slang term observed in an incident) without a
    release. Literal phrases are matched as substrings on normalised text.
    """
    normalized = normalize(text)
    if not normalized:
        return Verdict(layer=Layer.RULES)

    for rule in ALL_RULES:
        if rule.id in disabled_rules:
            continue
        match = rule.pattern.search(normalized)
        if match:
            return Verdict(
                action='block',
                category=rule.category,
                layer=Layer.RULES,
                score=1.0,
                rule=rule.id,
                detail=rule.description,
            )

    if extra_blocklist:
        haystack = normalized.casefold()
        for phrase in extra_blocklist:
            needle = normalize(phrase).casefold()
            if needle and needle in haystack:
                return Verdict(
                    action='block',
                    category=Category.HARM,
                    layer=Layer.RULES,
                    score=1.0,
                    rule='custom.blocklist',
                    detail='custom blocklist phrase',
                )

    return Verdict(layer=Layer.RULES)
