# Week 5 labs: the folder

This folder holds week 5 of the AI engineering track, part A, run by `tr lab` on this repo from the tag `week-5-start`: 6 exercises in 2 labs. Lab w5l1 is the code of the chapter's §4 (per-section grounding graders, in `evals.py`); lab w5l2 is the config of §5 (`experiments/context-ablation.toml`: the arms, the graders and cluster, the pre-registration). Nothing in it calls a model or opens a connection; it costs $0.

## Exercises

| Exercise | What the learner does | Edits | Wrong fixes |
|---|---|---|---|
| [w5l1.1](exercises/w5l1.1-the-claims-that-cite-a-section/) | Score the share of the claims citing a section that the validator keeps | `evals.py` | 14 |
| [w5l1.2](exercises/w5l1.2-not-cited-and-not-parsed/) | Give no score to a section no claim cites or a reply that did not parse; explain a failing section | `evals.py` | 15 |
| [w5l1.3](exercises/w5l1.3-four-graders-and-the-drop/) | Hand the grader its arm's drop; register one code grader per section | `evals.py` | 13 |
| [w5l2.1](exercises/w5l2.1-three-arms/) | Write three analyze-3 arms that differ only in what they drop | `experiments/context-ablation.toml` | 18 |
| [w5l2.2](exercises/w5l2.2-graders-and-cluster/) | Name the seven code graders once each; write the cluster out | `experiments/context-ablation.toml` | 13 |
| [w5l2.3](exercises/w5l2.3-the-pre-registration/) | Write the primary metric, the guard and the rule above the first key | `experiments/context-ablation.toml` | 20 |

93 wrong fixes for part A: 42 in w5l1, 51 in w5l2.

46 are `before: RED (author)`, written with the exercise (w5l1 8, 9, 7; w5l2 7, 6, 9).

12 come from a break pass on w5l2 run by the exercise's author after each exercise passed, all red when first tried (`before: RED (break pass)`; w5l2.1 5, w5l2.2 2, w5l2.3 5).

35 come from an independent break pass, written against the finished checks by a second writer. 32 were red when first tried (`before: RED (independent break pass)`; w5l1 4, 6, 5; w5l2 6, 5, 6). 3 passed the check as it then stood, and each now has a test (`before: GREEN (independent break pass)`): in w5l1.1, a claim id kept as the JSON gave it, so a numeric id never met its rejection, and a grader that read at most ten claims; in w5l1.3, the drop kept on the class instead of on each grader, so the next grader an arm builds resets it for all.

Every wrong fix is red with its `expect:` and passes the earlier exercises of its lab, so its own check is the one that catches it (checked in a scratch clone; `prove.py` checks the first part, not the second). Four w5l2.2 wrong fixes were dropped rather than kept: a misspelt grader, `cluster = "session"`, the cluster as a list and a capitalised cluster all make the loader refuse the whole file, so w5l2.1's check fails on them first. To let w5l2.2's wrong fixes reach their own check, w5l2.1's replay grades with `parsed` alone: it checks what each arm sends, and what the arms are graded with is w5l2.2.

Alternatives that are right but not the reference, each green: w5l1.1 2, w5l1.2 3, w5l1.3 3, w5l2.1 3 (the full arm with no drop key, the model set on each arm, the arms in another order), w5l2.2 2 (the graders in another order, the cluster after the graders), w5l2.3 2 (items with no bullets, the rule in other words).

## Layout

```
labs/w5/
  lab.toml                      base = "week-5-start", lab titles, pages, goals and sections, [unlock], [suite] deselect, [labs.w5l1.suite] deselect, [end]
  conftest.py                   marks every test in this folder `lab` (plain `pytest -q` never collects them) and installs the offline guard before any test module imports learner code
  data/fakea.context.json       the FAKEA ticker-day context: week 4's rows plus three invented headlines
  data/analyze3.request.json    one recorded analyze-3 request (claude-sonnet-5.5, 2026-11-17, $0.016048) and
  data/analyze3.reply.json        its reply: 11 claims, 7 citing indicator rows (one fails empty_placeholder), 1 citing a headline
  data/models.json              the model's /models price row, recorded with the exchange
  pages/                        index.md, w5l1.md, w5l2.md (one page per lab), concepts.md
  tools/offline.py              the offline guard: socket connections and DNS, subprocesses, os spawns and the real httpx transports raise Blocked and are counted
  tools/fakea.py                the context, the recorded reply as a sample, hand-built replies, the section grader lookup, and the ablation replay (`ablation`): the config's arms over its tickers, every request answered with the recorded reply ($0, no network)
  tools/observe.py              observe: `grader` (w5l1), `ablation` (w5l2); installs the offline guard first
  session/session.toml          the walked-through session on the pages: its steps, each one's `run` and its `output` file, 01-start.txt to 06-after-next.txt
  exercises/w5lN.K-<slug>/
    exercise.toml               id, title, effect, goal, what_tested, writes, show_tests, lab, concepts, touches, check, observe, paid, fixtures, origin, red_expect
    stub/                       the week-5-end file the exercise touches with this exercise's part and the later ones cut out (`evals.py` in w5l1.1 to w5l1.3, `experiments/context-ablation.toml` in w5l2.1); w5l2.2 and w5l2.3 have none and build on the learner's file
    expected_output/            fail.txt (the red run on the stub, or on the previous exercise's reference) and pass.txt (the solution's green run), captured by capture.py
    test_w5lN_K.py              the check; its assertion messages are the FAIL messages
    hints.md                    two hints, each under a `## Hint N` heading: the idea, no code
    solution.diff               the reference change, applied with `git apply` on the stub or the previous state
    wrong/*.diff                known wrong fixes, each with why / expect / before headers (prove.py runs them)
```

**The base.** `base = "week-5-start"` makes the first `tr lab start w5l1` set the repo's files to that tag and commit them, so week 5 does not depend on the learner's week-4 code. `week-5-start` already has the masking that drop arms use and analyze-3 with headlines (§2 and §3, shipped); its `evals.py` has no section grader, and `experiments/context-ablation.toml` does not exist.

**The data.** All four files in `data/` are byte copies of the repo's `tests/fixtures/week5/`. Only the reply is model output.

**The replay.** `fakea.ablation` runs the real `experiment.run_arms` on the config's arms over its tickers, one session, with the context size pinned, and answers every request with the recorded reply. Each request it was sent is kept, so a check can compare it with the recorded request masked by the arm's drop.

## Observe

`python labs/w5/tools/observe.py grader` (lab w5l1) prints the registered section graders, then scores five replies in each of the four sections: the recorded reply, a claim citing a close and a level with a second claim wrong, three indicator claims failing three ways and one kept, a parsed reply with no claims list, a reply that did not parse. Once the graders are registered it also scores the recorded reply in each arm's drop. What moves: `NotImplementedError` everywhere → indicators 0.857 and headlines 1.000 on the recorded reply (w5l1.1); `ZeroDivisionError` in every uncited section → `CannotGrade: not_cited`, and explanations (w5l1.2); no grader registered → four, and headlines 0.000 `dropped_source` in drop ['headlines'] (w5l1.3).

`python labs/w5/tools/observe.py ablation` (lab w5l2) loads the config and prints its arms, graders, cluster and the pre-registration lines above the first key, then replays it and prints each scored grader's mean and n per arm. What moves: the load refused, missing arms → 3 arms and 30 requests (w5l2.1); graders `['parsed']` → seven, with `claims_valid` 0.909 in full and no-edgar and 0.818 in no-headlines (w5l2.2); pre-registration `(none)` → three lines (w5l2.3).

## The suite gate

`tests/test_week5.py` (15 cases) covers the whole chapter and is red until the week ends. Passing, measured in a scratch copy of `week-5-start`: 0 at the base, on the w5l1.1 stub, and after w5l1.1 and w5l1.2 (the grader cases look the graders up in the registry); 10 after w5l1.3; 11, 13 and 13 after w5l2.1, .2 and .3.

| Deselected | Where | Why |
|---|---|---|
| `test_the_context_ablation_has_three_analyze3_arms_that_differ_only_in_drop`, `test_the_ablation_sends_each_arm_the_recorded_request_masked_over_one_dataset`, `test_the_ablation_grades_the_recorded_reply_per_arm` | `[labs.w5l1.suite]` | they read `experiments/context-ablation.toml`, which is lab w5l2 |
| `test_adr_007_records_the_decision_a_measured_table_and_the_consequences`, `test_adr_008_weighs_options_for_an_mcp_gateway_and_registry` | `[suite]` (every lab) | ADR-007 and ADR-008, written by hand from the chapter's §5 and §7; no lab writes them |

The cases still red at the end of each lab are exactly these: 5 after w5l1, 2 after w5l2.

**End state.** `[end] tag = "week-5-end"`, and its `files` are the two files the labs write: `src/tradingresearch/evals.py` and `experiments/context-ablation.toml`. After the last exercise both equal the tag byte for byte.

## What the labs do not cover

§1 (setup and the tour), §2 and §3 (the drop knob and headlines in analyze-3, shipped in the base). §5's paid run: the author ran the ablation once, $0.989286 over 60 analyses, and it needs the reader's own key, so it is not a lab; lab w5l2 builds the config it read. Also §5's change to `compare` (skipping a grader scored in one arm only, and `tr exp compare`) and ADR-007. §6 (the playbook, shipped), §7 (ADR-008, design only), §8 (the training split and the claim labels), §9 and §10. The files that change at `week-5-end` but no exercise writes: `docs/measured-costs.md`, `docs/runbook.md`, `evals/specs/section_grounding.md`, `tests/test_section_grounding.py`.

## Prove the folder

From the root of a clean clone (`uv sync` done):

```bash
uv run python labs/tools/prove.py w5
```

It copies the clone into temp folders and runs the chain (each stub red with `red_expect`, `solution.diff` green, earlier checks of the same lab still green, every `wrong/*.diff` red with its `expect:`), the end state (the two `[end]` files equal `week-5-end`), the hint guard, the captured output and the session.

The hint guard is a string match: it rejects a hint that repeats a `solution.diff` added line of 12 or more characters, or holds a code fence longer than one line. It does not judge whether prose dictates the answer; that is a reading job.

**Captures for the site.** As in week 1 (see [labs/w1/README.md](../w1/README.md)): each exercise's `expected_output/fail.txt` and `pass.txt`, and the walked-through session in `session/`. `python labs/tools/capture.py w5 --leakcheck` checks that no `solution.diff` added line of 12 or more characters appears in the page text, the shown tests' surroundings, the captures or the session.

## Reading

The week's reading is the published chapter, [Week 5](https://scout.edgelab.one/learn/ai-engineering/week-5/). These labs are the code of its [§4 Per-section grounding graders](https://scout.edgelab.one/learn/ai-engineering/week-5/#4-per-section-grounding-graders-15-h-0) and the config of [§5 The ablation](https://scout.edgelab.one/learn/ai-engineering/week-5/#5-the-ablation-pre-register-run-once-compare-adr-007-25-h-099-at-the-authors-run). The concepts are indexed in [pages/concepts.md](pages/concepts.md).
