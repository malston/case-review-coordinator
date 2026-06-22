"""Terminate-vs-degrade: the dividing line is honesty about what failed.

A failed step that is load-bearing must terminate/escalate -- never silently
suppress. A non-critical step may degrade, but only with an honest, scoped label
naming what failed. The partial result is not what makes degradation acceptable;
the honesty is.
"""

from case_review.errors import records_error, records_ok
from case_review.reliability import handle_step_result


def _timeout() -> dict:
    return records_error(
        category="timeout",
        operation="fetch_claim_history",
        detail="did not respond within 5s",
        retryable=True,
    )


def test_successful_step_proceeds():
    outcome = handle_step_result(records_ok(operation="fetch_claim_history", data=[]),
                                 load_bearing=True)
    assert outcome.proceed is True
    assert outcome.terminated is False
    assert outcome.escalated is False


def test_load_bearing_failure_terminates_and_escalates():
    outcome = handle_step_result(_timeout(), load_bearing=True)
    assert outcome.proceed is False
    assert outcome.terminated is True
    assert outcome.escalated is True


def test_load_bearing_failure_never_silently_proceeds():
    # The whole point: a load-bearing timeout can never become a clean pass.
    outcome = handle_step_result(_timeout(), load_bearing=True)
    assert outcome.proceed is False


def test_non_critical_failure_degrades_with_an_honest_scoped_label():
    outcome = handle_step_result(_timeout(), load_bearing=False)
    assert outcome.proceed is True  # degrade -- keep going
    assert outcome.terminated is False
    # ...but the label names exactly what failed -- this is what makes it
    # graceful degradation rather than silent suppression.
    assert "fetch_claim_history" in outcome.label
    assert "timeout" in outcome.label
    assert "not assessed" in outcome.label


def test_terminated_outcome_also_names_what_failed():
    outcome = handle_step_result(_timeout(), load_bearing=True)
    assert "fetch_claim_history" in outcome.label
    assert "timeout" in outcome.label
