"""The one piece of real logic in the live path: parsing the reader's output.

ClaudeClient / ClaudeDocumentReader need an API key and are not exercised here;
`parse_claims` is pure and is, so the offline suite covers it.
"""

import pytest

from case_review.live import parse_claims


def test_parses_claims_with_citations():
    text = (
        'Here you go:\n```json\n{"claims": ['
        '{"field": "payment_terms", "value": "Net 60", "source": "Amendment 2 §2", '
        '"effective_date": "2026-01-15"}]}\n```'
    )
    claims = parse_claims(text)
    assert len(claims) == 1
    assert claims[0].field == "payment_terms"
    assert claims[0].source == "Amendment 2 §2"
    assert claims[0].effective_date == "2026-01-15"


def test_prefers_a_fenced_json_block_over_surrounding_prose_with_braces():
    # Prose around the fenced block contains stray braces; a greedy match would
    # swallow them and fail to parse. The fenced block must win.
    text = (
        "Thinking: the set {payment_terms, renewal} is relevant. Here is the result:\n"
        '```json\n{"claims": [{"field": "renewal", "value": "auto-renews annually", '
        '"source": "MA §7.2", "effective_date": "2024-03-01"}]}\n```\n'
        "Let me know if you need anything else (e.g. {more fields})."
    )
    claims = parse_claims(text)
    assert len(claims) == 1
    assert claims[0].field == "renewal"


def test_parses_unfenced_json_object():
    text = (
        '{"claims": [{"field": "renewal", "value": "x", "source": "s", '
        '"effective_date": "2024-01-01"}]}'
    )
    claims = parse_claims(text)
    assert claims[0].value == "x"


def test_raises_when_no_json_present():
    with pytest.raises(ValueError, match="no JSON object"):
        parse_claims("I could not find anything.")


def test_raises_when_claims_key_is_missing():
    # Valid JSON, but not the expected shape -- a clear error, not a KeyError.
    with pytest.raises(ValueError, match="claims"):
        parse_claims('{"results": []}')
