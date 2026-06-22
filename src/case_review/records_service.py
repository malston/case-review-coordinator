"""The Records Service -- the external counterparty-history seam.

Two operations:
  - `match_counterparty(name)`  -> resolve a name to a counterparty. Returns all
    matches; two same-named parties surface as a two-element `data` list (the
    coordinator must disambiguate, not silently pick -- see escalation.py).
  - `fetch_claim_history(counterparty_id)` -> the LOAD-BEARING history fetch.
    This is where the timeout/outage occurs, and it must surface as a structured
    error, never as an empty answer.

`RecordsBackend` is the seam. `StubRecordsService` is the deterministic offline
double used by tests and the demo; the live path injects a real client.
"""

from dataclasses import asdict, dataclass, field
from typing import Protocol

from case_review.errors import records_error, records_ok


@dataclass(frozen=True)
class CounterpartyMatch:
    counterparty_id: str
    name: str
    registered: str  # ISO date the counterparty was registered


class RecordsBackend(Protocol):
    def match_counterparty(self, name: str) -> dict: ...
    def fetch_claim_history(self, counterparty_id: str) -> dict: ...


@dataclass
class StubRecordsService:
    matches: list[CounterpartyMatch] = field(default_factory=list)
    history: dict[str, list[dict]] = field(default_factory=dict)
    timeout_on_history: bool = False
    outage_on_history: bool = False

    def match_counterparty(self, name: str) -> dict:
        found = [m for m in self.matches if m.name == name]
        return records_ok(operation="match_counterparty", data=[asdict(m) for m in found])

    def fetch_claim_history(self, counterparty_id: str) -> dict:
        if self.timeout_on_history:
            return records_error(
                category="timeout",
                operation="fetch_claim_history",
                detail=(
                    "counterparty-history service did not respond within 5s for "
                    f"{counterparty_id}; the query did not run."
                ),
                retryable=True,
            )
        if self.outage_on_history:
            return records_error(
                category="outage",
                operation="fetch_claim_history",
                detail=f"counterparty-history service is unreachable for {counterparty_id}.",
                retryable=True,
            )
        # A known counterparty with no claims yields data:[] -- a valid empty answer.
        return records_ok(
            operation="fetch_claim_history", data=self.history.get(counterparty_id, [])
        )
