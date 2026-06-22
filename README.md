# Domain 5 -- Case-Review Coordinator

A runnable, test-driven implementation of the CCA Domain 5 build exercise. A
coordinator assesses a long-running case (a contract plus its amendments) by
delegating to two isolated subagents -- a **Document Reader** and a **Records
Service** -- and synthesizes one verdict. It maintains a persistent **case-facts
block**, isolates each subagent's heavy reads in its own context window,
propagates a simulated **timeout** as structured error context, and synthesizes
conflicting sources with provenance.

Two linchpins, each a real passing test:

- **The timeout test.** The load-bearing counterparty-history fetch times out. It
  surfaces as a structured error and the finalize gate stays shut -- it **never**
  becomes "no prior claims found," and never an `[]` masquerading as a valid empty
  answer.
- **The conflict test.** A genuine contradiction (two sources, same effective date)
  is **surfaced with both attributed**; a temporal conflict (a later amendment) is
  **resolved by supersession with its provenance preserved**.

- The design doc this implements: [`../deliverables/domain5-build-exercise.md`](../deliverables/domain5-build-exercise.md)
- The exercise prompt: [`../.prompts/domain5-build-exercise.prompt.md`](../.prompts/domain5-build-exercise.prompt.md)

## Quick start

```bash
poetry install --with dev
poetry run pytest                      # NO API key needed
poetry run python -m case_review.demo
```

The demo runs the same system along three model trajectories:

```
=== happy ===
  VERDICT ISSUED (disposition: human_review)
=== timeout ===
  no verdict issued
  BLOCKED: {"isError": true, "category": "timeout", "operation": "fetch_claim_history", ...}
  BLOCKED: finalize blocked: counterparty claim-history was not confirmed (status='failed'); ...
=== ambiguous ===
  no verdict issued
  BLOCKED: finalize blocked: counterparty identity is ambiguous -- disambiguate or escalate ...
```

The happy path issues a verdict (routed to human review because of a genuine
contradiction). The timeout and ambiguous paths refuse to finalize. The only
differences are whether the load-bearing history fetch succeeded and whether the
counterparty resolved -- the model's narration changes nothing.

## The two linchpins

**Timeout.** The counterparty-history fetch is load-bearing. On timeout,
`records_error` (`errors.py`) returns `isError:True` with a `category` and **no
`data` key at all** -- so it is structurally impossible to read the outage as
`data:[]` ("none found"). `Coordinator.fetch_history` records
`history_status="failed"` (never `"ok"`), and the `finalize_verdict` PreToolUse
gate (`gate.py`) refuses unless the history check succeeded. A timed-out
load-bearing step can never be laundered into a confident pass. See
`tests/test_end_to_end.py`.

**Conflict.** `synthesize` (`synthesis.py`) keeps each claim's source mapping
through the merge. Same effective date with no rule -> a `contradiction` surfaced
with both sources, value left `None`. Differing dates -> a `superseded` finding:
the later amendment governs, with the prior value and the superseding source/date
preserved (avoiding both time-blind and time-reckless). See `tests/test_synthesis.py`
and `tests/test_end_to_end.py`.

## How the deliverables map to code

| Deliverable                                   | Where                                               | Correct pattern (demonstrated)                                                            | Distractor (shown failing / defended)                           |
| --------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| 1. Topology + isolation + case-facts block    | `subagents.py`, `window.py`, `schemas.py`           | Reader burns its own window; facts pinned, verbatim, summarization-exempt                 | Raw reads flood the coordinator; facts kept in summarized prose |
| 2. Trim by relevance + reposition             | `window.py`                                         | `trim_by_relevance` selects fields; `reposition` moves the buried fact                    | Truncate to N chars (decapitates the field); re-add/summarize   |
| 3. Structured error + load-bearing timeout    | `errors.py`, `records_service.py`, `reliability.py` | `isError`/category/operation/detail/retryable, no `data` key; terminate when load-bearing | `return []` on timeout; degrade silently with no label          |
| 4. Escalation + ambiguous match               | `escalation.py`                                     | Objective triggers; frustration modulates; never silently pick a same-named party         | Escalate on sentiment; pick the newer registration              |
| 5. Synthesis + contradiction + supersession   | `synthesis.py`                                      | Provenance survives; contradiction surfaced; supersession resolved with trace             | Average/pick/drop; time-blind or time-reckless                  |
| 6. Per-field calibrated routing + measurement | `routing.py`                                        | Route per field on calibrated confidence; per-field + stratified measurement              | Document-level average; uncalibrated score; aggregate accuracy  |

## The load-bearing gate -- two decisions the model never makes

- **Classifying a failure.** `Coordinator.fetch_history` decides whether the history
  result is a success (`status="ok"`, data stored) or an access failure
  (`status="failed"`, structured error stored, `history` left `None`). The model
  cannot relabel a timeout as a clean result.
- **Issuing the verdict.** Only the gate authorizes `finalize_verdict`, and only when
  identity is resolved and the load-bearing history check succeeded. "The model said
  it checked the history" is the natural-language-termination anti-pattern, and the
  gate refuses it.

## Module guide

| Module               | Responsibility                                                                    |
| -------------------- | --------------------------------------------------------------------------------- |
| `loop.py`            | Model-agnostic agentic loop + `ModelClient` seam; forwards structured errors      |
| `harness.py`         | Wires read/resolve/fetch_history/finalize tools + the finalize gate onto the loop |
| `coordinator.py`     | Orchestration steps: read, resolve, fetch_history (load-bearing), finalize        |
| `gate.py`            | The `finalize_verdict` PreToolUse gate (the linchpin)                             |
| `window.py`          | `WorkingMemory` (pin + compact + reposition) and `trim_by_relevance`              |
| `schemas.py`         | `CaseFacts` (frozen, verbatim) and `Claim` (source + effective_date required)     |
| `state.py`           | `CaseState` -- the harness's memory, including `history_status`                   |
| `errors.py`          | `records_error` / `records_ok` -- access-failure vs valid-empty                   |
| `records_service.py` | The external counterparty-history seam (timeout, outage, ambiguous match)         |
| `reliability.py`     | `handle_step_result` -- terminate-vs-degrade                                      |
| `escalation.py`      | `should_escalate` (objective triggers) and `resolve_identity` (ambiguity)         |
| `synthesis.py`       | `synthesize` -- provenance, contradiction, temporal supersession                  |
| `routing.py`         | Per-field calibrated-confidence routing + disaggregated/stratified measurement    |
| `subagents.py`       | The Document Reader seam (`StubDocumentReader`) and its isolated `DocumentBundle` |
| `sample_case.py`     | The shared contract + amendments + records fixtures                               |
| `live.py`            | Optional `ClaudeClient` / `ClaudeDocumentReader` against the real Messages API    |
| `demo.py`            | The three-trajectory offline demonstration                                        |

## The live path (optional)

```bash
poetry install --with dev --with live
export ANTHROPIC_API_KEY=...           # or cp .env.example .env
```

`ClaudeClient` and `ClaudeDocumentReader` (`live.py`) drive the loop and the
isolated Document Reader against `claude-opus-4-8` with adaptive thinking. The
deterministic seam (`StubDocumentReader` + `ScriptedClient`) powers every test, so
the suite never needs a key.
