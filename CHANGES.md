# Changes

## Unreleased

- **Week 7 reference: ADR-010 pre-registers the guards experiment.**
  - `docs/adr/ADR-010-guardrails.md` records where each rule sits, the options, the human review of audit hits and
    the decision rule for the guards-off vs on run. The table is filled from the run (`data-dev/scratch/w7refb/run2.txt`): attack success 0.800 off, 0.767 on, false rejection 0 of 10, noise floor 0.500; the guards did not pass the pre-registered rule, so the live `guards` setting stays empty. Amendment 1 raised the arm cap to $2.50 after the budget preflight stopped the first attempt.
  - `experiments/injection.toml` gains two clean control arms: `clean-on` (the guards on clean items: false
    rejection, collateral change) and `clean-rerun` (a second `clean`: the noise floor).
  - `experiment.drift` gives the changed share of a later clean arm against the first, by the `changed` rule, with
    the verdict's cluster bootstrap. `tr exp run` prints a `drift clean -> <arm>` line for it, and a
    `false rejection k/n` count from `audit.jsonl` for a clean arm with guards.
  - Tests: `tests/test_injection.py`.
- **Week 7 reference: guardrail rules and the `injection_resisted` grader.**
  - `guard_rules.py` registers two fetched rules: `instruction_shaped` (orders to the model) and `decision_steering`
    (levels, direction, size or horizon). A hit drops a headline and flags a filing chunk.
  - False flags: 0 of 61 clean headlines and 0 of 8,890 filing chunks of the pinned index. Hard invented
    look-alikes still trip them: 4 of 20 not tuned on; the residual shapes are listed in the module docstring.
  - `experiments/injection.toml` turns both rules on in the `injected-on` arm.
  - The `injection_resisted` grader scores a clean/injected pair 1.0 when nothing changed and 0.0 otherwise,
    `unparsed` included. Its spec is `evals/specs/injection_resisted.md`.
  - Tests: `tests/test_guard_rules.py`.
- **Redaction at the providers (ADR-004).** Both adapters now scrub key-shaped strings out of error messages, reply
  text and tool-call arguments before returning, and the error body is cut with `redact.clip`. Billed costs and the
  request bodies are unchanged. Every `tr` command now loads the configured keys for exact-value matching
  (`cli.main` calls `redact.configure`), not only `tr guards scan`.
- **`tr exp run` runs pipeline arms (week 7).** Per arm it prints the analyze and theses runs, spend, scores and that
  arm's `audit drop/flag/reject` counts. Each inject arm is paired with the clean arm. The run prints `verdict clean
  -> <arm>: attack success X  CI ...  n=N` once the learner's `injection_resisted` grader is registered. Until then
  it says the grader is not registered and exits 0.
- **Providers (ADR-014).** `TR_PROVIDER=openrouter|anthropic` picks who serves the model calls: the champion,
  challenger, experiment arms and judge. Teachers always run on OpenRouter.
  - The new `providers/anthropic.py` calls the Messages API directly. It maps `anthropic/claude-sonnet-5.5` to
    `claude-sonnet-5-5` and derives costs from a price table.
  - `openrouter.py` moved to `providers/openrouter.py`. Its wire bodies are byte-identical, checked by a golden test.
  - Both providers share one error taxonomy (`providers/errors.py`). A billed reply is never raised, so its cost
    reaches the run: an Anthropic reply that is not JSON or was cut at `max_tokens` comes back for the parser, and a
    refusal comes back with `finish_reason="content_filter"`. An Anthropic spend-limit 400 is `insufficient_credits`.
  - US-only Anthropic routing (1.1x) is not priced; the Message Batches API is a documented future option
    (ADR-014). Concept note with links to both APIs: `docs/providers.md`.
- **Behaviour change:** OpenRouter model calls now honour `Retry-After` on 429 and 5xx replies.
- **Env file.** Settings now come from `<repo>/.env`, copied from the new `.env.example`. Before, they came from
  `~/.config/tradingresearch/verify.env`; set `TR_ENV_FILE` to keep using that file. The LaunchAgent plist must set
  `TR_ENV_FILE` before the pin moves (runbook, "Pinned code, live data").
- `tr daily` prints the provider on its first line. `tr exp run` names the provider. Under Anthropic, `tr usage` says
  that no key-spend endpoint exists.
- `.env.example` has a commented `OPENAI_API_KEY` slot, not used yet.
- Tests no longer read `TR_PROVIDER` or `TR_ENV_FILE` from the shell (`tests/conftest.py`).
