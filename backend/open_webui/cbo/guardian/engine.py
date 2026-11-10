"""Guard evaluation orchestration.

Ordering is the whole point of this module:

1. L0 normalize + L1 rules (microseconds). Most junk dies here.
2. L2 and L3 classifiers run **concurrently** when configured, so added
   latency is the slower model, not the sum of both.
3. L4 scope is evaluated last and only to annotate the request (unless strict
   mode is on), because it is the highest false-positive risk.

Any classifier infrastructure failure is handled by one policy decision
(``fail_open``) in one place rather than scattered through the layers.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import Counter
from typing import Any

from open_webui.cbo.guardian.classifiers import (
    ClassifierError,
    HarmClassifier,
    InjectionClassifier,
    evaluate_classifier,
)
from open_webui.cbo.guardian.normalize import coverage, has_arabic, normalize
from open_webui.cbo.guardian.rules import evaluate_rules
from open_webui.cbo.guardian.scope import evaluate_scope, match_scope
from open_webui.cbo.guardian.settings import GuardianSettings
from open_webui.cbo.guardian.types import Category, Decision, Layer, Verdict

log = logging.getLogger(__name__)

#: Process-wide model singletons. Loading an 86M discriminator is fast but not
#: free, and re-loading per request would defeat the purpose of the guard.
_injection_classifier: InjectionClassifier | None = None
_harm_classifier: HarmClassifier | None = None
_classifier_lock = asyncio.Lock()

#: Lightweight in-process counters surfaced on the admin page. Incremented only
#: on the request path, never for dry-run tests.
_COUNTERS: Counter[str] = Counter()


def record_counters(decision: Decision, settings: GuardianSettings, *, is_arabic: bool = False) -> None:
    """Bump the admin-facing counters for one real evaluation (never a dry run)."""
    _COUNTERS['evaluated'] += 1
    _COUNTERS['language_ar' if is_arabic else 'language_en'] += 1
    if decision.degraded:
        _COUNTERS['degraded'] += 1
    if not decision.verdict.hit:
        _COUNTERS['allowed'] += 1
        return
    _COUNTERS['flagged'] += 1
    _COUNTERS[f'category:{decision.verdict.category or "unknown"}'] += 1
    if settings.shadow:
        _COUNTERS['shadow_only'] += 1
    else:
        _COUNTERS['enforced_block'] += 1


def get_counters() -> dict[str, int]:
    return dict(_COUNTERS)


def reset_counters() -> None:
    _COUNTERS.clear()


def _get_classifiers(
    settings: GuardianSettings,
) -> tuple[InjectionClassifier | None, HarmClassifier | None]:
    """Return cached classifiers, rebuilding when the configured path changes."""
    global _injection_classifier, _harm_classifier

    if not settings.enable_classifiers:
        return None, None

    if settings.injection_model_path:
        if (
            _injection_classifier is None
            or _injection_classifier.model_path != settings.injection_model_path
        ):
            _injection_classifier = InjectionClassifier(
                model_path=settings.injection_model_path,
                threshold=settings.injection_threshold,
            )
    else:
        _injection_classifier = None

    if settings.harm_model_path:
        if _harm_classifier is None or _harm_classifier.model_path != settings.harm_model_path:
            _harm_classifier = HarmClassifier(
                model_path=settings.harm_model_path, threshold=settings.harm_threshold
            )
    else:
        _harm_classifier = None

    return _injection_classifier, _harm_classifier


def reset_classifiers() -> None:
    """Drop cached models. Used by tests and by the admin config endpoint."""
    global _injection_classifier, _harm_classifier
    _injection_classifier = None
    _harm_classifier = None


def _fingerprint(text: str) -> str:
    """Stable, non-reversible prompt identifier for the audit trail.

    CBO policy: audit records carry a hash and the verdict, never the raw
    prompt, unless an operator explicitly enables prompt retention.
    """
    return hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()[:16]


def _trace(trace: list[dict[str, Any]], layer: Layer, verdict: Verdict, elapsed_ms: float) -> None:
    trace.append(
        {
            'layer': int(layer),
            'name': Layer(layer).name.lower(),
            'hit': verdict.hit,
            'category': str(verdict.category) if verdict.category else None,
            'rule': verdict.rule,
            'score': round(float(verdict.score), 4),
            'ms': round(elapsed_ms, 3),
        }
    )


async def _run_classifiers(
    text: str, settings: GuardianSettings
) -> list[Verdict]:
    """Run configured classifiers concurrently; return hit verdicts."""
    async with _classifier_lock:
        injection, harm = _get_classifiers(settings)

    jobs = []
    if injection is not None:
        jobs.append(
            evaluate_classifier(
                injection,
                text,
                category=Category.INJECTION,
                layer=Layer.INJECTION,
                threshold=settings.injection_threshold,
            )
        )
    if harm is not None:
        jobs.append(
            evaluate_classifier(
                harm,
                text,
                category=Category.HARM,
                layer=Layer.HARM,
                threshold=settings.harm_threshold,
            )
        )
    if not jobs:
        return []

    results = await asyncio.gather(*jobs, return_exceptions=True)
    verdicts: list[Verdict] = []
    for result in results:
        if isinstance(result, ClassifierError):
            raise result
        if isinstance(result, BaseException):
            raise ClassifierError(str(result)) from result
        verdicts.append(result)
    return verdicts


async def evaluate(
    text: str,
    settings: GuardianSettings,
    *,
    user_role: str | None = None,
    history: list[str] | None = None,
) -> Decision:
    """Evaluate one prompt against every enabled layer.

    ``history`` holds the text of *earlier* user turns supplied by the client.
    They only get the cheap L1 rules: an API client (or an edited chat) can
    plant an injection in an earlier turn that the model will still read, but
    re-running classifiers over the whole conversation every turn would be
    too expensive.

    Never raises: infrastructure problems are converted into a Decision so the
    caller has exactly one branch to implement.
    """
    decision = Decision(shadow=settings.shadow)

    if user_role and user_role in settings.bypass_roles:
        decision.trace.append({'layer': -1, 'name': 'bypass', 'hit': False, 'ms': 0.0})
        return decision

    started = time.perf_counter()
    normalized = normalize(text)
    _trace(decision.trace, Layer.NORMALIZE, Verdict(layer=Layer.NORMALIZE), (time.perf_counter() - started) * 1000)

    # An image-only or empty latest turn still has its history checked below.
    if not normalized and not history:
        return decision

    # --- L1: deterministic rules ----------------------------------------
    started = time.perf_counter()
    if len(normalized) > settings.max_chars:
        verdict = Verdict(
            action='block',
            category=Category.OVERSIZED,
            layer=Layer.RULES,
            score=1.0,
            rule='limit.max_chars',
            detail=f'{len(normalized)} > {settings.max_chars} characters',
        )
    else:
        verdict = evaluate_rules(
            normalized,
            disabled_rules=settings.disabled_rules,
            extra_blocklist=settings.blocklist,
        )
    _trace(decision.trace, Layer.RULES, verdict, (time.perf_counter() - started) * 1000)
    if verdict.hit:
        decision.verdict = verdict
        return decision

    if history:
        started = time.perf_counter()
        history_verdict = Verdict(layer=Layer.RULES)
        for earlier in history:
            candidate = evaluate_rules(
                earlier,
                disabled_rules=settings.disabled_rules,
                extra_blocklist=settings.blocklist,
            )
            if candidate.hit:
                candidate.detail = f'earlier user turn: {candidate.detail}'
                history_verdict = candidate
                break
        decision.trace.append(
            {
                'layer': int(Layer.RULES),
                'name': 'history',
                'hit': history_verdict.hit,
                'category': str(history_verdict.category) if history_verdict.category else None,
                'rule': history_verdict.rule,
                'turns': len(history),
                'ms': round((time.perf_counter() - started) * 1000, 3),
            }
        )
        if history_verdict.hit:
            decision.verdict = history_verdict
            return decision

    if not normalized:
        return decision

    # --- L2 + L3: classifiers, concurrent ---------------------------------
    if settings.classifiers_configured and settings.enable_classifiers:
        started = time.perf_counter()
        try:
            verdicts = await _run_classifiers(normalized, settings)
        except ClassifierError as exc:
            decision.degraded = True
            log.warning('Prompt Guardian degraded to L0+L1: %s', exc)
            decision.trace.append({'layer': 2, 'name': 'classifiers', 'hit': False, 'error': str(exc)})
            if not settings.fail_open:
                decision.verdict = Verdict(
                    action='block',
                    category=Category.HARM,
                    layer=Layer.HARM,
                    score=1.0,
                    rule='classifier.unavailable',
                    detail='guard classifier unavailable and fail_open is disabled',
                )
                return decision
            verdicts = []
        elapsed = (time.perf_counter() - started) * 1000
        for item in verdicts:
            _trace(decision.trace, item.layer or Layer.INJECTION, item, elapsed)
        # Report injection before harm, matching the L1 precedence.
        hits = [v for v in verdicts if v.hit]
        if hits:
            hits.sort(key=lambda v: (v.layer or Layer.INJECTION))
            decision.verdict = hits[0]
            return decision

    # --- L4: business scope (annotate, or enforce in strict mode) ---------
    started = time.perf_counter()
    scope_verdict = evaluate_scope(normalized, settings.domains, strict=settings.strict_scope)
    matches = match_scope(normalized, settings.domains)
    if matches:
        scope_verdict.detail = ','.join(m.domain_id for m in matches)
    _trace(decision.trace, Layer.SCOPE, scope_verdict, (time.perf_counter() - started) * 1000)
    decision.verdict = scope_verdict

    return decision


def audit_record(
    decision: Decision,
    *,
    text: str,
    user_id: str | None = None,
    model_id: str | None = None,
    chat_id: str | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    """Build the audit payload. Never contains the prompt text itself."""
    signals = coverage(text)
    return {
        'event': 'cbo.guardian.verdict',
        'fingerprint': _fingerprint(text),
        'length': len(text or ''),
        'language': 'ar' if has_arabic(text or '') else 'en',
        'signals': signals,
        'user_id': user_id,
        'model_id': model_id,
        'chat_id': chat_id,
        'message_id': message_id,
        **decision.to_dict(),
    }


async def log_decision(record: dict[str, Any]) -> None:
    """Emit the audit record through the existing application logger.

    Deliberately routing through ``logging`` rather than a new sink means the
    record lands in whatever audit configuration IT already runs
    (``AUDIT_LOG_LEVEL`` / ``AUDIT_LOGS_FILE_PATH``) with no extra plumbing.
    """
    if record.get('verdict', {}).get('action') == 'block' or record.get('degraded'):
        log.info('guardian_verdict %s', record)
    else:
        log.debug('guardian_verdict %s', record)
