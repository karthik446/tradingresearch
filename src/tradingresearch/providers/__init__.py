"""One provider interface (ADR-014). `TR_PROVIDER` (`openrouter`, the default, or `anthropic`) picks the adapter for
every model call except the teachers': the champion and challenger (`analyze`, `thesis`, `daily`), experiment arms
and the judge. Teachers are not Claude and always run on OpenRouter. Only the chosen provider's key is read.

Both adapters are gigai-core `ModelProvider`s with the same `route_for`, `routes` and `served`, and both map their
failures into `errors.py`. A provider change for a role is a new route, never the same route: the trace's identity
and every record's `provider_route` name the provider. `with_fallback` asks a second model once when the first is
out of retries (an experiment arm's `route.fallback`, G15-SPIKE §1.1). `BatchReplay` answers from a completed
OpenRouter batch, so the batch judge writes what the sync judge writes (G15-SPIKE §1.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from gigai_core.budget import Price
from gigai_core.providers import ModelRequest, ModelResult, ProviderError, ProviderIdentity, TokenUsage, request_sha256

from .. import redact
from ..config import Settings, require
from ..retry import retryable
from . import anthropic, openrouter
from .anthropic import Anthropic
from .openrouter import OpenRouter, Routing

ROLES = ("champion", "experiment", "judge", "teacher")
KEYS = {"openrouter": "OPENROUTER_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def name_for(cfg: Settings, role: str) -> str:
    """The provider a role's calls go to: the teacher always OpenRouter, every other role `TR_PROVIDER`."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r} (one of {', '.join(ROLES)})")
    return "openrouter" if role == "teacher" else cfg.provider


def make_provider(cfg: Settings, role: str, *, routing: Routing | None = None) -> OpenRouter | Anthropic:
    """The role's adapter, built with its provider's key only; a missing key exits with one line naming it. `routing`
    (a teacher's host pin) is OpenRouter's alone."""
    name = name_for(cfg, role)
    if name == "anthropic":
        if routing is not None:
            raise SystemExit("an OpenRouter routing table cannot run on TR_PROVIDER=anthropic")
        return Anthropic(require(cfg.anthropic_key, KEYS[name]))
    return OpenRouter(require(cfg.openrouter_key, KEYS[name]), routing=routing)


def check_models(cfg: Settings, role: str, models: list[str]) -> None:
    """Refuse, before any call or spend, a model the role's provider cannot serve (another vendor on Anthropic)."""
    if name_for(cfg, role) == "anthropic":
        for model in models:
            try:
                anthropic.wire_model(model)
            except anthropic.WrongProvider as error:
                raise SystemExit(str(error)) from error


def prices(cfg: Settings, role: str, models: list[str]) -> dict[str, Price]:
    """The role's provider's per-token prices (neither reads a key): OpenRouter's public list, Anthropic's table."""
    check_models(cfg, role, models)
    source = anthropic.prices if name_for(cfg, role) == "anthropic" else openrouter.prices
    return source(models)


class Fallback:
    """A provider that asks `model` once more (one more invoke, with the adapter's own retries) when the inner adapter
    raised a retryable error with its retries spent (`retry.retryable`: 429, 5xx, a connection error or timeout).
    Never after a refusal (a reply, returned not raised), an authentication, credit or budget error, or a rejected
    request: those raise as they are. The result's `resolved_model` is the model that served it, so the span, its
    cost and `provider_route` show the fallback."""

    def __init__(self, inner, model: str) -> None:
        self.inner = inner
        self.model = model

    @property
    def identity(self):
        return self.inner.identity

    @property
    def capabilities(self):
        return self.inner.capabilities

    def invoke(self, request: ModelRequest, *, cancel=None) -> ModelResult:
        try:
            return self.inner.invoke(request, cancel=cancel)
        except Exception as exc:
            if not retryable(exc):
                raise
            settings = request.settings.model_copy(update={"model": self.model})  # the first error stays its context
            return self.inner.invoke(request.model_copy(update={"settings": settings}), cancel=cancel)

    def route_for(self, prompt: str) -> str:
        return self.inner.route_for(prompt)


def with_fallback(provider, model: str) -> Fallback:
    """`provider`, asking `model` once when a call fails on a retryable error (see Fallback)."""
    return Fallback(provider, model)


class BatchEntryFailed(ProviderError):
    """A batch had no usable answer for a request: an `error` entry, a non-200 response, no entry, or a prompt that
    is no longer the one submitted. A failed call, as in sync: CannotGrade, nothing stored."""

    code = "batch_entry_failed"


def entry_cost(entry: dict, price: Price) -> float | None:
    """One result entry's cost, derived: its tokens times the `:batch` price; None when the entry has no usage."""
    usage = (((entry.get("response") or {}).get("body") or {}).get("usage")) or {}
    if usage.get("prompt_tokens") is None or usage.get("completion_tokens") is None:
        return None
    return (usage["prompt_tokens"] * price.prompt_usd_per_token
            + usage["completion_tokens"] * price.completion_usd_per_token)


class BatchReplay:
    """A provider over a completed OpenRouter batch's `results`: `invoke(request)` answers from the entry whose
    `custom_id` is `request.metadata["item_id"]` (results come unordered), so `run_eval` writes the run file, spans and
    ScoreRecord of a sync call. `digests` (item id -> `request_sha256` at submit) refuses a prompt that changed since.
    The cost is `derived` (`entry_cost`); the latency is 0 because the batch reports none per request."""

    def __init__(self, results: list[dict], price: Price, digests: dict[str, str]) -> None:
        self.entries = {entry["custom_id"]: entry for entry in results}
        self.price = price
        self.digests = digests

    @property
    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(provider="openrouter:batch", endpoint=f"{openrouter.API}/batches",
                                adapter="tradingresearch/1")

    @property
    def capabilities(self):
        return frozenset({"text", "system", "messages"})

    def invoke(self, request: ModelRequest, *, cancel=None) -> ModelResult:
        item_id = request.metadata.get("item_id")
        if self.digests.get(item_id) != request_sha256(request):
            raise BatchEntryFailed(f"{item_id}: the prompt is not the one submitted (or was never submitted)")
        entry = self.entries.get(item_id)
        if entry is None:
            raise BatchEntryFailed(f"{item_id}: the batch holds no result for it")
        response = entry.get("response") or {}
        body = response.get("body") or {}
        if entry.get("error") or response.get("status_code") != 200 or "error" in body:
            error = entry.get("error") or body.get("error") or {}
            raise BatchEntryFailed(f"{item_id}: {error.get('type') or response.get('status_code')}: "
                                   f"{redact.clip(str(error.get('message')))}")
        choice = body["choices"][0]
        usage = body.get("usage") or {}
        cost = entry_cost(entry, self.price)
        now = datetime.now(UTC)
        return ModelResult(
            text=redact.scrub(choice["message"].get("content") or ""),
            finish_reason=openrouter.FINISH.get(choice.get("finish_reason"), "unknown"),
            resolved_model=body.get("model", request.settings.model),
            usage=TokenUsage(input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
                             total_tokens=usage.get("total_tokens"), raw=usage),
            cost_status="derived" if cost is not None else "unavailable", cost_usd=cost,
            latency_ms=0, started_at=now, completed_at=now,
        )
