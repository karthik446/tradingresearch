# Week 2 labs

> *"Educational software. Not investment advice. No orders are placed; trades are hypothetical and settled from historical bars by written rules. Past results, including these, do not predict future results."*

Week 2 of the AI engineering track turns the review of a thesis into code. These labs are the code half of the chapter's §2, [Process versus outcome: P2-P4 as code](https://scout.edgelab.one/learn/ai-engineering/week-2/#2-process-versus-outcome-p2-p4-as-code-2-h-0): 6 exercises in 2 labs, on the `labs` branch of your tradingresearch clone. Every exercise is a change to `src/tradingresearch/checks.py`, checked by pytest, with an observe command that runs your code on the author's recorded theses. $0: no exercise calls a model.

| Lab | You build | Exercises | What observe shows |
|---|---|---|---|
| [w2l1 P2: is the evidence real](w2l1.md) | `p2_evidence_valid` and `evidence_ok`: the four evidence rules | 4 | synthetic theses P2 still accepts: 4 → 3 → 2 → 1 → 0 of the four P2 rows |
| [w2l2 P3: can the invalidation be reached](w2l2.md) | `p3_invalidation_testable`: long, short, market_open | 2 | the P3 rows: 3 → 2 → 0 accepted; the market_open thesis goes from `!` (TypeError) to 1 |

**Week 2 starts from the author's code, not yours.** The first `tr lab start w2l1` makes the repo's files equal to the tag `week-2-start` (the author's code at the start of week 2, which includes the author's week-1 solutions) and commits that as `lab: week 2 base (week-2-start)`. Your week-1 commits stay in the history of the `lab` branch; you can start week 2 without finishing week 1. At `week-2-start`, `checks.py` does not exist yet: the w2l1.1 stub creates it.

**Not in these labs.** The rest of the chapter stays in the chapter: §1 (setup and the daily loop), §2's P4 (levels against the ATR) and the two grader registrations, §3 (the P1 rubric, the draft judge and ADR-003), §4 (reviewing thesis 1 on real output and the CI gate), §5 (pre-registering the teacher bake-off) and §6 (the runbook). A later set of labs covers P4 and the registrations.

**`tests/test_week2.py` is red until the week ends.** It covers all of §2 and §3: 51 tests, 2 passing at `week-2-start`. Each exercise turns some green:

| State | test_week2 passing (of 51) |
|---|---|
| `week-2-start` (no `checks.py`) | 2 |
| w2l1.1 stub | 7 (the stub's `return True` already passes the cases that expect True) |
| after w2l1.1, .2, .3, .4 | 8, 10, 11, 15 |
| w2l2.1 stub | 22 |
| after w2l2.1, w2l2.2 | 24, 30 |

The 21 still red after w2l2 are P4 (`test_p4_levels_coherent`), the grader registrations and §3's P1 rubric and judge. `tr lab next` runs the repo suite at the end of each lab and leaves those tests out (`[suite] deselect` in [`lab.toml`](../lab.toml)); plain `uv run pytest -q` still shows them failing until you write that code from the chapter.

Commands run from the root of your tradingresearch clone; this week's folder is `labs/w2/`. `tr lab` drives the exercises: `tr lab start w2l1`, then `tr lab verify` until green and `tr lab next`. All commands, and what to do when one refuses: [labs/README.md](../../README.md). Hints unlock after failed runs of `tr lab verify` (hint 1 after 2, hint 2 after 5, the solution after 10 or at once when green; [`lab.toml`](../lab.toml) holds the numbers).

Concepts: [index](concepts.md). Reading: the chapter, [Week 2](https://scout.edgelab.one/learn/ai-engineering/week-2/); the specs the checks implement are in the repo, `evals/specs/p2_evidence_valid.md` and `evals/specs/p3_invalidation_testable.md`. How the folder is built and proved: [README](../README.md).
