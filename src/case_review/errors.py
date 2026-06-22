"""Structured results for the Records Service -- the content the coordinator
reasons over at recovery time.

Two builders carry the contract:
  - `records_error`: isError=True, with category / operation / detail / retryable.
    It carries NO `data` field, because an access failure is the *absence of an
    answer*, not the answer "none".
  - `records_ok`: isError=False, with `data`. An empty `data` list is a real
    answer ("confirmed: none"), not a failure.

Collapsing the two -- letting a timeout return `data: []` -- is the latent
disaster the whole domain is about: an outage would silently read as "no prior
claims," and the outage would be making the approval decision.
"""

from typing import Literal

ErrorCategory = Literal["timeout", "outage", "permission"]


def records_error(
    *, category: ErrorCategory, operation: str, detail: str, retryable: bool
) -> dict:
    return {
        "isError": True,
        "category": category,
        "operation": operation,
        "detail": detail,
        "retryable": retryable,
    }


def records_ok(*, operation: str, data: list) -> dict:
    return {
        "isError": False,
        "operation": operation,
        "data": data,
    }
