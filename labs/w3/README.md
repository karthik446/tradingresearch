# Week 3 labs: the folder

This folder holds part A of week 3 of the AI engineering track: labs w3l1 (reading the P1 judge's verdict) and w3l2 (the judge prompt and the one call), 6 exercises, run by `tr lab` on this repo from the tag `week-3-start`. A learner starts at [pages/index.md](pages/index.md); how `tr lab` works is in [labs/README.md](../README.md). This page is for whoever maintains the folder.

## Exercises

| Exercise | What the learner does | Edits | Wrong fixes |
|---|---|---|---|
| [w3l1.1](exercises/w3l1.1-the-last-json-object/) | Read the verdict and the explanation from the last JSON object in the judge's reply | `evals.py` | 9 |
| [w3l1.2](exercises/w3l1.2-unknown-is-an-abstain/) | Store an `unknown` verdict as an abstain: `fail`, with `unknown: ` before the explanation | `evals.py` | 8 |
| [w3l1.3](exercises/w3l1.3-no-verdict-cannot-be-graded/) | Raise `CannotGrade` on a reply with no pass, fail or unknown verdict, never a quiet fail | `evals.py` | 12 |
| [w3l2.1](exercises/w3l2.1-rubric-in-thesis-out/) | Fill the judge's frame: the rubric into the prompt, the thesis text as the graded output | `evals.py` | 8 |
| [w3l2.2](exercises/w3l2.2-evidence-not-bars/) | Show the judge the cited claims and the code-written summary, never the raw bars | `evals.py` | 8 |
| [w3l2.3](exercises/w3l2.3-one-bounded-call/) | Make the one call bounded in tokens and capped in dollars | `evals.py` | 11 |

56 wrong fixes in all. 14 of them passed the checks when an independent break pass first tried them (`before: GREEN
(independent break pass)`): an explanation or verdict that is JSON but not text, a capital or space-less `unknown:`
prefix, a pass whose text says unknown, a padded or hedged verdict, a hard-coded thesis or INPUT, every claim instead
of the cited ones, and a cap with a margin, rounded to cents or with a cent of slack. The checks were hardened for each
(new rows in `data/replies.json`, a reworded FAKEA thesis in `tools/fakea.py`, the cap tested a twentieth of a cent
either side of one call's worst case), and all 14 are red now. The other 42 are `before: RED (author)`; three of them
(`own-client`, `live-price-lookup`, `live-price-or-given`) are red because of the offline guard below.

## Layout

```
labs/w3/
  lab.toml                 base = "week-3-start", lab titles and pages, [unlock], [suite] deselect, [end]
  conftest.py              marks every test in this folder `lab` (plain `pytest -q` never collects them), installs the offline guard before any test module imports learner code, and fails a passing test whose code tried a guarded call
  PROOF.md                 output of labs/tools/prove.py w3: every exercise red, green, chained, every wrong fix red
  data/replies.json        26 judge replies with the rubric's reading of each (`expect`) and where each comes from (`source`)
  data/judge_reply.json    the one recorded judge reply (openai/gpt-6-sol on the FAKEA trade)
  data/judge_request.json  the request that produced that reply: the body the w3l2 checks compare against
  data/models.json         the judge model's recorded /models row, for its price
  pages/                   index.md, w3l1.md, w3l2.md (one page per lab), concepts.md
  session/                 session.toml and the captured output of each step: the walked-through start of the week on the w3l1 page
  tools/offline.py         the offline guard: socket connections and DNS, subprocesses, os spawns and the real httpx transports raise Blocked and are counted
  tools/fakea.py           the judge on one closed trade, replayed through the real OpenRouter adapter ($0, no network)
  tools/observe.py         observe: `verdicts` (w3l1) and `judge` (w3l2), always exits 0; installs the offline guard first
  exercises/w3lN.K-<slug>/
    exercise.toml          id, title, effect, goal, what_tested, writes, show_tests, lab, concepts, touches, check, observe, paid, fixtures, origin, red_expect
    stub/src/tradingresearch/evals.py   the week-3-end file with this exercise's code and the later ones cut out
    test_w3lN_K.py         the check; its assertion messages are the FAIL messages
    hints.md               two hints, each under a `## Hint N` heading: the idea and a counterexample, no code
    expected_output/       fail.txt (the stub's red run) and pass.txt (the solution's green run), captured for the site
    solution.diff          the reference change, applied with `git apply` on the stub
    wrong/*.diff           known wrong fixes, each with why / expect / before headers (prove.py runs them)
```

**The base.** `base = "week-3-start"` makes the first `tr lab start w3l1` set the repo's files to that tag and commit them, so week 3 does not depend on the learner's week-2 code. `week-3-start` has the draft P1 judge of week 2 and no `p1_verdict`; the w3l1.1 stub brings in the week's `evals.py` with `p1_verdict` cut out.

**The data.** Only one judge reply in the data is model output: `recorded`, the reply in `data/judge_reply.json`, which is a copy of the repo's `tests/fixtures/week3/judge_reply.json` (run `run_54953ec7ce484649`, captured 2026-11-17). The author's journal holds no other P1 verdicts. The other 25 rows of `data/replies.json` are reply shapes: some come from `tests/test_week3.py`, some copy the shape of the judge library's own tests, and some were built for these labs (7 of those for the break pass above); `source` on each row says which. Each row carries `exercise`, the exercise whose rule decides it. `data/judge_request.json` is the request body that produced the recorded reply, so the w3l2 checks can compare a learner's request with it byte for byte. `data/models.json` is the recorded `/models` row for `openai/gpt-6-sol`; `fakea.py` reads the judge's price from it. `TR_LAB_DATA` points the checks and observe at another data folder.

**The trade.** The w3l2 checks and `observe.py judge` judge the synthetic FAKEA trade of `tests/test_week3.py` (filled on 2026-11-17, closed at its target the next session), the same trade the chapter's acceptance tests judge. `tools/fakea.py` builds it in a temporary data directory and swaps the OpenRouter adapter's HTTP transport for an `httpx.MockTransport` that answers every request with the recorded reply. With `reworded=True` it gives the trade a second thesis (other prediction, reason and invalidation text, citing only `cl_fakea_high`), so the checks can tell a request built from the thesis from one pasted from the recording.

**The offline guard.** The labs claim $0 and no network, so `tools/offline.py` enforces it: `conftest.py` installs it before any test module imports learner code, and `observe.py` before it imports `fakea`. Socket connections, DNS lookups, subprocesses, os spawns and the real httpx transports (sync and async) raise `Blocked` and are recorded; the `httpx.MockTransport` the checks use is not touched. A test whose code tried a guarded call fails even when the code swallowed the error, with `The code under test tried ... and caught the error`. Observe prints a `note: your code tried ...: blocked` line instead.

## Observe

`python labs/w3/tools/observe.py verdicts` (lab w3l1) runs the learner's `p1_verdict` on every reply in `data/replies.json` and prints the header `  reply  ex  ok  yours -> the rubric's reading`, one row per reply (`1` when the learner's reading equals `expect`, `0` with a second line `the rubric: ...` when not), then `matches: w3l1.1 N/9, w3l1.2 N/7, w3l1.3 N/10` and a note that `recorded` is the one model reply. On the w3l1.1 stub it reads 1/9, 0/7, 0/10; after w3l1.1 9/9, 2/7, 0/10; after each later exercise its own count reaches the total.

`python labs/w3/tools/observe.py judge` (lab w3l2) runs `p1_judge` on the FAKEA trade once with the cap of `tests/test_week3.py` ($0.05) and prints:

- `p1_judge ended with: ...` (the `NotImplementedError` that names the run, after w3l2.3; a new run's id is random and shows as `run_<id>`, so captured output stays the same)
- `requests sent: N (recorded: 1)`, `model: ...`, `max_tokens: N (recorded: 4000)`, `prompt chars: N (recorded: 5925)`
- `rubric sections: N/7; {rubric} placeholder left: True|False`
- `INPUT: N lines (recorded: 12), same: ...` and `OUTPUT: N lines (recorded: 3), same: ...`
- `raw bar values in the prompt: N/5` (opens, highs and a post-exit close of the trade; 0/5 is right)
- `same body as the recording: True|False`, and when False the first prompt line that differs, the learner's beside the recorded one, or, when the prompt is the recorded one, the body keys that differ (`max_tokens` after w3l2.2)

Then it runs the judge again under a $0.001 cap (`under max_usd=0.001: 0 request(s) sent, ended with BudgetExceeded ...` after w3l2.3) and prints `p1_verdict` on the recorded reply. What moves: the prompt length, the INPUT and OUTPUT blocks, the raw bar count, `max_tokens` and the capped run. What cannot move: the reply is the recording and says pass whatever is sent, so it is evidence for the learner's prompt only when the body equals the recorded one.

At `week-3-start`, before the w3l1.1 stub, `evals.py` has no `p1_verdict`, so every `verdicts` row shows the `AttributeError`; observe still exits 0.

## The suite gate

`tests/test_week3.py` (19 tests) covers the chapter's §2 to §7 and is red until the week ends. Passing: 0 at the base and on the w3l1.1 stub, 3, 4 and 6 after w3l1.1, .2 and .3 (the parser cases), and still 6 after each w3l2 exercise. The end-of-lab run of `tr lab next` deselects, in `[suite]` (every lab):

| Deselected | Why |
|---|---|
| `test_the_judge_sends_one_request_with_the_adr_003_model_the_rubric_and_the_summary`, `test_the_judge_prompt_holds_no_raw_bar_rows`, `test_the_judge_returns_a_score_and_stores_its_verdict_and_score`, `test_the_judge_call_and_its_cost_land_in_a_run_file` | they call `p1_judge` to the end and check its Score, its stored verdict and its run file; after w3l2.3 `p1_judge` raises `NotImplementedError` after its call (part B) |
| `test_teacher_and_never_entered_theses_are_never_judged` (2 cases) | the refusal of a teacher or never-entered thesis is part B |
| `test_tr_grade_judge_is_off_by_default_then_judges_once_and_prints_the_cost` | `tr grade --judge` is part B |
| `test_adr_004_names_what_never_enters_a_trace`, `test_the_slo_review_has_four_slos_and_the_injected_breach`, `test_measured_costs_has_a_row_per_step_with_its_run_id` (4 cases) | they read documents the learner writes by hand from the chapter (§2, §5, §6); no exercise writes prose |

The 13 cases still red after w3l2 are exactly these. The first two judge tests check the request, which the w3l2 checks already pin byte for byte; they stay deselected because they run `p1_judge` to its end.

**End state.** `[end] tag = "week-3-end"`, `files = []` for part A. `evals.py` is the one file these labs write, and it cannot equal the tag until part B finishes `p1_judge`; part B lists `src/tradingresearch/evals.py` there, and then the whole file must equal `week-3-end` byte for byte. After w3l2.3, `evals.py` equals `week-3-end` except `p1_judge`, which builds the recorded request, sends it once under `CallBudget(max_usd=max_usd, prices=prices)` and raises `NotImplementedError` naming the run; it has no refusal, no run file, no stored verdict and no Score yet.

## What part B adds

Labs w3l3 and w3l4 start from the w3l2.3 end state above and finish `p1_judge`: keep the call in a run file at its reported cost, read the reply with the learner's `p1_verdict`, store the verdict and the score with their ScoreRecord and return the Score; refuse teacher and never-entered theses before any call (`label.Refused` becomes `CannotGrade`); add `tr grade --judge`. That turns the 7 part-B cases above green and makes `evals.py` equal the tag.

## What the labs do not cover

§1 (setup and the tour of the shipped code), §2 (traces, redaction and retries; ADR-004 is written by hand), §3 (`tr grade`, the outcome, the shadow and P2-P4, already shipped), §5 (the SLOs and the SLO review), §6 (measured costs) and §7 (blind labels and Cohen's κ, which need trades to close). They are writing, review or setup, and stay in the chapter.

## Prove the folder

From the root of a clean clone (`uv sync` done):

```bash
uv run python labs/tools/prove.py w3 > labs/w3/PROOF.md
```

It copies the clone into temp folders and runs the chain (each stub red with `red_expect`, `solution.diff` green, earlier checks of the same lab still green, every `wrong/*.diff` red with its `expect:`), the end state (empty for part A), the hint guard, the captured output and a runner smoke; [labs/w1/README.md](../w1/README.md#prove-the-folder) describes each row. It exits 1 if any row reads NOT PROVEN. Re-run it after changing an exercise, a stub, a test message, the data, observe or `lab.py`.

The hint guard is a string match: it rejects a hint that repeats a `solution.diff` added line of 12 or more characters, or holds a code fence longer than one line. It does not judge whether prose dictates the answer; that is a reading job. The week-3 hints state the idea and a counterexample, with no code and no function to call.

**Captures for the site.** The same as week 1's (see [labs/w1/README.md](../w1/README.md)): each exercise's `expected_output/fail.txt` and `pass.txt`, the walked-through session in `session/` (the start of the week: the base commit from `week-3-start`, then w3l1.1 end to end), and the page text in each `exercise.toml`: `goal`, `what_tested`, `writes`, `show_tests` (no `show_data`), with `goal` and `section` per lab in `lab.toml`. `python labs/tools/capture.py w3 --write` regenerates the captured files, `--leakcheck` checks that no page text gives away a solution line or a locked hint, and `prove.py w3` re-captures and fails on any difference.

## Reading

The week's reading is the published chapter, [Week 3](https://scout.edgelab.one/learn/ai-engineering/week-3/). These labs are the first half of the code of its [§4 The P1 judge and `tr grade --judge`](https://scout.edgelab.one/learn/ai-engineering/week-3/#4-the-p1-judge-and-tr-grade---judge-2-h-0); the pages link its sections.
