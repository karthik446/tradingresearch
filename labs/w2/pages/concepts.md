# Concept index (week 2, labs w2l1-w2l4)

One entry per term: what it means, where to read it in the [week 2 chapter](https://scout.edgelab.one/learn/ai-engineering/week-2/), and the exercises that practise it.

| Term | Means | Practised in |
|---|---|---|
| [Process check](#process-check) | a pure function that grades how a thesis was made, not how the trade ended | w2l1.1 to w2l3.3 |
| [Evidence](#evidence) | the claim ids a thesis lists as its support | w2l1.1 to w2l1.4 |
| [Claim tag](#claim-tag) | fact, inference or opinion | w2l1.2, w2l1.3 |
| [Source table](#source-table) | the thesis-stage rows of code-computed values a fact may cite | w2l1.3, w2l1.4 |
| [Tolerance](#tolerance) | how far a fact's number may sit from its source: 0.5%, relative | w2l1.4 |
| [Invalidation](#invalidation) | the price at which the thesis says its idea was wrong | w2l2.1, w2l2.2 |
| [Market_open entry](#market_open-entry) | an entry at the next open, with no price when the thesis is written | w2l2.2 |
| [Level](#level) | a price the market has turned at before: a volume node, a pivot, the 20-day high or low | w2l3.1 to w2l3.4, w2l4.2 |
| [ATR allowance](#atr-allowance) | how far past the next level a target may sit: half the 14-day ATR | w2l3.2 to w2l3.4 |
| [Cents](#cents) | comparing prices rounded to 2 decimals, as the model quotes them | w2l3.4 |
| [Grader](#grader) | a class that scores one whole run of the model, for an experiment to name by id | w2l4.1 to w2l4.3 |
| [Registry](#registry) | `evals.GRADERS`, the table from id to class that `@grader` fills and configs read | w2l4.1 to w2l4.3 |
| [Thesis sample](#thesis-sample) | one recorded reply of the thesis model: its parse status and its parsed theses | w2l4.1, w2l4.2 |
| [Draft judge](#draft-judge) | a model grader that is registered but refuses to score until it is validated | w2l4.3 |

### Process check

A thesis can lose money and still be well made, or win and be badly made. The process checks grade the making: P2 asks whether the evidence is real, P3 whether the invalidation can be reached before the stop, P4 whether the levels are coherent. Each is a pure function on one stored thesis and its analysis, so it is code, not a judge. Read [§2 Process versus outcome](https://scout.edgelab.one/learn/ai-engineering/week-2/#2-process-versus-outcome-p2-p4-as-code-2-h-0); the specs are `evals/specs/p2_evidence_valid.md`, `p3_invalidation_testable.md` and `p4_levels_coherent.md`.

### Evidence

`Thesis.evidence` is a tuple of claim ids from the analysis the thesis was written from. P2 passes only if every id is real and usable: it names a claim of that analysis (rule 1), the claim is not an opinion (rule 2), and a fact's sources and number trace to the table (rules 3 and 4). One bad id fails the thesis.

### Claim tag

Every claim carries `tag`: `fact` (a number or label code computed, cited by source id), `inference` (derived from other claims by `derived_from`), or `opinion` (a view). `tr thesis` only refuses evidence that is all opinion; P2 refuses any opinion. An inference is evidence; its numbers were checked against its parents when the analysis was made, so rules 3 and 4 skip it.

### Source table

The rows the thesis prompt showed, as `{source_id: value}`. A label row such as `regime_spy` holds None and is still in the table. EDGAR rows (earnings, filings) were in the analyze prompt but not in the thesis-stage table, so a fact citing one cannot be traced from the thesis.

### Tolerance

`close_within(a, b, tolerance)`: `|a - b| <= tolerance * max(|a|, |b|)`, with `TOLERANCE = 0.005`, the same 0.5% analyze uses. Relative, so 0.5 on a price of 100 is inside and 0.5 on a price of 10 is not; edge included.

### Invalidation

`Thesis.invalidation_price`: where the idea is wrong. It is testable only if price can reach it before the stop: for a long, at or above the stop and below the entry; for a short, above the entry and at or below the stop. Equal to the stop passes (the stop is the invalidation); equal to the entry fails (it would fire on the fill).

### Market_open entry

`EntryRule(kind="market_open")` buys or sells at the next session's open, so `entry.price` is None when the thesis is written. P3 and P4 use the snapshot's last close as the entry; `entry_price(thesis, reference_close)` in `checks.py` does that for both.

### Level

`Level` in `records.py`: a price, its kind (`hvn` for a high-volume node, `pivot_high`, `pivot_low`, `high_20`, `low_20`), a strength and its distance in ATRs. analyze stores the levels as computed (hvn 343.40978) and in no particular price order. P4 asks for a stop beyond the nearest level against the trade (for a long, strictly below the highest level under the entry) and a target at or before the next level with the trade. A level exactly at the entry is on neither side; a side with no level holds. Spec: `evals/specs/p4_levels_coherent.md`.

### ATR allowance

The ATR (average true range, 14 sessions: the snapshot's `atr_14`) is how far price typically moves in a session. P4 lets a target sit past the next level by `TARGET_ALLOWANCE_ATR * atr14`, with `TARGET_ALLOWANCE_ATR = 0.5`; reaching the limit exactly passes. The ATR in price units, not `atr_pct`, which is the ATR as a percent of the close. The allowance is not rounded to cents.

### Cents

The model quotes prices in cents (entry 343.41); analyze stores levels unrounded (hvn 343.40978). Compared raw, that level sits a fraction of a cent under the entry and becomes the stop's floor; at cents it is the entry and counts on neither side. The spec's amendment, part of `week-2-end`: `checks.cents(price)` is `round(price, 2)`, applied to the entry, the stop, the target and every level before P4 compares them. It moves four of the chapter's six theses, which is why the chapter's table has P4 2/6. Read the trap *Floats against cents* in [§2](https://scout.edgelab.one/learn/ai-engineering/week-2/#2-process-versus-outcome-p2-p4-as-code-2-h-0).

### Grader

A check answers for one thesis; a grader answers for one sample, the model's whole reply for one ticker and day. A grader is a class with `id`, `version` (a string, stored beside every score so scores from a changed rule are never compared with old ones) and `kind` (`"code"` when a rule decides, `"model"` when a model does), and a `grade(sample, expected)` that returns a `Score`. P2-P4 score 1.0 only if every thesis in the run passes, else 0.0 with `fails: ` and the failing horizons. A run with nothing to check raises `CannotGrade` and is left out of the rate instead of counted as 0.

### Registry

`evals.GRADERS` maps each grader id to its class. The `@grader` decorator is the only way in, and it raises `ValueError` ("already registered") for a second class with an id it holds, so one grader can never silently replace another. An experiment config names graders by id, and `evals.graders(names)` builds them from the registry. A class without `@grader` exists, but no config can use it.

### Thesis sample

What an eval run hands a grader: one recorded reply of the thesis model, with its `parse_status` (`"ok"`, or why it did not parse) and `output_parsed`, the theses and no-trade items; `expected` carries the analysis the reply was written from. `built_theses(sample, expected)` in `evals.py` rebuilds that analysis and the items that build into a `Thesis`; an item that does not build is counted by `theses_valid`, not by P2-P4. The labs use the author's recorded AAPL reply in `tests/fixtures/thesis`.

### Draft judge

P1, whether the mechanism in a thesis's `reason` happened, needs a model as judge. A judge counts only once its verdicts agree with blind human labels on closed trades (Cohen's kappa ≥ 0.6 on 30 labels, by ADR-003), and labelling starts in week 3. Until then `p1_judge` is registered with `kind = "model"` and `validated = False`, and its `grade` raises `CannotGrade` before anything else: no model call, no cost, no score anyone could count. Read [§3](https://scout.edgelab.one/learn/ai-engineering/week-2/#3-p1-a-rubric-a-draft-judge-and-adr-003-15-h-0); the spec is `evals/specs/p1_judge.md`.
