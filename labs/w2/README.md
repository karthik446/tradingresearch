# Week 2 labs: the folder

This folder holds week 2 of the AI engineering track: labs w2l1 (P2), w2l2 (P3), w2l3 (P4) and w2l4 (the graders and the draft P1 judge), 13 exercises, run by `tr lab` on this repo from the tag `week-2-start`. A learner starts at [pages/index.md](pages/index.md); how `tr lab` works is in [labs/README.md](../README.md). This page is for whoever maintains the folder.

## Exercises

| Exercise | What the learner does | Edits | Wrong fixes |
|---|---|---|---|
| [w2l1.1](exercises/w2l1.1-unknown-evidence/) | Fail a thesis whose evidence names no claim of its analysis | `checks.py` | 10 |
| [w2l1.2](exercises/w2l1.2-opinion-is-not-evidence/) | Fail a thesis that leans on an opinion, even beside facts | `checks.py` | 9 |
| [w2l1.3](exercises/w2l1.3-source-in-the-table/) | Fail a fact that cites a source the thesis-stage table does not hold | `checks.py` | 7 |
| [w2l1.4](exercises/w2l1.4-number-matches-a-source/) | Fail a fact whose number matches none of its cited sources | `checks.py` | 15 |
| [w2l2.1](exercises/w2l2.1-long-invalidation/) | Pass a long only when its invalidation lies between stop and entry | `checks.py` | 8 |
| [w2l2.2](exercises/w2l2.2-short-and-market-open/) | Mirror the rule for a short and take the close as a market_open entry | `checks.py` | 8 |
| [w2l3.1](exercises/w2l3.1-long-stop/) | Place a long's stop beyond the nearest level under the entry | `checks.py` | 10 |
| [w2l3.2](exercises/w2l3.2-long-target/) | Keep a long's target at or before the next level over the entry, plus half an ATR | `checks.py` | 12 |
| [w2l3.3](exercises/w2l3.3-short-mirror/) | Mirror P4 for a short: stop over the nearest level above, target down to the next level below | `checks.py` | 9 |
| [w2l3.4](exercises/w2l3.4-cents/) | Amend P4 to compare prices at cents | `checks.py` | 11 |
| [w2l4.1](exercises/w2l4.1-p2-grader/) | Score a whole thesis run with P2: `every_thesis` and the `EvidenceValid` grader | `evals.py` | 10 |
| [w2l4.2](exercises/w2l4.2-p3-p4-graders/) | Register P3 and P4 as graders, each fed what its check reads from the snapshot | `evals.py` | 11 |
| [w2l4.3](exercises/w2l4.3-draft-judge/) | Register the draft P1 judge: a model grader that refuses to score | `evals.py` | 15 |

135 wrong fixes in all; the 23 whose header reads `before: GREEN (Codex review G..)` passed the check until the review's counterexamples were added as tests, and `w2l4.3 swallow-import-time-connection` passed until the guard's record stopped being cleared before each test. Two of them are known to be narrow: `w2l4.2 duplicate-kept-quietly` changes `grader()` itself, outside the exercise's TODO, to show why the registry refuses a duplicate id; `w2l4.2 p4-atr-close-swapped` is caught only by the case with a target of 366.0.

## Layout

```
labs/w2/
  lab.toml                 base = "week-2-start", lab titles and pages, [unlock], [suite] / [labs.<lab>.suite] deselects, [end]
  conftest.py              marks every test in this folder `lab` (plain `pytest -q` never collects them), installs the offline guard before any test module imports learner code, and fails a passing test whose code tried a guarded call, including one tried while the test module imported learner code
  PROOF.md                 output of labs/tools/prove.py w2: every exercise red, green, chained, every wrong fix red
  data/theses.json         10 real theses with their analyses' claims, levels and thesis-stage source tables, 7 synthetic copies
  pages/                   index.md, w2l1.md to w2l4.md (one page per lab), concepts.md
  tools/observe.py         observe: P2-P4 on every thesis in the data, the cents block and the graders block ($0, always exits 0)
  tools/offline.py         the offline guard: socket connections and DNS, subprocesses, os spawns, httpx sends and ModelJudge.grade raise Blocked and are counted
  exercises/w2lN.K-<slug>/
    exercise.toml          id, title, lab, concepts, touches, check, observe, fixtures, origin, red_expect
    stub/src/tradingresearch/checks.py   w2l1-w2l3: the week-2-end file with this exercise's rule and the later ones cut out
    stub/src/tradingresearch/evals.py    w2l4: the week-2-end file with this exercise's graders and the later ones cut out
    test_w2lN_K.py         the check; its assertion messages are the FAIL messages
    hints.md               two hints, each under a `## Hint N` heading: the idea and a counterexample, not the code
    solution.diff          the reference change, applied with `git apply` on the stub
    wrong/*.diff           known wrong fixes, each with why / expect / before headers (prove.py runs them)
```

The w2l4 stubs ship `evals.py` only: `checks.py` is complete after w2l3.4, and the learner's file carries over.

**The base.** `base = "week-2-start"` makes the first `tr lab start w2l1` set the repo's files to that tag and commit them, so week 2 does not depend on the learner's week-1 code. `week-2-start` has no `checks.py`; the w2l1.1 stub creates it.

**The data.** `data/theses.json` was copied read-only from the author's journal: the chapter's six theses, four later real ones (three shorts with limit, stop and limit entries; one market_open entry) and the claims, levels, ATR and source values of their analyses, computed by the `week-2-end` code. Seven synthetic rows copy a real thesis with one rule broken and carry `check` (the check that must reject them), `why` and `from` (the real row). The `week-2-end` checks give P2 6/6, P3 6/6 and P4 2/6 on the chapter rows, as the chapter's table does. The graders block does not read this file: it scores the author's recorded AAPL reply in `tests/fixtures/thesis`, which the repo ships.

## Observe

`python labs/w2/tools/observe.py` prints one row per thesis with a column per check written so far (1 pass, 0 fail, `-` not written yet, `!` raised), then these lines:

- **Per check, under the synthetic block:** `  P2: synthetic rows still accepted: N of 4` and `  P3: synthetic rows still accepted: N of 3`. A synthetic row counts as still accepted until its check returns False on it; a row that raises (`!`) is not a rejection, so it still counts. The total under them reads `synthetic rows the named check does not reject yet: N of 7`.
- **P4 at cents (from w2l3.1 on):** the header `P4 at cents: your P4 on the prices as stored, then on the same prices rounded to cents by observe (the ATR is not rounded)`, the columns `thesis  stored  cents  level that changes side at cents`, then `  chapter six passing: stored X/6, cents Y/6 (chapter: 2/6, at cents)` and `  rows where stored and cents differ: N of 10 (0 once your P4 compares at cents)`.
- **Graders (from w2l4.1 on):** the header `Graders on the author's recorded AAPL reply (tests/fixtures/thesis), scored as an eval run scores it, under the offline guard`, then one line per grader: `  <id>  (kind 'code', version '1')  reply: 1.0; reply + broken short: 0.0 (fails: short)`, or `  <id>  not registered yet`, or for P1 `(kind 'model', version '1', validated False)  reply: cannot grade (p1_judge is a draft: ...)`. A grader that tried a guarded call gets ` [tried <call>: blocked]` after its result; a guarded call tried while your code was imported, or while observe ran your checks, is named in a `note:` line at the end.

At `week-2-start`, before the w2l1.1 stub, observe prints a note that `tradingresearch.checks` did not import, and exits 0.

## The suite gate

`tests/test_week2.py` (51 tests) covers all of §2 and §3 and is red until the week's code is written. Passing: 2 at the base, 15 at the end of w2l1, 30 at the end of w2l2, 46 at the end of w2l3 and 50 at the end of w2l4. The end-of-lab run of `tr lab next` deselects:

| List | Deselects | Why |
|---|---|---|
| `[suite]` (every lab) | `test_the_p1_rubric_has_every_section` | it reads `evals/rubrics/p1_thesis_quality.md`, which the learner writes by hand in §3; no exercise writes prose |
| `[labs.w2l1.suite]` | `test_p3_invalidation_testable`, `test_p4_levels_coherent`, `test_the_code_check_is_a_registered_binary_code_grader`, `test_p1_judge_is_registered_as_an_unvalidated_model_grader` | P3 is lab w2l2, P4 lab w2l3, the registrations and the judge lab w2l4 |
| `[labs.w2l2.suite]` | `test_p4_levels_coherent` and the two registration tests | as above |
| `[labs.w2l3.suite]` | the two registration tests | lab w2l4 |
| `w2l4` | none of its own | after w2l4.3 only the rubric test is red |

**End state.** `[end] tag = "week-2-end"`, `files = ["src/tradingresearch/checks.py", "src/tradingresearch/evals.py"]`: after w2l4.3 both files equal the tag byte for byte. The tag's `tests/test_checks.py` (12 tests, including the cents cases) is not on this branch; on the end state it passes 12 of 12, and with it `tests/test_week2.py` fails only the rubric test.

## What the labs do not cover

§1 (setup and the daily loop), §3's rubric, judge prompt and ADR-003, §4 (reviewing thesis 1 and the CI gate), §5 (pre-registering the teacher bake-off), §6 (the runbook and the live stream) and §7 (what week 3 does with this). They are prose, review or setup, and stay in the chapter.

## Prove the folder

From the root of a clean clone (`uv sync` done):

```bash
uv run python labs/tools/prove.py w2 > labs/w2/PROOF.md
```

It copies the clone into temp folders and runs the chain (each stub red with `red_expect`, `solution.diff` green, earlier checks of the same lab still green, every `wrong/*.diff` red with its `expect:`), the end state, the hint guard, the captured output and a runner smoke (lab w2l1 end to end, then `tr lab start w2l3 --assume-previous`); [labs/w1/README.md](../w1/README.md#prove-the-folder) describes each row. It exits 1 if any row reads NOT PROVEN. Re-run it after changing an exercise, a stub, a test message, the data, observe or `lab.py`.

The hint guard is a string match: it rejects a hint that repeats a `solution.diff` added line of 12 or more characters, or holds a code fence longer than one line. It does not judge whether prose dictates the answer; that is a reading job (each hint states the idea and a counterexample, not the steps).

## Reading

The week's reading is the published chapter, [Week 2](https://scout.edgelab.one/learn/ai-engineering/week-2/). These labs are the code half of its §2 and the draft judge of its §3; the pages link its sections and observe cites `week-2.md §2`.
