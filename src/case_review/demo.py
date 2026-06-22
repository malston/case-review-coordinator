"""Runnable offline demo: `python -m case_review.demo`.

Drives the real loop, tools, and finalize gate with a ScriptedClient (no API
key) along three trajectories of the same system:

  - happy:    read -> resolve -> fetch_history(ok) -> finalize
              => a verdict is issued; the temporal conflict is resolved with
                 provenance, the genuine contradiction routes to human review.
  - timeout:  read -> resolve -> fetch_history(TIMEOUT) -> finalize
              => the load-bearing history failed; the gate keeps finalize shut.
                 No verdict is issued -- the timeout never becomes "no prior claims."
  - ambiguous: read -> resolve(TWO same-named parties) -> finalize
              => identity unresolved; the gate keeps finalize shut.

The only differences are whether the history fetch succeeded and whether the
counterparty resolved. The model's narration changes nothing.
"""

from dataclasses import dataclass

from case_review.coordinator import Coordinator
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
    AMBIGUOUS_MATCH,
    CASE_FACTS,
    CLAIM_HISTORY,
    RAW_DOCUMENTS,
    SAMPLE_CLAIMS,
    SINGLE_MATCH,
)
from case_review.state import CaseState
from case_review.subagents import StubDocumentReader
from case_review.window import WorkingMemory


def _coordinator(*, timeout: bool, ambiguous: bool) -> Coordinator:
    state = CaseState(facts=CASE_FACTS, memory=WorkingMemory(facts=CASE_FACTS))
    reader = StubDocumentReader(claims=SAMPLE_CLAIMS)
    records = StubRecordsService(
        matches=AMBIGUOUS_MATCH if ambiguous else SINGLE_MATCH,
        history=CLAIM_HISTORY,
        timeout_on_history=timeout,
    )
    return Coordinator(state=state, reader=reader, records=records)


def _script(*, skip_history: bool = False) -> list[Response]:
    steps = [
        Response("tool_use", [tool_use_block("d1", "read_documents", {})]),
        Response("tool_use", [tool_use_block("c1", "resolve_counterparty", {})]),
    ]
    if not skip_history:
        # When the counterparty resolves, the model fetches the load-bearing history.
        steps.append(Response("tool_use", [tool_use_block("h1", "fetch_history", {})]))
    # The model attempts to finalize either way; the gate decides whether it can.
    steps.append(Response("tool_use", [
        text_block("Finalizing."),
        tool_use_block("f1", "finalize_verdict", {}),
    ]))
    steps.append(Response("end_turn", [text_block("Done.")]))
    return steps


@dataclass
class Outcome:
    name: str
    issued: bool
    disposition: str | None
    blocked: list[str]


def _run(name: str, *, timeout: bool, ambiguous: bool) -> Outcome:
    coord = _coordinator(timeout=timeout, ambiguous=ambiguous)
    tools, pre_hooks, finalized = build_harness(coord, RAW_DOCUMENTS)
    # An ambiguous counterparty cannot proceed to the history fetch -- the model
    # stops short and attempts to finalize, which the gate refuses.
    messages = run_agentic_loop(
        ScriptedClient(_script(skip_history=ambiguous)),
        [{"role": "user", "content": "Assess the case and issue a verdict."}],
        tools=tools, pre_hooks=pre_hooks, state=coord,
    )
    blocked = [
        b["content"]
        for m in messages
        if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"]
        if isinstance(b, dict) and b.get("type") == "tool_result" and b["is_error"]
    ]
    return Outcome(
        name=name,
        issued=bool(finalized),
        disposition=finalized[0].disposition if finalized else None,
        blocked=blocked,
    )


def main() -> None:
    runs = [
        ("happy", dict(timeout=False, ambiguous=False)),
        ("timeout", dict(timeout=True, ambiguous=False)),
        ("ambiguous", dict(timeout=False, ambiguous=True)),
    ]
    for name, kw in runs:
        outcome = _run(name, **kw)
        print(f"=== {name} ===")
        if outcome.issued:
            print(f"  VERDICT ISSUED (disposition: {outcome.disposition})")
        else:
            print("  no verdict issued")
        for reason in outcome.blocked:
            print(f"  BLOCKED: {reason}")
        print()


if __name__ == "__main__":
    main()
