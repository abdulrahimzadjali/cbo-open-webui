"""L2-L4: optional on-prem classifier adapters.

Deliberately decoupled from the deterministic core. ``torch``/``transformers``
are **not** in ``backend/requirements.txt``, and they must stay out of it: the
guardian has to degrade to L0+L1 rather than break the app on a box where the
ML stack was never installed.

Contract for every adapter:

* ``available()`` never raises and never imports torch at module scope.
* ``score(text)`` returns a float in 0..1 for "this text is a positive".
* Loading happens once under a lock; a failed load is remembered so a
  misconfigured model path cannot cost 30s on every request.

Where models are chosen for CBO:

* Arabic is a hard requirement, so an English-only detector (Prompt-Guard-86M
  is labelled English-only on Hugging Face) is **not** acceptable as the only
  classifier -- an Arabic jailbreak walks straight past it.
* Smallest-first per the rollout decision: the 86M mDeBERTa discriminators are
  the fast tier, Llama Guard 3 1B is the accurate tier if hardware allows.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Any

from open_webui.cbo.guardian.types import Category, Layer, Verdict

log = logging.getLogger(__name__)


class ClassifierError(RuntimeError):
    """Raised when a model cannot be loaded or run."""


class _BaseClassifier:
    """Shared lazy-loading machinery for Hugging Face pipelines."""

    #: HuggingFace architecture family, used to pick the scoring path.
    kind: str = 'sequence-classification'
    #: Default local directory (a plain path -- no hub downloads at runtime).
    default_path: str = ''
    label: str = 'classifier'

    def __init__(self, model_path: str | None = None, threshold: float = 0.5):
        self.model_path = model_path or self.default_path
        self.threshold = float(threshold)
        self._pipeline: Any = None
        self._load_error: str | None = None
        self._lock = threading.Lock()

    # -- availability -----------------------------------------------------
    def available(self) -> bool:
        """True when the model directory exists locally.

        Never triggers a download: CBO deployments are air-gapped, and a
        runtime ``from_pretrained`` against the Hub would hang for the request
        timeout and then fail closed on every prompt.
        """
        if not self.model_path:
            return False
        return Path(self.model_path).is_dir()

    # -- loading ----------------------------------------------------------
    def _ensure_loaded(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        if self._load_error is not None:
            raise ClassifierError(self._load_error)

        with self._lock:
            if self._pipeline is not None:
                return self._pipeline
            if self._load_error is not None:
                raise ClassifierError(self._load_error)

            try:
                if not self.available():
                    raise ClassifierError(f'model directory not found: {self.model_path!r}')

                from transformers import (  # noqa: PLC0415 - intentional lazy import
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                    pipeline,
                )

                # local_files_only keeps the process offline even if a machine
                # does have egress by accident.
                tokenizer = AutoTokenizer.from_pretrained(self.model_path, local_files_only=True)
                model = AutoModelForSequenceClassification.from_pretrained(
                    self.model_path, local_files_only=True
                )
                device = -1
                try:
                    import torch  # noqa: PLC0415

                    if torch.cuda.is_available() and os.getenv('CBO_GUARDIAN_DEVICE', 'cpu') == 'cuda':
                        device = 0
                except Exception:  # pragma: no cover - torch missing is normal
                    device = -1

                self._pipeline = pipeline(
                    'text-classification',
                    model=model,
                    tokenizer=tokenizer,
                    device=device,
                    truncation=True,
                    max_length=512,
                )
                log.info('Prompt Guardian: loaded %s from %s', self.label, self.model_path)
                return self._pipeline
            except ClassifierError:
                raise
            except Exception as exc:  # noqa: BLE001 - must never escape to the request path
                self._load_error = f'{self.label} failed to load: {exc}'
                log.warning(self._load_error)
                raise ClassifierError(self._load_error) from exc

    # -- scoring ----------------------------------------------------------
    def score(self, text: str) -> float:
        """Probability (0..1) that *text* belongs to the positive class."""
        raise NotImplementedError


class InjectionClassifier(_BaseClassifier):
    """L2: jailbreak / prompt-injection detector (fast tier).

    Recommended default: a fine-tuned 86M mDeBERTa guard. For Arabic coverage
    point ``model_path`` at an Arabic-capable guard (for example an
    Ara-Prompt-Guard fine-tune) or run both and take the maximum.
    """

    kind = 'sequence-classification'
    label = 'injection classifier'
    default_path = ''

    #: Label names that mean "attack" across the guard models in common use.
    _POSITIVE_LABELS = frozenset({'LABEL_1', 'INJECTION', 'JAILBREAK', 'MALICIOUS', 'UNSAFE', '1'})

    def score(self, text: str) -> float:
        pipe = self._ensure_loaded()
        result = pipe(text)
        if isinstance(result, list) and result and isinstance(result[0], list):
            result = result[0]
        scores = {}
        for item in result if isinstance(result, list) else [result]:
            scores[str(item.get('label', '')).upper()] = float(item.get('score', 0.0))

        positive = [value for name, value in scores.items() if name in self._POSITIVE_LABELS]
        if positive:
            return max(positive)
        # Single-label binary heads sometimes return only the negative score.
        if len(scores) == 1 and 'LABEL_0' in scores:
            return 1.0 - next(iter(scores.values()))
        return 0.0


class HarmClassifier(_BaseClassifier):
    """L3: harm taxonomy classifier (accurate tier, e.g. Llama Guard 3 1B).

    Llama Guard is generative: it answers ``safe`` or ``unsafe\\nS<code>``.
    We map that text to a confidence rather than a calibrated probability,
    because the model does not expose logits in the pipeline API. That is
    sufficient for a threshold gate and is recorded as such in the audit log.
    """

    kind = 'text-generation'
    label = 'harm classifier'
    default_path = ''

    _tokenizer: Any = None

    @staticmethod
    def build_prompt(tokenizer: Any, text: str) -> str:
        """Wrap *text* in the model's own moderation chat template.

        Llama Guard only answers ``safe``/``unsafe`` when the prompt is framed
        by its chat template (the hazard taxonomy lives there). Fed raw text it
        just continues the user's prose. Llama Guard 3 1B expects list-style
        content parts; the 8B variant expects a plain string, so try both.
        """
        if not getattr(tokenizer, 'chat_template', None):
            raise ClassifierError(
                'harm model has no chat template; a Llama Guard-style model is required'
            )
        last_error: Exception | None = None
        for content in ([{'type': 'text', 'text': text}], text):
            try:
                return tokenizer.apply_chat_template(
                    [{'role': 'user', 'content': content}],
                    tokenize=False,
                    add_generation_prompt=True,
                )
            except Exception as exc:  # noqa: BLE001 - try the other content shape
                last_error = exc
        raise ClassifierError(f'could not apply harm model chat template: {last_error}')

    @staticmethod
    def parse_verdict(generated: str) -> float:
        """Map Llama Guard output (``safe`` / ``unsafe\\nS1``) to a score.

        Reads the *first* non-empty line of the newly generated text only. The
        caller must request ``return_full_text=False``: otherwise the prompt is
        echoed back and a user could end their message with "safe".
        """
        for line in (generated or '').splitlines():
            line = line.strip().lower()
            if not line:
                continue
            if line.startswith('unsafe'):
                return 1.0
            if line.startswith('safe'):
                return 0.0
            break
        return 0.5  # unparseable => ambiguous, let the threshold decide

    def score(self, text: str) -> float:
        pipe = self._ensure_loaded()
        prompt = self.build_prompt(self._tokenizer, text)
        out = pipe(prompt, max_new_tokens=12, do_sample=False, return_full_text=False)[0]
        return self.parse_verdict(str(out.get('generated_text', '')))

    def _ensure_loaded(self) -> Any:
        # Text-generation models need a different pipeline factory.
        if self._pipeline is not None:
            return self._pipeline
        if self._load_error is not None:
            raise ClassifierError(self._load_error)
        with self._lock:
            if self._pipeline is not None:
                return self._pipeline
            if self._load_error is not None:
                raise ClassifierError(self._load_error)
            try:
                if not self.available():
                    raise ClassifierError(f'model directory not found: {self.model_path!r}')
                from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline  # noqa: PLC0415

                tokenizer = AutoTokenizer.from_pretrained(self.model_path, local_files_only=True)
                model = AutoModelForCausalLM.from_pretrained(self.model_path, local_files_only=True)
                device = -1
                try:
                    import torch  # noqa: PLC0415

                    if torch.cuda.is_available() and os.getenv('CBO_GUARDIAN_DEVICE', 'cpu') == 'cuda':
                        device = 0
                except Exception:  # pragma: no cover
                    device = -1
                self._tokenizer = tokenizer
                self._pipeline = pipeline(
                    'text-generation', model=model, tokenizer=tokenizer, device=device
                )
                log.info('Prompt Guardian: loaded %s from %s', self.label, self.model_path)
                return self._pipeline
            except ClassifierError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._load_error = f'{self.label} failed to load: {exc}'
                log.warning(self._load_error)
                raise ClassifierError(self._load_error) from exc


async def evaluate_classifier(
    classifier: _BaseClassifier | None,
    text: str,
    *,
    category: str,
    layer: Layer,
    threshold: float,
) -> Verdict:
    """Run one classifier and convert its score into a Verdict.

    Coroutine by design: inference is CPU/GPU-bound and would otherwise block
    the event loop for every other in-flight chat request. ``asyncio.to_thread``
    keeps the guardian from becoming a throughput bottleneck on a shared box.

    Raises :class:`ClassifierError` on infrastructure problems so the caller
    can apply the deployment's fail-open/fail-closed policy in one place.
    """
    if classifier is None or not text.strip():
        return Verdict(layer=layer)
    # to_thread is unavailable for a None classifier path but keep types clear.
    score = await asyncio.to_thread(classifier.score, text)
    if score >= threshold:
        return Verdict(
            action='block',
            category=category,
            layer=layer,
            score=score,
            rule=f'{category}.classifier',
            detail=f'{classifier.label} score {score:.3f} >= {threshold:.2f}',
        )
    return Verdict(layer=layer, score=score)


#: Category -> (layer, default threshold) for the classifier tiers.
CLASSIFIER_CATEGORIES: dict[str, tuple[Layer, float]] = {
    Category.INJECTION: (Layer.INJECTION, 0.85),
    Category.HARM: (Layer.HARM, 0.85),
}
