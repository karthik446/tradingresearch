# Week 3 labs: the folder

This folder holds week 3 of the AI engineering track, 12 exercises run by `tr lab` on this repo from the tag `week-3-start`. Part A is labs w3l1 (reading the P1 judge's verdict) and w3l2 (the judge prompt and the one call); part B is labs w3l3 (keeping what the judge said) and w3l4 (judging in `tr grade`). A learner starts at [pages/index.md](pages/index.md); how `tr lab` works is in [labs/README.md](../README.md). This page is for whoever maintains the folder.

## Exercises

| Exercise | What the learner does | Edits | Wrong fixes |
|---|---|---|---|
| [w3l1.1](exercises/w3l1.1-the-last-json-object/) | Read the verdict and the explanation from the last JSON object in the judge's reply | `evals.py` | 14 |
| [w3l1.2](exercises/w3l1.2-unknown-is-an-abstain/) | Store an `unknown` verdict as an abstain: `fail`, with `unknown: ` before the explanation | `evals.py` | 16 |
| [w3l1.3](exercises/w3l1.3-no-verdict-cannot-be-graded/) | Raise `CannotGrade` on a reply with no pass, fail or unknown verdict, never a quiet fail | `evals.py` | 19 |
| [w3l2.1](exercises/w3l2.1-rubric-in-thesis-out/) | Fill the judge's frame: the rubric into the prompt, the thesis text as the graded output | `evals.py` | 13 |
| [w3l2.2](exercises/w3l2.2-evidence-not-bars/) | Show the judge the cited claims and the code-written summary, never the raw bars | `evals.py` | 13 |
| [w3l2.3](exercises/w3l2.3-one-bounded-call/) | Make the one call bounded in tokens and capped in dollars | `evals.py` | 16 |
| [w3l3.1](exercises/w3l3.1-keep-the-run-file/) | Keep the judge's call in a run file, and turn a failed call into `CannotGrade` naming its run file and error | `evals.py` | 18 |
| [w3l3.2](exercises/w3l3.2-verdict-and-score-together/) | Read the reply with `p1_verdict`, store the verdict and its ScoreRecord in one transaction, return the Score | `evals.py` | 24 |
| [w3l3.3](exercises/w3l3.3-refuse-before-the-call/) | Refuse a teacher or never-entered thesis before any call: `label.Refused` becomes `CannotGrade` | `evals.py` | 16 |
| [w3l4.1](exercises/w3l4.1-what-waits-for-the-judge/) | List the graded champion and challenger theses with no verdict yet, oldest first | `grade.py` | 16 |
| [w3l4.2](exercises/w3l4.2-one-cap-per-run/) | Judge every waiting thesis under one dollar cap for the run, counting what each call's run files say it spent | `grade.py` | 20 |
| [w3l4.3](exercises/w3l4.3-judge-only-when-asked/) | Run the judge only with `--judge`, and print each call's cost and the run's total to the millionth | `grade.py`, `commands/grade.py` | 23 |

208 wrong fixes in all: 91 in part A, 117 in part B. The counts are `ls exercises/*/wrong | wc -l`; `prove.py w3` runs
every one.

Part A: 91 wrong fixes. 26 of them passed the checks when first tried. 14 came from an independent break pass
(`before: GREEN (independent break pass)`): an explanation or verdict that is JSON but not text, a capital or
space-less `unknown:` prefix, a pass whose text says unknown, a padded or hedged verdict, a hard-coded thesis or INPUT,
every claim instead of the cited ones, and a cap with a margin, rounded to cents or with a cent of slack. 12 came from
an independent reader (`before: GREEN (independent reader)`): a lookup in `data/replies.json` (one per w3l1 exercise),
a nested `{"verdict"` object, a stripped bare `unknown:`, the word unknown taken as an abstain wherever it appears, a
rubric copied from the recorded request, bar lows added to the instructions, a pasted summary, and $0.0004 of slack on
the cap. The checks were hardened for each (new rows in `data/replies.json`, a reworded FAKEA thesis in
`tools/fakea.py`, the cap tested a twentieth of a cent and a thousandth of a cent either side of the budget's estimate
of one call's worst case), and all 26 are red now. 22 more came from an outside review. 10 of them passed the checks
(`before: GREEN (outside review)`): a trimmed explanation or unknown reason, a JSON `true` read as pass, a `CannotGrade`
returned instead of raised, the verdict taken from a `value` key, the rubric read from the working directory, the
reason cut to 1000 characters, only the first two cited claims, and a cap held under $0.05 or rounded to five
decimals. 12 are its break pass (`outside-review break pass`, 6 green when first tried). The checks were hardened for
each (padded explanations and JSON `true`, `false` and `{"value"` verdicts in the w3l1 checks, a line added to the
prompt file of the rubric copy, a reason of over 1300 characters, a third cited claim, doubled prices, the cap also
tested at the estimate itself and a millionth of a dollar under it), and all 22 are red now. 1 more came from a second
independent read (`before: GREEN (independent read)`): a verdict of `abstain` taken as a fourth readable verdict. The
w3l1.3 check now also refuses the verdicts `abstain`, `inconclusive` and `neutral`, and it is red now. The other 42
are `before: RED (author)`; three of them
(`own-client`, `live-price-lookup`, `live-price-or-given`) are red because of the offline guard below.

Part B: 117 wrong fixes. 33 come from break passes and a finish review (12 of them written while the outside review
below was fixed, `before: RED (independent break pass)`); 6 of those passed the checks when
first tried: a ScoreRecord under its own grader version, or with the rubric's digest as the prompt's sha256
(`bp-wrong-version`, `bp-rubric-digest`); the queue ordered by thesis id (`bp-id-order`); a run that counts a call's
cost only when it got a verdict (`bp-spent-only-on-verdict`); the judge part shown on a plain `--dry-run`
(`bp-judge-on-dry-run`); and every line priced at the recorded reply's cost (`constant-cost`). The checks were
hardened for each (the ScoreRecord's version compared with P1Judge's and its prompt digest with `fakea.judge_prompt_sha256`, a journal
whose newer thesis has the smaller random id, a $0.048 cap after a paid reply with no verdict, `tr grade --dry-run`
checked for no judge line, made-up costs given to `render_judged`). 16 more came from an independent reader
(`rd-*`, `before: GREEN (independent reader)`): a `CannotGrade` returned instead of raised (three exercises), a
hard-coded `http_400`, the verdict word as the ScoreRecord's explanation, a plain fail scored 1.0, a storage error
turned into a refusal, a refusal cut short or replaced by a fixed one, the queue in grading order or cut to two, the
run's spend set to the last call's, a bars error that stops the run, a capped thesis charged the newest run file,
costs to seven decimals, and the judge run before grading. The checks were hardened for each (`Judging.raised`, an HTTP
402 and a plain `fail` reply in `tools/fakea.py`, the refusal compared with `label.Refused`'s own text, a journal read
that fails, theses graded in reverse order, a $0.05 cap, bars that fail once, costs read whole, the order `tr grade`
grades and judges in). All 22 are red now. 20 more came from an outside review; 18 of them passed the checks when first
tried (`before: GREEN (outside review)`, and one `outside-review break pass`): an out-of-credits error stored as a
fail, a run file cut to its header, the verdict read before the run file is kept, or a reply that holds no verdict
deleting it; a prompt digest cut to 12 characters, the reply emptied in the ScoreRecord's note; a file error turned
into a refusal, every thesis refused; a FAKEA-only queue, a plain fail judged again, teachers left in the queue; every
call priced at the recording, only the dearest run file counted, a dry run that judges; and in `tr grade`, prices
read on a dry run, `--judge-max-usd` ignored, the key required for a dry run, every verdict printed as a pass. The
checks were hardened for each (an HTTP 402 and a reply with no verdict kept in their run files, the digest compared
whole, a challenger thesis and an injected file error, a second ticker and a plain `fail` verdict, made-up reply costs
and a call that adds two run files, a count of `/models` lookups in `fakea.offline`, a $0.001 cap on the command line,
`judge_lines` with no key, a fail given to `render_judged`). All 20 are red now. 3 more came from a second independent
read (`before: GREEN (independent read)`): an unknown's ScoreRecord without its `unknown: ` prefix, the judge run when
only `--judge-max-usd` is given, and a not-judged line that hides a $0 cost. The checks were hardened for each (the
unknown's ScoreRecord compared with its verdict row's reason, `tr grade --judge-max-usd 0.5` checked for no judge
line, a $0.000000 outcome given to `render_judged`), and all 3 are red now. The other 45 are `before: RED (author)`.

## Layout

```
labs/w3/
  lab.toml                 base = "week-3-start", lab titles and pages, [unlock], [suite] deselect, per-lab [labs.<id>.suite] deselect, [end]
  conftest.py              marks every test in this folder `lab` (plain `pytest -q` never collects them), installs the offline guard before any test module imports learner code, and fails a passing test whose code tried a guarded call
  PROOF.md                 output of labs/tools/prove.py w3: every exercise red, green, chained, every wrong fix red
  data/replies.json        26 judge replies with the rubric's reading of each (`expect`) and where each comes from (`source`)
  data/judge_reply.json    the one recorded judge reply (openai/gpt-6-sol on the FAKEA trade)
  data/judge_request.json  the request that produced that reply: the body the w3l2 checks compare against
  data/models.json         the judge model's recorded /models row, for its price
  pages/                   index.md, w3l1.md to w3l4.md (one page per lab), concepts.md
  session/                 session.toml and the captured output of each step: the walked-through start of the week on the w3l1 page
  tools/offline.py         the offline guard: socket connections and DNS, subprocesses, os spawns and the real httpx transports raise Blocked and are counted
  tools/fakea.py           the judge on closed FAKEA trades, replayed through the real OpenRouter adapter, and `tr` run on their journal ($0, no network)
  tools/observe.py         observe: `verdicts` (w3l1), `judge` (w3l2), `store` (w3l3) and `grade` (w3l4), always exits 0; installs the offline guard first
  exercises/w3lN.K-<slug>/
    exercise.toml          id, title, effect, goal, what_tested, writes, show_tests, lab, concepts, touches, check, observe, paid, fixtures, origin, red_expect
    stub/                  the week-3-end files the exercise touches (`src/tradingresearch/evals.py`; in w3l4 `grade.py`, `commands/grade.py` and `tests/fixtures/help/grade.txt`) with this exercise's code and the later ones cut out
    test_w3lN_K.py         the check; its assertion messages are the FAIL messages
    hints.md               two hints, each under a `## Hint N` heading: the idea and a counterexample, no code
    expected_output/       fail.txt (the stub's red run) and pass.txt (the solution's green run), captured for the site
    solution.diff          the reference change, applied with `git apply` on the stub
    wrong/*.diff           known wrong fixes, each with why / expect / before headers (prove.py runs them)
```

**The base.** `base = "week-3-start"` makes the first `tr lab start w3l1` set the repo's files to that tag and commit them, so week 3 does not depend on the learner's week-2 code. `week-3-start` has the draft P1 judge of week 2 and no `p1_verdict`; the w3l1.1 stub brings in the week's `evals.py` with `p1_verdict` cut out.

**The data.** Only one judge reply in the data is model output: `recorded`, the reply in `data/judge_reply.json`, which is a copy of the repo's `tests/fixtures/week3/judge_reply.json` (run `run_54953ec7ce484649`, captured 2026-11-17). The author's journal holds no other P1 verdicts. The other 25 rows of `data/replies.json` are reply shapes: some come from `tests/test_week3.py`, some copy the shape of the judge library's own tests, and some were built for these labs (7 of those for the break pass above); `source` on each row says which. Each row carries `exercise`, the exercise whose rule decides it. `data/judge_request.json` is the request body that produced the recorded reply, so the w3l2 checks can compare a learner's request with it byte for byte. `data/models.json` is the recorded `/models` row for `openai/gpt-6-sol`; `fakea.py` reads the judge's price from it. `TR_LAB_DATA` points the checks and observe at another data folder.

**The trade.** The w3l2 checks and `observe.py judge` judge the synthetic FAKEA trade of `tests/test_week3.py` (filled on 2026-11-17, closed at its target the next session), the same trade the chapter's acceptance tests judge. `tools/fakea.py` builds it in a temporary data directory and swaps the OpenRouter adapter's HTTP transport for an `httpx.MockTransport` that answers every request with the recorded reply. With `reworded=True` it gives the trade a second thesis (other prediction, reason and invalidation text, citing only `cl_fakea_high`), so the checks can tell a request built from the thesis from one pasted from the recording.

**Part B's journals.** For labs w3l3 and w3l4, `fakea.replaying` answers request i with `answer(replies[i])`: `recorded`, the recording ending in `unknown`, with no verdict line, or an HTTP 400 (no reply). The edits keep the recorded usage, so every paid reply costs the same $0.0051635 (shown as $0.005163) and an HTTP 400 costs $0. `fakea.offline` also answers Alpaca's daily FAKEA bars and the `/models` row, `closed_trade` and `journal_of` build fresh journals of closed FAKEA theses (one per arm asked for, graded on `SESSION` = 2026-11-19 unless told otherwise), and `cli` runs `tr` on such a journal with fake keys.

**The offline guard.** The labs claim $0 and no network, so `tools/offline.py` enforces it: `conftest.py` installs it before any test module imports learner code, and `observe.py` before it imports `fakea`. Socket connections, DNS lookups, subprocesses, os spawns and the real httpx transports (sync and async) raise `Blocked` and are recorded; the `httpx.MockTransport` the checks use is not touched. A test whose code tried a guarded call fails even when the code swallowed the error, with `The code under test tried ... and caught the error`. Observe prints a `note: your code tried ...: blocked` line instead. The guard catches mistakes; it is not a sandbox. C extension modules, `ctypes` and libraries that reach the network outside the entry points it patches are not covered, and code that hides or clears the guard's record passes. Like the rest of the labs, it relies on the honor system ([labs/README.md](../README.md#hints-and-the-solution)).

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

`python labs/w3/tools/observe.py store` (lab w3l3) runs `p1_judge` once per case on a fresh journal: the recorded reply, the same reply ending in `unknown`, no verdict line, an HTTP 400, a teacher and a never-entered thesis, then the recorded reply with the journal's verdict write or score write failing. Each row shows the requests sent, the run files and what they say was spent, the `judge_verdict` row, the `p1_judge` scores, and what `p1_judge` returned or raised. What moves: run files 0 → 1, verdict rows and scores, nothing kept when a write fails, and the refusals sending nothing. [pages/w3l3.md](pages/w3l3.md) has the table per exercise.

`python labs/w3/tools/observe.py grade` (lab w3l4) runs `grade.to_judge` on a journal of six theses, `grade.judge` on four waiting theses under a $0.25 cap (replies pass, no verdict, HTTP 400, pass) and under a $0.05 cap (the recorded pass each time), then `tr grade` plain, `--judge --dry-run` and `--judge` twice on two waiting theses. What moves: which theses wait, what each run sends and spends under its cap, and what `tr grade` prints. [pages/w3l4.md](pages/w3l4.md) has the table per exercise. The cap is $0.05, not the checks' $0.045, because `grade.judge` prints the cap to the cent.

## The suite gate

`tests/test_week3.py` (19 tests) covers the chapter's §2 to §7 and is red until the week ends. Passing: 0 at the base and on the w3l1.1 stub, 3, 4 and 6 after w3l1.1, .2 and .3 (the parser cases), still 6 after each w3l2 exercise and after w3l3.1, 10 after w3l3.2 (the 4 judge tests), 12 after w3l3.3 (the 2 refusal cases), 12 after w3l4.1 and w3l4.2, and 13 after w3l4.3 (`tr grade --judge`). The end-of-lab run of `tr lab next` deselects what that lab cannot turn green yet:

| Deselected | Where | Why |
|---|---|---|
| `test_the_judge_sends_one_request_with_the_adr_003_model_the_rubric_and_the_summary`, `test_the_judge_prompt_holds_no_raw_bar_rows`, `test_the_judge_returns_a_score_and_stores_its_verdict_and_score`, `test_the_judge_call_and_its_cost_land_in_a_run_file` | `[labs.w3l1.suite]`, `[labs.w3l2.suite]` | they call `p1_judge` to the end and check its Score, its stored verdict and its run file; after w3l2.3 `p1_judge` raises `NotImplementedError` after its call (lab w3l3) |
| `test_teacher_and_never_entered_theses_are_never_judged` (2 cases) | `[labs.w3l1.suite]`, `[labs.w3l2.suite]` | the refusal of a teacher or never-entered thesis is w3l3.3 |
| `test_tr_grade_judge_is_off_by_default_then_judges_once_and_prints_the_cost` | `[labs.w3l1.suite]` to `[labs.w3l3.suite]` | `tr grade --judge` is lab w3l4 |
| `test_adr_004_names_what_never_enters_a_trace`, `test_the_slo_review_has_four_slos_and_the_injected_breach`, `test_measured_costs_has_a_row_per_step_with_its_run_id` (6 cases: ADR-004, the SLO review and 4 measured-costs cases) | `[suite]` (every lab) | they read documents the learner writes by hand from the chapter (§2, §5, §6); no exercise writes prose |

The cases still red at the end of each lab are exactly these: 13 after w3l1 and w3l2, 7 after w3l3, 6 after w3l4. The first two judge tests check the request, which the w3l2 checks already pin byte for byte; they stay deselected in part A because they run `p1_judge` to its end.

**End state.** `[end] tag = "week-3-end"`, `files` = `src/tradingresearch/evals.py`, `src/tradingresearch/grade.py`, `src/tradingresearch/commands/grade.py` and `tests/fixtures/help/grade.txt`: after w3l4.3 each must equal the tag byte for byte. `evals.py` already equals it after w3l3.3. After w3l2.3 it equals `week-3-end` except `p1_judge`, which builds the recorded request, sends it once under `CallBudget(max_usd=max_usd, prices=prices)` and raises `NotImplementedError` naming the run; it has no refusal, no run file, no stored verdict and no Score yet. The w3l4.1 stub brings in the help fixture as it is at the tag, and the two grade files with `to_judge`, the loop of `grade.judge` and the costs in `render_judged` and `cmd_grade` cut out.

## What the labs do not cover

§1 (setup and the tour of the shipped code), §2 (traces, redaction and retries; ADR-004 is written by hand), §3 (`tr grade`, the outcome, the shadow and P2-P4, already shipped), §5 (the SLOs and the SLO review), §6 (measured costs) and §7 (blind labels and Cohen's κ, which need trades to close). They are writing, review or setup, and stay in the chapter.

## Prove the folder

From the root of a clean clone (`uv sync` done):

```bash
uv run python labs/tools/prove.py w3 > labs/w3/PROOF.md
```

It copies the clone into temp folders and runs the chain (each stub red with `red_expect`, `solution.diff` green, earlier checks of the same lab still green, every `wrong/*.diff` red with its `expect:`), the end state (the four `[end]` files equal `week-3-end`), the hint guard, the captured output and a runner smoke; [labs/w1/README.md](../w1/README.md#prove-the-folder) describes each row. It exits 1 if any row reads NOT PROVEN. Re-run it after changing an exercise, a stub, a test message, the data, observe or `lab.py`.

The hint guard is a string match: it rejects a hint that repeats a `solution.diff` added line of 12 or more characters, or holds a code fence longer than one line. It does not judge whether prose dictates the answer; that is a reading job. The week-3 hints state the idea and a counterexample, with no code and no function to call.

**Captures for the site.** The same as week 1's (see [labs/w1/README.md](../w1/README.md)): each exercise's `expected_output/fail.txt` and `pass.txt`, the walked-through session in `session/` (the start of the week: the base commit from `week-3-start`, then w3l1.1 end to end), and the page text in each `exercise.toml`: `goal`, `what_tested`, `writes`, `show_tests` (no `show_data`), with `goal` and `section` per lab in `lab.toml`. `python labs/tools/capture.py w3 --write` regenerates the captured files, `--leakcheck` checks that no page text gives away a solution line or a locked hint, and `prove.py w3` re-captures and fails on any difference.

## Reading

The week's reading is the published chapter, [Week 3](https://scout.edgelab.one/learn/ai-engineering/week-3/). These labs are the code of its [§4 The P1 judge and `tr grade --judge`](https://scout.edgelab.one/learn/ai-engineering/week-3/#4-the-p1-judge-and-tr-grade---judge-2-h-0); the pages link its sections.
