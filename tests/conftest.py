"""Test fixtures over the shared sample case (case_review.sample_case)."""

import pytest

from case_review.coordinator import Coordinator
from case_review.records_service import StubRecordsService
from case_review.sample_case import (
    AMBIGUOUS_MATCH,
    CASE_FACTS,
    CLAIM_HISTORY,
    SAMPLE_CLAIMS,
    SINGLE_MATCH,
)
from case_review.state import CaseState
from case_review.subagents import StubDocumentReader
from case_review.window import WorkingMemory


def make_coordinator(*, timeout: bool = False, ambiguous: bool = False) -> Coordinator:
    state = CaseState(facts=CASE_FACTS, memory=WorkingMemory(facts=CASE_FACTS))
    reader = StubDocumentReader(claims=SAMPLE_CLAIMS)
    records = StubRecordsService(
        matches=AMBIGUOUS_MATCH if ambiguous else SINGLE_MATCH,
        history=CLAIM_HISTORY,
        timeout_on_history=timeout,
    )
    return Coordinator(state=state, reader=reader, records=records)


@pytest.fixture
def coordinator() -> Coordinator:
    return make_coordinator()
