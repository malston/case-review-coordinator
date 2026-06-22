"""Structured error context -- never a bare null, never a fabricated empty.

An access failure (timeout / outage / permission) is the *absence of an answer*;
it carries no `data` field, so it can never be misread as `data: []` ("none
found"). A valid empty result is an *answer* and carries `data: []`.
"""

from case_review.errors import records_error, records_ok


def test_error_carries_full_structured_context():
    err = records_error(
        category="timeout",
        operation="fetch_claim_history",
        detail="counterparty-history service did not respond within 5s",
        retryable=True,
    )
    assert err["isError"] is True
    assert err["category"] == "timeout"
    assert err["operation"] == "fetch_claim_history"
    assert err["retryable"] is True
    assert "did not respond" in err["detail"]


def test_ok_result_is_not_an_error_and_carries_data():
    ok = records_ok(operation="fetch_claim_history", data=[])
    assert ok["isError"] is False
    assert ok["operation"] == "fetch_claim_history"
    assert ok["data"] == []  # a real answer: "confirmed, none"


def test_access_failure_carries_no_data_field():
    # The cardinal sin is an outage that reads as "no prior claims found." The
    # error object structurally cannot do that: it has no `data` key to mistake
    # for an empty answer.
    err = records_error(
        category="timeout", operation="fetch_claim_history", detail="...", retryable=True
    )
    assert "data" not in err
