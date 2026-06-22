"""PreToolUse gate for finalize_verdict -- the load-bearing linchpin.

Producing an approved case verdict is a consequential action: it asserts the
counterparty's claim history was checked. So it is gated programmatically on real
completion state, not on a prompt instruction and not on the model's narration.

The gate refuses to finalize unless every load-bearing precondition is truly
met. The one that matters most: a SUCCESSFUL claim-history fetch. A timeout sets
`history_status = "failed"`, which the gate rejects -- so a timed-out, load-
bearing check can never be laundered into a confident "no prior claims" verdict.
"""

from dataclasses import dataclass

from case_review.state import CaseState


@dataclass
class GateDecision:
    allowed: bool
    reason: str = ""


def pre_tool_finalize(state: CaseState) -> GateDecision:
    # 1. The Document Reader must have actually returned claims to assess.
    if not state.claims:
        return GateDecision(False, "finalize blocked: no claims have been read yet.")

    # 2. The counterparty identity must be resolved -- and an ambiguous match is
    #    NOT resolved (recency is not identity; acting on the wrong party is
    #    high-stakes and irreversible).
    if state.resolved_counterparty_id is None:
        if state.identity_ambiguous:
            return GateDecision(
                False,
                "finalize blocked: counterparty identity is ambiguous -- disambiguate "
                "or escalate before finalizing.",
            )
        return GateDecision(False, "finalize blocked: counterparty identity is unresolved.")

    # 3. The load-bearing check: a SUCCESSFUL claim-history fetch. A timeout/outage
    #    leaves status "failed" or "missing" -- never "ok" -- and is refused here.
    if state.history_status != "ok":
        return GateDecision(
            False,
            "finalize blocked: counterparty claim-history was not confirmed "
            f"(status={state.history_status!r}); a load-bearing check did not succeed.",
        )

    return GateDecision(True)
