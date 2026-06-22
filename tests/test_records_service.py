"""The Records Service: the external counterparty-history seam.

This is where the load-bearing timeout and the ambiguous record match occur. The
service keeps two outcomes that must never collapse into one another:
  - a successful query that finds nothing  -> isError False, data []
  - a timeout / outage                      -> isError True, no data
"""

from case_review.records_service import CounterpartyMatch, StubRecordsService


def _service(**kw) -> StubRecordsService:
    base = dict(
        matches=[CounterpartyMatch(counterparty_id="CP-100", name="Acme Robotics LLC",
                                   registered="2019-06-01")],
        history={"CP-100": [{"claim_id": "PR-7", "amount": 50000, "status": "settled"}]},
    )
    base.update(kw)
    return StubRecordsService(**base)


def test_history_found_returns_the_claims():
    result = _service().fetch_claim_history("CP-100")
    assert result["isError"] is False
    assert result["data"][0]["claim_id"] == "PR-7"


def test_known_counterparty_with_no_claims_is_a_valid_empty_answer():
    svc = _service(history={"CP-100": []})
    result = svc.fetch_claim_history("CP-100")
    assert result["isError"] is False
    assert result["data"] == []  # confirmed: none -- this is an answer


def test_timeout_is_a_structured_error_not_an_empty_answer():
    svc = _service(timeout_on_history=True)
    result = svc.fetch_claim_history("CP-100")
    assert result["isError"] is True
    assert result["category"] == "timeout"
    assert result["retryable"] is True
    assert "data" not in result  # NOT data:[] -- the outage cannot read as "none"


def test_outage_is_a_structured_error():
    svc = _service(outage_on_history=True)
    result = svc.fetch_claim_history("CP-100")
    assert result["isError"] is True
    assert result["category"] == "outage"


def test_match_counterparty_returns_all_matches_for_disambiguation():
    svc = _service(matches=[
        CounterpartyMatch(counterparty_id="CP-100", name="Acme Robotics LLC",
                          registered="2019-06-01"),
        CounterpartyMatch(counterparty_id="CP-771", name="Acme Robotics LLC",
                          registered="2025-02-14"),
    ])
    result = svc.match_counterparty("Acme Robotics LLC")
    assert result["isError"] is False
    assert len(result["data"]) == 2  # two same-named parties -- ambiguity is visible
