"""Coordinator orchestration steps.

These are the deterministic actions behind the agentic loop's tools. The model
decides *when* to call them; the harness decides *what they do* -- including the
decisions that must never be the model's: classifying a load-bearing failure
(fetch_history), resolving counterparty identity, and writing the real
completion state the finalize gate reads.

Context isolation is structural here: `read_documents` stores the Document
Reader's short claim list and appends only a one-line summary to the
coordinator's window -- the raw reads stay in the reader.
"""

from dataclasses import dataclass
from typing import Literal

from case_review.escalation import IdentityResolution, resolve_identity
from case_review.gate import pre_tool_finalize
from case_review.records_service import RecordsBackend
from case_review.reliability import StepOutcome, handle_step_result
from case_review.routing import RouteDecision, route_fields
from case_review.state import CaseState
from case_review.subagents import DocumentBundle, DocumentReader
from case_review.synthesis import Finding, synthesize


class FinalizeBlockedError(RuntimeError):
    """Raised when finalize is attempted but the load-bearing gate refuses it."""


@dataclass
class CaseVerdict:
    case_id: str
    findings: list[Finding]
    prior_claims: list[dict]
    routing: list[RouteDecision]
    disposition: Literal["auto_approve", "human_review"]
    reasons: list[str]


class Coordinator:
    def __init__(self, *, state: CaseState, reader: DocumentReader, records: RecordsBackend):
        self.state = state
        self.reader = reader
        self.records = records

    def read_documents(self, bundle: DocumentBundle) -> list:
        claims = self.reader.read(bundle)
        self.state.claims = claims
        summary = "; ".join(f"{c.field}={c.value} ({c.source})" for c in claims)
        self.state.memory.append(f"Document Reader returned {len(claims)} claims: {summary}")
        return claims

    def resolve_counterparty(self) -> IdentityResolution:
        match = self.records.match_counterparty(self.state.facts.counterparty)
        res = resolve_identity(match)
        self.state.resolved_counterparty_id = res.resolved_id
        self.state.identity_ambiguous = res.needs_disambiguation
        # A lookup access failure is recorded so the gate has the structured
        # error to act on; identity stays unresolved, so finalize is refused.
        if match.get("isError"):
            self.state.last_error = match
        return res

    def fetch_history(self) -> StepOutcome:
        """Fetch the load-bearing counterparty claim-history and classify the result.

        A successful fetch records status 'ok' and the data; an access failure
        records 'failed' and the structured error -- never 'ok', never data:[].
        """
        if self.state.resolved_counterparty_id is None:
            raise RuntimeError("resolve the counterparty before fetching its history.")
        result = self.records.fetch_claim_history(self.state.resolved_counterparty_id)
        outcome = handle_step_result(result, load_bearing=True)
        if result.get("isError"):
            self.state.history_status = "failed"
            self.state.last_error = result
            # Clear any prior data: 'failed' with a non-None history would be a
            # contradictory state, and the absence of an answer is not stale data.
            self.state.history = None
            self.state.memory.append(f"[step] {outcome.label}")
        else:
            self.state.history = result["data"]
            self.state.history_status = "ok"
        return outcome

    def finalize(self, confidences: dict[str, float] | None = None) -> CaseVerdict:
        decision = pre_tool_finalize(self.state)
        if not decision.allowed:
            raise FinalizeBlockedError(decision.reason)

        synthesis = synthesize(self.state.claims)
        reasons: list[str] = []
        disposition = "auto_approve"

        # An unresolved contradiction is signal for a human, never an auto-approve.
        for finding in synthesis.findings:
            if finding.kind == "contradiction":
                disposition = "human_review"
                reasons.append(
                    f"unresolved contradiction in {finding.field} -- needs adjudication."
                )

        # Per-field calibrated-confidence routing: any low-confidence field is
        # routed to a human even if the rest is pristine.
        routing: list[RouteDecision] = []
        if confidences:
            from case_review.routing import FieldConfidence

            routing = route_fields(
                [FieldConfidence(field=f, confidence=c) for f, c in confidences.items()]
            )
            for r in routing:
                if r.route == "human_review":
                    disposition = "human_review"
                    reasons.append(f"{r.field}: {r.reason}")

        return CaseVerdict(
            case_id=self.state.facts.case_id,
            findings=synthesis.findings,
            prior_claims=self.state.history or [],
            routing=routing,
            disposition=disposition,
            reasons=reasons,
        )
