# ADR-004: what never goes into a trace

**Status:** accepted, 2026-11-17 (week 3). Keys are kept out by code; fetched content is kept out of git by
`.gitignore` only. What the code does not enforce is listed under Gaps.

**Context.** A *trace* is one record per model call, a *span*, holding the model, tokens, latency, cost and outcome
(the OpenTelemetry GenAI conventions name the same fields: https://github.com/open-telemetry/semantic-conventions-genai).
gigai-core's `run()` writes them: every model step (`analyze.py`, `thesis.py`, `experiment.py`, and the P1 judge in
`evals.py`) passes `trace_dir=data_dir / "traces"`, so each run leaves `data/traces/<run_id>.jsonl` (`JsonlTrace`) and
`data/runs/<run_id>.jsonl`, whose samples carry the same spans (`trace.py`). `tr usage` reads cost from the run files.
A trace that holds a secret leaks it to anyone who reads the file; OWASP lists this as LLM02, *Sensitive Information
Disclosure* (https://genai.owasp.org/llm-top-10/).

What a model span holds today (gigai-core `trace.py`, read from a real span in `data/traces/`): the call settings and
`ProviderIdentity` (provider, endpoint, adapter, argv), `request_sha256` (a digest of the whole conversation sent),
`last_turn` (the last message sent, in full), `text` (the reply, in full), usage, cost, latency, and on failure a
`CallError` with the provider's code and message. `request_turns` (the full conversation) is written only when
`store_inputs=True`; gigai-core's default is False and no tradingresearch call sets it, so it is `null` in every span.

The last turn is built from fetched data: the analyze prompt lists Alpaca-derived indicators (close, SMAs, ATR,
levels) and EDGAR XBRL facts (revenue, net income, EPS); the thesis prompt adds the analysis's claims and prices.

**Decision.**
- **API keys never enter a trace, a run file, a log line or a committed file.** Keys are read from
  `~/.config/tradingresearch/verify.env` in Python into `config.Secret`, whose `repr` and `str` print a mask
  (`tests/test_week1.py` checks it), and are never put in `os.environ`. The OpenRouter key lives only in the HTTP
  client's `Authorization` header (`OpenRouter.__init__`), the Alpaca keys only in the market-data client's headers
  (`alpaca.client`). A span records `ProviderIdentity`, which has no field for a credential.
- **No account data exists to trace.** The repo calls Alpaca's market-data host only (`data.alpaca.markets`: bars,
  news, corporate actions) and no trading or account endpoint. The one account-level number read, the OpenRouter
  key's lifetime spend (`openrouter.key_usage`, `GET /key`), is printed by `tr usage` and written nowhere. Calling an
  Alpaca account or order endpoint needs a new ADR first.
- **Fetched content stays in the git-ignored `data/`.** Bars, EDGAR facts, headlines, the prompts built from them,
  the replies, `journal.db`, `data/traces/` and `data/runs/` are all under `data/` (`.gitignore`: `data/`,
  `data-dev/`, `.env`). New test fixtures that record a model exchange use synthetic inputs, as
  `tests/fixtures/week3/` does (ticker FAKEA).
- **Redaction rule: structural, not pattern-based.** Nothing scans or rewrites text before it is written. What keeps
  a value out of a trace is that the trace has no place for it: no credential field, and no earlier turns
  (`store_inputs` stays False, so a request is stored as its digest plus its last turn). Turning `store_inputs` on is
  a change to this ADR.

**Gaps (not enforced by code).**
- No scrubbing. A key pasted into a prompt, echoed in a reply or in a provider error would be written as it is.
  `CallError.message` is `str(exc)`; for `OpenRouterError` that is the HTTP status plus the first 300 characters of
  the response body (`openrouter.py`, `_post`).
- `.gitignore` is the only barrier, and a copy bypasses it. `tests/fixtures/usage/` holds two real runs, committed
  with their traces (`run_10fc0a886ddb42a2`, `run_c40caab0968e44a3`): their last turns hold indicators computed from
  Alpaca bars, and EDGAR facts, for real tickers on 2026-11-12 and 2026-11-13. A grep for `sk-or`,
  `bearer`, `authorization` and `APCA` in `tests/fixtures/usage/` and `tests/fixtures/week3/` finds nothing
  (2026-11-17), but no test runs that check.
- No retention rule: `data/traces/` and `data/runs/` grow without limit (21 run files each on 2026-11-17).

**Consequences.**
- A span is enough to read one reply against the message that produced it, with its tokens, cost and latency. It
  cannot replay a multi-turn request: the earlier turns are only a digest.
- Cost per run, arm, day or call (`tr usage`) comes from the run files, so `docs/measured-costs.md` needs no
  extra logging.
- The safety of fetched content depends on `data/` staying git-ignored and on nobody copying a trace into the repo.
  Closing the first two gaps needs code: a scrub of known key prefixes before a span is written, and a test that
  greps `tests/fixtures/` for them. Neither is built.

**Readings.** OWASP Top 10 for LLM applications, LLM02 Sensitive Information Disclosure
(https://genai.owasp.org/llm-top-10/); OpenTelemetry semantic conventions for GenAI spans
(https://github.com/open-telemetry/semantic-conventions-genai).
