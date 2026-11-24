# Week 1 labs: the folder

Labs spike v3, not published. This folder holds week 1 of the AI engineering track as 19 exercises in 4 labs, run by `tr lab` on this repo from `week-1-start`. A learner starts at [pages/index.md](pages/index.md); how `tr lab` works is in [labs/README.md](../README.md). This page is for whoever maintains the folder.

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

`check` and `observe` are repo-relative commands, run without a shell; a leading `python` is replaced by the interpreter `tr lab` and `prove.py` run under. `tr lab` notes an observe exit code other than 0 (it never decides the exercise); `observe_ok_exit` lists the codes that are no news, e.g. `[0, 1]` for w1l4.1's `git diff --no-index`, which exits 1 whenever the files differ. The `check` passes `-m lab` (a later `-m` overrides the `addopts` in `pyproject.toml`). Tests and tools read `labs/w1/data/`; `TR_LAB_DATA` overrides it. `.gitignore` re-includes `labs/**/data/` (the repo ignores `data/` elsewhere) and ignores `.tr-lab/`, the runner's state.

## Old and new ids

The spike's prototype (v2) numbered labs 1a-1d and exercises `1a-01`..`1d-05`. v3 renamed them; the order and the content are the same, and the slugs did not change.

| Old (prototype v2) | New | Lab |
|---|---|---|
| 1a-01-unknown-source | w1l1.1-unknown-source | w1l1 claim checks |
| 1a-02-number-in-text | w1l1.2-number-in-text | |
| 1a-03-placeholders | w1l1.3-placeholders | |
| 1a-04-cascade | w1l1.4-cascade | |
| 1b-01-open-coding | w1l2.1-open-coding | w1l2 open and axial coding |
| 1b-02-class-counts | w1l2.2-class-counts | |
| 1b-03-taxonomy-table | w1l2.3-taxonomy-table | |
| 1b-04-back-fill-classes | w1l2.4-back-fill-classes | |
| 1c-01-item-names | w1l3.1-item-names | w1l3 a code grader |
| 1c-02-direct-parents | w1l3.2-direct-parents | |
| 1c-03-recurse | w1l3.3-recurse | |
| 1c-04-whole-token | w1l3.4-whole-token | |
| 1c-05-dist-alias | w1l3.5-dist-alias | |
| 1c-06-register | w1l3.6-register | |
| 1d-01-prompt-variant | w1l4.1-prompt-variant | w1l4 a paired experiment |
| 1d-02-experiment-config | w1l4.2-experiment-config | |
| 1d-03-paired-test | w1l4.3-paired-test | |
| 1d-04-cluster-bootstrap | w1l4.4-cluster-bootstrap | |
| 1d-05-decide | w1l4.5-decide | |

Pages: `lab-1a.md`..`lab-1d.md` became `pages/w1l1.md`..`pages/w1l4.md`, `concepts-sample.md` became `pages/concepts.md`. Stub tags became `TODO(w1l1.1)` and so on; test file names (`test_w1l1_1.py`), messages, hints and diffs follow.

## Prove the folder

From the root of a clean clone (code at `week-1-start`, `uv sync` done):

```bash
uv run python labs/w1/tools/prove.py > labs/w1/PROOF.md
```

It takes one to three minutes (65-182 s measured) and never touches the clone it runs from. It copies the clone's files (tracked and untracked, not ignored) into two temp folders, gives each copy a git repo of its own, and runs:

- **The chain**, exercise by exercise: the stub is red with the message in `red_expect`; `solution.diff` makes it green; every earlier check of the lab stays green; every `wrong/*.diff` is red with its `expect:` message; a stub never overwrites a learner's data file from an earlier exercise.
- **The end state**: after w1l4.5, the six files week 1 ends with equal the `week-1-end` tag byte for byte.
- **A runner smoke**: `tr lab` itself through lab w1l1 (start, red verify, next refused, hint locked then unlocked, solution, verify, next, the repo-suite gate), then `start w1l3 --assume-previous`.

It exits 1 if any row reads NOT PROVEN. Re-run it after changing an exercise, a stub, a test message or `lab.py`. The runner's own unit tests are `tests/test_lab.py`, which run under plain `pytest -q`.

## Outside this repo

The pages name these by plain text, because they live in the gigai orchestrator workspace, not in this repo (paths relative to its `research/learning-curriculum/`):

| Named on the pages as | Path | What it is |
|---|---|---|
| the build guide `week-1.md` | `build-guide/week-1.md` | week 1 as the author built it; the pages cite its sections (§1-§7) |
| the v1 slim reading `week-1-reading-slim.md` | `labs-spike/prototype/week-1-reading-slim.md` | the reading the concept index points to |
| labs spike report `READ-V2.md` | `labs-spike/workers/READ-V2.md` | the independent read of prototype v2 (finding 4: the suite is red during w1l1) |
| labs spike `AUDIT.md` | `labs-spike/AUDIT.md` | the audit behind the concept index (finding 2: concepts defined twice) |
| labs spike `RUNNER.md` | `labs-spike/RUNNER.md` | the runner design; its learner-facing parts now live in [labs/README.md](../README.md) |
| the spike's decision log | `labs-spike/SPIKE.md` | why the labs look like this (v1, v2, v3) |
