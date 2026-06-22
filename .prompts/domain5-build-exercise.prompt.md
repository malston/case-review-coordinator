# Domain 5 Build Exercise — Review Coordinator with Persistent Case Facts

You are helping me build a multi-agent review coordinator that exercises every concept in
Domain 5 (Context Management & Reliability) of the Claude Certified Architect exam. Build it
with me incrementally. Explain each design choice as you go, and push back hard if my
instructions violate the principles below.

## Build target

A **review coordinator** that assesses a long-running case (a contract plus its amendments)
by delegating to **two subagents** and synthesizing one verdict. It must maintain a
**persistent case-facts block**, isolate each subagent's heavy reads in its **own context
window**, **simulate a timeout** that propagates as **structured error context**, and
**synthesize conflicting sources** with provenance — surfacing a genuine contradiction and
resolving a temporal one. The two subagents:

- **Document Reader** — reads the contract + amendments (heavy, noisy reads) and returns a
  short list of **claims, each with a source citation**. Its raw file reads never enter the
  coordinator's window.
- **Records Service** — queries an external counterparty-history service via a tool. This is
  where the **timeout** and an **ambiguous record match** occur.

The two tests the system must pass (the linchpins — like Domain 4's fabrication-trap document):

> **The timeout test.** The Records Service call to fetch counterparty claim-history **times
> out**, and that history is **load-bearing** for the verdict. The system must **never** turn
> the timeout into a clean result (e.g. "no prior claims found"). A timed-out load-bearing step
> must surface as a structured error and **terminate or escalate** — it must not produce an
> approved verdict. If the final output reads as a confident pass while a required check silently
> failed, the system fails the test.
>
> **The conflict test.** Among the sources, two values conflict. One is a **genuine
> contradiction** (two sources, same effective date, no rule to pick a winner) and must be
> **surfaced with both sources attributed**. The other is **temporal** (an amendment, dated
> later, supersedes the original) and must be **resolved with its provenance preserved** — the
> newer value, plus what it changed and when. Silently picking, averaging, or dropping either
> conflict fails the test.

## Requirements — every one must be satisfied

1. **Coordinator + two subagents with context isolation, and a persistent case-facts block.**
   Stand up the topology and the memory model:
   - Each subagent runs in its **own context window**. The Document Reader burns its window on
     the raw file reads and returns only a **short structured summary** (claims + citations);
     those raw reads **never touch the coordinator's window**. State the context economics: the
     coordinator pays a few lines for what would otherwise cost thousands of tokens of reads.
   - Define a **case-facts block** — the load-bearing specifics the workflow cannot function
     without (e.g. `case_id`, `counterparty`, `contract_id`, `claim_amount`, `key_dates`). It is
     **re-injected verbatim into every turn**, **exempt from summarization**, and **pinned at a
     high-attention position** (top of the rebuilt window, or restated right before the model
     decides). Explain why the conversational back-and-forth may be summarized but these facts
     may not — and why progressive summarization (summarizing a context that already contains a
     summary) would decay exactly these specifics first.

2. **Tool-result trimming and position discipline (the lost-in-the-middle defense).** Curate
   what re-enters the window:
   - When a subagent or tool returns a large payload, **trim by relevance, not by truncation** —
     select the needed fields, never blind-cut to N characters. State plainly why "truncate the
     result to 500 tokens" is wrong: it can decapitate the one needed field or cut mid-structure.
   - Show that a fact being **present** in the window is not the same as it being **attended to**.
     Name where the case-facts block sits and why (beginning/end beat the middle), and give the
     fix when the agent ignores a fact it "has": **reposition**, not re-add and not summarize.

3. **Structured error propagation — simulate the timeout.** Wire the failure path:
   - Simulate the Records Service tool **timing out**. It must return **structured error
     context** — `isError: true`, a `category` (e.g. `timeout`), the `operation`, a short
     `detail`, and `retryable` — **not** a bare `null`, **not** an empty `[]` that looks like a
     valid answer, and **not** a raw stack trace dumped into context.
   - Encode the **access-failure vs valid-empty** distinction explicitly: a successful query that
     finds nothing returns `isError:false, data:[]` ("confirmed: none" — do not retry); a
     timeout/permission/outage returns `isError:true` ("unknown — could not check"). Show why
     collapsing both into `[]` is a latent disaster (an outage silently reads as "no prior
     claims," and an outage is now making the approval decision).
   - Give the coordinator the **terminate-vs-degrade** judgment: because counterparty history is
     **load-bearing**, a timeout there must **terminate or escalate**, never silently suppress.
     Contrast with a **non-critical** failure (e.g. one of several optional reference lookups),
     which may **degrade gracefully with an honest, scoped label** ("history check failed:
     timeout, not assessed"). State the dividing line: the difference between graceful degradation
     and silent suppression is **honesty about what failed**, not the partial result itself.

4. **Escalation and ambiguity.** Define when the coordinator hands off to a human:
   - The **three valid triggers**, each detectable from objective state: explicit user request
     for a human; **repeated** failure on the same issue (a count, not first-failure); a request
     that exceeds the agent's **authorized scope** / crosses a risk threshold.
   - Explain why **detected frustration** and **self-reported model confidence** are **not**
     standalone triggers (both require unreliable inference), and show frustration used correctly
     — as a **threshold modulator** ("2nd failure **and** frustration → stop retrying now"),
     never as the trigger itself.
   - Handle the **ambiguous record match**: the Records Service returns **two counterparties with
     the same name**. The coordinator must **not silently pick one** (recency is not identity) —
     it **disambiguates** (asks a question only the right party can answer) or **escalates**.
     State why acting on the wrong record is a high-stakes, often-irreversible error.

5. **Synthesis with provenance, conflict handling, and temporal supersession.** Produce the
   verdict honestly:
   - Every claim in the synthesized output carries a **claim → source mapping** that **survives
     synthesis** (e.g. `"auto-renews annually" ← Master Agreement §7.2`). State why this makes
     the output verifiable and correctable, and that the mapping is **part of the output**, not a
     discarded scaffold.
   - For the **genuine contradiction** (same effective date, no rule to choose): **surface both
     with attribution** — do not pick, do not average into a fabricated third value, do not drop
     the field. The conflict is signal for a human to adjudicate.
   - For the **temporal conflict**: apply **supersession** (the later amendment governs) **and
     preserve provenance** — output the newer value plus what changed and when (e.g. `"Net 60
(per Amendment 2, 2026-01-15, superseding the original's Net 30)"`). Name the two failure
     modes you are avoiding: **time-blind** (reporting a settled supersession as an open dispute)
     and **time-reckless** (using the new value with no trace of the change). Reconcile with the
     conflict rule: you may **resolve** when a sound rule exists, but never **resolve by erasure**.

6. **Human review by calibrated, per-field confidence (and honest measurement).** Route the
   verdict for review:
   - Route **per field**, not per document — a low-confidence field goes to a human even if the
     rest of the verdict is pristine. Explain why a document-level average lets a strong field
     drag a weak high-stakes field across the auto-approve line.
   - Use confidence that is **calibrated against ground truth** — "fields scored ≥0.9 are right
     ~90% of the time" must be empirically verified, not assumed. State why an uncalibrated score
     is a vibe, not a measurement (and tie it back to Requirement 4's self-confidence trap).
   - When you describe how you'd **measure** the pipeline's accuracy, reject a single **aggregate**
     number (it masks concentrated, high-stakes errors) in favor of **per-field accuracy** and
     **stratified sampling** that deliberately over-covers the rare/high-stakes strata (the
     claim-amount / counterparty-identity fields), not a frequency-proportional random sample.

## Principles to enforce while building (Domain 5 spine)

- **The window is working memory, not storage — lossy and position-sensitive.** Curate it
  deliberately: pin load-bearing facts verbatim, exempt them from summarization, place them at
  high-attention positions, and keep tool noise out.
- **Progressive summarization decays specifics first.** Summarizing a summary compounds loss
  geometrically; the high-value specifics (numbers, names, dates) die before the gist. Critical
  facts belong in a persistent block that is never summarized, not in the prose that is.
- **Present ≠ attended.** Lost-in-the-middle means a fact can be in the window and ignored. When
  an agent ignores something it "has," **reposition** — do not re-add and do not summarize.
- **Trim by relevance, never by blind truncation.** Trimming is selecting needed fields, not
  cutting to a character count; truncation decapitates fields and corrupts structure.
- **Errors are information that must propagate as structured context.** `isError` + category +
  operation + retryability — never a swallowed `null`, never a fabricated success, never a raw
  trace. Silent suppression (manufacturing a clean result from a failure) is the cardinal sin: a
  confident wrong answer is worse than a loud failure.
- **"Couldn't access" is not the answer "none."** A valid empty result is an answer (do not
  retry); an access failure is the absence of an answer (retry / escalate / label the gap).
  Collapsing them lets an outage make decisions.
- **Terminate when the failed step is load-bearing; degrade only with an honest, scoped label.**
  The line between graceful degradation and silent suppression is honesty about what failed.
- **Escalate on objective state, never on inferred state.** Explicit request, repeated failure,
  out-of-scope are detectable; sentiment and self-reported confidence are unreliable inference.
  Frustration modulates a real trigger's threshold — it is never the trigger.
- **Never resolve identity ambiguity by guessing.** An ambiguous record match is a
  disambiguate-or-escalate trigger; recency is not identity.
- **Synthesis must preserve provenance.** Every claim carries a source mapping that survives the
  merge. Surface conflicts with attribution; resolve only by a sound rule (temporal supersession)
  and never by erasure — keep what changed and when.
- **Disaggregate and calibrate before you trust a number.** Aggregate accuracy masks concentrated
  errors; route per-field by confidence calibrated against ground truth; sample by risk and
  rarity, not frequency.

## Deliverables

Produce, with the design explained:

1. The topology — coordinator + two subagents — with the context-isolation rationale, and the
   **case-facts block** (its fields, the verbatim re-injection, the summarization exemption, the
   pinned position), plus the one-paragraph progressive-summarization-decay explanation.
2. The tool-result **trimming** rule (relevance vs truncation) and the **positioning** statement
   (present ≠ attended; reposition as the fix).
3. The Records Service **timeout** return — the exact structured error object — plus the
   **access-failure vs valid-empty** table and the coordinator's **terminate-vs-degrade** decision
   for this load-bearing step, with the suppression-vs-degradation line stated.
4. The **escalation** design — the three valid triggers, the frustration-as-modulator example,
   and the **ambiguous-match** handling (disambiguate or escalate, recency-is-not-identity).
5. The **synthesis** output — claim→source mappings, the genuine contradiction surfaced with
   attribution, and the temporal conflict **resolved with provenance** (naming the time-blind and
   time-reckless failure modes you avoided).
6. The **human-review routing** — per-field, calibrated-confidence, with the stratified-sampling /
   aggregate-masking measurement note.
7. One paragraph each, walking the **two linchpin tests** end to end: (a) the **timeout test** —
   show the load-bearing timeout surfacing as structured error and terminating/escalating, naming
   the mechanism that stops it becoming "no prior claims"; (b) the **conflict test** — show the
   genuine contradiction surfaced and the temporal conflict resolved-with-trace.

## How I want you to grade the result (apply this to your own output)

- Does the **timeout test** hold — a load-bearing timeout becomes a **structured error** that
  **terminates/escalates**, never a fabricated clean verdict, and never an `[]` masquerading as
  "none found"?
- Does the **conflict test** hold — the genuine contradiction **surfaced with attribution**, the
  temporal conflict **resolved with provenance** (not time-blind, not time-reckless)?
- Are the load-bearing facts in a **persistent case-facts block** that is verbatim, summarization-
  exempt, and **high-attention positioned** — and is the progressive-summarization decay explained?
- Is tool output **trimmed by relevance** (not truncated), and is **present ≠ attended** handled by
  **repositioning**?
- Are escalation triggers **objective** (request / repeated-failure / out-of-scope), is frustration
  only a **modulator**, and is the **ambiguous match** never silently resolved?
- Is review routing **per-field** on **calibrated** confidence, and is the measurement **stratified
  / disaggregated** rather than a single aggregate?

Build it step by step. Where my instructions would violate a principle above, stop and tell me.
