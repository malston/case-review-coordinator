"""The shared sample case: one contract, its amendments, and the records data.

Used by the demo and the tests. The raw documents are deliberately noisy (the
Document Reader burns its window on them); the claims it returns are short. The
claim set carries both conflict types the linchpin test exercises:

  - payment_terms: Net 30 (original, 2024-03-01) superseded by Net 60
    (Amendment 2, 2026-01-15) -- a TEMPORAL conflict to resolve with provenance.
  - governing_law: Delaware (Master Agreement §12) vs New York (Schedule A §1),
    both effective 2024-03-01 -- a GENUINE contradiction to surface.
"""

from decimal import Decimal

from case_review.records_service import CounterpartyMatch
from case_review.schemas import CaseFacts, Claim

CASE_FACTS = CaseFacts(
    case_id="case-acme-2026-014",
    counterparty="Acme Robotics LLC",
    contract_id="MSA-2024-ACME",
    claim_amount=Decimal("4200000.00"),
    key_dates={"contract_effective": "2024-03-01", "claim_filed": "2026-05-20"},
)

# Heavy, noisy raw reads -- these live in the Document Reader's window, never the
# coordinator's. Padded to make the context economics concrete.
RAW_DOCUMENTS = {
    "MSA-2024-ACME.pdf": (
        "MASTER SERVICES AGREEMENT\n"
        "This Agreement is entered into as of March 1, 2024 ...\n"
        + ("WHEREAS the parties agree to the following boilerplate terms. " * 400)
        + "\n§4.1 Payment terms: Net 30."
        + "\n§7.2 This Agreement auto-renews annually."
        + "\n§12 Governing law: Delaware."
    ),
    "Schedule-A.pdf": (
        "SCHEDULE A\n"
        + ("Definitions and service levels follow in exhaustive detail. " * 200)
        + "\n§1 Governing law: New York."
    ),
    "Amendment-2.pdf": (
        "AMENDMENT 2, dated January 15, 2026\n"
        + ("The parties hereby amend the Master Services Agreement as follows. " * 150)
        + "\n§2 Payment terms are amended to Net 60, superseding §4.1."
    ),
}

# What the Document Reader returns -- short, each with a source citation.
SAMPLE_CLAIMS = [
    Claim(field="renewal", value="auto-renews annually",
          source="Master Agreement §7.2", effective_date="2024-03-01"),
    Claim(field="payment_terms", value="Net 30",
          source="Master Agreement §4.1", effective_date="2024-03-01"),
    Claim(field="payment_terms", value="Net 60",
          source="Amendment 2 §2", effective_date="2026-01-15"),
    Claim(field="governing_law", value="Delaware",
          source="Master Agreement §12", effective_date="2024-03-01"),
    Claim(field="governing_law", value="New York",
          source="Schedule A §1", effective_date="2024-03-01"),
]

# A single clean counterparty match for the happy/timeout trajectories.
SINGLE_MATCH = [CounterpartyMatch("CP-100", "Acme Robotics LLC", "2019-06-01")]

# Two same-named parties for the ambiguous-match trajectory.
AMBIGUOUS_MATCH = [
    CounterpartyMatch("CP-100", "Acme Robotics LLC", "2019-06-01"),
    CounterpartyMatch("CP-771", "Acme Robotics LLC", "2025-02-14"),
]

CLAIM_HISTORY = {"CP-100": [{"claim_id": "PR-7", "amount": 50000, "status": "settled"}]}

# Per-field calibrated confidences -- claim-amount / counterparty-identity are the
# high-stakes strata; here every field is confident enough to auto-approve, so the
# only thing that forces human review is a genuine contradiction.
FIELD_CONFIDENCES = {
    "renewal": 0.97,
    "payment_terms": 0.95,
    "governing_law": 0.93,
}
