"""Framework-aligned output envelope.

The DIA / TDAH framework specifies three canonical output types:

  • ABS     — absolute count or volume (e.g. 142 mentions)
  • PERCENT — share or rate (e.g. 23.4% positive)
  • SCORE   — 0–100 normalised composite (e.g. Brand Potential Index = 67)

Every analytic that surfaces to a dashboard or API should wrap its result in
`MetricValue` so the frontend can render units, scales, and badges uniformly,
and so downstream consumers (alert engine, action recos) can reason about
values regardless of which intelligence module emitted them.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


class OutputKind(str, enum.Enum):
    ABS = "abs"
    PERCENT = "percent"
    SCORE = "score"


@dataclass
class MetricValue:
    """Canonical output envelope. All intelligence modules emit this shape."""
    kind: OutputKind
    value: float
    label: str
    # Optional fields below are populated when the producing module has them
    unit: Optional[str] = None                     # e.g. "mentions", "%", "0–100"
    delta: Optional[float] = None                  # Δ vs comparison period
    delta_kind: Optional[OutputKind] = None        # delta is ABS or PERCENT typically
    comparison_window: Optional[str] = None        # e.g. "vs previous 30d"
    confidence: Optional[float] = None             # 0–1
    sample_size: Optional[int] = None
    computed_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "value": round(self.value, 4) if self.value is not None else None,
            "label": self.label,
            "unit": self.unit,
            "delta": round(self.delta, 4) if self.delta is not None else None,
            "delta_kind": self.delta_kind.value if self.delta_kind else None,
            "comparison_window": self.comparison_window,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "sample_size": self.sample_size,
            "computed_at": self.computed_at.isoformat(),
            "metadata": self.metadata,
        }


def clamp_score(raw: Optional[float], lo: float = 0.0, hi: float = 100.0) -> Optional[float]:
    """Clamp arbitrary composites into the 0–100 SCORE range. None passes through
    (an undefined metric — e.g. momentum with no activity — shown as 'No signal')."""
    if raw is None:
        return None
    if raw != raw:  # NaN guard
        return lo
    return max(lo, min(hi, raw))


def as_score(value: float, label: str, **kw) -> MetricValue:
    return MetricValue(
        kind=OutputKind.SCORE,
        value=clamp_score(value),
        label=label,
        unit="0–100",
        **kw,
    )


def as_percent(value: float, label: str, **kw) -> MetricValue:
    return MetricValue(
        kind=OutputKind.PERCENT,
        value=value,
        label=label,
        unit="%",
        **kw,
    )


def as_abs(value: float, label: str, unit: str = "count", **kw) -> MetricValue:
    return MetricValue(
        kind=OutputKind.ABS,
        value=value,
        label=label,
        unit=unit,
        **kw,
    )


@dataclass
class MetricBundle:
    """Group of related MetricValues — what a dashboard tile usually consumes."""
    name: str
    metrics: List[MetricValue] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "metrics": [m.to_dict() for m in self.metrics],
            "context": self.context,
        }
