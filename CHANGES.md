# Changes

## Unreleased

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
