# ADR-001: code checks for claims now, an LLM judge later

**Status:** accepted, 2026-11-16 (week 1)

**Context.** Error analysis of 20 analyses (`evals/taxonomy.md`) found seven failure classes. Five are mechanical:
the answer is a fact about strings and ids (a window name in prose, a label in {value}, an opinion with parents,
an inference naming uncited indicators, an unknown source). One, a verdict inside a fact (33 claims), needs a
reading of the wording. A judge costs a model call per analysis and is itself a classifier that can be wrong; its
agreement with a human has to be measured on labelled data before its score means anything.

**Decision.**
- Every mechanical class gets a deterministic code check: `claims_valid` / `all_claims_valid` (shipped) and
  `inferences_grounded` (new, `evals/specs/inferences_grounded.md`). They run free on every analysis.
- judgement_in_fact waits for an LLM judge in week 4, built against `labels.csv` with agreement (TPR/TNR) measured
  on a held-out split.
- The headline metric for prompt work is `all_claims_valid`: one bad claim spoils an analysis for the reader.

**Consequences.** Week 1 metrics say nothing about tone or verdicts; a prompt can score 1.0 here and still editorialise.
`labels.csv` must keep the judgement_in_fact notes so the judge has training and test labels later.

**Readings.** Shankar & Husain, *Evals for AI Engineers*, on code-based evaluators before LLM judges and on
validating a judge against human labels.
