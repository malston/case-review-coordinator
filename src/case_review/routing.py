"""Human-review routing by calibrated, per-field confidence -- and honest measurement.

Routing is per field, not per document: a document-level average lets a strong
field drag a weak high-stakes field across the auto-approve line. The confidence
that drives routing must be *calibrated* against ground truth ("fields scored
>=0.9 are right ~90% of the time"), which `is_calibrated` checks empirically --
an uncalibrated score is a vibe, the same self-reported-confidence trap that
disqualifies confidence as an escalation trigger.

Measuring the pipeline's accuracy: a single aggregate number masks concentrated,
high-stakes errors, so report `per_field_accuracy` and sample with
`stratified_plan`, which deliberately over-covers the rare/high-stakes strata
rather than sampling in proportion to frequency.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass
class FieldConfidence:
    field: str
    confidence: float
    high_stakes: bool = False


@dataclass
class RouteDecision:
    field: str
    route: Literal["auto_approve", "human_review"]
    reason: str


def route_fields(
    fields: list[FieldConfidence], *, threshold: float = 0.9
) -> list[RouteDecision]:
    decisions: list[RouteDecision] = []
    for f in fields:
        if f.confidence < threshold:
            decisions.append(
                RouteDecision(
                    f.field, "human_review",
                    f"calibrated confidence {f.confidence} < {threshold}",
                )
            )
        else:
            decisions.append(
                RouteDecision(
                    f.field, "auto_approve",
                    f"calibrated confidence {f.confidence} >= {threshold}",
                )
            )
    return decisions


# ---- calibration against ground truth --------------------------------------

@dataclass
class LabeledPrediction:
    confidence: float
    correct: bool


def observed_accuracy_at_or_above(samples: list[LabeledPrediction], threshold: float) -> float:
    band = [s for s in samples if s.confidence >= threshold]
    if not band:
        raise ValueError(f"no labeled predictions at or above {threshold}")
    return sum(s.correct for s in band) / len(band)


def is_calibrated(
    samples: list[LabeledPrediction], *, threshold: float = 0.9, tolerance: float = 0.05
) -> bool:
    """Calibrated iff the observed accuracy in the >=threshold band is at least
    `threshold - tolerance`. Confidence the model asserts but cannot back with
    ground truth is not a measurement."""
    return observed_accuracy_at_or_above(samples, threshold) >= threshold - tolerance


# ---- disaggregated measurement ---------------------------------------------

def per_field_accuracy(by_field: dict[str, list[bool]]) -> dict[str, float]:
    return {field: sum(results) / len(results) for field, results in by_field.items()}


def aggregate_accuracy(by_field: dict[str, list[bool]]) -> float:
    all_results = [r for results in by_field.values() for r in results]
    return sum(all_results) / len(all_results)


# ---- sampling plans --------------------------------------------------------

def proportional_plan(strata_sizes: dict[str, int], n: int) -> dict[str, int]:
    """Frequency-proportional sampling -- under-covers rare strata by design."""
    total = sum(strata_sizes.values())
    return {stratum: round(n * size / total) for stratum, size in strata_sizes.items()}


def stratified_plan(
    strata_sizes: dict[str, int], n: int, *, high_stakes: set[str], floor: int
) -> dict[str, int]:
    """Stratified sampling that guarantees at least `floor` samples for each
    high-stakes stratum regardless of how rare it is, then fills the rest
    proportionally across the remaining strata."""
    plan = {stratum: (floor if stratum in high_stakes else 0) for stratum in strata_sizes}
    remaining = n - sum(plan.values())
    common = {s: size for s, size in strata_sizes.items() if s not in high_stakes}
    common_total = sum(common.values())
    if remaining > 0 and common_total > 0:
        for stratum, size in common.items():
            plan[stratum] += round(remaining * size / common_total)
    return plan
