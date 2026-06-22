"""Canonical data structures carried end-to-end.

The `CaseFacts` block is the load-bearing core: the specifics the workflow
cannot function without. It is immutable (a fact cannot be silently rewritten
mid-run) and renders verbatim, because it is re-injected into every turn and is
*exempt from summarization* -- progressive summarization decays exactly these
specifics (names, amounts, dates) first, so they never enter the prose that gets
compressed (see `window.py`).
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class Claim(BaseModel):
    """One claim returned by the Document Reader, with its source citation.

    `source` and `effective_date` are required, not optional: attribution that
    is not carried as structured metadata at context-passing time cannot be
    recovered at synthesis, and `effective_date` is what lets synthesis tell a
    temporal supersession from a genuine contradiction.
    """

    field: str
    value: str
    source: str
    effective_date: str  # ISO date the cited source took effect


class CaseFacts(BaseModel):
    """The persistent, load-bearing facts for one case.

    Frozen on purpose: these are the facts the verdict depends on, so the model
    must never be able to mutate them and the harness re-injects them verbatim.
    """

    model_config = ConfigDict(frozen=True)

    case_id: str
    counterparty: str
    contract_id: str
    claim_amount: Decimal
    key_dates: dict[str, str]

    def render(self) -> str:
        """The verbatim block pinned into every turn. Deterministic by design."""
        lines = [
            "=== CASE FACTS (load-bearing; never summarize, never paraphrase) ===",
            f"case_id: {self.case_id}",
            f"counterparty: {self.counterparty}",
            f"contract_id: {self.contract_id}",
            f"claim_amount: ${self.claim_amount:,.2f}",
        ]
        for label, date in self.key_dates.items():
            lines.append(f"key_date[{label}]: {date}")
        return "\n".join(lines)
