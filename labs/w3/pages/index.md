# Week 3 labs

> *"Educational software. Not investment advice. No orders are placed; trades are hypothetical and settled from historical bars by written rules. Past results, including these, do not predict future results."*

Week 3 of the AI engineering track puts a model in as a grader: the P1 judge reads one closed trade and says whether the thesis's reason played out. These labs are part A of the code half of the chapter's [§4 The P1 judge and `tr grade --judge`](https://scout.edgelab.one/learn/ai-engineering/week-3/#4-the-p1-judge-and-tr-grade---judge-2-h-0): 6 exercises in 2 labs, on the `labs` branch of your tradingresearch clone. Every exercise is a change to `src/tradingresearch/evals.py`, checked by pytest, with an observe command that runs your code on recorded judge replies (lab w3l1) or on the one recorded judge request and reply (lab w3l2). $0: the judge's provider is the repo's real OpenRouter adapter with its transport replaced by one that answers with the recorded reply, so nothing leaves your machine.

| Lab | You build | Exercises | What observe shows |
|---|---|---|---|
| [w3l1 Reading the verdict](w3l1.md) | `p1_verdict`: the rubric's Verdict format, read from the judge's reply | 3 | your reading of 26 replies against the rubric's; matches per exercise: w3l1.1 1/9 on the stub → 9/9, w3l1.2 7/7, w3l1.3 10/10 |
| [w3l2 The judge prompt and the one call](w3l2.md) | `judged_sample` and `p1_judge` up to its call: the rubric, the thesis, the evidence and one bounded, capped request | 3 | your request against the recorded one: prompt chars 1336 → 5158 → 5925 of 5925, INPUT 0 → 12 of 12 lines, `max_tokens` 1024 → 4000, same body: yes after w3l2.3, 0 requests under a $0.001 cap |

**Week 3 starts from the author's code, not yours.** The first `tr lab start w3l1` makes the repo's files equal to the tag `week-3-start` (the author's code at the start of week 3, which includes the author's week-1 and week-2 solutions) and commits that as `lab: week 3 base (week-3-start)`. Your earlier commits stay in the history of the `lab` branch; you can start week 3 without finishing week 2. At `week-3-start`, `evals.py` has the draft P1 judge of week 2 and no `p1_verdict`; the w3l1.1 stub brings in the week's code with `p1_verdict` cut out.

**Part B (labs w3l3, w3l4) finishes `p1_judge`.** After w3l2.3, `p1_judge` sends the recorded request under its cap and then raises `NotImplementedError` naming the run. Part B keeps that run in a run file, reads its reply with your `p1_verdict`, stores the verdict with its ScoreRecord and returns the Score, refuses teacher and never-entered theses before any call, and adds `tr grade --judge`. Only then does `evals.py` equal the tag `week-3-end`.

**Not in these labs.** Part B's code, above. The rest of the chapter stays in the chapter, because it is prose, review or setup rather than code: §1 (setup and the tour of the shipped code), §2 (traces, redaction and retries; ADR-004 is written by hand), §3 (`tr grade`, the outcome, the shadow and P2-P4, already shipped), §5 (the SLOs and the SLO review), §6 (measured costs) and §7 (blind labels and Cohen's κ, which need trades to close).

**`tests/test_week3.py` is red until the week ends.** It covers §2 to §7: 19 tests, 0 passing at `week-3-start` (no `p1_verdict`, so every test that imports it fails). Each exercise of lab w3l1 turns some green; lab w3l2 turns none:

| State | test_week3 passing (of 19) |
|---|---|
| `week-3-start`, and the w3l1.1 stub | 0 |
| after w3l1.1, .2, .3 | 3, 4, 6 (the parser cases) |
| after w3l2.1, .2, .3 | 6, 6, 6 |

The 13 still red after w3l2: the 4 judge tests call `p1_judge` to the end and check its Score, its stored verdict and its run file, and the 2 refusal cases (teacher, never entered) need the refusal, all part B; the `tr grade --judge` test is part B; the ADR-004, SLO review and measured-costs tests (6 cases) read documents you write by hand from the chapter. `tr lab next` runs the repo suite at the end of each lab and leaves out the tests part A cannot turn green (`[suite] deselect` in [`lab.toml`](../lab.toml), each with the reason). Plain `uv run pytest -q` still shows them failing.

Commands run from the root of your tradingresearch clone; this week's folder is `labs/w3/`. `tr lab` drives the exercises: `tr lab start w3l1`, then `tr lab verify` until green and `tr lab next`. All commands, and what to do when one refuses: [labs/README.md](../../README.md). Hints unlock after failed runs of `tr lab verify` (hint 1 after 2, hint 2 after 5, the solution after 10 or at once when green; [`lab.toml`](../lab.toml) holds the numbers).

Concepts: [index](concepts.md). Reading: the chapter, [Week 3](https://scout.edgelab.one/learn/ai-engineering/week-3/); the files the code implements are in the repo: `evals/specs/p1_judge.md`, `evals/rubrics/p1_thesis_quality.md`, `evals/rubrics/p1_judge_prompt.txt` and `docs/adr/ADR-003-judge-choice-and-validation.md`. How the folder is built and proved: [README](../README.md).
