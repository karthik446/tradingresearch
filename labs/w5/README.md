# Week 5 labs: the folder

This folder holds week 5 of the AI engineering track, run by `tr lab` on this repo from the tag `week-5-start`: 12 exercises in 4 labs. Part A: lab w5l1 is the code of the chapter's §4 (per-section grounding graders, in `evals.py`); lab w5l2 is the config of §5 (`experiments/context-ablation.toml`: the arms, the graders and cluster, the pre-registration). Part B: lab w5l3 is §5's change to `compare` (a grader it cannot pair is skipped with a line that says why, in `experiment.py`); lab w5l4 is §8's training split (the embargo floor in `records.py`, then `split.py`: register once, refused before the cutoff opens, the embargo window and the derived sets). Nothing in it calls a model or opens a connection; it costs $0.

## Exercises

| Exercise | What the learner does | Edits | Wrong fixes |
|---|---|---|---|
| [w5l1.1](exercises/w5l1.1-the-claims-that-cite-a-section/) | Score the share of the claims citing a section that the validator keeps | `evals.py` | 21 |
| [w5l1.2](exercises/w5l1.2-not-cited-and-not-parsed/) | Give no score to a section no claim cites or a reply that did not parse; explain a failing section | `evals.py` | 17 |
| [w5l1.3](exercises/w5l1.3-four-graders-and-the-drop/) | Hand the grader its arm's drop; register one code grader per section | `evals.py` | 13 |
| [w5l2.1](exercises/w5l2.1-three-arms/) | Write three analyze-3 arms that differ only in what they drop | `experiments/context-ablation.toml` | 18 |
| [w5l2.2](exercises/w5l2.2-graders-and-cluster/) | Name the seven code graders once each; write the cluster out | `experiments/context-ablation.toml` | 13 |
| [w5l2.3](exercises/w5l2.3-the-pre-registration/) | Write the primary metric, the guard and the rule above the first key | `experiments/context-ablation.toml` | 21 |
| [w5l3.1](exercises/w5l3.1-the-graders-both-arms-scored/) | Compare on the graders both runs scored on a common item, skip the rest, refuse with `no_shared_metric` when none is left | `experiment.py` | 17 |
| [w5l3.2](exercises/w5l3.2-why-and-how-many/) | Say why each grader was skipped and how many items each run scored; name every skipped grader in the refusal | `experiment.py` | 18 |
| [w5l4.1](exercises/w5l4.1-the-embargo-floor/) | Derive the embargo floor (entry window 2 + longest hold 20) and refuse a split under it with the reason | `records.py` | 14 |
| [w5l4.2](exercises/w5l4.2-register-once/) | Register a split stamped in New York time under a content-addressed id, stored once | `split.py` | 18 |
| [w5l4.3](exercises/w5l4.3-a-cutoff-still-ahead/) | Refuse a cutoff whose session has opened, by now or by the pre-registration, before writing a row | `split.py` | 18 |
| [w5l4.4](exercises/w5l4.4-the-derived-sets/) | The embargo window from the NYSE calendar; train/val, embargoed and test derived from the journal's sessions | `split.py` | 22 |

### Part A

103 wrong fixes: 51 in w5l1, 52 in w5l2.

46 are `before: RED (author)`, written with the exercise (w5l1 8, 9, 7; w5l2 7, 6, 9).

12 come from a break pass on w5l2 run by the exercise's author after each exercise passed, all red when first tried (`before: RED (break pass)`; w5l2.1 5, w5l2.2 2, w5l2.3 5).

35 come from an independent break pass, written against the finished checks by a second writer. 32 were red when first tried (`before: RED (independent break pass)`; w5l1 4, 6, 5; w5l2 6, 5, 6). 3 passed the check as it then stood, and each now has a test (`before: GREEN (independent break pass)`): in w5l1.1, a claim id kept as the JSON gave it, so a numeric id never met its rejection, and a grader that read at most ten claims; in w5l1.3, the drop kept on the class instead of on each grader, so the next grader an arm builds resets it for all.

10 come from an independent read of the finished lab and passed the checks as they then stood; each now has a test (`before: GREEN (independent read)`; w5l1.1 7, w5l1.2 2, w5l2.3 1).

Every wrong fix is red with its `expect:` and passes the earlier exercises of its lab, so its own check is the one that catches it (checked in a scratch clone; `prove.py` checks the first part, not the second). Four w5l2.2 wrong fixes were dropped rather than kept: a misspelt grader, `cluster = "session"`, the cluster as a list and a capitalised cluster all make the loader refuse the whole file, so w5l2.1's check fails on them first. To let w5l2.2's wrong fixes reach their own check, w5l2.1's replay grades with `parsed` alone: it checks what each arm sends, and what the arms are graded with is w5l2.2.

Alternatives that are right but not the reference, each green: w5l1.1 2, w5l1.2 3, w5l1.3 3, w5l2.1 3 (the full arm with no drop key, the model set on each arm, the arms in another order), w5l2.2 2 (the graders in another order, the cluster after the graders), w5l2.3 2 (items with no bullets, the rule in other words).

### Part B

107 wrong fixes: 35 in w5l3, 72 in w5l4.

65 are `before: RED (author)`, written with the exercise (w5l3 11, 10; w5l4 8, 11, 12, 13).

35 come from a break pass run by the exercise's author after each check passed (`before: RED (break pass)`; w5l3 5, 6; w5l4 5, 6, 5, 8). Each was red when kept, with three cases where it was not at first:

- w5l3.1: missing in one run only and missing in both are the same at w5l3.1 (a run with no score has no common item); only the reason text differs, so that wrong fix lives in w5l3.2, and its w5l3.1 twin moved there too.
- w5l4.2: storing the pre-registration's `registered_at` as the split's passed at first, because every probe's pre-registration was registered at now. The store test's pre-registration is now registered the day before.
- w5l4.3: writing the row before refusing first failed on the chained `Refused` (the row count was asserted inside `except`). The row count is now asserted after the `try`.

Dropped rather than kept: in w5l3.2 the skipped graders as a set (red or green by `PYTHONHASHSEED`); in w5l4.2 the real clock (its first failing line moves with the date). Not saved as wrong because they are right: in w5l4.1 the cutoff rule checked before the floor; in w5l4.2 the pre-registration dumped in Python mode (its fields dump the same). Not observable: in w5l4.3 the embargo checked after the lookup (a stored split cannot have an embargo under 22).

7 come from an independent read of the finished lab and passed the checks as they then stood; each now has a test (`before: GREEN (independent read)`; w5l3.1 1, w5l3.2 2, w5l4.1 1, w5l4.2 1, w5l4.3 1, w5l4.4 1):

- w5l3.1 and w5l3.2: a grader kept only when one run's items are a subset of the other's, so two runs that share one item and each have one of their own skip it (`either-subset-overlap`, one in each exercise).
- w5l3.2: the refusal's skipped graders sorted by name instead of in the order asked (`refusal-sorted`).
- w5l4.1: the floor and its reason written in as 22 and `longest hold 20` instead of derived from `HOLD_RANGE` (`floor-hard-coded`); the test runs a copy of `records.py` with a swing hold of 45.
- w5l4.2: the stored split looked up by cutoff and embargo alone, so a different pre-registration gets the old split (`lookup-by-cutoff-and-embargo`).
- w5l4.3: a session taken as a weekday that is no federal holiday, which stores Good Friday 2027-03-26 and refuses Veterans Day 2026-11-11 (`weekday-and-no-federal-holiday`).
- w5l4.4: the window counted back from the calendar day before the cutoff, which raises on a Monday cutoff or one after a holiday (`window-from-the-calendar-day-before`).

The same read found that w5l4.2's `registered_at` check compared the tzinfo object, so a correct `register` that returns the split read back from the journal failed. It now compares the instant and New York's UTC offset; `store-before-lookup` now first fails on the second register, and its header says so.

Every part B wrong fix is red with its `expect:` and passes the earlier exercises of its lab (checked in a scratch clone), except the w5l3.2 copy of `either-subset-overlap`: w5l3.1's check catches it too, and it is kept in w5l3.2 so that exercise's check is proven on it.

Alternatives that are right but not the reference, each green, kept out of the folder: w5l3.1 3 (one rule for a common item, comprehensions, scores de-duplicated first), w5l3.2 3 (`str.format`, `%` formatting, the reasons first then formatted), w5l4.1 4 (the cutoff rule first, the longest hold named, the ranges sorted, the message concatenated), w5l4.2 5 (a walrus lookup, the digest sliced, UTC then New York, the Python-mode dump, the split read back from the journal after storing it), w5l4.3 3 (two plain `if`s, "not after" written out, the first failing rule), w5l4.4 3 (walk back with `sessions.previous`, the window as `recent(n + 1, cutoff)` without its last, `bisect` on the sorted days).

## Layout

```
labs/w5/
  lab.toml                      base = "week-5-start", lab titles, pages, goals and sections, [unlock], [suite] deselect, [labs.w5l1.suite] deselect, [end]
  conftest.py                   marks every test in this folder `lab` (plain `pytest -q` never collects them) and installs the offline guard before any test module imports learner code
  data/fakea.context.json       the FAKEA ticker-day context: week 4's rows plus three invented headlines
  data/analyze3.request.json    one recorded analyze-3 request (claude-sonnet-5.5, 2026-11-17, $0.016048) and
  data/analyze3.reply.json        its reply: 11 claims, 7 citing indicator rows (one fails empty_placeholder), 1 citing a headline
  data/models.json              the model's /models price row, recorded with the exchange
  data/ablation.runs.json       the author's context-ablation run of 2026-11-17: its dataset and items, and per arm every score as [grader, version, item, value]; nothing else of the runs
  pages/                        index.md, w5l1.md to w5l4.md (one page per lab), concepts.md
  tools/offline.py              the offline guard: socket connections and DNS, subprocesses, os spawns and the real httpx transports raise Blocked and are counted
  tools/fakea.py                the context, the recorded reply as a sample, hand-built replies, the section grader lookup, and the ablation replay (`ablation`): the config's arms over its tickers, every request answered with the recorded reply ($0, no network)
  tools/runs.py                 the gigai-core runs lab w5l3 compares: the author's three arms rebuilt from data/ablation.runs.json, and hand-built runs whose scores a check chooses
  tools/observe.py              observe: `grader` (w5l1), `ablation` (w5l2); installs the offline guard first
  tools/observe_compare.py      observe for w5l3: what your `experiment.compare` prints as `tr exp compare`
  tools/observe_split.py        observe for w5l4: the embargo floor, `split.register` at a fixed clock, the window and the derived sets
  session/session.toml          the walked-through session on the pages: its steps, each one's `run` and its `output` file, 01-start.txt to 06-after-next.txt
  exercises/w5lN.K-<slug>/
    exercise.toml               id, title, effect, goal, what_tested, writes, show_tests, lab, concepts, touches, check, observe, paid, fixtures, origin, red_expect
    stub/                       the week-5-end files the exercise touches with this exercise's part and the later ones cut out: `evals.py` (w5l1.1 to w5l1.3), `experiments/context-ablation.toml` (w5l2.1), `experiment.py` with `commands/exp.py` and its help (w5l3.1), `records.py` (w5l4.1), `split.py` with its command, `tests/test_cli.py` and help (w5l4.2, which also holds w5l4.3's and w5l4.4's holes); the others have none and build on the learner's file
    expected_output/            fail.txt (the red run on the stub, or on the previous exercise's reference) and pass.txt (the solution's green run), captured by capture.py
    test_w5lN_K.py              the check; its assertion messages are the FAIL messages
    hints.md                    two hints, each under a `## Hint N` heading: the idea, no code
    solution.diff               the reference change, applied with `git apply` on the stub or the previous state
    wrong/*.diff                known wrong fixes, each with why / expect / before headers (prove.py runs them)
```

**The base.** `base = "week-5-start"` makes the first `tr lab start w5l1` set the repo's files to that tag and commit them, so week 5 does not depend on the learner's week-4 code. `week-5-start` already has the masking that drop arms use and analyze-3 with headlines (§2 and §3, shipped); its `evals.py` has no section grader, `experiments/context-ablation.toml` does not exist, its `compare` refuses over any grader it cannot pair, and there is no `split.py`.

**The data.** The first four files in `data/` are byte copies of the repo's `tests/fixtures/week5/`. Only the reply is model output. `ablation.runs.json` holds the scores of the author's paid run and nothing else (no prompts, no replies, no costs); `tools/runs.py` rebuilds the three runs from it, so `compare` sees the run the chapter compared. `week-5-start`'s `.gitignore` has `data/`, so a learner's own `data/` stays untracked; this folder is tracked on the labs branch.

**The replay.** `fakea.ablation` runs the real `experiment.run_arms` on the config's arms over its tickers, one session, with the context size pinned, and answers every request with the recorded reply. Each request it was sent is kept, so a check can compare it with the recorded request masked by the arm's drop.

## Observe

`python labs/w5/tools/observe.py grader` (lab w5l1) prints the registered section graders, then scores five replies in each of the four sections: the recorded reply, a claim citing a close and a level with a second claim wrong, three indicator claims failing three ways and one kept, a parsed reply with no claims list, a reply that did not parse. Once the graders are registered it also scores the recorded reply in each arm's drop. What moves: `NotImplementedError` everywhere → indicators 0.857 and headlines 1.000 on the recorded reply (w5l1.1); `ZeroDivisionError` in every uncited section → `CannotGrade: not_cited`, and explanations (w5l1.2); no grader registered → four, and headlines 0.000 `dropped_source` in drop ['headlines'] (w5l1.3).

`python labs/w5/tools/observe.py ablation` (lab w5l2) loads the config and prints its arms, graders, cluster and the pre-registration lines above the first key, then replays it and prints each scored grader's mean and n per arm. What moves: the load refused, missing arms → 3 arms and 30 requests (w5l2.1); graders `['parsed']` → seven, with `claims_valid` 0.909 in full and no-edgar and 0.818 in no-headlines (w5l2.2); pre-registration `(none)` → three lines (w5l2.3).

`python labs/w5/tools/observe_compare.py` (lab w5l3) runs your `experiment.compare` on the author's three runs as the chapter's two `tr exp compare` commands, then with the graders in config order, then on `edgar_grounded` and `levels_grounded` alone. What moves: `compare raised NotImplementedError` four times → the chapter's two blocks with a `skipped` line per grader left out, and the refusal `cannot compare: no grader is scored on a common item in both runs` (w5l3.1); the same lines with why and the counts, `not scored in both arms (n=16 vs 0)`, and a refusal that names every skipped grader (w5l3.2).

`python labs/w5/tools/observe_split.py` (lab w5l4) prints the embargo floor, builds a `TrainingSplit` one session under it, registers splits at a fixed clock (2026-10-30 22:00 UTC) into a temporary store, and partitions a journal's sessions. What moves: `MIN_EMBARGO: '(missing)'` and an embargo of 21 accepted → 22, `entry window 2 + longest hold 20`, and 21 refused (w5l4.1); `register raised NotImplementedError` → `sp_511d03d559bae169` stored once, but a Thanksgiving cutoff stored too (w5l4.2); Thanksgiving, the last completed session, and a cutoff whose session opened before now (cutoff 2026-11-02, now 10:00 New York) refused, no row written (w5l4.3); `embargo_window raised NotImplementedError` → 22 sessions from 2026-11-25 to 2026-12-28, and the three sets (w5l4.4).

## The suite gate

`tests/test_week5.py` (15 cases) covers the whole chapter and is red until the week ends. Passing, measured in a scratch copy of `week-5-start`: 0 at the base, on the w5l1.1 stub, and after w5l1.1 and w5l1.2 (the grader cases look the graders up in the registry); 10 after w5l1.3; 11, 13 and 13 after w5l2.1, .2 and .3; 13 after w5l3 and after w5l4, which have no case in it.

| Deselected | Where | Why |
|---|---|---|
| `test_the_context_ablation_has_three_analyze3_arms_that_differ_only_in_drop`, `test_the_ablation_sends_each_arm_the_recorded_request_masked_over_one_dataset`, `test_the_ablation_grades_the_recorded_reply_per_arm` | `[labs.w5l1.suite]` | they read `experiments/context-ablation.toml`, which is lab w5l2 |
| `test_adr_007_records_the_decision_a_measured_table_and_the_consequences`, `test_adr_008_weighs_options_for_an_mcp_gateway_and_registry` | `[suite]` (every lab) | ADR-007 and ADR-008, written by hand from the chapter's §5 and §7; no lab writes them |

The cases still red at the end of each lab are exactly these: 5 after w5l1, 2 after w5l2, w5l3 and w5l4 (at the end of w5l4: 664 passed, those 2 failing when not deselected). w5l3 and w5l4 need no suite list of their own. `tests/test_experiment_compare.py` and `tests/test_split.py`, which test what w5l3 and w5l4 build, are not in `week-5-start` and are not shipped; the pages tell the learner to run them from `week-5-end` once green (both pass on the reference).

**End state.** `[end] tag = "week-5-end"`, and its `files` are the 15 files the labs write: `src/tradingresearch/evals.py`, `experiments/context-ablation.toml`, `experiment.py`, `commands/exp.py` and its help `exp.txt` and `exp_compare.txt`, `records.py`, `split.py`, `commands/split.py`, `commands/__init__.py`, `tests/test_cli.py`, and the help `split.txt`, `split_register.txt`, `split_show.txt` and `tr.txt`. After the last exercise every one equals the tag byte for byte.

## What the labs do not cover

§1 (setup and the tour), §2 and §3 (the drop knob and headlines in analyze-3, shipped in the base). §5's paid run: the author ran the ablation once, $0.989286 over 60 analyses, and it needs the reader's own key, so it is not a lab; lab w5l2 builds the config it read and lab w5l3 compares its stored scores. ADR-007. §6 (the playbook, shipped), §7 (ADR-008, design only), §8's claim labels (`tr label --claims`, `label.py` and its command and help: labelling is a human task), §9 and §10. The files that change at `week-5-end` but no exercise writes: `README.md`, `docs/measured-costs.md`, `docs/runbook.md`, `evals/specs/section_grounding.md`, `tests/test_section_grounding.py`, `tests/test_label_claims.py`, and the two test files above.

## Prove the folder

From the root of a clean clone (`uv sync` done):

```bash
uv run python labs/tools/prove.py w5
```

It copies the clone into temp folders and runs the chain (each stub red with `red_expect`, `solution.diff` green, earlier checks of the same lab still green, every `wrong/*.diff` red with its `expect:`), the end state (the 15 `[end]` files equal `week-5-end`), the hint guard, the captured output and the session. It copies committed files only, so commit the folder before proving it.

The hint guard is a string match: it rejects a hint that repeats a `solution.diff` added line of 12 or more characters, or holds a code fence longer than one line. It does not judge whether prose dictates the answer; that is a reading job.

**Captures for the site.** As in week 1 (see [labs/w1/README.md](../w1/README.md)): each exercise's `expected_output/fail.txt` and `pass.txt`, and the walked-through session in `session/`. `python labs/tools/capture.py w5 --leakcheck` checks that no `solution.diff` added line of 12 or more characters appears in the page text, the shown tests' surroundings, the captures or the session.

## Reading

The week's reading is the published chapter, [Week 5](https://scout.edgelab.one/learn/ai-engineering/week-5/). These labs are the code of its [§4 Per-section grounding graders](https://scout.edgelab.one/learn/ai-engineering/week-5/#4-per-section-grounding-graders-15-h-0), the config and the compare of [§5 The ablation](https://scout.edgelab.one/learn/ai-engineering/week-5/#5-the-ablation-pre-register-run-once-compare-adr-007-25-h-099-at-the-authors-run), and the training split of [§8](https://scout.edgelab.one/learn/ai-engineering/week-5/#8-a-training-split-with-an-embargo-and-claim-labels-1-h-0). The concepts are indexed in [pages/concepts.md](pages/concepts.md).
