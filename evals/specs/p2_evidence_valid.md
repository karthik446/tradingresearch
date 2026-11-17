# Eval spec: p2_evidence_valid

**What it checks:** SPIKE §7.2 row P2. A thesis lists `evidence` (claim ids of its analysis). P2 asks whether that
evidence is real: every id names a fact or inference claim of the analysis, every fact cites a source in the
analysis's source table, and every numeric fact matches one of its cited sources within a relative tolerance of
0.5%. This is the code half of *process grading* (grade the reasoning, not only the P&L; one line, then the link:
https://arxiv.org/abs/2305.20050). P1, the half that needs reading, is `p1_judge.md`.

**Where it lives:** you write it.
- `src/tradingresearch/checks.py`:
  `p2_evidence_valid(thesis: Thesis, claims: tuple[Claim, ...], values: dict[str, float | None], tolerance: float = 0.005) -> bool`
  - `thesis`: a `records.Thesis`; only `evidence` is read.
  - `claims`: the analysis's claims (`Analysis.claims`).
  - `values`: the analysis's source table, source id → number (`None` for a label such as `regime_spy`). Same
    shape as `analyze.validate_claims` takes.
  - `tolerance`: relative, as `analyze.close_to`: `|a − b| ≤ tolerance · max(|a|, |b|)`.
- `src/tradingresearch/evals.py`: a `@grader` class with `id = "p2_evidence_valid"`, `kind = "code"`,
  `version = "1"`. It scores one thesis-run sample (`thesis.item_for`: `expected["analysis"]` is the Analysis
  JSON). Each item in `output_parsed["theses"]` that builds into a `Thesis` (`thesis.build`) is checked with
  `values` from `analyze.snapshot_rows(analysis.snapshot)` (the table the thesis prompt shows,
  `thesis.source_block`). Score 1 if every built thesis passes, 0 if any fails (binary, so experiments compare it
  with McNemar: https://en.wikipedia.org/wiki/McNemar%27s_test). Output that did not parse, or no item that builds,
  raises CannotGrade.

**Rule** (True only if all hold, for every id in `thesis.evidence`):
1. The id is the `claim_id` of a claim in `claims`.
2. That claim is tagged `fact` or `inference`. An `opinion` (a hypothesis such as "buyers should return at the
   level") is not evidence, even beside a fact. (`thesis.check_thesis` only refuses evidence that is *all*
   opinion; P2 is stricter.)
3. A fact cites at least one source id that is in `values`; a cited id missing from `values` fails.
4. A fact with a `value` matches at least one cited source holding a number, within `tolerance`. A fact without a
   `value` (a text-only fact) needs no number. A numeric fact whose cited sources hold only `None` fails.

Inferences are checked by rule 1 and 2 only: their numbers were checked against their parents at analyze time.

**Edge cases:**
- Direction and entry kind do not matter.
- A fact citing two sources passes if either holds a matching number.
- Exactly at the tolerance passes (`≤`).
- `tolerance` is a parameter: the same fact may pass at 0.005 and fail at 0.001.
- EDGAR facts: the thesis-stage table is the snapshot rows only, so in the grader an evidence fact that cites
  only an EDGAR source fails rule 3. Called directly, pass the full table to avoid this.

**Pass / fail means:** pass = a reader can follow every piece of evidence to a number code computed. Fail = the
thesis leans on an opinion, an id that does not exist, or a number that is not in the source table.

**Worked example:** `values = {"src_close": 100.0}`; claim `cl_f4` is a fact citing `src_close` with value 100.4.
|100.4 − 100.0| = 0.4 ≤ 0.005 × 100.4 = 0.502, so a thesis with `evidence = ("cl_f4",)` passes. A fact with value
100.6 gives 0.6 > 0.503 and fails. With `tolerance=0.001`, `cl_f4` fails too (0.4 > 0.1004).

**Acceptance:** `tests/test_week2.py` runs every case in `tests/fixtures/week2/p2_evidence_valid.json` (hand-built,
made-up ticker) and checks the registry entry.

**Out of scope:** whether the evidence supports the prediction (P1, a judge question); facts in `reason` or
`prediction` text that are not listed in `evidence`.
