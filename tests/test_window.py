"""Working memory: the window is lossy and position-sensitive.

The conversational history may be compacted; the case-facts block never is. The
summarizer is structurally barred from seeing the facts, so progressive
summarization (summarizing a window that already contains a summary) decays the
history's specifics while the load-bearing facts survive verbatim.
"""

from decimal import Decimal

from case_review.schemas import CaseFacts
from case_review.window import WorkingMemory


def _facts() -> CaseFacts:
    return CaseFacts(
        case_id="case-acme-2026-014",
        counterparty="Acme Robotics LLC",
        contract_id="MSA-2024-ACME",
        claim_amount=Decimal("4200000.00"),
        key_dates={"contract_effective": "2024-03-01", "claim_filed": "2026-05-20"},
    )


def test_facts_pinned_at_both_high_attention_ends():
    wm = WorkingMemory(facts=_facts())
    wm.append("user: review the renewal terms")
    out = wm.render()
    block = _facts().render()
    # Beginning and end beat the middle: the block is pinned at both ends.
    assert out.startswith(block)
    assert out.endswith(block)


def test_history_is_verbatim_without_compaction():
    wm = WorkingMemory(facts=_facts())
    wm.append("entry A")
    wm.append("entry B")
    out = wm.render()
    assert "entry A" in out
    assert "entry B" in out


def test_compaction_never_feeds_the_facts_to_the_summarizer():
    seen: list[str] = []

    def spy(entries: list[str]) -> str:
        seen.extend(entries)
        return "COMPRESSED"

    wm = WorkingMemory(facts=_facts())
    for i in range(5):
        wm.append(f"turn {i}")
    wm.compact(spy)

    # The summarizer only ever sees conversational history -- never the facts.
    assert all("Acme Robotics LLC" not in e for e in seen)
    assert all("4,200,000" not in e for e in seen)
    # History was compressed; facts remain verbatim in the rendered window.
    assert any(e.startswith("[summary] COMPRESSED") for e in wm.history)
    assert "Acme Robotics LLC" in wm.render()
    assert "$4,200,000.00" in wm.render()


def test_progressive_summarization_decays_history_but_never_the_facts():
    batches: list[list[str]] = []

    def spy(entries: list[str]) -> str:
        batches.append(list(entries))
        return f"summary#{len(batches)}"

    wm = WorkingMemory(facts=_facts())
    for i in range(3):
        wm.append(f"turn DET{i}")
    wm.compact(spy)  # pass 1: summarize the three turns
    wm.append("turn DET-late")
    wm.compact(spy)  # pass 2: summarize a window that ALREADY contains a summary

    # Pass 2 received the pass-1 summary -- this is summarizing a summary.
    assert any("[summary] summary#1" in e for e in batches[1])
    # The facts were never handed to the summarizer on any pass.
    assert all("Acme Robotics LLC" not in e for batch in batches for e in batch)
    # History specifics have decayed; load-bearing facts survive verbatim.
    out = wm.render()
    assert "DET0" not in out
    assert "Acme Robotics LLC" in out
    assert "$4,200,000.00" in out
    assert "2026-05-20" in out


def test_compaction_keeps_recent_turns_verbatim():
    wm = WorkingMemory(facts=_facts())
    for i in range(4):
        wm.append(f"old {i}")
    wm.append("most recent turn")
    wm.compact(lambda entries: "OLD", keep_recent=1)
    out = wm.render()
    assert "most recent turn" in out  # recent kept verbatim
    assert "old 0" not in out  # older turns compacted away


def test_reposition_moves_a_buried_entry_without_duplicating_or_altering_it():
    # Present != attended: a fact buried in the middle is ignored. The fix is to
    # reposition it to a high-attention position -- NOT to re-add it (duplicate)
    # and NOT to summarize it (lossy).
    wm = WorkingMemory(facts=_facts())
    wm.append("the cap is $1,000,000")  # this gets buried
    for i in range(10):
        wm.append(f"chatter {i}")

    wm.reposition(lambda e: "cap is" in e)

    # Appears exactly once -- repositioned, not re-added as a second copy.
    assert sum("cap is $1,000,000" in e for e in wm.history) == 1
    # Now at the most-recent (high-attention) position, verbatim -- not summarized.
    assert wm.history[-1] == "the cap is $1,000,000"
