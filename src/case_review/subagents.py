"""The Document Reader subagent seam and its isolated context.

A subagent runs in its own context window. The Document Reader's entire universe
is the `DocumentBundle` it is handed -- the heavy, noisy raw contract and
amendment text. It burns its window on those reads and returns only a short list
of `Claim`s (value + source citation). Those raw reads never enter the
coordinator's window: the coordinator pays a few lines for what would otherwise
cost thousands of tokens of reads and crowd out the case-facts block.

`DocumentReader` is the seam. `StubDocumentReader` returns scripted claims
offline (tests and the demo); the live path runs a real isolated subagent.
"""

from dataclasses import dataclass, field
from typing import Protocol

from case_review.schemas import Claim


@dataclass
class DocumentBundle:
    """The raw reads -- contract + amendments. Lives in the reader's window only."""

    documents: dict[str, str] = field(default_factory=dict)


class DocumentReader(Protocol):
    def read(self, bundle: DocumentBundle) -> list[Claim]: ...


class StubDocumentReader:
    """Deterministic Document Reader for offline runs and tests.

    Records how many characters of raw text it consumed, so a test can show the
    reader (not the coordinator) bears the cost of the heavy reads.
    """

    def __init__(self, claims: list[Claim]):
        self._claims = claims
        self.chars_read = 0

    def read(self, bundle: DocumentBundle) -> list[Claim]:
        self.chars_read = sum(len(text) for text in bundle.documents.values())
        return list(self._claims)
