"""Prompt Guardian: rejects off-policy prompts before the model or tools run.

Design constraints (see docs/PROMPT_GUARDIAN.md):

* Fully on-prem. No network calls, ever.
* Bilingual (Arabic + English) from layer zero, not retrofitted.
* Cheapest layers first, so the expensive path is rarely reached.
* Fail-closed for configured categories, fail-open for infrastructure errors
  that are explicitly opted into (see ``fail_open`` in settings).
* Shadow mode by default so IT can measure false positives before enforcing.
"""

from open_webui.cbo.guardian.types import (
    Action,
    Category,
    Decision,
    Layer,
    Verdict,
)

__all__ = [
    'Action',
    'Category',
    'Decision',
    'Layer',
    'Verdict',
]
