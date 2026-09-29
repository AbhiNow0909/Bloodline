"""Flag a value against its reference bounds (deterministic, Section 4.4)."""

from decimal import Decimal

from app.models import MetricFlag
from app.services.normalization.ranges import Bounds


def compute_flag(value: Decimal | None, bounds: Bounds | None) -> MetricFlag:
    if value is None or bounds is None or (bounds.low is None and bounds.high is None):
        return "unknown"
    if bounds.low is not None and value < bounds.low:
        return "low"
    if bounds.high is not None and value > bounds.high:
        return "high"
    return "normal"
