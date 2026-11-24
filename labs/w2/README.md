# Week 2 labs: the folder

This folder holds week 2 of the AI engineering track: labs w2l1 (P2) and w2l2 (P3), 6 exercises, run by `tr lab` on this repo from the tag `week-2-start`. A learner starts at [pages/index.md](pages/index.md); how `tr lab` works is in [labs/README.md](../README.md). This page is for whoever maintains the folder.

## Layout

```
labs/w2/
  lab.toml                 base = "week-2-start", lab titles and pages, [unlock], [suite] / [labs.<lab>.suite] deselects, [end]
  conftest.py              marks every test in this folder `lab`, so plain `pytest -q` never collects them
  PROOF.md                 output of labs/tools/prove.py w2: every exercise red, green, chained, every wrong fix red
  data/theses.json         10 real theses with their analyses' claims and thesis-stage source tables, 7 synthetic copies
  pages/                   index.md, w2l1.md, w2l2.md (one page per lab), concepts.md
  tools/observe.py         observe: P2 and P3 on every thesis in the data, one column per check ($0, always exits 0)
  exercises/w2lN.K-<slug>/
    exercise.toml          id, title, lab, concepts, touches, check, observe, fixtures, origin, red_expect
    stub/src/tradingresearch/checks.py   the week-2-end file without P4 and with this exercise's rule cut out
    test_w2lN_K.py         the check; its assertion messages are the FAIL messages
    hints.md               two hints, each under a `## Hint N` heading
    solution.diff          the reference change, applied with `git apply` on the stub
    wrong/*.diff           known wrong fixes, each with why / expect / before headers (prove.py runs them)
```

**The base.** `base = "week-2-start"` makes the first `tr lab start w2l1` set the repo's files to that tag and commit them, so week 2 does not depend on the learner's week-1 code. `week-2-start` has no `checks.py`; the w2l1.1 stub creates it.

**The suite gate.** `tests/test_week2.py` (51 tests) covers all of §2 and §3 and is red until the week's code is written. Passing: 2 at the base, 15 at the end of w2l1, 30 at the end of w2l2. `[suite] deselect` drops the P1 rubric and judge tests from every end-of-lab suite run; `[labs.w2l1.suite]` also drops P3, P4 and the grader registrations, `[labs.w2l2.suite]` P4 and the registrations. Part B (P4, registrations) removes its entries from these lists.

**The data.** `data/theses.json` was copied read-only from the author's journal: the chapter's six theses, four later real ones (three shorts with limit, stop and limit entries; one market_open entry) and the claims and source values of their analyses, computed by the `week-2-end` code. Seven synthetic rows copy a real thesis with one rule broken and carry `check` (the check that must reject them), `why` and `from` (the real row). The `week-2-end` checks give P2 6/6 and P3 6/6 on the chapter rows, as the chapter's table does.

**End state.** `[end] files = []`: after w2l2.2 `checks.py` is `week-2-end` minus P4 and `TARGET_ALLOWANCE_ATR`, so it is not yet byte-identical to the tag. Part B lists `src/tradingresearch/checks.py` once P4 is in.

## Prove the folder

From the root of a clean clone (`uv sync` done):

```bash
uv run python labs/tools/prove.py w2 > labs/w2/PROOF.md
```

It copies the clone into temp folders and runs the chain (each stub red with `red_expect`, `solution.diff` green, earlier checks still green, every `wrong/*.diff` red with its `expect:`), the end state, the hint guard and a runner smoke through lab w2l1; [labs/w1/README.md](../w1/README.md#prove-the-folder) describes each row. It exits 1 if any row reads NOT PROVEN. Re-run it after changing an exercise, a stub, a test message, the data or `lab.py`.

## Reading

The week's reading is the published chapter, [Week 2](https://scout.edgelab.one/learn/ai-engineering/week-2/). These labs are the code half of its §2; the pages link its sections and observe cites `week-2.md §2`.
