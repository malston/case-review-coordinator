# Domain 5 Build Exercise -- Review Coordinator with Persistent Case Facts

## Prompt

See [build prompt](../.prompts/domain5-build-exercise.prompt.md).

## Response

This is a coordinator plus two isolated subagents that assess a long-running case
and synthesize one verdict. The deliverables below are the topology, the memory
model, the failure path, the escalation rules, the synthesis, and the review
routing -- each implemented in [`domain5-case-review-coordinator/`](../domain5-case-review-coordinator/)
and demonstrated by an offline test suite.

One note up front, because you asked me to push back where instructions force a
principle violation: **they don't.** The spec is internally consistent. The single
place I sharpen rather than reject is the **shape** of the structured error. The
prompt names the fields `isError / category / operation / detail / retryable`;
Domain 2's house convention is `isError` + a metadata block. I kept your exact
field names and made the cardinal rule structural: **an access-failure error
object carries no `data` key at all**, so a timeout can never be read as
`data: []`. That is stronger than "don't set data to empty" -- the field is simply
absent, so the collapse is impossible, not merely discouraged.

Here are the deliverables.

---

## 1. Topology, context isolation, and the case-facts block

### The topology

```
Coordinator  (thin window: case-facts block + short claim list + structured results)
  |
  |-- Document Reader  (own window; burns it on the raw contract + amendments;
  |                     returns claims[], each with a source citation)
  |
  |-- Records Service  (own window; queries counterparty-history via a tool;
                        where the timeout and the ambiguous match occur)
```

Code: `coordinator.py` (the steps), `subagents.py` (the Document Reader seam),
`records_service.py` (the external seam).

### Context isolation and its economics

The Document Reader's entire universe is the `DocumentBundle` handed to it
(`subagents.py`). It reads thousands of tokens of noisy contract and amendment
text **in its own window** and returns a short list of `Claim`s
(value + source + effective date). The coordinator stores that list and appends a
**one-line summary** to its own window (`Coordinator.read_documents`). The raw
reads never touch the coordinator's window.

The economics, made concrete in a test
(`test_coordinator.py::test_document_reader_raw_reads_never_enter_the_coordinator_window`):
the reader consumes >10,000 characters of raw text; the coordinator's rendered
window contains the claim `auto-renews annually` but **not** the boilerplate it
came from. The coordinator pays a few lines for what would otherwise cost thousands
of tokens of reads -- tokens that would crowd out the load-bearing facts.

### The case-facts block

`CaseFacts` (`schemas.py`) holds the specifics the workflow cannot function
without: `case_id`, `counterparty`, `contract_id`, `claim_amount`, `key_dates`.
Three properties make it load-bearing:

- **Verbatim re-injection.** `CaseFacts.render()` is deterministic and is pinned
  into every rebuilt window by `WorkingMemory.render()` (`window.py`).
- **Summarization exemption.** The block lives **outside** `WorkingMemory.history`.
  `compact()` only ever passes history strings to the summarizer -- the facts are
  structurally unreachable from the compression path
  (`test_window.py::test_compaction_never_feeds_the_facts_to_the_summarizer`).
- **High-attention position.** `render()` pins the block at **both** the top and
  the bottom of the window (beginning and end beat the middle), so the facts sit
  where attention is strongest and are restated right before the model decides.

`CaseFacts` is also `frozen=True`: a fact the verdict depends on cannot be silently
rewritten mid-run.

### Why progressive summarization would decay exactly these specifics

Summarization is lossy and biased toward gist over specifics -- names, numbers, and
dates die before the narrative does. Summarize a window that **already contains a
summary** and the loss compounds geometrically: `claim_amount = $4,200,000.00`
becomes "a multi-million-dollar claim" becomes "a claim." Those are precisely the
load-bearing fields. So they belong in a block that is never fed to the summarizer,
not in the prose that is. `test_window.py::test_progressive_summarization_decays_history_but_never_the_facts`
runs two compaction passes (the second summarizing the first's summary) and asserts
the history's specifics decay while `Acme Robotics LLC`, `$4,200,000.00`, and the
key date survive verbatim.

**Correct pattern:** facts pinned, verbatim, summarization-exempt, double-ended.
**Distractor defeated:** keeping the facts in the conversational prose, where the
first compaction starts eroding them.

---

## 2. Tool-result trimming and position discipline

### Trim by relevance, never by blind truncation

`trim_by_relevance(payload, keep=[...])` (`window.py`) selects named fields. It does
**not** cut to a character or token budget. The distractor "truncate the result to
500 tokens" is wrong because a blind cut can decapitate the one needed field (if it
sits late in the payload) or slice a structure mid-object. `test_trimming.py::test_blind_truncation_decapitates_the_needed_field_but_trimming_does_not`
makes this literal: the needed `counterparty_claims` field sits after a block of
noise, so `serialized[:500]` drops it entirely, while `trim_by_relevance` keeps it
regardless of position. Asking to keep an absent field **raises** rather than
silently returning less than asked -- a field you meant to keep is never quietly
dropped.

### Present is not attended; reposition is the fix

A fact can be in the window and still ignored (lost-in-the-middle). The fix is to
**reposition** it, not to re-add it (which duplicates) and not to summarize it
(which is lossy). `WorkingMemory.reposition(predicate)` moves the matching entry to
the end -- the high-attention position right before the decision -- verbatim and
still unique (`test_window.py::test_reposition_moves_a_buried_entry_without_duplicating_or_altering_it`).
This is why the case-facts block is pinned at both ends in `render()`: position is a
first-class lever, not an afterthought.

---

## 3. Structured error propagation -- the simulated timeout

### The exact structured error object

`records_error` (`errors.py`) returns:

```python
{
    "isError": True,
    "category": "timeout",            # or "outage" | "permission"
    "operation": "fetch_claim_history",
    "detail": "counterparty-history service did not respond within 5s ...",
    "retryable": True,
}
```

Not a bare `null`, not an empty `[]`, not a raw stack trace. The Records Service
returns this on `timeout_on_history` (`records_service.py`).

### Access-failure vs. valid-empty

| Situation                     | Builder               | `isError` | `data`     | Meaning                        | Retry?                |
| ----------------------------- | --------------------- | --------- | ---------- | ------------------------------ | --------------------- |
| Query ran, found nothing      | `records_ok(data=[])` | `False`   | `[]`       | "confirmed: none" -- an answer | No                    |
| Timeout / outage / permission | `records_error(...)`  | `True`    | **absent** | "unknown -- could not check"   | Yes (per `retryable`) |

The error object **has no `data` key** (`test_errors.py::test_access_failure_carries_no_data_field`),
so the collapse that makes an outage read as "no prior claims" is structurally
impossible. Collapsing the two is a latent disaster: an outage would silently read
as "no prior claims found," and the outage would be making the approval decision.

### Terminate-vs-degrade for this load-bearing step

`handle_step_result(result, load_bearing=True)` (`reliability.py`):

- **Load-bearing failure -> terminate + escalate.** Counterparty history is
  load-bearing, so a timeout there returns `proceed=False, terminated=True,
escalated=True`. The coordinator records `history_status="failed"` and the
  finalize gate refuses (`gate.py`). The verdict is never produced.
- **Non-critical failure -> degrade with an honest, scoped label.** The same
  function with `load_bearing=False` returns `proceed=True` but attaches the label
  `"<operation> failed: <category>, not assessed"`.

The dividing line between graceful degradation and silent suppression is **honesty
about what failed**, not the partial result itself -- so the label is attached on
**both** paths (`test_reliability.py`). Degradation that hides the gap behind a
clean-looking result is suppression wearing a friendlier name.

**Correct pattern:** structured error, no `data` key, terminate when load-bearing.
**Distractor defeated:** `return []` on timeout (see the linchpin walkthrough).

---

## 4. Escalation and ambiguity

### The three objective triggers

`should_escalate(...)` (`escalation.py`) fires only on state you can detect:

1. **`explicit_request`** -- the user asked for a human.
2. **`repeated_failure`** -- `failure_count >= retry_threshold`. A count, never the
   first failure.
3. **`out_of_scope`** -- the request crosses authorized scope / a risk threshold.

### Why frustration and self-confidence are not triggers

Both require unreliable inference. Detected frustration is a guess about sentiment;
self-reported model confidence is the same trap that disqualifies confidence as a
routing signal (a confident-wrong model suppresses its own escalation). Model
confidence is **not even an input** to `should_escalate`. Frustration is allowed
only as a **threshold modulator**: it lowers the repeated-failure bar by one (so a
2nd failure with frustration stops the retries that a 2nd failure alone would not),
but never fires with zero failures and never drops below a genuine repeat
(`MIN_REPEATED_FAILURES = 2`). Tests:
`test_escalation.py::test_frustration_alone_never_escalates`,
`::test_frustration_lowers_the_repeated_failure_threshold`.

### The ambiguous record match

`resolve_identity(match_result)` (`escalation.py`): one match resolves, zero
escalates, **two-or-more is ambiguous** -- `resolved_id=None`,
`needs_disambiguation=True`, and the stated reason is "recency is not identity." The
coordinator does not pick the newer registration or either party
(`test_escalation.py::test_two_same_named_parties_never_silently_picks`). It asks a
question only the right party can answer (e.g. the `contract_id` on file) or
escalates. Acting on the wrong record is a high-stakes, often-irreversible error, so
the finalize gate also refuses while identity is ambiguous (`gate.py`).

---

## 5. Synthesis with provenance, contradiction, and supersession

`synthesize(claims)` (`synthesis.py`) groups claims by field and emits a `Finding`
that carries the claim -> source mapping as part of the output (not a discarded
scaffold). Each `Finding.sources` is the surviving list of `Claim`s, and
`provenance` is the human-readable trace.

- **Single claim -> `single`.** `"auto-renews annually" <- Master Agreement §7.2`.
- **Same effective date, no rule -> `contradiction`.** `value=None`, both sources
  attributed. We do not pick, do not average into a fabricated third value, do not
  drop the field. The conflict is signal for a human
  (`test_synthesis.py::test_genuine_contradiction_is_surfaced_with_both_sources_attributed`).
- **Differing dates, unambiguous latest -> `superseded`.** The latest-dated claim
  governs; the prior value, the superseding source, and its date are preserved:
  `"Net 60 (per Amendment 2 §2, 2026-01-15, superseding Net 30 from Master
Agreement §4.1, 2024-03-01)"`. Supersession keys off the **date**, not list order
  (`test_synthesis.py::test_supersession_picks_the_later_date_not_the_listed_order`).
- **Differing dates, contradictory latest -> `contradiction`.** If two claims share
  the latest effective date with different values, the governing date is itself
  ambiguous, so supersession does not resolve it -- it falls back to a contradiction
  over the tied-latest claims rather than picking one
  (`test_synthesis.py::test_contradiction_at_the_latest_date_is_not_collapsed_by_supersession`).
  The `Finding` model enforces this structurally: a `contradiction` with a non-None
  value, or a `superseded` with no `changed_from`, cannot be constructed.

The two failure modes avoided:

- **Time-blind** -- reporting a settled supersession as an open dispute. Defeated by
  not labeling differing-date claims a contradiction.
- **Time-reckless** -- adopting the new value with no trace. Defeated by keeping
  `changed_from` and the superseding provenance.

We resolve only when a sound rule exists (recency), and never **by erasure** -- the
superseded value stays in the output.

---

## 6. Human review by calibrated, per-field confidence

`route_fields(fields, threshold=0.9)` (`routing.py`) decides **per field**. A
low-confidence field routes to a human even if the rest of the verdict is pristine.
`test_routing.py::test_weak_high_stakes_field_routes_to_human_even_when_average_would_approve`
constructs a verdict whose document-level average clears the 0.9 bar while one
high-stakes field sits at 0.55 -- per-field routing still sends that field to a
human, where a document average would auto-approve it.

Confidence must be **calibrated against ground truth**. `is_calibrated(samples)`
checks that the observed accuracy in the `>=0.9` band is actually near 90%
(`test_routing.py`). An uncalibrated score is a vibe, not a measurement -- the same
self-confidence trap that disqualifies confidence as an escalation trigger.

For measuring the pipeline's accuracy, a single **aggregate** number masks
concentrated, high-stakes errors: `aggregate_accuracy` reads >0.9 even when a
high-stakes field is at 50%, while `per_field_accuracy` exposes it
(`test_routing.py::test_aggregate_accuracy_masks_a_concentrated_high_stakes_error`).
And `stratified_plan(...)` deliberately over-covers the rare/high-stakes strata
(claim-amount, counterparty-identity) with a coverage floor, where
`proportional_plan(...)` samples them near zero
(`::test_stratified_sampling_guarantees_coverage_of_the_rare_high_stakes_stratum`).

---

## 7. The two linchpin tests, end to end

### (a) The timeout test

`test_end_to_end.py::test_timeout_test_load_bearing_timeout_never_becomes_a_clean_verdict`.
The model runs `read_documents -> resolve_counterparty -> fetch_history ->
finalize_verdict`. The Records Service times out on the history fetch.
`StubRecordsService.fetch_claim_history` returns `records_error(category="timeout")`
-- `isError:True`, **no `data` key**. `Coordinator.fetch_history` classifies it with
`handle_step_result(load_bearing=True)`, sets `history_status="failed"`, and leaves
`history=None` (not `[]`). The loop forwards the result as a `tool_result` with
`is_error=True` (it never launders a structured error into a clean result). When the
model calls `finalize_verdict`, the PreToolUse gate (`pre_tool_finalize`) sees
`history_status != "ok"` and refuses. **No verdict is issued.** The mechanism that
stops the timeout becoming "no prior claims" is the missing `data` key plus the
gate's insistence on a _successful_ load-bearing fetch -- a timeout literally cannot
present itself as a valid empty answer, and an unconfirmed history cannot clear the
gate. The distractor (`test_timeout_distractor_collapsing_to_empty_would_fabricate_a_clean_pass`)
swaps in a service that returns `data:[]` on timeout, shows a verdict **is** wrongly
issued off the fabricated empty, then re-asserts that the honest service returns
`isError:True` with no `data`.

### (b) The conflict test

`test_end_to_end.py::test_conflict_test_contradiction_surfaced_and_supersession_resolved_with_trace`.
With a healthy history fetch, the verdict is issued and synthesis runs over the five
sample claims. `governing_law` has `Delaware` (Master Agreement §12) and `New York`
(Schedule A §1), both effective `2024-03-01` -- a genuine contradiction, surfaced
with `value=None` and **both** sources attributed for a human to adjudicate.
`payment_terms` has `Net 30` (original) and `Net 60` (Amendment 2, dated later) -- a
temporal conflict, resolved to `Net 60` with `changed_from="Net 30"` and the
superseding provenance preserved (not time-blind, not time-reckless). The unresolved
contradiction routes the whole verdict to `human_review`. The distractor test
contrasts both wrong rules: "two values = open dispute" (time-blind) and "newest
wins, drop the rest" (time-reckless).

---

## Self-grade against your rubric

- **Timeout test holds.** Load-bearing timeout -> structured error (no `data` key)
  -> terminate + gate refusal. No fabricated clean verdict, no `[]` masquerading as
  "none." Distractor shown failing-then-defended.
- **Conflict test holds.** Genuine contradiction surfaced with attribution; temporal
  conflict resolved by supersession with provenance. Neither time-blind nor
  time-reckless.
- **Persistent facts.** `CaseFacts` is verbatim, summarization-exempt (structurally
  outside the compaction path), and double-end pinned; progressive-summarization
  decay is explained and tested.
- **Trimming and positioning.** `trim_by_relevance` selects fields and raises on an
  absent key; `reposition` is the present-not-attended fix.
- **Escalation.** Three objective triggers; frustration is a modulator with a floor;
  the ambiguous match is never silently resolved.
- **Routing.** Per-field, calibrated, with disaggregated / stratified measurement.

## Next increment

The retry path is intentionally minimal: `retryable=True` is carried but the
coordinator escalates a load-bearing timeout rather than retrying with backoff. A
production build would add a bounded retry (honoring `retryable`) before the
repeated-failure escalation trigger fires -- which is exactly where the Domain 4
"repeated failure is a count, not the first failure" rule and this domain's
`should_escalate` threshold meet.
