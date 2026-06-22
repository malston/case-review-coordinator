"""Coordinator-owned state -- the harness's memory, not the model's.

The model drives the loop by emitting tool calls; the harness writes real
completion state here. The finalize gate reads `history_status`,
`resolved_counterparty_id`, and `claims` from this object -- which is why the
model cannot forge an approved verdict by narrating that it "checked the
history."

`history_status` is the load-bearing flag:
  - "missing"  -- the fetch has not run.
  - "ok"       -- a successful fetch (isError False); `history` is populated.
  - "failed"   -- an access failure (timeout/outage); `history` stays None.
A timeout sets "failed", never "ok", so it can never clear the gate.
"""

from dataclasses import dataclass, field
from typing import Literal

from case_review.schemas import CaseFacts, Claim
from case_review.window import WorkingMemory

HistoryStatus = Literal["missing", "ok", "failed"]


@dataclass
class CaseState:
    facts: CaseFacts
    memory: WorkingMemory
    claims: list[Claim] = field(default_factory=list)
    resolved_counterparty_id: str | None = None
    identity_ambiguous: bool = False
    history: list[dict] | None = None
    history_status: HistoryStatus = "missing"
    last_error: dict | None = None
