"""Wires the case-review tools and the finalize gate onto the agentic loop.

Tools:        read_documents, resolve_counterparty, fetch_history, finalize_verdict
PreToolUse:   finalize_verdict -> the load-bearing completion gate

`finalized` is the simulated consequential action: a verdict appended to it has
been issued. The whole point of the gate is that the timeout trajectory never
appends to it -- the load-bearing history failure keeps it shut.
"""

from collections.abc import Callable
from typing import Any

from case_review.coordinator import Coordinator, FinalizeBlockedError
from case_review.gate import pre_tool_finalize
from case_review.sample_case import FIELD_CONFIDENCES
from case_review.subagents import DocumentBundle

Tool = Callable[[dict, Coordinator], Any]
Hook = Callable[..., Any]


def build_harness(
    coordinator: Coordinator, raw_documents: dict[str, str]
) -> tuple[dict[str, Tool], dict[str, Hook], list]:
    finalized: list = []

    def read_documents(tool_input: dict, coord: Coordinator) -> dict:
        claims = coord.read_documents(DocumentBundle(documents=raw_documents))
        # The coordinator's tool_result is the short summary -- not the raw reads.
        return {"claims": [c.model_dump() for c in claims]}

    def resolve_counterparty(tool_input: dict, coord: Coordinator) -> dict:
        res = coord.resolve_counterparty()
        return {
            "resolved_id": res.resolved_id,
            "needs_disambiguation": res.needs_disambiguation,
            "escalate": res.escalate,
            "action": res.action,
        }

    def fetch_history(tool_input: dict, coord: Coordinator) -> dict:
        outcome = coord.fetch_history()
        if coord.state.history_status == "ok":
            return {"isError": False, "data": coord.state.history}
        # Forward the structured error verbatim -- isError stays True. A non-ok
        # status must have recorded the error for this step; assert it rather than
        # trust the cross-field invariant silently.
        error = coord.state.last_error
        assert error is not None, "history fetch is not ok but no error was recorded."
        return {**error, "terminated": outcome.terminated}

    def finalize_verdict(tool_input: dict, coord: Coordinator) -> dict:
        try:
            verdict = coord.finalize(confidences=FIELD_CONFIDENCES)
        except FinalizeBlockedError as exc:
            return {"isError": True, "category": "blocked", "detail": str(exc)}
        finalized.append(verdict)
        return {
            "disposition": verdict.disposition,
            "findings": [f.model_dump() for f in verdict.findings],
            "reasons": verdict.reasons,
        }

    def pre_finalize(tool_input: dict, coord: Coordinator):
        return pre_tool_finalize(coord.state)

    tools: dict[str, Tool] = {
        "read_documents": read_documents,
        "resolve_counterparty": resolve_counterparty,
        "fetch_history": fetch_history,
        "finalize_verdict": finalize_verdict,
    }
    pre_hooks: dict[str, Hook] = {"finalize_verdict": pre_finalize}
    return tools, pre_hooks, finalized
