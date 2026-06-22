"""Escalation on objective state, and ambiguous-identity handling.

Three valid triggers, each detectable from objective state: explicit request,
repeated failure (a count, not first-failure), and out-of-scope / risk
threshold. Frustration is only a threshold modulator -- it can lower the
repeated-failure bar but can never trigger on its own. An ambiguous record match
is a disambiguate-or-escalate trigger; recency is not identity.
"""

from case_review.escalation import resolve_identity, should_escalate

# ---- the three objective triggers ------------------------------------------

def test_explicit_request_escalates():
    d = should_escalate(explicit_request=True)
    assert d.escalate is True
    assert d.trigger == "explicit_request"


def test_out_of_scope_escalates():
    d = should_escalate(out_of_scope=True)
    assert d.escalate is True
    assert d.trigger == "out_of_scope"


def test_repeated_failure_at_threshold_escalates():
    d = should_escalate(failure_count=3, retry_threshold=3)
    assert d.escalate is True
    assert d.trigger == "repeated_failure"


def test_first_failure_does_not_escalate():
    # "Repeated" means a count, not the first failure.
    d = should_escalate(failure_count=1, retry_threshold=3)
    assert d.escalate is False


def test_explicit_request_takes_precedence_over_a_concurrent_repeated_failure():
    # When more than one trigger is live, the explicit request is reported.
    d = should_escalate(explicit_request=True, failure_count=5, retry_threshold=3)
    assert d.escalate is True
    assert d.trigger == "explicit_request"


# ---- frustration is a modulator, never a trigger ---------------------------

def test_frustration_alone_never_escalates():
    # No failures, just detected frustration -> not a trigger (unreliable inference).
    d = should_escalate(failure_count=0, frustration=True)
    assert d.escalate is False


def test_frustration_lowers_the_repeated_failure_threshold():
    # 2nd failure WITHOUT frustration: keep trying.
    assert should_escalate(failure_count=2, retry_threshold=3, frustration=False).escalate is False
    # 2nd failure WITH frustration: stop retrying now -- frustration modulated the
    # threshold of the real (repeated-failure) trigger.
    d = should_escalate(failure_count=2, retry_threshold=3, frustration=True)
    assert d.escalate is True
    assert d.trigger == "repeated_failure"


def test_frustration_cannot_lower_the_bar_below_a_repeated_failure():
    # Even frustrated, a single failure is not "repeated".
    d = should_escalate(failure_count=1, retry_threshold=3, frustration=True)
    assert d.escalate is False


# ---- ambiguous record match ------------------------------------------------

def _match(data: list[dict]) -> dict:
    return {"isError": False, "operation": "match_counterparty", "data": data}


def test_single_match_resolves_cleanly():
    res = resolve_identity(_match([{"counterparty_id": "CP-100", "name": "Acme Robotics LLC",
                                    "registered": "2019-06-01"}]))
    assert res.resolved_id == "CP-100"
    assert res.needs_disambiguation is False


def test_two_same_named_parties_never_silently_picks():
    candidates = [
        {"counterparty_id": "CP-100", "name": "Acme Robotics LLC", "registered": "2019-06-01"},
        {"counterparty_id": "CP-771", "name": "Acme Robotics LLC", "registered": "2025-02-14"},
    ]
    res = resolve_identity(_match(candidates))
    # Does NOT pick a winner -- not the newer one, not either one.
    assert res.resolved_id is None
    assert res.needs_disambiguation is True
    assert len(res.candidates) == 2
    # recency-is-not-identity must be the stated reason.
    assert "recency is not identity" in res.reason.lower()


def test_no_match_escalates():
    res = resolve_identity(_match([]))
    assert res.resolved_id is None
    assert res.escalate is True


def test_match_lookup_access_failure_escalates_and_does_not_crash():
    # The Records Service can time out on the lookup itself (same dict contract as
    # the history fetch). An access failure must escalate as a structured outcome,
    # never crash, and never be read as "no counterparty matched."
    from case_review.errors import records_error

    err = records_error(
        category="timeout", operation="match_counterparty",
        detail="lookup did not respond", retryable=True,
    )
    res = resolve_identity(err)
    assert res.resolved_id is None
    assert res.escalate is True
    assert res.needs_disambiguation is False
    # The reason names the failure -- it is NOT reported as "no match found".
    assert "timeout" in res.reason.lower()
    assert "no counterparty matched" not in res.reason.lower()
