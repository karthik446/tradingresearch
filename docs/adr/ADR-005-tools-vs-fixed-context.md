# ADR-005: analyze keeps the fixed context; tools mode stays an experiment arm

**Status:** accepted, 2026-11-17 (week 4). Decided by the pre-registered metrics of one run of
`experiments/tools-vs-fixed.toml`.

**Context.** Week 4 added a second way to hand an analysis its data. In the *fixed* mode (weeks 1-3) the user turn
holds the SOURCES table up front. In the *tools* mode (`analyze.analyze_with_tools`, `tools.py`) the user turn names
only the ticker and the session, and the model asks for rows with three tools, `get_indicators`, `get_levels` and
`get_fundamentals`, which serve the same Context rows on request (`tools.py` module docstring). The loop allows
`MAX_TOOL_TURNS` = 5 model calls per item (`analyze.py`). The question: does a model that asks for its rows write more
valid claims than one that is handed them?

**Pre-registered before the run** (the comment in `experiments/tools-vs-fixed.toml`): primary metric
`all_claims_valid`; guard metric `parsed` must not drop. Both arms use prompt analyze-1 on
`anthropic/claude-sonnet-5.5`, no provider pin, a $1.00 cap per arm, the same 20 ticker-days (10 tickers ×
2026-11-12, 2026-11-13), paired by item and clustered by ticker (10 clusters).

**Result.** One run, `TR_DATA_DIR=$PWD/data-dev uv run tr exp run experiments/tools-vs-fixed.toml` on 2026-11-17:
fixed `run_a24247c2a8b54462`, tools `run_e80dcfcca6294408`. Means are per ticker-day (n = 20 per arm).

| Metric | fixed | tools |
|---|---|---|
| all_claims_valid | 0.100 | 0.100 |
| parsed | 1.000 | 1.000 |
| claims_valid | 0.798 | 0.798 |
| inferences_grounded | 0.200 | 0.250 |
| tool_calls_ok | 1.000 | 1.000 |
| failed items | 0 | 0 |
| tokens in, mean | 2,537.7 | 7,054.1 |
| tokens out, mean | 1,189.25 | 1,282.35 |
| cost, mean | $0.016968 | $0.026932 |
| cost, arm total | $0.339358 | $0.538634 |
| latency, mean | 8,344.5 ms | 10,929.15 ms |
| model calls, mean | 1 | 2.05 |
| tool calls, mean | 0 | 3.05 |

Where each number comes from:
- Grader means and failed items: the two `arm` lines `tr exp run` printed (`failed=0`, `all_claims_valid=0.100
  (n=20)` and so on), which `experiment.means` reads from the run files `data-dev/runs/<run_id>.jsonl`.
- Tokens and cost: `tr usage` on `data-dev`, run_a24247c2a8b54462 20 calls, 50,754 in, 23,785 out, $0.339358;
  run_e80dcfcca6294408 41 calls, 141,082 in, 25,647 out, $0.538634; each divided by 20 items.
- Latency: per item, the sum of its model calls' `latency_ms` in `data-dev/traces/<run_id>.jsonl` (the tools ran in
  process, 0 ms each), then the mean over 20 items. `tr usage --by arm` prints the mean per *call* instead: 8,344 ms
  fixed, 5,331 ms tools; 5,331.29 × 41 ÷ 20 = 10,929.15.
- Model and tool calls: the trace's `model_call` and `tool_call` spans, grouped by the item of their trial span.

The paired comparison, as `tr exp run` printed it (gigai-core `compare`, intervals resampled over the 10 tickers):

| Metric | Difference (tools − fixed) | 95% interval | Test |
|---|---|---|---|
| all_claims_valid | +0.000 | [−0.200, +0.200] | McNemar p = 1 |
| parsed | +0.000 | [+0.000, +0.000] | McNemar p = 1 |
| claims_valid | −0.000 | [−0.083, +0.086] | Wilcoxon p = 0.739, MDE 0.124 |
| inferences_grounded | +0.050 | [−0.200, +0.250] | McNemar p = 1 |
| tool_calls_ok | +0.000 | [+0.000, +0.000] | McNemar p = 1 |

What the tools arm did, from its trace: in 19 of 20 items the model made one round of three calls, every tool with
the arguments `{}` (every row), then answered: 2 model calls, 3 tool calls. AAPL:2026-11-12 made a second round,
`get_indicators` with `{"names": ["close"]}`: 3 model calls, 4 tool calls, $0.035774, the arm's most expensive item.
No item made 0 tool calls, none hit the 5-call limit, no tool call erred, none repeated, none went over
`tool_calls_ok`'s limit of 6. Input tokens are 2.78 times the fixed arm's because each call re-sends the
conversation: the first call (system, tool schemas, the short user turn) is 2,137-2,139 tokens and the answering call,
carrying the tool results, 4,480-4,885.

The route finding of the week: the turns of one tool loop can be served by different providers, and the route used to
record only one of them; `provider_route` is now `openrouter:mixed(...)` for such an exchange, and a record marked
trainable refuses it (`records._trainable_route`). In this run 12 of the 20 tools items were mixed (4
Anthropic+Azure, 4 Anthropic+Google, 4 Azure+Google; `analysis.provider_route` in the data-dev journal), 8 had one
route; the fixed arm, one call per item, had none mixed.

**Decision.**
- **No difference at n=20 ticker-days.** The primary metric moved +0.000 (95% interval −0.200 to +0.200, McNemar
  p = 1) and the guard held (`parsed` 1.000 in both arms). With no gain on the primary metric, tools mode is not
  adopted: `tr analyze` and `tr daily` keep the fixed context (`analyze_with_tools` is called only from
  `experiment.run_tools`).
- **Tools mode stays as an experiment arm** (`mode = "tools"`), for a later config with its own pre-registration.
- Cost and latency were not pre-registered and do not decide; they point the same way: tools cost 1.59 times as much
  per item ($0.026932 ÷ $0.016968 = 1.587) and take 1.31 times as long (10,929.15 ÷ 8,344.5 = 1.310).

**Gaps (known limits of this run).**
- A failed item gets no grade, so it is invisible to every metric, the `parsed` guard included. Here no item failed in
  either arm and both arms graded all 20, so the guard was read on 20 items per arm and none was dropped. The config
  states no rule for failed items; a run with failures would need one.
- `tool_calls_ok` scores a sample with no tool calls 1.0 (`evals.py`, `ToolCallsOk.grade`), so the fixed arm's 1.000
  holds by construction. In the tools arm no item made 0 tool calls, so its 1.000 is earned.
- Small n: 20 items in 10 clusters give an interval of ±0.200 on the primary metric, so the run could see only a
  large effect. "No difference" means none was seen, not that none exists. `compare` prints no MDE for the McNemar
  metrics.
- The model fetched every row in 19 of 20 items, so the run tested the same rows delivered in a second turn, not
  selective retrieval. [INFERENCE] With a context this small (2,537.7 input tokens mean in the fixed arm), asking
  saves nothing; a larger context (headlines, filings) is where the modes could differ. That is not measured.
- One prompt (analyze-1, `DEFAULT_PROMPT` in `analyze.py`), one model, one run.

**Consequences.**
- An analysis keeps costing one call. [INFERENCE] At the decided shortlist of 10, the fixed context saves
  10 × ($0.026932 − $0.016968) = $0.09964 per `tr daily` run of analyses, arithmetic on this run's means.
- Mixed routes are the normal case in a tool loop (12 of 20 here). A tools-mode record bound for training is refused
  unless its arm pins one provider (the `provider` table, `Routing`), so a tools teacher arm needs that pin.
- Asking whether tools help again needs a new config with a larger context and a rule for failed items, registered
  before its run.
