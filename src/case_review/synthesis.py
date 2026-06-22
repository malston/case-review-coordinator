"""Synthesize claims into findings, preserving provenance through the merge.

For each field the Document Reader reported, claims are grouped:
  - one claim            -> a `single` finding carrying its source.
  - many, same date      -> a genuine `contradiction`: surfaced with every source
    attributed, value left None. We do not pick, average, or drop -- the conflict
    is signal for a human to adjudicate.
  - many, differing dates -> a temporal `superseded` finding: the latest-dated
    claim governs, and the prior value + the superseding source + its date are
    preserved.

The two failure modes this avoids:
  - time-blind: reporting a settled supersession as an open dispute.
  - time-reckless: adopting the new value with no trace of what it changed.

We resolve when a sound rule exists (recency), never by erasure: the superseded
value stays in the output.
"""

from typing import Literal

from pydantic import BaseModel, model_validator

from case_review.schemas import Claim

FindingKind = Literal["single", "superseded", "contradiction"]


class Finding(BaseModel):
    field: str
    kind: FindingKind
    value: str | None  # None for an unresolved contradiction
    provenance: str
    sources: list[Claim]  # the claim -> source mapping that survives synthesis
    changed_from: str | None = None

    @model_validator(mode="after")
    def _kind_invariants(self) -> "Finding":
        # The tag determines which fields are meaningful; an illegal combination
        # (a contradiction with a chosen value, or a supersession with no prior
        # value) is the failure this module exists to prevent, so it cannot be
        # constructed at all.
        if self.kind == "contradiction" and self.value is not None:
            raise ValueError("a contradiction is unresolved; its value must be None.")
        if self.kind == "superseded" and self.changed_from is None:
            raise ValueError("a supersession must record what it changed from.")
        return self


class Synthesis(BaseModel):
    findings: list[Finding]

    def by_field(self, field: str) -> Finding:
        return next(f for f in self.findings if f.field == field)


def _single(claim: Claim) -> Finding:
    return Finding(
        field=claim.field,
        kind="single",
        value=claim.value,
        provenance=f"{claim.value} <- {claim.source}",
        sources=[claim],
    )


def _superseded(claims: list[Claim]) -> Finding:
    ordered = sorted(claims, key=lambda c: c.effective_date)
    latest_date = ordered[-1].effective_date
    tied_latest = [c for c in ordered if c.effective_date == latest_date]
    # Supersession resolves only when the governing (latest) date is itself
    # unambiguous. Two different values sharing the latest date is a contradiction
    # AT the date that governs -- picking one would be the time-reckless failure.
    if len({c.value for c in tied_latest}) > 1:
        return _contradiction(tied_latest)
    prior, newest = ordered[0], ordered[-1]
    return Finding(
        field=newest.field,
        kind="superseded",
        value=newest.value,
        changed_from=prior.value,
        provenance=(
            f"{newest.value} (per {newest.source}, {newest.effective_date}, "
            f"superseding {prior.value} from {prior.source}, {prior.effective_date})"
        ),
        sources=ordered,
    )


def _contradiction(claims: list[Claim]) -> Finding:
    parts = " vs ".join(f"{c.value} <- {c.source}" for c in claims)
    date = claims[0].effective_date
    return Finding(
        field=claims[0].field,
        kind="contradiction",
        value=None,
        provenance=(
            f"CONFLICT (same effective date {date}, no rule to choose): {parts}. "
            "Needs human adjudication."
        ),
        sources=claims,
    )


def synthesize(claims: list[Claim]) -> Synthesis:
    by_field: dict[str, list[Claim]] = {}
    for claim in claims:
        by_field.setdefault(claim.field, []).append(claim)

    findings: list[Finding] = []
    for field_claims in by_field.values():
        if len(field_claims) == 1:
            findings.append(_single(field_claims[0]))
        elif len({c.effective_date for c in field_claims}) == 1:
            findings.append(_contradiction(field_claims))
        else:
            findings.append(_superseded(field_claims))
    return Synthesis(findings=findings)
