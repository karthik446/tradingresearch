# Week 2 labs

> *"Educational software. Not investment advice. No orders are placed; trades are hypothetical and settled from historical bars by written rules. Past results, including these, do not predict future results."*

Week 2 of the AI engineering track turns the review of a thesis into code. These labs are the code half of the chapter's [§2 Process versus outcome: P2-P4 as code](https://scout.edgelab.one/learn/ai-engineering/week-2/#2-process-versus-outcome-p2-p4-as-code-2-h-0), plus the draft judge of [§3](https://scout.edgelab.one/learn/ai-engineering/week-2/#3-p1-a-rubric-a-draft-judge-and-adr-003-15-h-0): 13 exercises in 4 labs, on the `labs` branch of your tradingresearch clone. Every exercise is a change to `src/tradingresearch/checks.py` (labs w2l1-w2l3) or `src/tradingresearch/evals.py` (lab w2l4), checked by pytest, with an observe command that runs your code on the author's recorded theses. $0: no exercise calls a model.

| Lab | You build | Exercises | What observe shows |
|---|---|---|---|
| [w2l1 P2: is the evidence real](w2l1.md) | `p2_evidence_valid` and `evidence_ok`: the four evidence rules | 4 | `P2: synthetic rows still accepted`: 4 → 3 → 2 → 1 → 0 of 4 |
| [w2l2 P3: can the invalidation be reached](w2l2.md) | `p3_invalidation_testable`: long, short, market_open | 2 | `P3: synthetic rows still accepted`: 3 → 2 → 0 of 3; the real market_open thesis reads `!` (TypeError) after w2l2.1 and 1 after w2l2.2 |
| [w2l3 P4: are stop and target placed against the levels](w2l3.md) | `p4_levels_coherent`: a long's stop and target, the short mirror, then prices compared at cents | 4 | the chapter's six at P4 6/6 on the stub → 5/6 → 4/6 → 4/6 → 2/6, the chapter's figure; `rows where stored and cents differ`: 0 on the stub, then 3, 4, 4, then 0 of 10 |
| [w2l4 Graders and the draft judge](w2l4.md) | `EvidenceValid`, `InvalidationTestable`, `LevelsCoherent` and the draft `P1Judge`, registered in `evals.GRADERS` | 3 | each grader's score on the author's recorded AAPL reply: P2 and P3 1.0, P4 0.0 (`fails: swing`); `p1_judge` cannot grade (a draft) |

**Week 2 starts from the author's code, not yours.** The first `tr lab start w2l1` makes the repo's files equal to the tag `week-2-start` (the author's code at the start of week 2, which includes the author's week-1 solutions) and commits that as `lab: week 2 base (week-2-start)`. Your week-1 commits stay in the history of the `lab` branch; you can start week 2 without finishing week 1. At `week-2-start`, `checks.py` does not exist yet: the w2l1.1 stub creates it.

**Not in these labs.** The rest of the chapter stays in the chapter, because it is prose, review or setup rather than code: §1 (setup and the daily loop), the cents amendment written into the P4 spec `evals/specs/p4_levels_coherent.md` (w2l3.4 adds it to the code only), §3's P1 rubric (`evals/rubrics/p1_thesis_quality.md`), its judge prompt and ADR-003, §4 (reviewing thesis 1 on real output and the CI gate), §5 (pre-registering the teacher bake-off) and §6 (the runbook and the live stream).

**`tests/test_week2.py` is red until the week ends.** It covers all of §2 and §3: 51 tests, 2 passing at `week-2-start`. Each exercise turns some green:

| State | test_week2 passing (of 51) |
|---|---|
| `week-2-start` (no `checks.py`) | 2 |
| w2l1.1 stub | 7 (the stub's `return True` already passes the cases that expect True) |
| after w2l1.1, .2, .3, .4 | 8, 10, 11, 15 |
| w2l2.1 stub | 22 |
| after w2l2.1, w2l2.2 | 24, 30 |
| w2l3.1 stub | 37 |
| after w2l3.1, .2, .3, .4 | 40, 42, 46, 46 (no case in this file sits on a rounding edge) |
| w2l4.1 stub | 46 |
| after w2l4.1, .2, .3 | 47, 49, 50 |

The one still red at the end is `test_the_p1_rubric_has_every_section`: it reads the rubric file you write by hand in §3. `tr lab next` runs the repo suite at the end of each lab and leaves out the tests that lab cannot have turned green yet (`[suite] deselect` and `[labs.<lab>.suite]` in [`lab.toml`](../lab.toml)): after w2l1 P3, P4, the grader registrations and the P1 judge; after w2l2 P4 onwards; after w2l3 the registrations and the judge; after w2l4 only the rubric. Plain `uv run pytest -q` still shows them failing until you write that code, or that rubric.

Commands run from the root of your tradingresearch clone; this week's folder is `labs/w2/`. `tr lab` drives the exercises: `tr lab start w2l1`, then `tr lab verify` until green and `tr lab next`. All commands, and what to do when one refuses: [labs/README.md](../../README.md). Hints unlock after failed runs of `tr lab verify` (hint 1 after 2, hint 2 after 5, the solution after 10 or at once when green; [`lab.toml`](../lab.toml) holds the numbers).

Concepts: [index](concepts.md). Reading: the chapter, [Week 2](https://scout.edgelab.one/learn/ai-engineering/week-2/); the specs the code implements are in the repo: `evals/specs/p2_evidence_valid.md`, `evals/specs/p3_invalidation_testable.md`, `evals/specs/p4_levels_coherent.md` and `evals/specs/p1_judge.md`. How the folder is built and proved: [README](../README.md).
