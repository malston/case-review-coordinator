"""The persistent case-facts block: verbatim, immutable, fully attributed."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from case_review.schemas import CaseFacts


def _facts() -> CaseFacts:
    return CaseFacts(
        case_id="case-acme-2026-014",
        counterparty="Acme Robotics LLC",
        contract_id="MSA-2024-ACME",
        claim_amount=Decimal("4200000.00"),
        key_dates={"contract_effective": "2024-03-01", "claim_filed": "2026-05-20"},
    )


def test_render_carries_every_load_bearing_field_verbatim():
    rendered = _facts().render()
    # The specifics that progressive summarization would kill first must be present
    # verbatim -- exact counterparty, exact contract id, exact amount, exact dates.
    assert "case-acme-2026-014" in rendered
    assert "Acme Robotics LLC" in rendered
    assert "MSA-2024-ACME" in rendered
    assert "$4,200,000.00" in rendered
    assert "2024-03-01" in rendered
    assert "2026-05-20" in rendered


def test_render_is_deterministic():
    # Re-injected verbatim every turn means the text cannot drift between renders.
    assert _facts().render() == _facts().render()


def test_case_facts_are_immutable():
    # Load-bearing facts must not be silently mutated mid-workflow.
    facts = _facts()
    with pytest.raises(ValidationError):
        facts.counterparty = "Acme Robotics Inc"
