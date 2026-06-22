"""Synthesis preserves provenance; conflicts are surfaced or resolved, never erased.

A claim -> source mapping survives the merge (it is part of the output). A
genuine contradiction (same effective date, no rule) is surfaced with both
sources attributed. A temporal conflict is resolved by supersession (the later
amendment governs) with the change preserved -- avoiding both time-blind
(reporting a settled supersession as an open dispute) and time-reckless (using
the new value with no trace of the change).
"""

from case_review.schemas import Claim
from case_review.synthesis import synthesize


def _claim(field: str, value: str, source: str, date: str) -> Claim:
    return Claim(field=field, value=value, source=source, effective_date=date)


def test_single_claim_carries_its_source_into_the_output():
    syn = synthesize([_claim("renewal", "auto-renews annually", "Master Agreement §7.2",
                             "2024-03-01")])
    finding = syn.by_field("renewal")
    assert finding.kind == "single"
    assert finding.value == "auto-renews annually"
    assert "Master Agreement §7.2" in finding.provenance
    assert finding.sources[0].source == "Master Agreement §7.2"


def test_temporal_conflict_is_resolved_by_supersession_with_a_trace():
    claims = [
        _claim("payment_terms", "Net 30", "Master Agreement §4.1", "2024-03-01"),
        _claim("payment_terms", "Net 60", "Amendment 2 §2", "2026-01-15"),
    ]
    finding = synthesize(claims).by_field("payment_terms")
    assert finding.kind == "superseded"
    assert finding.value == "Net 60"  # the later amendment governs
    assert finding.changed_from == "Net 30"
    # provenance preserves what changed and when -- not time-reckless.
    assert "Amendment 2 §2" in finding.provenance
    assert "2026-01-15" in finding.provenance
    assert "Net 30" in finding.provenance
    assert "supersed" in finding.provenance.lower()


def test_supersession_picks_the_later_date_not_the_listed_order():
    # Newer claim listed FIRST -- supersession must key off the date, not position.
    claims = [
        _claim("payment_terms", "Net 60", "Amendment 2 §2", "2026-01-15"),
        _claim("payment_terms", "Net 30", "Master Agreement §4.1", "2024-03-01"),
    ]
    finding = synthesize(claims).by_field("payment_terms")
    assert finding.value == "Net 60"
    assert finding.changed_from == "Net 30"


def test_contradiction_at_the_latest_date_is_not_collapsed_by_supersession():
    # An older claim plus TWO claims that conflict at the latest effective date.
    # Supersession must not silently pick one of the tied-latest claims (that is
    # the time-reckless "newest wins, drop the rest" failure): the latest date is
    # itself contradictory, so the field is an unresolved contradiction.
    claims = [
        _claim("governing_law", "Old", "Schedule Z", "2020-01-01"),
        _claim("governing_law", "Delaware", "Master Agreement §12", "2026-01-15"),
        _claim("governing_law", "New York", "Schedule A §1", "2026-01-15"),
    ]
    finding = synthesize(claims).by_field("governing_law")
    assert finding.kind == "contradiction"
    assert finding.value is None
    attributed = {(s.value, s.source) for s in finding.sources}
    assert ("Delaware", "Master Agreement §12") in attributed
    assert ("New York", "Schedule A §1") in attributed


def test_contradiction_at_latest_date_is_order_independent():
    base = [
        _claim("governing_law", "Old", "Schedule Z", "2020-01-01"),
        _claim("governing_law", "Delaware", "Master Agreement §12", "2026-01-15"),
        _claim("governing_law", "New York", "Schedule A §1", "2026-01-15"),
    ]
    swapped = [base[0], base[2], base[1]]
    # Neither order resolves to a single governing value.
    assert synthesize(base).by_field("governing_law").value is None
    assert synthesize(swapped).by_field("governing_law").value is None


def test_three_claim_chain_supersedes_to_the_latest_with_a_trace():
    # A clean chain (distinct dates) resolves to the latest, tracing the original.
    claims = [
        _claim("payment_terms", "Net 30", "Master Agreement §4.1", "2024-03-01"),
        _claim("payment_terms", "Net 45", "Amendment 1 §3", "2025-06-01"),
        _claim("payment_terms", "Net 60", "Amendment 2 §2", "2026-01-15"),
    ]
    finding = synthesize(claims).by_field("payment_terms")
    assert finding.kind == "superseded"
    assert finding.value == "Net 60"
    assert finding.changed_from == "Net 30"  # traces back to the original
    assert "Amendment 2 §2" in finding.provenance


def test_genuine_contradiction_is_surfaced_with_both_sources_attributed():
    claims = [
        _claim("governing_law", "Delaware", "Master Agreement §12", "2024-03-01"),
        _claim("governing_law", "New York", "Schedule A §1", "2024-03-01"),
    ]
    finding = synthesize(claims).by_field("governing_law")
    assert finding.kind == "contradiction"
    # Not picked, not averaged into a fabricated third value, not dropped.
    assert finding.value is None
    # Both sources attributed for a human to adjudicate.
    attributed = {(s.value, s.source) for s in finding.sources}
    assert ("Delaware", "Master Agreement §12") in attributed
    assert ("New York", "Schedule A §1") in attributed


def test_contradiction_keeps_both_distinct_values_visible():
    claims = [
        _claim("governing_law", "Delaware", "Master Agreement §12", "2024-03-01"),
        _claim("governing_law", "New York", "Schedule A §1", "2024-03-01"),
    ]
    finding = synthesize(claims).by_field("governing_law")
    assert "Delaware" in finding.provenance
    assert "New York" in finding.provenance
