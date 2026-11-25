# Concept index (week 5, labs w5l1-w5l4)

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
| [Skipped grader](#skipped-grader) | a grader asked that two runs cannot be compared on, left out with a line that says why and how many items each run scored | w5l3.1, w5l3.2 |
| [No shared metric](#no-shared-metric) | no grader asked is scored on a common item in both runs, so `compare` refuses and names every grader it left out | w5l3.1, w5l3.2 |
| [Embargo floor](#embargo-floor) | the shortest embargo that keeps every train/val outcome before the cutoff: entry window 2 + longest hold 20 = 22 sessions | w5l4.1 |
| [Content-addressed split](#content-addressed-split) | a split's id is a digest of the cutoff, the embargo and the pre-registration, so the same split is stored once | w5l4.2 |
| [Registered before the cutoff](#registered-before-the-cutoff) | a split is written down before its test period starts, or refused without a row | w5l4.2, w5l4.3 |
| [Embargo window](#embargo-window) | the embargo's NYSE sessions right before the cutoff session, in neither set | w5l4.4 |
| [Derived sets](#derived-sets) | train/val, embargoed and test, computed from the journal's sessions when read, never stored | w5l4.4 |

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

### Skipped grader

Core `compare` refuses the whole comparison over one grader it cannot pair: one run never scored it (`metric_missing`), or the two runs scored it on no common item (`no_paired_items`). A drop arm never cites its dropped section, so the author's first compare refused every block. `experiment.compare` keeps each grader both runs scored on at least one common item, in the order asked, and leaves out the rest with a line such as `edgar_grounded: not scored in both arms (n=6 vs 0)` or `levels_grounded: no item scored in both arms (n=1 vs 3)`. A grader left out without a line would read like one that showed no difference. Read [§5](https://scout.edgelab.one/learn/ai-engineering/week-5/#5-the-ablation-pre-register-run-once-compare-adr-007-25-h-099-at-the-authors-run).

### No shared metric

With no grader left there is nothing to compare, and `compare` refuses as core refuses: `no_shared_metric`, `cannot compare: no grader is scored on a common item in both runs`, followed by every skipped line, so a reader sees why nothing was compared. Full against no-edgar on `edgar_grounded` and `levels_grounded` alone is the author's case. Read [§5](https://scout.edgelab.one/learn/ai-engineering/week-5/#5-the-ablation-pre-register-run-once-compare-adr-007-25-h-099-at-the-authors-run).

### Embargo floor

A swing thesis written after session S enters on one of the next 2 sessions and exits at most 20 sessions after its entry, so its outcome reads bars up to S + 22. With an embargo of 22 sessions, the last train/val session's latest exit is the session before the cutoff; with 20, the longest hold alone, it is one session into the test period, the trap the chapter found. `records.py` derives `MIN_EMBARGO` from `HOLD_RANGE`, and a `TrainingSplit` under it is refused with the reason, `entry window 2 + longest hold 20`. Read [§8](https://scout.edgelab.one/learn/ai-engineering/week-5/#8-a-training-split-with-an-embargo-and-claim-labels-1-h-0).

### Content-addressed split

`split_id` is `sp_` plus the first 16 hex digits of a digest of the cutoff, the embargo and the pre-registration without its `registered_at`. Asking for the same split again returns the stored one and writes nothing; a different embargo, cutoff or rule is a different split. `registered_at` says when a split was written, not which split it is, so it stays out of the digest. Read [§8](https://scout.edgelab.one/learn/ai-engineering/week-5/#8-a-training-split-with-an-embargo-and-claim-labels-1-h-0).

### Registered before the cutoff

A held-out period only holds out if it is written down before it starts. `register` stores the split at the time it is called, in New York time, and refuses, before it writes a row: an embargo under the floor, a cutoff that is not an NYSE session, one not after the last completed session, and one whose session opens no later than now or than the pre-registration's own `registered_at`. The open question stays open: a later split can still be registered after a cutoff opens and quietly govern. Read [§8](https://scout.edgelab.one/learn/ai-engineering/week-5/#8-a-training-split-with-an-embargo-and-claim-labels-1-h-0).

### Embargo window

The `embargo_sessions` NYSE sessions right before the cutoff session, oldest first. Holidays are not sessions: 22 sessions before 2026-12-29 skip Thanksgiving and Christmas and reach back to 2026-11-25. The window comes from the calendar, not from the journal, so it is the same whatever was analysed. Read [§8](https://scout.edgelab.one/learn/ai-engineering/week-5/#8-a-training-split-with-an-embargo-and-claim-labels-1-h-0).

### Derived sets

A split stores its cutoff and embargo, never its sessions. The sets are derived when read from the journal's analysis sessions: each distinct day once, oldest first, train/val before the window, embargoed from the window's first session up to the cutoff, test on or after the cutoff. A set no day falls in is empty. Read [§8](https://scout.edgelab.one/learn/ai-engineering/week-5/#8-a-training-split-with-an-embargo-and-claim-labels-1-h-0).
