"""The one error taxonomy every provider adapter maps into (ADR-014).

Five kinds: `credit_exhausted` (out of credit, billing refused or a spend limit reached), `rate_limited` (429; the
server's Retry-After is honoured by `retry.Policy.wait`), `upstream_5xx` (the provider or its upstream failed),
`output_not_json` (a JSON or schema call that returned an empty reply) and `refused` (the model declined). Any other
HTTP error is `rejected`. A billed reply is never raised, so its cost reaches the run: a refusal comes back as a
ModelResult with `finish_reason="content_filter"` (`kind` names it `refused`) and a reply that is not JSON comes back
for the caller's parser, on every provider. `code` stays the journal's error string and is the same on every provider
(`insufficient_credits`, `rate_limited`, `http_<status>`, `model_output_not_json`), so `retry.py`, the daily run and
the journal treat a failure the same whichever provider raised it. Only 429 and 5xx are retryable."""

from __future__ import annotations

from gigai_core.providers import OutputNotJSON, ProviderError

CREDIT_EXHAUSTED = "credit_exhausted"
RATE_LIMITED = "rate_limited"
UPSTREAM_5XX = "upstream_5xx"
OUTPUT_NOT_JSON = "output_not_json"
REFUSED = "refused"
REJECTED = "rejected"  # any other HTTP error (400, 403, 404, 413...): never retried

CODES = {CREDIT_EXHAUSTED: "insufficient_credits", RATE_LIMITED: "rate_limited"}


def kind_of(status: int) -> str:
    if status == 402:
        return CREDIT_EXHAUSTED
    if status == 429:
        return RATE_LIMITED
    if status >= 500:
        return UPSTREAM_5XX
    return REJECTED


class HttpFailure(ProviderError):
    """A provider answered with an HTTP error (or a 200 carrying one). `kind` overrides the status's own kind, for an
    error the provider reports under another status (Anthropic's out-of-credit 400)."""

    def __init__(self, provider: str, status: int, message: str, *, kind: str | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__(f"{provider} {status}: {message}")
        self.status = status
        self.kind = kind or kind_of(status)
        self.code = CODES.get(self.kind, f"http_{status}")
        self.retryable = self.kind in (RATE_LIMITED, UPSTREAM_5XX)
        self.retry_after = retry_after if self.retryable else None


def kind(outcome: object) -> str | None:
    """The taxonomy kind of an adapter's error, or `refused` for a returned refusal (a ModelResult whose
    finish_reason is content_filter); None for anything else (a success, a connection error, a bug)."""
    if isinstance(outcome, OutputNotJSON):
        return OUTPUT_NOT_JSON
    if getattr(outcome, "finish_reason", None) == "content_filter":
        return REFUSED
    return getattr(outcome, "kind", None)
