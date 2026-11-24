# Concept index (week 2, labs w2l1-w2l2)

One entry per term: what it means, where to read it in the [week 2 chapter](https://scout.edgelab.one/learn/ai-engineering/week-2/), and the exercises that practise it.

| Term | Means | Practised in |
|---|---|---|
| [Process check](#process-check) | a pure function that grades how a thesis was made, not how the trade ended | w2l1.1 to w2l2.2 |
| [Evidence](#evidence) | the claim ids a thesis lists as its support | w2l1.1 to w2l1.4 |
| [Claim tag](#claim-tag) | fact, inference or opinion | w2l1.2, w2l1.3 |
| [Source table](#source-table) | the thesis-stage rows of code-computed values a fact may cite | w2l1.3, w2l1.4 |
| [Tolerance](#tolerance) | how far a fact's number may sit from its source: 0.5%, relative | w2l1.4 |
| [Invalidation](#invalidation) | the price at which the thesis says its idea was wrong | w2l2.1, w2l2.2 |
| [Market_open entry](#market_open-entry) | an entry at the next open, with no price when the thesis is written | w2l2.2 |

### Process check

A thesis can lose money and still be well made, or win and be badly made. The process checks grade the making: P2 asks whether the evidence is real, P3 whether the invalidation can be reached before the stop, P4 whether the levels are coherent. Each is a pure function on one stored thesis and its analysis, so it is code, not a judge. Read [§2 Process versus outcome](https://scout.edgelab.one/learn/ai-engineering/week-2/#2-process-versus-outcome-p2-p4-as-code-2-h-0); the specs are `evals/specs/p2_evidence_valid.md` and `p3_invalidation_testable.md`.

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
