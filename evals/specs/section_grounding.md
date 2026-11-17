# Eval spec: per-section grounding (`indicators_grounded`, `levels_grounded`, `edgar_grounded`, `headlines_grounded`)

**Question it answers:** when an analysis leans on one part of its context, are those claims valid? Week 5's context
ablation drops whole SOURCES sections; these graders show, per section, how the claims that cite it fare.

**Unit and score:** one analysis, one score per section (`masking.SECTIONS`). A claim *cites* a section when one of
its `source_ids` is a row whose table name `masking.section_of` puts in that section; a claim citing rows of two
sections counts in both. Score = (claims citing the section that `analyze.validate_claims` keeps) ÷ (claims citing
the section). Below 1.0 the explanation starts with the sorted, distinct rejection reasons, e.g.
`empty_placeholder: 1 of 7 claims citing indicators fail`.

**Not cited:** no claim cites the section → `CannotGrade("not_cited: ...")`. No score is stored, so
`experiment.means` and `compare` see a smaller n for that grader; a section nobody cites is never 1.0.

**Drop arms:** the arm's `drop` reaches the grader (`evals.graders(names, drop)`), and a claim citing a row the
arm never saw is rejected `dropped_source`, so it counts as failing in its section.

**What is checked:** exactly `validate_claims` and nothing more: no digit in the claim text outside `{value}`,
placeholders, every cited id exists in the table, no dropped row, no number in an opinion, a fact's value matches a
cited row's value, an inference derives from kept claims and its value matches a parent's.

**What is not checked:**
- **A headline claim passes on its citation alone.** A headline row has no number (its value is the quoted text), so
  a claim citing it with a null value and no digit in its text passes. Nothing checks that the claim says what the
  headline says (faithfulness of the paraphrase) or that the headline is true.
- Whether an indicator or level is read correctly (above/below, trend words): only the number is compared.
- Inferences grounded only through `derived_from`: only direct `source_ids` count toward a section
  (`inferences_grounded` covers the parent chain).
- Two claims with the same id: a rejection is matched to claims by id, so both count as failing.

**Inputs:** the parsed reply, `expected["values"]` and `expected["names"]` from `analyze.item_for`. A reply that did not
parse raises CannotGrade (`parsed` counts it).

**Tests:** `tests/test_week5.py` (hand-built claims on the FAKEA context and the recorded analyze-3 reply:
indicators 6/7 with `empty_placeholder`, headlines 1/1, levels and EDGAR not cited) and
`tests/test_section_grounding.py`.
