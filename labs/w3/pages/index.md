# Week 3 labs

> *"Educational software. Not investment advice. No orders are placed; trades are hypothetical and settled from historical bars by written rules. Past results, including these, do not predict future results."*

Week 3 of the AI engineering track puts a model in as a grader: the P1 judge reads one closed trade and says whether the thesis's reason played out. These labs are the code half of the chapter's [§4 The P1 judge and `tr grade --judge`](https://scout.edgelab.one/learn/ai-engineering/week-3/#4-the-p1-judge-and-tr-grade---judge-2-h-0): 12 exercises in 4 labs, on the `labs` branch of your tradingresearch clone. Every exercise is a change to `src/tradingresearch/evals.py` (labs w3l1 to w3l3) or to `grade.py` and `commands/grade.py` (lab w3l4), checked by pytest. Each has an observe command that runs your code on recorded judge replies (lab w3l1), on the one recorded judge request and reply (lab w3l2), on the recorded reply and edits of it (lab w3l3, `observe.py store`), or on journals of waiting theses (lab w3l4, `observe.py grade`). $0: the judge's provider is the repo's real OpenRouter adapter with its transport replaced by one that answers with the recorded reply or an edit of it, so nothing leaves your machine.

| Lab | You build | Exercises | What observe shows |
|---|---|---|---|
| [w3l1 Reading the verdict](w3l1.md) | `p1_verdict`: the rubric's Verdict format, read from the judge's reply | 3 | your reading of 26 replies against the rubric's; matches per exercise: w3l1.1 1/9 on the stub → 9/9, w3l1.2 7/7, w3l1.3 10/10 |
| [w3l2 The judge prompt and the one call](w3l2.md) | `judged_sample` and `p1_judge` up to its call: the rubric, the thesis, the evidence and one bounded, capped request | 3 | your request against the recorded one: prompt chars 1336 → 5158 → 5925 of 5925, INPUT 0 → 12 of 12 lines, `max_tokens` 1024 → 4000, same body: yes after w3l2.3, 0 requests under a $0.001 cap |
| [w3l3 Keeping what the judge said](w3l3.md) | the rest of `p1_judge`: the run file, the verdict and its ScoreRecord in one transaction, the refusal before any call | 3 | what `p1_judge` ends with and keeps, case by case: run files 0 → 1 ($0.005163, or $0 for an HTTP 400), verdict rows none → `pass` / `fail unknown:` with scores 1.0 / 0.0, nothing kept when a write fails, teacher and never-entered `Refused` → `CannotGrade` with 0 sent |
| [w3l4 Judging in tr grade](w3l4.md) | `to_judge`, the loop of `grade.judge` under one cap per run, and `tr grade --judge` with costs | 3 | the queue lists 6 → 2 theses; a $0.25 run sends 0 → 4 ($0.015489), a $0.05 run 0 → 2 ($0.010326) with the rest capped; `tr grade --judge` prints nothing → a line per thesis and `cost $0.010326`, and plain `tr grade` still sends nothing |

**Week 3 starts from the author's code, not yours.** The first `tr lab start w3l1` makes the repo's files equal to the tag `week-3-start` (the author's code at the start of week 3, which includes the author's week-1 and week-2 solutions) and commits that as `lab: week 3 base (week-3-start)`. Your earlier commits stay in the history of the `lab` branch; you can start week 3 without finishing week 2. At `week-3-start`, `evals.py` has the draft P1 judge of week 2 and no `p1_verdict`; the w3l1.1 stub brings in the week's code with `p1_verdict` cut out.

**Part B (labs w3l3, w3l4) finishes the judge.** After w3l2.3, `p1_judge` sends the recorded request under its cap and then raises `NotImplementedError` naming the run. Lab w3l3 keeps that run in a run file, reads its reply with your `p1_verdict`, stores the verdict with its ScoreRecord and returns the Score, and refuses teacher and never-entered theses before any call; after it, `evals.py` equals the tag `week-3-end`. Lab w3l4 puts the judge into `tr grade`: the queue, one cap per run, and `--judge`, off by default; after it, `grade.py`, `commands/grade.py` and the `tr grade --help` fixture equal the tag too.

**Not in these labs.** The rest of the chapter stays in the chapter, because it is prose, review or setup rather than code: §1 (setup and the tour of the shipped code), §2 (traces, redaction and retries; ADR-004 is written by hand), §3 (`tr grade`, the outcome, the shadow and P2-P4, already shipped), §5 (the SLOs and the SLO review), §6 (measured costs) and §7 (blind labels and Cohen's κ, which need trades to close).

**`tests/test_week3.py` is red until the week ends.** It covers §2 to §7: 19 tests, 0 passing at `week-3-start` (no `p1_verdict`, so every test that imports it fails). Each exercise of lab w3l1 turns some green, lab w3l2 none, lab w3l3 the judge tests and lab w3l4 the `tr grade --judge` test:

| State | test_week3 passing (of 19) |
|---|---|
| `week-3-start`, and the w3l1.1 stub | 0 |
| after w3l1.1, .2, .3 | 3, 4, 6 (the parser cases) |
| after w3l2.1, .2, .3 | 6, 6, 6 |
| after w3l3.1, .2, .3 | 6, 10 (the 4 judge tests), 12 (the teacher and never-entered refusals) |
| after w3l4.1, .2, .3 | 12, 12, 13 (`tr grade --judge`) |

The 6 still red at the end are the ADR-004, SLO review and measured-costs cases, which read documents you write by hand from the chapter. `tr lab next` runs the repo suite at the end of each lab and leaves out the tests that lab cannot turn green yet: the 3 hand-written-document tests always (`[suite] deselect` in [`lab.toml`](../lab.toml)), the 6 judge tests after labs w3l1 and w3l2, and the `tr grade --judge` test after lab w3l3 (the per-lab `[labs.<id>.suite]` lists), each with the reason. Plain `uv run pytest -q` still shows them failing.

Commands run from the root of your tradingresearch clone; this week's folder is `labs/w3/`. `tr lab` drives the exercises: `tr lab start w3l1`, then `tr lab verify` until green and `tr lab next`. All commands, and what to do when one refuses: [labs/README.md](../../README.md). Hints unlock after failed runs of `tr lab verify` (hint 1 after 2, hint 2 after 5, the solution after 10 or at once when green; [`lab.toml`](../lab.toml) holds the numbers).

Concepts: [index](concepts.md). Reading: the chapter, [Week 3](https://scout.edgelab.one/learn/ai-engineering/week-3/); the files the code implements are in the repo: `evals/specs/p1_judge.md`, `evals/rubrics/p1_thesis_quality.md`, `evals/rubrics/p1_judge_prompt.txt` and `docs/adr/ADR-003-judge-choice-and-validation.md`. How the folder is built and proved: [README](../README.md).
