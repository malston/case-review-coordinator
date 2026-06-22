"""Route review per field on calibrated confidence; measure without masking.

A low-confidence field goes to a human even if the rest of the verdict is
pristine -- a document-level average lets a strong field drag a weak high-stakes
field across the auto-approve line. Confidence must be calibrated against ground
truth, and accuracy must be reported per field with stratified sampling that
over-covers the rare/high-stakes strata.
"""

from statistics import mean

from case_review.routing import (
    FieldConfidence,
    LabeledPrediction,
    aggregate_accuracy,
    is_calibrated,
    per_field_accuracy,
    proportional_plan,
    route_fields,
    stratified_plan,
)


def _route(decisions, field):
    return next(d for d in decisions if d.field == field)


# ---- per-field routing beats a document-level average ----------------------

def test_weak_high_stakes_field_routes_to_human_even_when_average_would_approve():
    fields = [
        FieldConfidence("counterparty_identity", 0.55, high_stakes=True),
        FieldConfidence("renewal", 0.99),
        FieldConfidence("notice_period", 0.99),
        FieldConfidence("payment_terms", 0.99),
        FieldConfidence("governing_law", 0.99),
    ]
    decisions = route_fields(fields, threshold=0.9)

    # The document-level average clears the bar -- the distractor would auto-approve.
    assert mean(f.confidence for f in fields) >= 0.9
    # Per-field routing still sends the weak high-stakes field to a human.
    assert _route(decisions, "counterparty_identity").route == "human_review"
    assert _route(decisions, "renewal").route == "auto_approve"


# ---- calibration: a score is a measurement, not a vibe ---------------------

def test_route_fields_auto_approves_exactly_at_the_threshold():
    # Pin the >= vs > decision: a field exactly at the threshold auto-approves.
    decisions = route_fields([FieldConfidence("f", 0.9)], threshold=0.9)
    assert decisions[0].route == "auto_approve"


def test_route_fields_routes_just_below_the_threshold_to_human():
    decisions = route_fields([FieldConfidence("f", 0.8999)], threshold=0.9)
    assert decisions[0].route == "human_review"


def test_calibration_holds_exactly_at_the_tolerance_boundary():
    # Observed accuracy == threshold - tolerance (0.85) is still calibrated.
    samples = [LabeledPrediction(0.95, correct=True) for _ in range(85)]
    samples += [LabeledPrediction(0.95, correct=False) for _ in range(15)]
    assert is_calibrated(samples, threshold=0.9, tolerance=0.05) is True


def test_calibration_fails_just_below_the_tolerance_boundary():
    samples = [LabeledPrediction(0.95, correct=True) for _ in range(84)]
    samples += [LabeledPrediction(0.95, correct=False) for _ in range(16)]
    assert is_calibrated(samples, threshold=0.9, tolerance=0.05) is False


def test_calibrated_scores_pass_the_ground_truth_check():
    # In the >=0.9 band, ~90% are actually correct.
    samples = [LabeledPrediction(0.95, correct=True) for _ in range(9)]
    samples.append(LabeledPrediction(0.95, correct=False))
    assert is_calibrated(samples, threshold=0.9) is True


def test_overconfident_scores_fail_the_ground_truth_check():
    # Scores say >=0.9 but only 60% are correct -- the score is a vibe, not a
    # measurement, and routing on it would auto-approve wrong fields.
    samples = [LabeledPrediction(0.95, correct=True) for _ in range(6)]
    samples += [LabeledPrediction(0.95, correct=False) for _ in range(4)]
    assert is_calibrated(samples, threshold=0.9) is False


# ---- measurement: per-field accuracy vs a masking aggregate ----------------

def test_aggregate_accuracy_masks_a_concentrated_high_stakes_error():
    by_field = {
        "renewal": [True] * 50,
        "notice_period": [True] * 50,
        "payment_terms": [True] * 48 + [False] * 2,
        "counterparty_identity": [False] * 5 + [True] * 5,  # 50% on a high-stakes field
    }
    # The single aggregate number looks healthy...
    assert aggregate_accuracy(by_field) > 0.9
    # ...but per-field accuracy exposes the high-stakes field's failure.
    assert per_field_accuracy(by_field)["counterparty_identity"] == 0.5


# ---- stratified sampling over-covers the rare/high-stakes strata -----------

def test_proportional_sampling_under_covers_a_rare_high_stakes_stratum():
    sizes = {"common": 995, "claim_amount": 5}  # claim_amount is rare AND high-stakes
    plan = proportional_plan(sizes, n=50)
    # Frequency-proportional sampling barely touches the rare stratum.
    assert plan["claim_amount"] == 0


def test_stratified_sampling_guarantees_coverage_of_the_rare_high_stakes_stratum():
    sizes = {"common": 995, "claim_amount": 5}
    plan = stratified_plan(sizes, n=50, high_stakes={"claim_amount"}, floor=10)
    # The high-stakes stratum is deliberately over-covered, not sampled by frequency.
    assert plan["claim_amount"] >= 10
