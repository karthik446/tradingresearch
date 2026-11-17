# Eval spec: citation_accuracy

**Question it answers:** when an analysis cites a retrieved filing or headline passage, was that passage really
given to the model, and does it hold the number the claim states? `claims_valid` cannot answer this: a passage has no
value row, so a numeric claim citing only a passage is rejected `unsourced_number` whatever the passage says
(runbook, "Arm knob"), and a value-less claim citing it passes on the citation alone.

**Failure modes it was built for:**
- An invented citation: a chunk id the model never saw, either made up in the `<doc id>#<n>` shape or copied from
  another analysis. `validate_claims` rejects an unknown id as `unknown_source`, but only against the arm's own view;
  this grader states it as its own reason, so a run shows how often it happens.
- A misread number: the claim's value is not in the passage it cites (wrong row, wrong period, a figure from another
  passage or from the model's memory).

**Unit and score:** one analysis. A claim is *graded* when at least one of its `source_ids` is a chunk id (`<doc
id>#<n>`, as `tr retrieval query` prints it; SOURCES rows are `src_...`). Score = supported graded claims ÷ graded
claims. Claims citing only SOURCES rows are not graded here (`claims_valid` covers them). Below 1.0 the explanation
starts with the sorted, distinct reasons, e.g. `not_retrieved, number_mismatch: 2 of 3 claims citing passages fail`.

**What counts as supported:** a graded claim is supported when both hold:
1. every chunk id it cites is a key of `expected["passages"]`, the passages that arm sent for that item (else
   `not_retrieved`). One unseen id fails the claim even if another cited passage holds the number: a citation list is
   only as good as its worst entry.
2. its `value`, when not null, matches a number written in at least one of its cited passages (else
   `number_mismatch`). A value-less claim (an event, a reason) passes on check 1 alone.

Why the chunk id is the citation and the chunk text is the quote: analyze-3 claims have no quote field, and a claim
whose text holds a digit already fails `number_in_text`, so the only number to check is `value` and the only pointer
to the evidence is the id.

**Tolerance:** rtol 0.5% (`analyze.REL_TOL` = 0.005, the same `close_to` as `validate_claims`), so `703` matches a
printed `701` and prose rounding is absorbed. Numbers in a passage are every `\d[\d,]*(\.\d+)?`: thousands
separators are dropped, and signs are ignored on both sides, because a filing prints a loss as `(45)` while the
model writes `-45`. Units are **not** converted: a claim of `15.3` (billions) against a table printing `15,305` (in
millions) is `number_mismatch`.

**Edge cases:**
- A reply that did not parse, or has no `claims` list: `CannotGrade("no_claims: ...")`.
- No claim cites a chunk id (the usual case today: the recorded week-6 reply cites none of its 3 passages):
  `CannotGrade("no_claims: ...")`. No score is stored, so a run that never cites a passage is never 1.0 and `compare`
  sees a smaller n for this grader.
- The no-retrieval arm has no `passages`: any chunk id it cites is `not_retrieved`; with none cited it cannot be
  graded, so the experiment table reads `n/a` there.
- Small values (under about 100) can match an unrelated number in a long passage (a page number, a year, a note
  number); the check is "the number is written in the passage", not "in the right row".
- A non-numeric `value` is `number_mismatch`.

**What is not checked:**
- Prose faithfulness: whether the claim's words say what the passage says (a value-less claim citing the recall 8-K
  as evidence of a buyback passes).
- Whether the number is in the right row, period or unit.
- Whether the passage is true or relevant, or whether a better passage existed (that is retrieval recall,
  `tr retrieval eval`).
- Claims that use a passage without citing it.

**Judge variant:** a later grader would send each value-less graded claim and its cited passage texts to an LLM judge
(a different vendor from the analyst, as ADR-003) that answers whether the passage supports the claim, validated
against hand labels before it is trusted (REPO-PLAN Week 6 names "a judge for filing-text claims" and budgets about
$0.30 for it). It is not part of this contract.

**Inputs:** the parsed reply (`claims[].source_ids`, `claims[].value`) and `expected["passages"]` (chunk id → text, in
rank order), which a retrieval arm adds with `experiment.with_passages`.

**Tests:** `tests/test_week6.py`: hand-made claims on the three recorded FAKEA passages (exact, within 0.5%, a
thousands separator, a parenthesised loss, a per-share decimal, the value in the second of two cited passages, a
value-less claim → 1.0; a wrong value, a value only in an uncited passage, a value not in the passage →
`number_mismatch`; an unseen chunk alone or beside a retrieved one → `not_retrieved`; one of three supported → 1/3
with `not_retrieved, number_mismatch` first; the no-passage arm → `not_retrieved`; no claims, a reply that did not
parse and the recorded reply → `CannotGrade`). How it was validated: those cases, plus a mutation (rtol tightened to
0) that makes the `rounded` case fail.
