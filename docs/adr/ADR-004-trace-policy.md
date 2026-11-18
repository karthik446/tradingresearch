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
- **Redaction rule: structural first, patterns as a backstop.** What keeps a value out of a trace is that the trace
  has no place for it: no credential field, and no earlier turns (`store_inputs` stays False, so a request is stored
  as its digest plus its last turn). Turning `store_inputs` on is a change to this ADR. Since week 7 a pattern scrub
  (`redact.py`, Gaps) also rewrites key-shaped strings in every provider error, reply and tool-call arguments, and
  again on the repo-written trace path before a span is written.

**Gaps (what code enforces since week 7, and what it still does not).**
- **Built (G14c, `redact.py`):**
  - `redact.scrub` replaces key-shaped strings with `[REDACTED:<name>]`. Seven patterns cover this:
    - `sk-or-v1-…` (OpenRouter keys), `sk-ant-…` (Anthropic keys), `sk-proj-…` (OpenAI project keys), each only
      where no letter or digit runs into the prefix
    - `Bearer …` (a token of 20 characters or more with a digit among them)
    - `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY` headers, and `x-api-key` headers, whatever the value's shape
    - Alpaca key ids (`PK`/`AK` plus 18)
  - `cli.main` runs `redact.configure(settings)` before every command, so the exact configured key values are
    replaced too, wherever `scrub` runs. An empty or short value is ignored.
  - A marker names the pattern or the settings field, never the value. `redact.clip` scrubs first and cuts after,
    so a key cut at 300 characters is still caught.
  - A record is scrubbed by its decoded string values and dict keys, never as JSON text, so a key after a newline
    is caught and the rebuilt record stays valid. A string under a credential-header key is replaced whole.
  - Not covered: a key split by a newline keeps the part after it; URL-encoded headers (`Bearer%20…`,
    `key_id%3DPK…`), `sk-or-v2-…` and upper-case-hex `sk-or-v1-…` are not matched. None is a live key shape today.
- **Built: the repo-written trace path.** `experiment.run_items` is the loop that writes its own `JsonlTrace`,
  used by tools arms (`run_tools`) and by masked or augmented arms (`run_masked`). It writes that trace through
  `redact.Scrubbing`, and scrubs each sample before the sample is graded and written to `data/runs/`. Every
  scrubbed span leaves one audit line per pattern (`tr guards`). The line carries stage and decision `redact`, the
  pattern name and a digest of the scrubbed span. Fixed and pipeline arms go through gigai-core's `run_eval`,
  which writes its own trace; that trace holds what the providers return, scrubbed at the provider sites below.
- **Built: the checks.**
  - `tests/test_redact.py` greps `tests/fixtures/` for every pattern and for headline rows from any source other
    than `fakewire`, the invented FAKEA source (0 hits).
  - `tr guards scan --dir DIR` walks a directory read-only and exits 1 on any hit. Its patterns include the
    configured keys by exact value.
  - On 2026-11-17 the scan found 0 hits in the live `data/`: 276 files.
- **Built (G14d): the provider sites.** Nothing an adapter returns carries a raw key:
  - `providers/errors.py` `HttpFailure.__init__` scrubs `message`, which covers `OpenRouterError` and
    `AnthropicError`; the adapters cut an error body with `redact.clip` instead of `[:300]`.
  - `providers/openrouter.py` and `providers/anthropic.py` scrub a reply's `text` and each tool call's `arguments`
    before they become a `ModelResult`. The billed cost is unchanged; request bodies are untouched, so the
    OpenRouter wire bodies stay byte-identical.
  - So the traces gigai-core writes (`analyze`, `thesis`, the judge, the fixed and pipeline arms of `tr exp run`)
    hold the `[REDACTED:…]` marker. A provider has no data dir, so this scrub leaves no audit line; the trace-path
    scrub above stays as the backstop, and audits whatever still gets through.
- **`.gitignore` is still the only barrier for fetched content.** A copy bypasses it.
  - `tests/fixtures/usage/` holds two real runs, committed with their traces (`run_10fc0a886ddb42a2`,
    `run_c40caab0968e44a3`).
  - Their last turns hold indicators computed from Alpaca bars, and EDGAR facts, for real tickers on 2026-11-12
    and 2026-11-13. The fixture grep catches keys and headline rows, not indicator numbers.
- **No retention rule:** `data/traces/` and `data/runs/` grow without limit (21 run files each on 2026-11-17).

**Consequences.**
- A span is enough to read one reply against the message that produced it, with its tokens, cost and latency. It
  cannot replay a multi-turn request: the earlier turns are only a digest.
- Cost per run, arm, day or call (`tr usage`) comes from the run files, so `docs/measured-costs.md` needs no
  extra logging.
- The safety of fetched content depends on `data/` staying git-ignored and on nobody copying a trace into the repo.
  Keys are scrubbed where a provider returns text and again on the repo-written trace path, and the fixtures are
  grepped for them (Gaps).

**Readings.** OWASP Top 10 for LLM applications, LLM02 Sensitive Information Disclosure
(https://genai.owasp.org/llm-top-10/); OpenTelemetry semantic conventions for GenAI spans
(https://github.com/open-telemetry/semantic-conventions-genai).

**Addendum, 2026-11-18 (COST-6): cost joins the SLIs.** The run files and the `daily_run` rows already carry what
each call cost (Context and Consequences above), so a day's spend needed no new logging to become a reading: `tr slo`
now holds the session's first paid `tr daily` run to `COST_BUDGET_USD` ($0.60; `--budget-usd` to change it) from
`daily_run.cost_usd`, champion and challenger rows counted, teacher rows shown apart because they are paid under
`--teacher-max-usd`. A session with no paid row is `no data`, not `met`. The trace policy itself is unchanged: `tr slo`
still reads the journal only. Account burn (the balance at the provider, `GET /credits`) is deliberately not an SLI:
it is a network read that answers for every project on the key, not for this loop, and the pre-flight that would use
it is COST-3b's. `docs/slo-review.md` has the SLO; `docs/measured-costs.md`, "Cost attribution", has the snapshot of
where the money went and the commands that answer it today.
