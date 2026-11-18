"""Anthropic's Messages API as a gigai-core ModelProvider (ADR-014): the champion's Claude calls without OpenRouter.

Configs keep OpenRouter-style ids (`anthropic/claude-sonnet-5.5`); `wire_model` maps one to the API id
(`claude-sonnet-5-5`: no vendor prefix, dots to hyphens) and refuses another vendor's model before any call. API
version 2026-10-21 rejects `temperature`, `top_p` and `top_k`, so a request that sets one is refused here, as the
OpenRouter adapter refuses them. A `schema` call sends the schema as `output_config.format` (structured outputs); a
`json` call has no schema-less mode on this API. Cost is derived from `PRICES` and the reply's usage, cache reads and
writes included. Errors map into `errors.py`'s taxonomy; every try runs under the shared retry policy (`retry.py`). A
billed reply always comes back with its cost, as on OpenRouter: one that is not JSON or was cut at `max_tokens` is
returned for the caller's parser to record, and a refusal is returned with `finish_reason="content_filter"`; only an
empty JSON reply raises `OutputNotJSON`. The route is `anthropic:<served model>` (`/us` when the reply says it ran
US-only). The Message Batches API (half price, results within 24 h) is a possible later mode for non-urgent runs such
as experiments; it is not implemented (platform.claude.com/docs/en/build-with-claude/batch-processing)."""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime

import httpx
from gigai_core.budget import Price
from gigai_core.providers import (
    AuthenticationRequired, Capability, ModelRequest, ModelResult, OutputNotJSON, ProviderError, ProviderIdentity,
    TokenUsage, ToolCall, ToolSpec, Turn, UnsupportedRequestField,
)

from ..records import clean_route
from ..retry import DEFAULT, Policy, retry_after
from .errors import CREDIT_EXHAUSTED, HttpFailure
from .openrouter import exchange_key

API = "https://api.anthropic.com/v1"
VERSION = "2026-10-21"  # the anthropic-version header (platform.claude.com/docs/en/api/versioning)
UNKNOWN = "anthropic:unknown"
PREFIX = "anthropic/"
FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls",
          "refusal": "content_filter"}
PRICES_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing (read 2026-11-17)"
MTOK = 1_000_000
# USD per million tokens by API id: base input, output, 5-minute cache write, 1-hour cache write, cache hit. Global
# routing (no `inference_geo`), standard tier. US-only routing (`inference_geo: "us"`) costs 1.1x every category and
# is not modelled: such a call (route `.../us`) is underpriced by 10%. Add a model only from the pricing page, with
# the date it was read.
PRICES = {
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_write_5m": 2.5, "cache_write_1h": 4.0,
                          "cache_read": 0.10},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_write_5m": 5.0, "cache_write_1h": 8.0,
                        "cache_read": 0.20},
}


class AnthropicError(HttpFailure):
    def __init__(self, status: int, message: str, *, kind: str | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__("Anthropic", status, message, kind=kind, retry_after=retry_after)


class WrongProvider(ProviderError):
    """The model belongs to another vendor: this provider cannot serve it (refused before any call)."""

    code = "model_wrong_provider"


def wire_model(model: str) -> str:
    """The API id of a config id: `anthropic/claude-sonnet-5.5` -> `claude-sonnet-5-5`. Another vendor's id (any other
    `vendor/` prefix) is refused."""
    name = model.removeprefix(PREFIX)
    if "/" in name or not name.startswith("claude-"):
        raise WrongProvider(f"TR_PROVIDER=anthropic cannot serve {model}: only anthropic/claude-* models "
                            "(set TR_PROVIDER=openrouter for it)")
    return name.replace(".", "-")


def prices(models: list[str]) -> dict[str, Price]:
    """Per-token prices from `PRICES`, keyed by the config id. CallBudget refuses a model with no price."""
    fetched = datetime.now(UTC)
    out, missing = {}, []
    for model in models:
        row = PRICES.get(wire_model(model))
        if row is None:
            missing.append(model)
            continue
        out[model] = Price(model=model, prompt_usd_per_token=row["input"] / MTOK,
                           completion_usd_per_token=row["output"] / MTOK, fetched_at=fetched, source=PRICES_SOURCE)
    if missing:
        raise KeyError(f"no Anthropic price for {sorted(missing)}: add it to PRICES from {PRICES_SOURCE}")
    return out


def cost(model: str, usage: dict) -> float | None:
    """The call's USD from the reply's usage: uncached input, output, cache writes (5-minute and 1-hour) and cache hits.
    None for a model with no price."""
    row = PRICES.get(model)
    if row is None:
        return None
    written = usage.get("cache_creation") or {}
    write_1h = written.get("ephemeral_1h_input_tokens") or 0
    write_5m = written.get("ephemeral_5m_input_tokens", (usage.get("cache_creation_input_tokens") or 0) - write_1h)
    total = ((usage.get("input_tokens") or 0) * row["input"] + (usage.get("output_tokens") or 0) * row["output"]
             + (write_5m or 0) * row["cache_write_5m"] + write_1h * row["cache_write_1h"]
             + (usage.get("cache_read_input_tokens") or 0) * row["cache_read"])
    return total / MTOK


def messages(turns: tuple[Turn, ...]) -> list[dict]:
    """The non-system turns as Messages API messages: a tool turn is a `tool_result` block in a user message, and
    consecutive tool results share one user message (the API alternates user and assistant)."""
    out: list[dict] = []
    for turn in turns:
        if turn.role == "system":
            continue
        if turn.role == "tool":
            block = {"type": "tool_result", "tool_use_id": turn.tool_call_id, "content": turn.content}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif turn.role == "assistant" and turn.tool_calls:
            blocks: list[dict] = [{"type": "text", "text": turn.content}] if turn.content else []
            blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": json.loads(c.arguments or "{}")}
                       for c in turn.tool_calls]
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": turn.role, "content": turn.content})
    return out


def tool(spec: ToolSpec) -> dict:
    return {"name": spec.name, "description": spec.description, "input_schema": spec.parameters}


def tool_choice(value: str) -> dict:
    """`auto`, `none` or `required` (the API's `any`); any other value names the one tool the model must call."""
    named = {"auto": {"type": "auto"}, "none": {"type": "none"}, "required": {"type": "any"}}
    return named.get(value, {"type": "tool", "name": value})


def failure(response: httpx.Response) -> AnthropicError:
    """A non-200 reply in the taxonomy: 402 or `billing_error`, a 400 saying the credit balance is too low, or a 400
    for a spend limit you set ("You have reached your specified [workspace] API usage limits", errors and rate-limits
    docs) is credit_exhausted; 429 rate_limited (with Retry-After); 5xx and 529 upstream_5xx; anything else rejected."""
    try:
        error = response.json().get("error") or {}
    except ValueError:
        error = {}
    message = str(error.get("message") or response.text)[:300]
    lower = message.lower()
    out_of_credit = (response.status_code == 402 or error.get("type") == "billing_error"
                     or (response.status_code == 400
                         and ("credit balance" in lower or lower.startswith("you have reached your specified"))))
    return AnthropicError(response.status_code, f"{error.get('type', 'error')}: {message}",
                          kind=CREDIT_EXHAUSTED if out_of_credit else None,
                          retry_after=retry_after(response.headers.get("retry-after")))


class Anthropic:
    """Messages API over httpx, the key in `x-api-key`. No `routed()`: OpenRouter's routing table has no meaning here."""

    def __init__(self, api_key: str, *, timeout: float = 120.0, policy: Policy = DEFAULT) -> None:
        if not api_key:
            raise AuthenticationRequired("ANTHROPIC_API_KEY is not set")
        self._http = httpx.Client(
            base_url=API, timeout=timeout,
            headers={"x-api-key": api_key, "anthropic-version": VERSION, "content-type": "application/json"},
        )
        self.served: list[tuple[str, str]] = []  # (first user turn, route) per successful call, in order
        self.routes: dict[str, list[str]] = {}  # first user turn -> the route of each turn of its latest exchange
        self.policy = policy

    def route_for(self, prompt: str) -> str:
        """The exchange's route: its one route, `anthropic:mixed(a+b)` when turns were served by different models,
        unknown when nothing was served."""
        routes = self.routes.get(prompt)
        if not routes or not all(clean_route(r) for r in routes):
            return UNKNOWN
        distinct = sorted(set(routes))
        if len(distinct) == 1:
            return distinct[0]
        return f"anthropic:mixed({'+'.join(r.removeprefix('anthropic:') for r in distinct)})"

    @property
    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(provider="anthropic", endpoint=f"{API}/messages",
                                adapter=f"tradingresearch/1 anthropic-version={VERSION}")

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({"text", "json", "schema", "system", "messages", "tools"})

    def invoke(self, request: ModelRequest, *, cancel: threading.Event | None = None) -> ModelResult:
        """One model call under the shared retry policy: 429, 5xx and connection failures are tried again, a reply that
        arrived and parsed never is."""
        s = request.settings
        refused = [name for name in ("temperature", "top_p", "seed") if getattr(s, name) is not None]
        if refused:
            raise UnsupportedRequestField(refused)
        body = self.body(request)
        if all(t.role in ("system", "user") for t in request.turns):  # a fresh exchange, not a tool-loop follow-up
            self.routes[exchange_key(request)] = []
        failures: list[Exception] = []

        def attempt() -> ModelResult:
            try:
                return self._post(request, body)
            except Exception as exc:
                failures.append(exc)
                raise

        result = self.policy.call(attempt)
        if not failures:
            return result
        return result.model_copy(update={"retry_count": len(failures),
                                         "last_error_class": type(failures[-1]).__name__})

    def body(self, request: ModelRequest) -> dict:
        """The Messages request: system turns joined into `system`; tool fields only when the request has tools."""
        s = request.settings
        body: dict = {"model": wire_model(s.model), "max_tokens": s.max_output_tokens}
        system = "\n\n".join(t.content for t in request.turns if t.role == "system")
        if system:
            body["system"] = system
        body["messages"] = messages(request.turns)
        if s.output_mode == "schema":
            body["output_config"] = {"format": {"type": "json_schema", "schema": s.json_schema}}
        if request.tools:
            body["tools"] = [tool(spec) for spec in request.tools]
            body["tool_choice"] = tool_choice(s.tool_choice)
        return body

    def _post(self, request: ModelRequest, body: dict) -> ModelResult:
        """One HTTP try."""
        s = request.settings
        started = datetime.now(UTC)
        t0 = time.monotonic()
        response = self._http.post("/messages", json=body)
        latency_ms = int((time.monotonic() - t0) * 1000)
        if response.status_code == 401:
            raise AuthenticationRequired("Anthropic rejected the key (401)")
        if response.status_code != 200:
            raise failure(response)
        data = response.json()
        usage = dict(data.get("usage") or {})
        served = data.get("model") or body["model"]
        price = cost(served, usage)
        geo = usage.get("inference_geo")
        route = f"anthropic:{served}" + (f"/{geo}" if geo and geo != "global" else "")
        key = exchange_key(request)
        self.routes.setdefault(key, []).append(route)
        self.served.append((key, route))
        content = data.get("content") or []
        text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
        calls = tuple(ToolCall(id=b["id"], name=b["name"], arguments=json.dumps(b.get("input") or {}))
                      for b in content if b.get("type") == "tool_use")
        refused = data.get("stop_reason") == "refusal"  # billed: returned with its cost, never raised
        if s.output_mode != "text" and not text.strip() and not calls and not refused:
            raise OutputNotJSON("empty reply in JSON mode")
        cached = (usage.get("cache_creation_input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0)
        prompt = (usage["input_tokens"] + cached) if usage.get("input_tokens") is not None else None
        output = usage.get("output_tokens")
        return ModelResult(
            text=text,
            finish_reason=FINISH.get(data.get("stop_reason"), "unknown"),
            resolved_model=served,
            usage=TokenUsage(input_tokens=prompt, output_tokens=output,
                             total_tokens=prompt + output if prompt is not None and output is not None else None,
                             raw={**usage, "response_id": data.get("id"),
                                  **({"stop_details": data.get("stop_details")} if refused else {})}),
            cost_status="derived" if price is not None else "unavailable",
            cost_usd=price,
            latency_ms=latency_ms,
            started_at=started,
            completed_at=datetime.now(UTC),
            tool_calls=calls,
        )

    def close(self) -> None:
        self._http.close()
