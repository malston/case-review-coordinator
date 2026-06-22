"""PreToolUse gate for finalize_verdict -- the load-bearing linchpin.

The gate reads real completion state, never the model's narration. An approved
verdict requires: claims read, the counterparty identity resolved (not
ambiguous), and a SUCCESSFUL load-bearing claim-history fetch. A timed-out
history sets status "failed", and the gate refuses to finalize -- so a timeout
can never become a clean "no prior claims" pass.
"""

from decimal import Decimal

from case_review.gate import pre_tool_finalize
from case_review.schemas import CaseFacts, Claim
from case_review.state import CaseState
from case_review.window import WorkingMemory


def _state(**kw) -> CaseState:
    facts = CaseFacts(
        case_id="case-acme-2026-014",
        counterparty="Acme Robotics LLC",
        contract_id="MSA-2024-ACME",
        claim_amount=Decimal("4200000.00"),
        key_dates={"claim_filed": "2026-05-20"},
    )
    state = CaseState(facts=facts, memory=WorkingMemory(facts=facts))
    state.claims = [Claim(field="renewal", value="auto-renews annually",
                          source="Master Agreement §7.2", effective_date="2024-03-01")]
    state.resolved_counterparty_id = "CP-100"
    state.history_status = "ok"
    for k, v in kw.items():
        setattr(state, k, v)
    return state


def test_finalize_allowed_when_all_real_state_is_present():
    assert pre_tool_finalize(_state()).allowed is True


def test_finalize_blocked_when_history_timed_out():
    decision = pre_tool_finalize(_state(history_status="failed"))
    assert decision.allowed is False
    assert "history" in decision.reason.lower()


def test_finalize_blocked_when_history_never_fetched():
    decision = pre_tool_finalize(_state(history_status="missing"))
    assert decision.allowed is False


def test_finalize_blocked_when_identity_unresolved():
    decision = pre_tool_finalize(_state(resolved_counterparty_id=None))
    assert decision.allowed is False


def test_finalize_blocked_when_identity_ambiguous():
    decision = pre_tool_finalize(_state(resolved_counterparty_id=None, identity_ambiguous=True))
    assert decision.allowed is False
    assert "ambiguous" in decision.reason.lower()


def test_finalize_blocked_when_no_claims_read():
    decision = pre_tool_finalize(_state(claims=[]))
    assert decision.allowed is False
