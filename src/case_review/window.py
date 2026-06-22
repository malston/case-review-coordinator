"""The coordinator's working memory -- lossy and position-sensitive by nature.

`WorkingMemory` holds two things with different rules:

  - `facts`: the load-bearing `CaseFacts` block. Pinned at high-attention
    positions (top of the rebuilt window AND restated right before the model
    decides) and never passed to the summarizer.
  - `history`: the conversational back-and-forth. This is what gets compacted.

`compact` is where progressive summarization happens: summarizing a window that
already contains a summary. Because the facts live outside `history`, that decay
hits the conversation's specifics, not the case's. A fact that the model "has"
but ignores is a positioning problem, not a presence problem -- the fix is to
reposition (re-pin), which `render` does structurally, not to re-add or summarize.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from case_review.schemas import CaseFacts

Summarizer = Callable[[list[str]], str]


def trim_by_relevance(payload: dict, keep: list[str]) -> dict:
    """Select the needed fields from a large tool/subagent payload.

    This is the opposite of blind truncation. Cutting a serialized result to a
    character or token budget can decapitate the one needed field (if it sits
    late in the payload) or slice a structure mid-object; selecting fields by
    name cannot. Asking to keep a field that is absent is a bug, not a quiet
    no-op -- it raises, so a field you meant to keep is never silently dropped.
    """
    missing = [k for k in keep if k not in payload]
    if missing:
        raise KeyError(f"trim_by_relevance asked to keep absent fields: {missing}")
    return {k: payload[k] for k in keep}


@dataclass
class WorkingMemory:
    facts: CaseFacts
    history: list[str] = field(default_factory=list)

    def append(self, entry: str) -> None:
        self.history.append(entry)

    def compact(self, summarizer: Summarizer, *, keep_recent: int = 0) -> None:
        """Compress older history into a single summary entry, keeping the most
        recent `keep_recent` entries verbatim.

        The summarizer is handed ONLY history strings -- the facts block is
        structurally outside this path, so it cannot decay no matter how many
        times the window is compacted.
        """
        if keep_recent > 0:
            old, recent = self.history[:-keep_recent], self.history[-keep_recent:]
        else:
            old, recent = self.history, []
        if not old:
            return
        self.history = [f"[summary] {summarizer(old)}", *recent]

    def reposition(self, predicate: Callable[[str], bool]) -> None:
        """Move a present-but-ignored entry to a high-attention position.

        When the model ignores a fact it already "has," the problem is position,
        not presence. The fix is to move the entry to the end (right before the
        model decides) -- NOT to re-add it (which duplicates) and NOT to
        summarize it (which is lossy). The entry is moved verbatim and stays
        unique.
        """
        match = next((e for e in self.history if predicate(e)), None)
        if match is None:
            return
        self.history = [e for e in self.history if e is not match]
        self.history.append(match)

    def render(self) -> str:
        """Rebuild the model-facing window with the facts pinned at both ends."""
        block = self.facts.render()
        return "\n\n".join([block, *self.history, block])
