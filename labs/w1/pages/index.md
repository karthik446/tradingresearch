# Week 1 labs

> *"Educational software. Not investment advice. No orders are placed; trades are hypothetical and settled from historical bars by written rules. Past results, including these, do not predict future results."*

Week 1 of the AI engineering track as 19 exercises in 4 labs, on the `labs` branch of your tradingresearch clone (code at `week-1-start`). Every exercise is a change to a file in the repo, checked by pytest, with an observe command that shows a number move. $0: no exercise calls a model; the paid runs are replaced by the author's recordings in [`data/`](../data/observe.jsonl).

| Lab | You build | Exercises | The number that moves |
|---|---|---|---|
| [w1l1 claim checks](w1l1.md) | `check_one` in `analyze.py`: the code that rejects a bad claim | 4 | claims rejected on the observe run, yours vs the recording |
| [w1l2 open and axial coding](w1l2.md) | `evals/labels.csv`, `evals/taxonomy.md`, and the code that reads them in `taxonomy.py` | 4 | notes read per analysis, analyses per failure class, rows left to back-fill |
| [w1l3 a code grader](w1l3.md) | `InferencesGrounded` in `evals.py` | 6 | analyses flagged of 20: 0 → 19 → 17 → 15 |
| [w1l4 a paired experiment](w1l4.md) | `analyze-2.txt`, `prompt-v2.toml`, the replay that reads them in `replay.py`, and `paired.py` | 5 | rules aimed at the failure classes, the replayed arm table, then all_claims_valid diff +0.700, CI [+0.450, +0.950], decision: ship |

Each lab starts where the previous one ended. After w1l4.5 the six implementation and exercise-data files the author changed in week 1 (`analyze.py`, `evals.py`, `evals/labels.csv`, `evals/taxonomy.md`, `prompts/analyze-2.txt`, `experiments/prompt-v2.toml`) are byte-identical to `week-1-end`: see [PROOF](../PROOF.md#end-state). The other six paths of that diff are not rebuilt: the four documents (`docs/adr/ADR-001-claim-checks.md`, `docs/adr/ADR-002-prompt-analyze-2.md`, `docs/fine-tuning.md`, `docs/scope.md`) and the spec `evals/specs/inferences_grounded.md` are reading, and `tests/test_evals.py` is the author's test, which passes on the rebuilt files. The labs also add three modules `week-1-end` does not have: `taxonomy.py` (w1l2.1 to w1l2.4), `replay.py` (w1l4.1 and w1l4.2) and `paired.py` (w1l4.3 to w1l4.5). Every step is code you write: the notes, the prompt and the config you edit are read by that code, and the observe command shows the result.

Commands run from the root of your tradingresearch clone; this week's folder is `labs/w1/`. `tr lab` drives the exercises: `tr lab start w1l1`, then `tr lab verify` until green and `tr lab next`. All commands, and what to do when one refuses: [labs/README.md](../../README.md).

**How an exercise works** (details on [lab w1l1](w1l1.md#lab-w1l1-claim-checks)): read the concept, open the file at its `TODO(<id>)`, run `tr lab verify` until it is green (it runs the check, then observe to show the effect), then `tr lab next`. Hints and the solution unlock after failed runs of `tr lab verify`. The defaults are hint 1 after 2, hint 2 after 5 and the solution after 10, or at once when the check is green; [`lab.toml`](../lab.toml) holds the numbers.

Concepts: [index](concepts.md). Reading: the chapter, [Week 1: error analysis and evals](https://scout.edgelab.one/learn/ai-engineering/week-1/); the pages link its sections §1-§7, and the check messages cite them as `week-1.md §N`. How to run and prove the folder: [README](../README.md).
