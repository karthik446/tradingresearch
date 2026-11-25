# Concept index (week 5, labs w5l1-w5l2)

One entry per term: what it means, where to read it in the [week 5 chapter](https://scout.edgelab.one/learn/ai-engineering/week-5/), and the exercises that practise it.

| Term | Means | Practised in |
|---|---|---|
| [Section grounding](#section-grounding) | per part of the context, the share of the claims citing it that the validator keeps | w5l1.1 |
| [Cites a section](#cites-a-section) | one of a claim's own `source_ids` is a row `masking.section_of` puts in that section | w5l1.1 |
| [Not cited](#not-cited) | a section no claim cites gets no score, `CannotGrade("not_cited: ...")`, never 1.0 | w5l1.2 |
| [Cannot grade](#cannot-grade) | a grader that has nothing to grade raises `CannotGrade`: the sample gets no score, and the run goes on | w5l1.2 |
| [Drop arm](#drop-arm) | an arm that never shows the model some sections; a claim citing a row it never saw fails | w5l1.3, w5l2.1 |
| [Ablation](#ablation) | arms that differ in one removed part only, so a change in the result belongs to that part | w5l2.1 |
| [Code graders](#code-graders) | graders that are plain code, the only kind a drop arm is graded by | w5l2.2 |
| [Cluster](#cluster) | the unit a paired interval resamples; here the ticker | w5l2.2 |
| [Pre-registration](#pre-registration) | the metrics and the decision rule of an experiment, written before any paid run | w5l2.3 |
| [Primary and guard metric](#primary-and-guard-metric) | the one metric that decides, and the one that must not get worse | w5l2.3 |

### Section grounding

A whole-analysis score says how many claims hold up, not which source the bad ones leaned on. Section grounding scores each part of the context on its own: indicators, levels, EDGAR rows, headlines. The score is kept ÷ citing, with `validate_claims` run once on the whole reply, so a claim keeps the verdict it gets everywhere else. On the recorded reply: indicators 6 of 7 (0.857), headlines 1 of 1. Read [§4 Per-section grounding graders](https://scout.edgelab.one/learn/ai-engineering/week-5/#4-per-section-grounding-graders-15-h-0).

### Cites a section

Only a claim's own `source_ids` cite. A source id names a row of the context, and `masking.section_of` maps the row's table name to its section; an id that names no row cites nothing, and a claim reached only through another claim's `derived_from` counts in no section (`inferences_grounded` covers the chain). A claim citing a close and a level counts once in indicators and once in levels. Read [§4](https://scout.edgelab.one/learn/ai-engineering/week-5/#4-per-section-grounding-graders-15-h-0).

### Not cited

A section no claim cites has no share: 0 ÷ 0. Scoring it 1.0 would count silence as success in every mean, and scoring it 0.0 would punish a reply that had no reason to cite it. So it raises `CannotGrade("not_cited: no claim cites a <section> row")` and stores nothing. The cost: each section grader has its own n, and in a drop arm the dropped section is scored on 0 items, which is what made the author's first `compare` refuse. Read [§4](https://scout.edgelab.one/learn/ai-engineering/week-5/#4-per-section-grounding-graders-15-h-0) and [§5](https://scout.edgelab.one/learn/ai-engineering/week-5/#5-the-ablation-pre-register-run-once-compare-adr-007-25-h-099-at-the-authors-run).

### Cannot grade

`CannotGrade` is the grader's way to say "no score here" without failing the run: core `run` skips the score and goes on, while any other exception is a bug and stops it. A reply that did not parse cannot be graded at all, whatever it holds, and its reason differs from `not_cited`, so a reader can tell the two apart. Read [§4](https://scout.edgelab.one/learn/ai-engineering/week-5/#4-per-section-grounding-graders-15-h-0).

### Drop arm

An experiment arm with a `drop` list masks those sections out of the analysis prompt (§2's knob). A claim citing a row the arm never saw cannot be grounded in what the model was shown, so the validator rejects it (`dropped_source`) once the grader passes it the hidden rows; `evals.graders(names, drop)` builds each grader with its arm's drop. On the recorded reply in no-headlines, the one headline claim fails: headlines 0.000. Read [§2 The drop knob](https://scout.edgelab.one/learn/ai-engineering/week-5/#2-the-drop-knob-an-ablation-in-the-config-1-h-0-shipped).

### Ablation

Remove one part, keep the rest, and see what the result loses. Here the part is a section of the context: three analyze-3 arms on one model, `full`, `no-headlines` and `no-edgar`, that differ only in their drop list, so each request differs from `full`'s only by the masked rows, and so does its token count. The author's run measured headlines at 4.69% of the input and EDGAR at 17.96%. Read [§5 The ablation](https://scout.edgelab.one/learn/ai-engineering/week-5/#5-the-ablation-pre-register-run-once-compare-adr-007-25-h-099-at-the-authors-run).

### Code graders

A grader whose verdict is plain code over the reply and the context rows, `kind = "code"`. The ablation is read with seven: `parsed`, `claims_valid`, `all_claims_valid` and the four section graders. A model grader on a drop arm would judge a reply against rows the model never saw, so `run_arms` refuses one beside a drop arm, before its first call. Read [§5](https://scout.edgelab.one/learn/ai-engineering/week-5/#5-the-ablation-pre-register-run-once-compare-adr-007-25-h-099-at-the-authors-run).

### Cluster

`compare` pairs each item across two arms and builds the interval of the difference by resampling. Items that share a ticker are not independent, so it resamples whole tickers: 10 clusters for 20 ticker-days. The loader picks the ticker when the file says nothing; writing it out makes the interval's unit visible to anyone reading the config. Read [§5](https://scout.edgelab.one/learn/ai-engineering/week-5/#5-the-ablation-pre-register-run-once-compare-adr-007-25-h-099-at-the-authors-run).

### Pre-registration

What will be measured and what each result means, fixed before the result exists, so the result cannot pick its own reading. In the config's header, above the first key: a primary metric, a guard metric and a rule. The author's rule could only say "go" when nothing is seen, since it has no non-inferiority margin; ADR-007 says so, and a drop needs a new pre-registration with a margin before it is adopted. Read [§5](https://scout.edgelab.one/learn/ai-engineering/week-5/#5-the-ablation-pre-register-run-once-compare-adr-007-25-h-099-at-the-authors-run) and [§10](https://scout.edgelab.one/learn/ai-engineering/week-5/#10-adr-007-in-review-and-what-week-6-does-with-it-05-h-0).

### Primary and guard metric

The primary metric decides; the guard only vetoes. `claims_valid` is primary because it has room on both sides (0.798 in week 4), where `all_claims_valid` sat at 0.100 in both week-4 arms, a floor at which one bad claim zeroes an analysis. `parsed` is the guard: a drop must not cost replies that parse. Every other grader is reported, and decides nothing, however it moves. Read [§5](https://scout.edgelab.one/learn/ai-engineering/week-5/#5-the-ablation-pre-register-run-once-compare-adr-007-25-h-099-at-the-authors-run).
