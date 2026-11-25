# Week 5 labs

> *"Educational software. Not investment advice. No orders are placed; trades are hypothetical and settled from historical bars by written rules. Past results, including these, do not predict future results."*

Week 5 of the AI engineering track asks which parts of the analysis context earn their place. These labs are the code half of the chapter's [§4 Per-section grounding graders](https://scout.edgelab.one/learn/ai-engineering/week-5/#4-per-section-grounding-graders-15-h-0), the config and the compare of [§5 The ablation](https://scout.edgelab.one/learn/ai-engineering/week-5/#5-the-ablation-pre-register-run-once-compare-adr-007-25-h-099-at-the-authors-run), and the training split of [§8](https://scout.edgelab.one/learn/ai-engineering/week-5/#8-a-training-split-with-an-embargo-and-claim-labels-1-h-0): a grader per section of the context, the three-arm experiment that drops one section at a time with its rule written before the run, a compare that skips a grader it cannot pair and says why, and a held-out later period registered before it starts.

| Lab | You build | Exercises | What observe shows |
|---|---|---|---|
| [w5l1 Per-section grounding graders](w5l1.md) | `SectionGrounded` and the four `<section>_grounded` code graders in `evals.py` | 3 | every section `NotImplementedError` → the recorded reply's indicators 0.857 and headlines 1.000; `ZeroDivisionError` where nothing is cited → `CannotGrade: not_cited`; no section grader registered → four, and the headline claim failing `dropped_source` in the no-headlines arm |
| [w5l2 The ablation config](w5l2.md) | `experiments/context-ablation.toml`: three drop arms, seven code graders, the cluster, the pre-registration | 3 | the load refused (no arms) → 3 arms and a 30-request $0 replay; graders `['parsed']` → seven, `claims_valid` 0.909 in full and 0.818 in no-headlines; pre-registration lines `(none)` → the primary metric, the guard and the rule |
| [w5l3 Compare skips a grader](w5l3.md) | `experiment.compare`: the graders both runs scored on a common item, a skipped line for each other one, `no_shared_metric` when none is left | 2 | `compare raised NotImplementedError` → the chapter's two blocks, `skipped headlines_grounded: not scored in both arms`; then the counts, `(n=16 vs 0)`, and a refusal that names every skipped grader |
| [w5l4 A training split with an embargo](w5l4.md) | the 22-session embargo floor in `records.py`; `split.register`, content-addressed and refused before the cutoff opens; the embargo window and the derived sets | 4 | `MIN_EMBARGO: '(missing)'` → 22 and its reason; `register raised NotImplementedError` → `sp_511d03d559bae169`, stored once; Thanksgiving stored → refused; `embargo_window raised NotImplementedError` → 22 sessions, 2026-11-25 to 2026-12-28, and the sets |

**Week 5 starts from the author's code, not yours.** The first `tr lab start w5l1` makes the repo's files equal to the tag `week-5-start` (the author's code at the start of week 5, which includes the author's solutions to weeks 1 to 4) and commits that as `lab: week 5 base (week-5-start)`. Your earlier commits stay in the history of `lab`. The masking that drop arms use (§2) and analyze-3 with headlines (§3) are shipped in that base; these labs build on them.

**Nothing here calls a model.** Every check and every observe run replays one recorded exchange or the author's stored scores, for $0. The ablation itself was run once, by the author, on 2026-11-17: $0.989286 for three arms over 20 ticker-days. It is never run in these labs; lab w5l3 compares its stored scores, rebuilt from [`data/ablation.runs.json`](../data/ablation.runs.json).

**Not in these labs.** The rest of the chapter stays in the chapter:

- [§1](https://scout.edgelab.one/learn/ai-engineering/week-5/#1-setup-and-a-tour-of-the-shipped-code-1-h-0): setup and the tour of the shipped code; [§2](https://scout.edgelab.one/learn/ai-engineering/week-5/#2-the-drop-knob-an-ablation-in-the-config-1-h-0-shipped) and [§3](https://scout.edgelab.one/learn/ai-engineering/week-5/#3-headlines-in-analyze-3-untrusted-text-in-the-prompt-1-h-0-shipped), the drop knob and headlines in analyze-3, both shipped in the base.
- §5's paid run, and ADR-007, written by hand from the measured table. Lab w5l2 builds the config the run read, and lab w5l3 the compare it forced.
- [§6](https://scout.edgelab.one/learn/ai-engineering/week-5/#6-the-playbook-in-thesis-2-05-h-0-shipped), the playbook in thesis-2 (shipped), and [§7](https://scout.edgelab.one/learn/ai-engineering/week-5/#7-adr-008-an-mcp-gateway-and-registry-design-only-15-h-0), ADR-008, a design with no code.
- [§8](https://scout.edgelab.one/learn/ai-engineering/week-5/#8-a-training-split-with-an-embargo-and-claim-labels-1-h-0)'s claim labels (`tr label --claims`): labelling is a human task. Lab w5l4 builds the training split.
- [§9](https://scout.edgelab.one/learn/ai-engineering/week-5/#9-the-live-stream-what-week-5-changed-and-what-waits-05-h-0-now) and [§10](https://scout.edgelab.one/learn/ai-engineering/week-5/#10-adr-007-in-review-and-what-week-6-does-with-it-05-h-0): the live stream and ADR-007 in review.
- `docs/measured-costs.md`, `docs/runbook.md`, `evals/specs/section_grounding.md` and `tests/test_section_grounding.py`, which change at `week-5-end` but no exercise writes. The measured costs are in [Week 5 cash](https://scout.edgelab.one/learn/ai-engineering/week-5/#week-5-cash-as-measured-by-the-author). The reference's `tests/test_experiment_compare.py` and `tests/test_split.py` are not shipped, since they would show the answers; the w5l3 and w5l4 pages say how to run them once a lab is green.

**`tests/test_week5.py` is red until the week ends.** It covers the whole chapter: 15 cases, 0 passing at `week-5-start` (there is no section grader).

| State | test_week5 passing (of 15) |
|---|---|
| `week-5-start` | 0 |
| the w5l1.1 stub | 0 |
| after w5l1.1, .2, .3 | 0, 0, 10 (the grader cases look the graders up in the registry, which w5l1.3 fills) |
| after w5l2.1, .2, .3 | 11 (the replay of what each arm sends), 13 (the config and the graded replay), 13 |
| after w5l3, after w5l4 | 13, 13 (neither lab has a case in it) |

The 2 still red at the end are ADR-007 and ADR-008, written by hand. `tr lab next` runs the repo suite at the end of each lab and leaves out the tests that lab cannot turn green yet: those 2 always (`[suite] deselect` in [`lab.toml`](../lab.toml)), plus the three ablation-config cases after lab w5l1. At the end of w5l4 the suite is 664 passed with those 2 deselected.

Commands run from the root of your tradingresearch clone; this week's folder is `labs/w5/`. `tr lab` drives the exercises: `tr lab start w5l1`, then `tr lab verify` until green and `tr lab next`. All commands, and what to do when one refuses: [labs/README.md](../../README.md). Hints unlock after failed runs (2, then 5), the solution after 10 or as soon as the check is green.

The start of the week, run for real: the [walked-through session](../session/session.toml), with what each command printed in [`session/`](../session/).

Concepts: [index](concepts.md). Reading: the chapter, [Week 5](https://scout.edgelab.one/learn/ai-engineering/week-5/). How the folder is built and proved: [README](../README.md).
