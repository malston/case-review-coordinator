"""Terminate-vs-degrade for a structured step result.

A failed step that is load-bearing must terminate and escalate -- producing a
verdict would mean letting an outage make the decision. A non-critical step may
degrade gracefully, but only with an honest, scoped label that names what
failed. The dividing line between graceful degradation and silent suppression is
that honesty: both paths attach a label saying exactly what did not run.
"""

from dataclasses import dataclass


@dataclass
class StepOutcome:
    proceed: bool
    terminated: bool
    escalated: bool
    label: str
    reason: str


def handle_step_result(result: dict, *, load_bearing: bool) -> StepOutcome:
    if not result.get("isError"):
        return StepOutcome(
            proceed=True, terminated=False, escalated=False, label="ok", reason=""
        )

    category = result["category"]
    operation = result["operation"]
    # Honest, scoped label -- attached on BOTH paths so degradation never hides
    # the gap behind a clean-looking result.
    label = f"{operation} failed: {category}, not assessed"

    if load_bearing:
        return StepOutcome(
            proceed=False,
            terminated=True,
            escalated=True,
            label=label,
            reason=(
                f"load-bearing step {operation!r} failed ({category}); cannot produce "
                "a verdict without it -- escalating instead of fabricating a clean result."
            ),
        )

    return StepOutcome(
        proceed=True,
        terminated=False,
        escalated=False,
        label=label,
        reason=(
            f"non-critical step {operation!r} failed ({category}); proceeding with the "
            "gap labelled honestly rather than suppressed."
        ),
    )
