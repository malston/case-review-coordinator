"""The coordinator orchestration steps and their effect on real state.

Covers context isolation (the Document Reader's raw reads never reach the
coordinator's window), the load-bearing history fetch (timeout -> terminate, and
the finalize gate stays shut), and synthesis at finalize.
"""

from decimal import Decimal

import pytest

from case_review.coordinator import Coordinator, FinalizeBlockedError
from case_review.records_service import CounterpartyMatch, StubRecordsService
from case_review.schemas import CaseFacts, Claim
from case_review.state import CaseState
from case_review.subagents import DocumentBundle, StubDocumentReader
from case_review.window import WorkingMemory

RAW_CONTRACT = "MASTER AGREEMENT\n" + ("boilerplate clause text " * 500)


def _facts() -> CaseFacts:
    return CaseFacts(
        case_id="case-acme-2026-014",
        counterparty="Acme Robotics LLC",
        contract_id="MSA-2024-ACME",
        claim_amount=Decimal("4200000.00"),
        key_dates={"claim_filed": "2026-05-20"},
    )


def _claims() -> list[Claim]:
    return [
        Claim(field="renewal", value="auto-renews annually",
              source="Master Agreement §7.2", effective_date="2024-03-01"),
        Claim(field="payment_terms", value="Net 30",
              source="Master Agreement §4.1", effective_date="2024-03-01"),
        Claim(field="payment_terms", value="Net 60",
              source="Amendment 2 §2", effective_date="2026-01-15"),
    ]


def _coordinator(records: StubRecordsService, claims=None) -> Coordinator:
    facts = _facts()
    state = CaseState(facts=facts, memory=WorkingMemory(facts=facts))
    reader = StubDocumentReader(claims=claims if claims is not None else _claims())
    return Coordinator(state=state, reader=reader, records=records)


def _records(**kw) -> StubRecordsService:
    base = dict(
        matches=[CounterpartyMatch("CP-100", "Acme Robotics LLC", "2019-06-01")],
        history={"CP-100": [{"claim_id": "PR-7", "amount": 50000, "status": "settled"}]},
    )
    base.update(kw)
    return StubRecordsService(**base)


def test_document_reader_raw_reads_never_enter_the_coordinator_window():
    coord = _coordinator(_records())
    bundle = DocumentBundle(documents={"acme_msa.pdf": RAW_CONTRACT})
    coord.read_documents(bundle)

    window = coord.state.memory.render()
    # The coordinator's window holds the short claim summary...
    assert "auto-renews annually" in window
    # ...but NOT the thousands of tokens of raw contract boilerplate.
    assert "boilerplate clause text" not in window
    # The reader did burn its own window on the raw read.
    assert coord.reader.chars_read > 10_000


def test_resolve_counterparty_single_match_sets_the_id():
    coord = _coordinator(_records())
    res = coord.resolve_counterparty()
    assert res.resolved_id == "CP-100"
    assert coord.state.resolved_counterparty_id == "CP-100"
    assert coord.state.identity_ambiguous is False


def test_resolve_counterparty_ambiguous_match_does_not_set_an_id():
    records = _records(matches=[
        CounterpartyMatch("CP-100", "Acme Robotics LLC", "2019-06-01"),
        CounterpartyMatch("CP-771", "Acme Robotics LLC", "2025-02-14"),
    ])
    coord = _coordinator(records)
    res = coord.resolve_counterparty()
    assert res.needs_disambiguation is True
    assert coord.state.resolved_counterparty_id is None
    assert coord.state.identity_ambiguous is True


def test_resolve_counterparty_lookup_timeout_escalates_without_resolving():
    class TimingOutMatch(StubRecordsService):
        def match_counterparty(self, name: str) -> dict:
            from case_review.errors import records_error

            return records_error(
                category="timeout", operation="match_counterparty",
                detail="lookup did not respond", retryable=True,
            )

    coord = _coordinator(TimingOutMatch())
    res = coord.resolve_counterparty()
    assert res.escalate is True
    assert coord.state.resolved_counterparty_id is None
    assert coord.state.identity_ambiguous is False
    # The outage is recorded so the gate has the structured error to act on.
    assert coord.state.last_error["category"] == "timeout"


def test_fetch_history_success_records_ok_state():
    coord = _coordinator(_records())
    coord.resolve_counterparty()
    outcome = coord.fetch_history()
    assert outcome.proceed is True
    assert coord.state.history_status == "ok"
    assert coord.state.history[0]["claim_id"] == "PR-7"


def test_fetch_history_timeout_terminates_and_records_failed_state():
    coord = _coordinator(_records(timeout_on_history=True))
    coord.resolve_counterparty()
    outcome = coord.fetch_history()
    assert outcome.terminated is True
    assert outcome.escalated is True
    assert coord.state.history_status == "failed"
    assert coord.state.history is None  # NOT [] -- the outage is not "none found"
    assert coord.state.last_error["category"] == "timeout"


def test_fetch_history_timeout_clears_any_stale_history():
    # A prior populate must not survive a later failure: status 'failed' and a
    # non-None history would be a contradictory, misleading state.
    coord = _coordinator(_records(timeout_on_history=True))
    coord.resolve_counterparty()
    coord.state.history = [{"claim_id": "STALE", "amount": 1}]  # seed stale data
    coord.fetch_history()
    assert coord.state.history is None


def test_finalize_is_blocked_after_a_history_timeout():
    coord = _coordinator(_records(timeout_on_history=True))
    coord.read_documents(DocumentBundle(documents={"x": RAW_CONTRACT}))
    coord.resolve_counterparty()
    coord.fetch_history()
    with pytest.raises(FinalizeBlockedError):
        coord.finalize()


def test_finalize_synthesizes_findings_and_routes_contradiction_to_human():
    # Add a genuine contradiction on governing_law (same effective date).
    claims = _claims() + [
        Claim(field="governing_law", value="Delaware",
              source="Master Agreement §12", effective_date="2024-03-01"),
        Claim(field="governing_law", value="New York",
              source="Schedule A §1", effective_date="2024-03-01"),
    ]
    coord = _coordinator(_records(), claims=claims)
    coord.read_documents(DocumentBundle(documents={"x": RAW_CONTRACT}))
    coord.resolve_counterparty()
    coord.fetch_history()
    verdict = coord.finalize()

    # Temporal conflict resolved by supersession.
    payment = next(f for f in verdict.findings if f.field == "payment_terms")
    assert payment.kind == "superseded"
    assert payment.value == "Net 60"
    # Genuine contradiction surfaced, and it forces human review.
    gov = next(f for f in verdict.findings if f.field == "governing_law")
    assert gov.kind == "contradiction"
    assert verdict.disposition == "human_review"
