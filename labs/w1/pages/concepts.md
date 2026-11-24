# Concept index (week 1)

Labs spike v3, not published. One entry per term: what it means, where to read it, and the exercises that practise it. "Defined again in" is the duplication found in the audit (labs spike `AUDIT.md`, outside this repo), finding 2; in the full design those weeks link here instead. Reading links go to the labs spike v1 slim reading `week-1-reading-slim.md` (outside this repo), which the labs keep as is.

| Term | Means | Practised in | Defined again in |
|---|---|---|---|
| [Source table](#source-table) | the prompt's rows of code-computed numbers the model may cite | w1l1.1, w1l1.2 | – |
| [Claim check](#claim-check) | `check_one`: the code that rejects a claim, with a reason | w1l1.1 to w1l1.4 | – |
| [Trace](#trace) | the full record of one model call | w1l2.1 | week 3 |
| [Grader](#grader) | scores one output against a written rule; registered by id | w1l3.1, w1l3.6 | – |
| [Code-checkable grader](#code-checkable-grader) | a deterministic assertion over the parsed reply | w1l3.1 to w1l3.5 | – |
| [Error analysis](#error-analysis) | read outputs, note failures, count them, then write evals | w1l2.1 to w1l2.4, w1l3.6 | – |
| [Open coding](#open-coding) | notes in your own words before any categories | w1l2.1 | – |
| [Axial coding](#axial-coding) | group the notes into classes and count them | w1l2.2, w1l2.3 | – |
| [Failure taxonomy](#failure-taxonomy) | the classes, each with a definition and counts | w1l1.4, w1l2.3, w1l2.4, w1l4.1 | – |
| [LLM judge](#llm-judge) | a second model call that grades against a rubric | reading only (lab w1l3) | week 2 |
| [ADR](#adr) | one short file per decision: context, decision, consequences | reading only (labs w1l3, w1l4) | – |
| [Eval spec](#eval-spec) | the grader's failure, unit, rule and acceptance checks, before code | w1l3.2, w1l3.5, w1l3.6 | – |
| [Prompt version](#prompt-version) | a prompt kept as its own file in git | w1l4.1 | – |
| [Pre-registration](#pre-registration) | primary and guard metric fixed before the results | w1l4.2, w1l4.5 | weeks 2, 8 |
| [Paired comparison](#paired-comparison) | compare arms item by item on the same items | w1l4.2, w1l4.3 | – |
| [Confidence interval](#confidence-interval) | the range of differences the data are consistent with | w1l4.4, w1l4.5 | – |
| [Cluster bootstrap](#cluster-bootstrap) | resample whole tickers to get the interval | w1l4.4 | week 3 |
| [McNemar's test](#mcnemars-test) | binary-metric test on the items where arms disagree | w1l4.3 | week 4 |
| [Wilcoxon signed-rank test](#wilcoxon-signed-rank-test) | ranks the per-item differences | reading only (lab w1l4) | – |
| [Power and MDE](#power-and-mde) | the smallest effect this many items could reliably see | reading only (lab w1l4) | week 3 |
| [Ablation](#ablation) | remove one component to measure what it adds | reading only (lab w1l4) | week 5 |
| [Scope](#scope) | one page: user, job, out of scope, quality and cost bars | reading only (lab w1l4) | – |
| [Fine-tuning](#fine-tuning) | more training of a model's weights on your examples | reading only (lab w1l4) | – |
| [Build versus tune](#build-versus-tune) | is the next gain in the system or in the model? | reading only (lab w1l4) | – |

## Week 1

### Source table

The prompt's SOURCES rows (`source_id | name | value | unit`), computed by code; the model cites ids and writes `{value}`. Read: week 1, source table (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l1.1](w1l1.md#w1l11-unknown_source), [w1l1.2](w1l1.md#w1l12-number_in_text).

### Claim check

`check_one` rejects a claim and returns the reason (`number_in_text`, `bad_placeholder`, ...). Read: week 1, claim check (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l1.1](w1l1.md#w1l11-unknown_source), [w1l1.2](w1l1.md#w1l12-number_in_text), [w1l1.3](w1l1.md#w1l13-placeholders), [w1l1.4](w1l1.md#w1l14-cascade).

### Trace

The full record of one model call: input, raw output, parse, checks. Read: week 1, trace (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l2.1](w1l2.md#w1l21-open-coding).

### Grader

Scores one output against a written rule; registered by id in `GRADERS`, and only registered graders can be named in a config. Read: week 1, grader (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l3.1](w1l3.md#w1l31-names-in-each-item), [w1l3.6](w1l3.md#w1l36-register-and-meet-the-spec).

### Code-checkable grader

A deterministic assertion over the parsed reply: free and exact. Read: week 1, code-checkable grader (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l3.2](w1l3.md#w1l32-rule-on-direct-parents), [w1l3.3](w1l3.md#w1l33-recurse-through-inference-parents), [w1l3.4](w1l3.md#w1l34-whole-tokens-only), [w1l3.5](w1l3.md#w1l35-dist-alias).

### Error analysis

Read many real outputs, write down what goes wrong, count it, then write evals. Read: week 1, error analysis (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [lab w1l2](w1l2.md#w1l21-open-coding), closed by [w1l3.6](w1l3.md#w1l36-register-and-meet-the-spec) (the grader's flags must match your labels).

### Open coding

Notes in your own words, first failure per trace, no classes yet. Read: week 1, open coding (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l2.1](w1l2.md#w1l21-open-coding).

### Axial coding

Group the notes into classes and count them. Read: week 1, axial coding (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l2.2](w1l2.md#w1l22-tally-classes), [w1l2.3](w1l2.md#w1l23-taxonomy-table).

### Failure taxonomy

The classes from axial coding, each with a definition, a claim count and an analysis count. Read: week 1, failure taxonomy (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l2.3](w1l2.md#w1l23-taxonomy-table), [w1l2.4](w1l2.md#w1l24-back-fill-classes); used by [w1l1.4](w1l1.md#w1l14-cascade) and [w1l4.1](w1l4.md#w1l41-write-the-variant-prompt).

### LLM judge

A second model call that grades against a rubric; untrusted until measured against labels. Read: week 1, LLM judge (labs spike v1 `week-1-reading-slim.md`, outside this repo). Reading only in week 1 (ADR-001 defers it); built in week 2.

### ADR

Architecture decision record: one short file per decision with context, decision and consequences. Read: week 1, ADR (labs spike v1 `week-1-reading-slim.md`, outside this repo). Reading only: ADR-001 in [lab w1l3](w1l3.md), ADR-002 in [lab w1l4](w1l4.md).

### Eval spec

Before any code: the failure, unit and score, rule and acceptance checks. Read: week 1, eval spec (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l3.2](w1l3.md#w1l32-rule-on-direct-parents), [w1l3.5](w1l3.md#w1l35-dist-alias), [w1l3.6](w1l3.md#w1l36-register-and-meet-the-spec).

### Prompt version

A prompt as its own file in git, so an arm names exact text. Read: week 1, prompt version (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l4.1](w1l4.md#w1l41-write-the-variant-prompt).

### Pre-registration

The primary metric and guard metric are fixed before you see results. Read: week 1, pre-registration (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l4.2](w1l4.md#w1l42-write-the-experiment-config), [w1l4.5](w1l4.md#w1l45-apply-the-pre-registered-rule).

### Paired comparison

Both arms on the same items, compared item by item; clustered by ticker. Read: week 1, paired comparison (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l4.2](w1l4.md#w1l42-write-the-experiment-config), [w1l4.3](w1l4.md#w1l43-paired-differences-and-mcnemar).

### Confidence interval

The range of differences the data are consistent with at the stated level. Read: week 1, confidence interval (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l4.4](w1l4.md#w1l44-cluster-bootstrap), [w1l4.5](w1l4.md#w1l45-apply-the-pre-registered-rule).

### Cluster bootstrap

Resample whole tickers, recompute the mean difference, read the interval off the spread. Read: week 1, cluster bootstrap (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l4.4](w1l4.md#w1l44-cluster-bootstrap).

### McNemar's test

For a binary metric: uses only the items where the arms disagree. Read: week 1, McNemar's test (labs spike v1 `week-1-reading-slim.md`, outside this repo). Practised in: [w1l4.3](w1l4.md#w1l43-paired-differences-and-mcnemar).

### Wilcoxon signed-rank test

For a share metric: ranks the per-item differences. Read: week 1, Wilcoxon signed-rank test (labs spike v1 `week-1-reading-slim.md`, outside this repo). Reading only: `paired.py` prints "(not 0/1: no McNemar)" for `claims_valid` instead.

### Power and MDE

Power is the chance of detecting a real effect of a given size; the MDE is the smallest effect this many items can reliably detect. Read: week 1, power and MDE (labs spike v1 `week-1-reading-slim.md`, outside this repo). Reading only (lab w1l4).

### Ablation

Remove one component to measure what it contributes. Read: week 1, ablation (labs spike v1 `week-1-reading-slim.md`, outside this repo). Reading only (lab w1l4).

### Scope

One page: user, job, out of scope, quality and cost bars, measured numbers only. Read: week 1, scope (labs spike v1 `week-1-reading-slim.md`, outside this repo). Reading only (lab w1l4).

### Fine-tuning

Continued training of a pre-trained model's weights on your own examples. Read: week 1, fine-tuning (labs spike v1 `week-1-reading-slim.md`, outside this repo). Reading only (lab w1l4).

### Build versus tune

Does the next gain come from the system around the model or from the model? Read: week 1, build versus tune (labs spike v1 `week-1-reading-slim.md`, outside this repo). Reading only (lab w1l4).
