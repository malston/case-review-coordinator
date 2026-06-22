"""The offline demo's three trajectories produce the expected outcomes."""

from case_review.demo import _run


def test_happy_trajectory_issues_a_verdict_routed_to_human_review():
    outcome = _run("happy", timeout=False, ambiguous=False)
    assert outcome.issued is True
    # The genuine contradiction (governing_law) forces human review.
    assert outcome.disposition == "human_review"
    assert outcome.blocked == []


def test_timeout_trajectory_issues_no_verdict_and_surfaces_the_error():
    outcome = _run("timeout", timeout=True, ambiguous=False)
    assert outcome.issued is False
    # The structured timeout error AND the finalize block both surface.
    assert any("timeout" in b for b in outcome.blocked)
    assert any("load-bearing check did not succeed" in b for b in outcome.blocked)


def test_ambiguous_trajectory_issues_no_verdict():
    outcome = _run("ambiguous", timeout=False, ambiguous=True)
    assert outcome.issued is False
    assert any("ambiguous" in b for b in outcome.blocked)
