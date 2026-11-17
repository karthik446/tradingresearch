# Scope: tradingresearch (one page)

**User.** One person who wants a short, checkable read of a US large-cap stock after the close: what the price,
trend, levels and latest filings say, each statement traceable to a number computed by code.

**Job.** `tr analyze TICKER --session DATE` returns 6 to 12 claims. Facts restate a source; inferences cite earlier
claims; opinions are marked as opinions. Code rejects any claim it cannot trace.

**In scope.** S&P 100 stocks, a shortlist of 10 for experiments (AAPL MSFT NVDA AMZN JPM XOM UNH HD KO CAT). Daily
bars from Alpaca's free tier, SEC EDGAR facts, completed NYSE sessions only. Live data. Model calls via OpenRouter,
spend logged with `tr usage`.

**Out of scope.** Orders, paper trading, signals, price targets and backtests as evidence. Intraday analysis. News.
Any statement that reads as advice: the output is educational research.

**Quality bar (measured, not hoped).** `parsed` = 1.0; `all_claims_valid` and `inferences_grounded` reported with a
paired interval against the current prompt before any change ships (week 1 baseline: 0.20 and 0.25).

**Cost bar.** About $0.017 per analysis on the default model (observe run: $0.3468 for 20). A week of experiments
stays under $2.00.

**Who decides.** Prompt and grader changes ship through an experiment config and an ADR, never by eyeballing one run.
