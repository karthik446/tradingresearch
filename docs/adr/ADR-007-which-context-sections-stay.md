# ADR-007: which SOURCES sections stay in the analysis context

**Status:** proposed, 2026-11-17 (week 5). Pre-registered; the experiment has not run. Every cell below is
"awaiting experiment" until `tr exp run experiments/context-ablation.toml` and `tr exp compare` fill it with the run's
numbers and run id.

**Context.** The analyze-3 SOURCES table has four sections (`masking.SECTIONS`): indicators, levels, EDGAR facts and,
new this week, up to 5 news headlines (`analyze.MAX_HEADLINES`) read from the local news store. Each section costs
input tokens on every call and each is something the model can cite wrongly; headlines are also untrusted text in
the prompt. ADR-005 kept the fixed context over tools; this ADR asks which parts of that context earn their place.
`experiments/context-ablation.toml` runs three fixed arms of analyze-3 on the week-4 sample (10 tickers × sessions
2026-11-12 and 2026-11-13 = 20 ticker-days, clustered by ticker): `full`, `no-headlines` (`drop = ["headlines"]`)
and `no-edgar` (`drop = ["edgar"]`). One dataset serves all three; `masking.Masked` removes the rows from each
request.

What the sample holds before any call (`tr news` for all 20 ticker-days, then the rendered prompts):
- 39 headlines shown over 20 ticker-days; 16 have at least one, 4 have none (UNH 11-12 and 11-13, HD 11-12,
  CAT 11-12). On those 4 the `full` and `no-headlines` requests are byte-identical, so they pair a request with
  itself; on the other 16 the requests differ. `full` and `no-edgar` differ on all 20.
- Headline rows are an estimated 5.1% of the system + user characters on average (6.4% over the 16 days with
  headlines, 12.4% at most, MSFT 11-12); EDGAR rows about 17.6% (15.4% to 18.8%). Estimates from characters, not
  tokens, over a mean prompt of 4,919 characters.

**Pre-registered metrics (fixed before the run).**
- **Primary:** `claims_valid`, the share of an analysis's claims that pass `validate_claims`, per ticker-day, paired
  by item (drop arm minus `full`), clustered by ticker, 95% interval and Wilcoxon p from `tr exp compare`. Not
  `all_claims_valid`: it was 0.100 in both week-4 arms (ADR-005, interval [−0.200, +0.200], McNemar p = 1), a floor
  at which one bad claim zeroes an analysis, so it cannot separate arms. `claims_valid` was 0.798 in both week-4 arms
  with an interval of [−0.083, +0.086] at n = 20 (MDE 0.124), so it has room to move both ways.
- **Guard:** `parsed` must not be lower in a drop arm than in `full`.
- **Reported, not deciding:** `all_claims_valid`; the four `<section>_grounded` graders (`evals/specs/section_grounding.md`;
  a section no claim cites gets no score, so their n differs by arm and they are not paired); input tokens, cost and
  latency per item.

| metric | full | no headlines | no EDGAR |
|---|---|---|---|
| parsed | awaiting experiment | awaiting experiment | awaiting experiment |
| claims_valid (primary) | awaiting experiment | awaiting experiment | awaiting experiment |
| all_claims_valid | awaiting experiment | awaiting experiment | awaiting experiment |
| indicators_grounded | awaiting experiment | awaiting experiment | awaiting experiment |
| levels_grounded | awaiting experiment | awaiting experiment | awaiting experiment |
| edgar_grounded | awaiting experiment | awaiting experiment | awaiting experiment |
| headlines_grounded | awaiting experiment | awaiting experiment | awaiting experiment |
| tokens in, mean | awaiting experiment | awaiting experiment | awaiting experiment |
| cost per item, mean (USD) | awaiting experiment | awaiting experiment | awaiting experiment |

**Decision.** Awaiting experiment. The rule, fixed now, applied to each drop arm against `full`:
- The section **stays** if dropping it lowers `claims_valid` with the whole 95% interval below 0 (a measured loss).
- The section **goes** if the interval is not wholly below 0, the guard holds, and dropping it lowers the mean input
  tokens (a saving with no measured loss).
- Otherwise (the guard fails, or no saving) the section stays.
A section that goes is removed by a new prompt version, not by editing analyze-3 (prompts are immutable).

**Consequences.**
- Whatever the result, n = 20 sees only a moderate loss: week 4's interval half-width on `claims_valid` was about
  0.085, so "no measured loss" is not "no loss", and the decision says so when it is applied.
- The 4 headline-free ticker-days count in the no-headlines comparison as identical requests; they add sampling noise,
  not signal, and pull its mean difference toward 0. The rule above is applied to all 20 as pre-registered; the 16-day
  view may be shown, labelled post hoc.
- If headlines go, analyze-3's news rules and the `tr news` prerequisite leave the default path; if they stay, the
  injection guards of week 7 become required before analyze-3 is the default.

**Gaps.**
- No paid run yet: no numbers, no run id.
- A headline claim passes on its citation alone (`headlines_grounded`); nothing measures whether it says what the
  headline says, so headlines can only look better here, never worse, on faithfulness.
- One model, one prompt, 20 ticker-days over two sessions; a result does not carry to other models, prompts or
  market regimes.
- Indicators and levels are not ablated (the config drops only headlines and EDGAR).
