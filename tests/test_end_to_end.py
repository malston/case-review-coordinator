"""End-to-end through the real loop, tools, and finalize gate -- the two linchpins.

Linchpin 1 (the timeout test): a load-bearing Records Service timeout surfaces as
a structured error and the gate keeps finalize shut -- it never becomes "no prior
claims," and never an `[]` masquerading as a valid empty answer.

Linchpin 2 (the conflict test): the genuine contradiction is surfaced with both
sources attributed; the temporal conflict is resolved by supersession with its
provenance preserved.

Each linchpin is shown alongside the distractor it defeats, failing-then-defended.
"""

from case_review.errors import records_ok
from case_review.harness import build_harness
from case_review.loop import (
    Response,
    ScriptedClient,
    run_agentic_loop,
    text_block,
    tool_use_block,
)
from case_review.records_service import StubRecordsService
from case_review.sample_case import (
    CASE_FACTS,
    CLAIM_HISTORY,
    RAW_DOCUMENTS,
    SAMPLE_CLAIMS,
    SINGLE_MATCH,
)
from case_review.state import CaseState
from case_review.subagents import StubDocumentReader
from case_review.synthesis import synthesize
from case_review.window import WorkingMemory


def _coordinator(records: StubRecordsService):
    from case_review.coordinator import Coordinator

    state = CaseState(facts=CASE_FACTS, memory=WorkingMemory(facts=CASE_FACTS))
    reader = StubDocumentReader(claims=SAMPLE_CLAIMS)
    return Coordinator(state=state, reader=reader, records=records)


def _full_script(*, skip_history: bool = False) -> list[Response]:
    steps = [
        Response("tool_use", [tool_use_block("d1", "read_documents", {})]),
        Response("tool_use", [tool_use_block("c1", "resolve_counterparty", {})]),
    ]
    if not skip_history:
        steps.append(Response("tool_use", [tool_use_block("h1", "fetch_history", {})]))
    steps.append(Response("tool_use", [
        text_block("Counterparty history checked; finalizing."),
        tool_use_block("f1", "finalize_verdict", {}),
    ]))
    steps.append(Response("end_turn", [text_block("Done.")]))
    return steps


def _run(records: StubRecordsService, *, skip_history: bool = False):
    coord = _coordinator(records)
    tools, pre_hooks, finalized = build_harness(coord, RAW_DOCUMENTS)
    messages = run_agentic_loop(
        ScriptedClient(_full_script(skip_history=skip_history)),
        [{"role": "user", "content": "Assess the case and issue a verdict."}],
        tools=tools, pre_hooks=pre_hooks, state=coord,
    )
    errors = [
        b["content"]
        for m in messages
        if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"]
        if isinstance(b, dict) and b.get("type") == "tool_result" and b["is_error"]
    ]
    return coord, finalized, errors


# ---- Linchpin 1: the timeout test ------------------------------------------

def test_timeout_test_load_bearing_timeout_never_becomes_a_clean_verdict():
    records = StubRecordsService(
        matches=SINGLE_MATCH, history=CLAIM_HISTORY, timeout_on_history=True
    )
    coord, finalized, errors = _run(records)

    # No verdict issued -- the load-bearing timeout terminated the path.
    assert finalized == []
    # The timeout surfaced as a STRUCTURED error (category timeout), not a null,
    # not an empty list, not a stack trace.
    assert any('"category": "timeout"' in e for e in errors)
    # State proves the outage was never laundered into "no prior claims".
    assert coord.state.history_status == "failed"
    assert coord.state.history is None  # NOT [] -- absence of answer, not "none"
    # And the gate explicitly refused to finalize.
    assert any("load-bearing check did not succeed" in e for e in errors)


def test_timeout_distractor_collapsing_to_empty_would_fabricate_a_clean_pass():
    # THE DISTRACTOR: a Records Service that turns a timeout into a valid empty
    # result (data: []). Show it is a latent disaster, then show our design
    # structurally prevents it.
    class CollapsingRecordsService(StubRecordsService):
        def fetch_claim_history(self, counterparty_id: str) -> dict:
            # The cardinal sin: the outage reads as "confirmed: no prior claims."
            return records_ok(operation="fetch_claim_history", data=[])

    coord, finalized, errors = _run(CollapsingRecordsService(matches=SINGLE_MATCH))

    # FAILING-THEN-DEFENDED: with the distractor, the gate is satisfied and a
    # verdict IS issued off a fabricated empty -- an outage made the decision.
    assert finalized != []
    assert coord.state.history == []  # the outage now looks like "none found"

    # DEFENSE: the real service never does this -- a timeout is isError True with
    # no data field at all, so it cannot be mistaken for a valid empty answer.
    honest = StubRecordsService(matches=SINGLE_MATCH, timeout_on_history=True)
    result = honest.fetch_claim_history("CP-100")
    assert result["isError"] is True
    assert "data" not in result


# ---- Linchpin 2: the conflict test -----------------------------------------

def test_conflict_test_contradiction_surfaced_and_supersession_resolved_with_trace():
    records = StubRecordsService(matches=SINGLE_MATCH, history=CLAIM_HISTORY)
    coord, finalized, errors = _run(records)

    assert len(finalized) == 1
    verdict = finalized[0]
    by_field = {f.field: f for f in verdict.findings}

    # Genuine contradiction: surfaced, both sources attributed, value not picked.
    gov = by_field["governing_law"]
    assert gov.kind == "contradiction"
    assert gov.value is None
    attributed = {(s.value, s.source) for s in gov.sources}
    assert ("Delaware", "Master Agreement §12") in attributed
    assert ("New York", "Schedule A §1") in attributed

    # Temporal conflict: resolved by supersession WITH provenance preserved.
    pay = by_field["payment_terms"]
    assert pay.kind == "superseded"
    assert pay.value == "Net 60"
    assert pay.changed_from == "Net 30"
    assert "Amendment 2 §2" in pay.provenance and "2026-01-15" in pay.provenance

    # The unresolved contradiction routes the whole verdict to a human.
    assert verdict.disposition == "human_review"


def test_conflict_distractors_time_blind_and_time_reckless_are_both_avoided():
    # THE DISTRACTORS, contrasted with synthesize()'s behavior on the same claims.
    findings = {f.field: f for f in synthesize(SAMPLE_CLAIMS).findings}
    pay = findings["payment_terms"]

    # time-blind distractor: "two values for one field => open dispute." That
    # would mislabel a settled supersession as a contradiction. We do NOT:
    assert pay.kind != "contradiction"
    assert pay.kind == "superseded"

    # time-reckless distractor: "newest wins, drop the rest." That would lose the
    # trace. We keep what changed and when:
    assert pay.changed_from == "Net 30"
    assert "superseding" in pay.provenance.lower()

    # And the genuine contradiction is NOT resolved by erasure -- both survive.
    gov = findings["governing_law"]
    assert {s.value for s in gov.sources} == {"Delaware", "New York"}
