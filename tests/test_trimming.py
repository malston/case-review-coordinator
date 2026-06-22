"""Trim tool results by relevance, never by blind truncation.

Truncating to a character budget can decapitate the one needed field or cut a
structure mid-object; selecting needed fields cannot.
"""

import json

import pytest

from case_review.window import trim_by_relevance


def _records_payload() -> dict:
    return {
        "counterparty_claims": [{"claim_id": "C-1", "amount": 90000, "status": "settled"}],
        "raw_audit_log": "x" * 5000,
        "debug_trace": "stack frames ...",
        "pagination_cursor": "eyJvZmZzZXQiOjUwfQ==",
    }


def test_trim_selects_only_the_needed_fields():
    trimmed = trim_by_relevance(_records_payload(), keep=["counterparty_claims"])
    assert set(trimmed) == {"counterparty_claims"}
    assert trimmed["counterparty_claims"][0]["amount"] == 90000


def test_trim_refuses_to_silently_drop_a_field_it_was_told_to_keep():
    # Asking to keep an absent field is a bug, not a quiet no-op.
    with pytest.raises(KeyError):
        trim_by_relevance(_records_payload(), keep=["counterparty_claims", "nonexistent"])


def test_blind_truncation_decapitates_the_needed_field_but_trimming_does_not():
    # The needed field sits AFTER a block of noise, so a blind cut to N chars
    # drops it entirely -- the distractor "truncate the result to 500 tokens".
    payload = {"noise": "n" * 600, "counterparty_claims": [{"amount": 4200000}]}
    serialized = json.dumps(payload)

    truncated = serialized[:500]  # blind character-count cut
    assert "counterparty_claims" not in truncated  # the load-bearing field is gone

    # Relevance trimming keeps the field regardless of its position or the noise size.
    trimmed = trim_by_relevance(payload, keep=["counterparty_claims"])
    assert trimmed["counterparty_claims"][0]["amount"] == 4200000
