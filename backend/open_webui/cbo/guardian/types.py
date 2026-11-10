"""Result types shared by every guard layer.

Kept deliberately small and dependency-free so the engine can be unit tested
without FastAPI, a database, or the ML stack installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Action(str):
    """What the guardian wants done with a prompt."""

    ALLOW = 'allow'
    BLOCK = 'block'


class Category(str):
    """Why a prompt was flagged.

    ``INJECTION`` and ``HARM`` are classifier-driven threat classes that must be
    kept separate: they have different training data and different failure
    modes. ``OFF_TOPIC`` is CBO policy, not a vendor taxonomy -- it is decided
    by the business-scope allowlist.
    """

    INJECTION = 'injection'
    HARM = 'harm'
    OFF_TOPIC = 'off_topic'
    OVERSIZED = 'oversized'


class Layer(IntEnum):
    """Evaluation tiers, cheapest first. Lower value == evaluated earlier."""

    NORMALIZE = 0  # L0: unicode hardening, no verdicts
    RULES = 1  # L1: deterministic bilingual rules
    INJECTION = 2  # L2: optional on-prem classifier
    HARM = 3  # L3: optional on-prem classifier
    SCOPE = 4  # L4: optional business-scope classifier


@dataclass
class Verdict:
    """Outcome of one evaluation.

    ``hit`` is True when the prompt should be rejected. ``score`` is the
    confidence (0..1) when a classifier produced it, else 1.0 for a
    deterministic rule match.
    """

    action: Action = Action.ALLOW
    category: str | None = None
    layer: Layer | None = None
    score: float = 0.0
    rule: str | None = None
    detail: str = ''

    @property
    def hit(self) -> bool:
        return self.action == Action.BLOCK

    def to_dict(self) -> dict[str, Any]:
        return {
            'action': str(self.action),
            'category': str(self.category) if self.category else None,
            'layer': int(self.layer) if self.layer is not None else None,
            'score': round(float(self.score), 4),
            'rule': self.rule,
            'detail': self.detail,
        }


@dataclass
class Decision:
    """Full result of a guard evaluation, including audit metadata."""

    verdict: Verdict = field(default_factory=Verdict)
    #: True when the verdict is logged but not enforced (shadow mode).
    shadow: bool = False
    #: True when an infrastructure failure prevented a full evaluation.
    degraded: bool = False
    #: Layers that actually ran, in order, with per-layer latency in ms.
    trace: list[dict[str, Any]] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """Whether the caller should actually refuse the request."""
        return self.verdict.hit and not self.shadow

    def to_dict(self) -> dict[str, Any]:
        return {
            'verdict': self.verdict.to_dict(),
            'shadow': self.shadow,
            'degraded': self.degraded,
            'blocked': self.blocked,
            'trace': self.trace,
        }
