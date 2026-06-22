"""Escalation on objective state, and identity disambiguation.

`should_escalate` fires only on objective triggers:
  1. explicit_request  -- the user asked for a human.
  2. repeated_failure  -- the same issue failed `>= retry_threshold` times. This
     is a count, never the first failure.
  3. out_of_scope      -- the request crosses the agent's authorized scope / a
     risk threshold.

Detected frustration and self-reported model confidence are NOT triggers: both
require unreliable inference, and a confident-wrong model would suppress its own
escalation. Frustration is allowed only as a *modulator* -- it lowers the
repeated-failure threshold by one (so "2nd failure AND frustrated -> stop now"),
but never below a genuine repeat, and never fires with zero failures. Model
confidence is deliberately not an input at all.

`resolve_identity` turns a counterparty match into a resolution. One match
resolves; zero escalates; two-or-more is ambiguous and must be disambiguated or
escalated -- never silently picked. Recency is not identity: the newer
registration is not "the" counterparty, and acting on the wrong record is a
high-stakes, often-irreversible error.
"""

from dataclasses import dataclass

# Frustration may pull the repeated-failure threshold down to here, no lower.
MIN_REPEATED_FAILURES = 2


@dataclass
class EscalationDecision:
    escalate: bool
    trigger: str | None
    action: str
    reason: str


def should_escalate(
    *,
    explicit_request: bool = False,
    failure_count: int = 0,
    retry_threshold: int = 3,
    out_of_scope: bool = False,
    frustration: bool = False,
) -> EscalationDecision:
    if explicit_request:
        return EscalationDecision(
            True, "explicit_request", "hand off to a human",
            "the user explicitly asked for a human.",
        )
    if out_of_scope:
        return EscalationDecision(
            True, "out_of_scope", "hand off to an authorized human",
            "the request crosses the agent's authorized scope / risk threshold.",
        )

    # Frustration modulates the threshold of the real trigger; it never triggers
    # on its own and never lowers the bar below a genuine repeat.
    effective = retry_threshold - 1 if frustration else retry_threshold
    effective = max(effective, MIN_REPEATED_FAILURES)
    if failure_count >= effective:
        return EscalationDecision(
            True, "repeated_failure", "stop retrying and hand off to a human",
            f"the same issue failed {failure_count} times "
            f"(threshold {effective}{', lowered by detected frustration' if frustration else ''}).",
        )

    return EscalationDecision(False, None, "continue", "no objective escalation trigger met.")


@dataclass
class IdentityResolution:
    resolved_id: str | None
    needs_disambiguation: bool
    escalate: bool
    candidates: list[dict]
    action: str
    reason: str


def resolve_identity(match_result: dict) -> IdentityResolution:
    # The lookup is an outage-prone seam (same result contract as the history
    # fetch). An access failure carries no `data` -- classify it first, and
    # escalate it as the failure it is. It must never read as "no match found":
    # an outage is the absence of an answer, not the answer "this party is
    # unknown."
    if match_result.get("isError"):
        return IdentityResolution(
            resolved_id=None,
            needs_disambiguation=False,
            escalate=True,
            candidates=[],
            action=f"escalate: counterparty lookup failed ({match_result['category']})",
            reason=(
                f"match_counterparty failed ({match_result['category']}); identity is "
                "unconfirmed. This is an access failure (the lookup did not run), so "
                "whether the party exists is unknown -- do not proceed against an "
                "unverified party."
            ),
        )

    candidates = match_result["data"]

    if len(candidates) == 1:
        return IdentityResolution(
            resolved_id=candidates[0]["counterparty_id"],
            needs_disambiguation=False,
            escalate=False,
            candidates=candidates,
            action="proceed with the single matched counterparty",
            reason="exactly one counterparty matched.",
        )

    if len(candidates) == 0:
        return IdentityResolution(
            resolved_id=None,
            needs_disambiguation=False,
            escalate=True,
            candidates=[],
            action="escalate: no counterparty matched the name",
            reason="no match -- the workflow cannot proceed against an unknown party.",
        )

    return IdentityResolution(
        resolved_id=None,
        needs_disambiguation=True,
        escalate=False,
        candidates=candidates,
        action=(
            "do NOT pick one. Ask a disambiguating question only the right party can "
            "answer (e.g. the contract_id on file or the registration date); if it "
            "cannot be answered, escalate."
        ),
        reason=(
            "two counterparties share this name; recency is not identity, so the newer "
            "registration is not the answer. Acting on the wrong record is a high-stakes, "
            "often-irreversible error."
        ),
    )
