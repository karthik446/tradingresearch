# Week 1 labs: the folder

This folder holds week 1 of the AI engineering track as 19 exercises in 4 labs, run by `tr lab` on this repo from `week-1-start`. A learner starts at [pages/index.md](pages/index.md); how `tr lab` works is in [labs/README.md](../README.md). This page is for whoever maintains the folder.

## Layout

```
labs/w1/
  lab.toml                 lab titles and pages, and the unlock numbers ([unlock] hints = [2, 5], solution = 10)
  conftest.py              marks every test in this folder `lab`, so plain `pytest -q` never collects them
  PROOF.md                 output of tools/prove.py: every exercise red, green, chained, every wrong fix red
  data/                    the author's recorded runs (observe, prompt-v2 baseline and variant), 20 analyses each
  pages/                   index.md, w1l1.md .. w1l4.md (one page per lab), concepts.md
  tools/regrade.py         observe: regrade a recorded run with the learner's code ($0)
  tools/prove.py           the proof (below)
  exercises/w1lN.K-<slug>/
    exercise.toml          id, title, lab, concepts, touches, check, observe, observe_ok_exit, fixtures, origin, red_expect
    stub/<repo path>       the repo files with this exercise's TODO cut out (w1l2.4 has none: it works on the learner's file)
    test_w1lN_K.py         the check; its assertion messages are the FAIL messages
    hints.md               two hints, each under a `## Hint N` heading
    solution.diff          the reference change, applied with `git apply` on the stub
    wrong/*.diff           known wrong fixes, each with why / expect / before headers (prove.py runs them)
    fixtures/, observe.py  where an exercise needs its own data or observe command
```

`check` and `observe` are repo-relative commands, run without a shell; a leading `python` is replaced by the interpreter `tr lab` and `prove.py` run under. `tr lab` notes an observe exit code other than 0 (it never decides the exercise); `observe_ok_exit` lists the codes that are no news, for an observe that exits 1 by design (none of week 1's observes needs it). The `check` passes `-m lab` (a later `-m` overrides the `addopts` in `pyproject.toml`). Tests and tools read `labs/w1/data/`; `TR_LAB_DATA` overrides it. `.gitignore` re-includes `labs/**/data/` (the repo ignores `data/` elsewhere) and ignores `.tr-lab/`, the runner's state.

## Prove the folder

From the root of a clean clone (code at `week-1-start`, `uv sync` done):

```bash
uv run python labs/w1/tools/prove.py > labs/w1/PROOF.md
```

It takes one to three minutes (65-182 s measured) and never touches the clone it runs from. It copies the clone's files (tracked and untracked, not ignored) into two temp folders, gives each copy a git repo of its own, and runs:

- **The chain**, exercise by exercise: the stub is red with the message in `red_expect`; `solution.diff` makes it green; every earlier check of the lab stays green; every `wrong/*.diff` is red with its `expect:` message; a stub never overwrites a learner's data file from an earlier exercise.
- **The end state**: after w1l4.5, the six files week 1 ends with equal the `week-1-end` tag byte for byte.
- **The hint guard**: every `hints.md` is prose. No fenced block of more than one line, and no line copied from the exercise's `solution.diff`; a self-test plants a leak and the guard must catch it.
- **A runner smoke**: `tr lab` itself through lab w1l1 (start, red verify, next refused, hint locked then unlocked, solution, verify, next, the repo-suite gate), then `start w1l3 --assume-previous`.

It exits 1 if any row reads NOT PROVEN. Re-run it after changing an exercise, a stub, a test message or `lab.py`. The runner's own unit tests are `tests/test_lab.py`, which run under plain `pytest -q`.

## Reading

The week's reading is the published chapter, [Week 1: error analysis and evals](https://scout.edgelab.one/learn/ai-engineering/week-1/). The pages and the concept index link its sections §1-§7; test messages and `exercise.toml` cite them as `week-1.md §N`.
