"""OpenRouter as a gigai-core ModelProvider (gigai-core ships no OpenRouter adapter), plus prices and key spend.

A `Routing` pins which hosts may serve a call (the teacher arm's DeepInfra pin, SPIKE §9.4, P12); without one the
request is the plain Claude-route request. Every request runs under the shared retry policy (`retry.py`). Tools travel
as gigai-core's own `ToolSpec` / `ToolCall` types (week 4 plumbing: no tool loop here). The served route is logged per
exchange (its first user turn), so a tool loop's route covers every turn: it is provenance (runbook, "Provenance")."""

from __future__ import annotations

import copy
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from gigai_core.budget import Price
from gigai_core.providers import (
    AuthenticationRequired, Capability, ModelRequest, ModelResult, OutputNotJSON, ProviderError, ProviderIdentity,
    TokenUsage, ToolCall, ToolSpec, Turn, UnsupportedRequestField,
)

from .. import redact
from ..records import clean_route
from ..retry import DEFAULT, HttpError, Policy, retry_after
from .errors import HttpFailure

API = "https://openrouter.ai/api/v1"
UNKNOWN = "openrouter:unknown"
FINISH = {"stop": "stop", "length": "length", "tool_calls": "tool_calls", "content_filter": "content_filter"}
QUANTIZATIONS = ("int4", "int8", "fp4", "fp6", "fp8", "fp16", "bf16", "fp32", "unknown")  # OpenRouter's filter values
ROUTING_KEYS = ("only", "allow_fallbacks", "quantizations")


class OpenRouterError(HttpFailure):
    """Codes as before the provider interface: 402 `insufficient_credits`, 429 `rate_limited`, else `http_<status>`."""

    def __init__(self, status: int, message: str, retry_after: float | None = None) -> None:
        super().__init__("OpenRouter", status, message, retry_after=retry_after)


class RouteMismatch(ProviderError):
    """The reply came from a host or tier the routing does not allow: never reroute silently (SPIKE §9.4)."""

    code = "route_mismatch"


@dataclass(frozen=True)
class Routing:
    """OpenRouter's `provider` block: endpoint slugs allowed (`provider[/variant][/tier]`), fallbacks, quantizations."""

    only: tuple[str, ...] = ()
    allow_fallbacks: bool = True
    quantizations: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, raw: object) -> Routing:
        """An experiment arm's `provider` table, checked before any spend."""
        if not isinstance(raw, dict):
            raise ValueError("provider must be a table")
        unknown = sorted(set(raw) - set(ROUTING_KEYS))
        if unknown:
            raise ValueError(f"unknown provider key(s) {unknown}; allowed {list(ROUTING_KEYS)}")
        only, fallbacks, quants = raw.get("only", []), raw.get("allow_fallbacks", True), raw.get("quantizations", [])
        if not (isinstance(only, list) and all(isinstance(s, str) and s for s in only)):
            raise ValueError("provider.only must be a list of endpoint slugs")
        if not isinstance(fallbacks, bool):
            raise ValueError("provider.allow_fallbacks must be true or false")
        if not (isinstance(quants, list) and all(q in QUANTIZATIONS for q in quants)):
            raise ValueError(f"provider.quantizations must be a list of {list(QUANTIZATIONS)}")
        return cls(tuple(only), fallbacks, tuple(quants))

    @property
    def tier(self) -> str | None:
        """`flex` when every allowed endpoint is a flex one: sent as `service_tier` and checked on the reply."""
        return "flex" if self.only and all(slug.endswith("/flex") for slug in self.only) else None

    def block(self) -> dict:
        out: dict = {"allow_fallbacks": self.allow_fallbacks}
        if self.only:
            out["only"] = list(self.only)
        if self.quantizations:
            out["quantizations"] = list(self.quantizations)
        return out

    def describe(self) -> str:
        """The pin as one line, kept in the trace (`ProviderIdentity.provider`) so a run shows how it was routed."""
        return (f"only={'+'.join(self.only) or '*'},allow_fallbacks={str(self.allow_fallbacks).lower()},"
                f"quantizations={'+'.join(self.quantizations) or '*'}")

    def served(self, data: dict) -> str:
        """The route that answered (`openrouter:<slug>`), or RouteMismatch if the reply names another host or tier."""
        host = str(data.get("provider", "")).lower().replace(" ", "-")
        hosts = {slug.split("/")[0] for slug in self.only}
        if hosts and host not in hosts:
            raise RouteMismatch(f"served by {data.get('provider')!r}, pinned to {'+'.join(self.only)}")
        tier = data.get("service_tier")
        if self.tier and tier != self.tier:
            raise RouteMismatch(f"served at tier {tier!r}, pinned to {self.tier}")
        if len(self.only) == 1:
            return f"openrouter:{self.only[0]}"
        return f"openrouter:{host or 'unknown'}" + (f"/{tier}" if tier and tier != "default" else "")


def message(turn: Turn) -> dict:
    """One turn as a chat message; the tool-call fields only when set, so a plain request is unchanged."""
    out: dict = {"role": turn.role, "content": turn.content}
    if turn.tool_calls:
        out["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                             for c in turn.tool_calls]
    if turn.tool_call_id is not None:
        out["tool_call_id"] = turn.tool_call_id
    return out


def tool(spec: ToolSpec) -> dict:
    return {"type": "function",
            "function": {"name": spec.name, "description": spec.description, "parameters": spec.parameters}}


def tool_choice(value: str) -> str | dict:
    """`auto`, `none` or `required` as is; any other value names the one tool the model must call."""
    return value if value in ("auto", "none", "required") else {"type": "function", "function": {"name": value}}


def exchange_key(request: ModelRequest) -> str:
    """The exchange's first user turn (the item prompt): every request of one tool loop shares it."""
    return next((t.content for t in request.turns if t.role == "user"), "")


class OpenRouter:
    """Chat completions over httpx. No temperature or seed: the Claude 5.5 routes do not accept them."""

    def __init__(self, api_key: str, *, timeout: float = 120.0, routing: Routing | None = None,
                 policy: Policy = DEFAULT) -> None:
        if not api_key:
            raise AuthenticationRequired("OPENROUTER_API_KEY is not set")
        self._http = httpx.Client(
            base_url=API, timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "X-Title": "tradingresearch"},
        )
        self.served: list[tuple[str, str]] = []  # (first user turn, route) per successful call, in order
        self.routes: dict[str, list[str]] = {}  # first user turn -> the route of each turn of its latest exchange
        self.routing = routing
        self.policy = policy

    def routed(self, routing: Routing) -> OpenRouter:
        """The same client pinned by `routing` (an experiment arm's `provider` knob)."""
        pinned = copy.copy(self)
        pinned.routing = routing
        pinned.served, pinned.routes = [], {}  # its own log: arms never see each other's routes
        return pinned

    def cached(self, ttl: str) -> OpenRouter:
        """Refused: an arm's `cache` knob is Anthropic's alone (G15-SPIKE §1.2), so this wire body stays as captured."""
        raise ValueError(f"cache {ttl!r} runs on TR_PROVIDER=anthropic only; OpenRouter sends no cache_control")

    def route_for(self, prompt: str) -> str:
        """The exchange's route (Analysis.provider_route): its one route, `openrouter:mixed(a+b)` when turns were
        served by different routes, unknown when any turn's provider is (or nothing was served)."""
        routes = self.routes.get(prompt)
        if not routes or not all(clean_route(r) for r in routes):
            return UNKNOWN
        distinct = sorted(set(routes))
        if len(distinct) == 1:
            return distinct[0]
        return f"openrouter:mixed({'+'.join(r.removeprefix('openrouter:') for r in distinct)})"

    @property
    def identity(self) -> ProviderIdentity:
        provider = "openrouter" if self.routing is None else f"openrouter:{self.routing.describe()}"
        return ProviderIdentity(provider=provider, endpoint=f"{API}/chat/completions", adapter="tradingresearch/1")

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({"text", "json", "schema", "system", "messages", "tools"})

    def invoke(self, request: ModelRequest, *, cancel: threading.Event | None = None) -> ModelResult:
        """One model call under the shared retry policy: a retryable failure (429, 5xx, connection) is tried again,
        a reply that arrived and parsed never is. Cost any failed try reported is added to the result, never dropped."""
        s = request.settings
        refused = [name for name in ("temperature", "top_p", "seed") if getattr(s, name) is not None]
        if refused:
            raise UnsupportedRequestField(refused)
        body = self.body(request)
        if all(t.role in ("system", "user") for t in request.turns):  # a fresh exchange, not a tool-loop follow-up
            self.routes[exchange_key(request)] = []
        failures: list[Exception] = []
        billed: list[float] = []  # usage.cost of failed tries (a 200 with an error body or an empty JSON reply)

        def attempt() -> ModelResult:
            try:
                return self._post(request, body, billed)
            except Exception as exc:
                failures.append(exc)
                raise

        try:
            result = self.policy.call(attempt)
        except ProviderError as exc:
            if billed:
                exc.args = (f"{exc} (failed tries billed ${sum(billed):.6f})",)
            raise
        if not failures:
            return result
        cost = result.cost_usd if not billed else (result.cost_usd or 0.0) + sum(billed)
        return result.model_copy(update={
            "retry_count": len(failures), "last_error_class": type(failures[-1]).__name__,
            "cost_usd": cost, "cost_status": "provider_reported" if cost is not None else result.cost_status,
        })

    def body(self, request: ModelRequest) -> dict:
        """The chat-completions request. Tool fields appear only when the request has tools or tool turns."""
        s = request.settings
        body: dict = {
            "model": s.model,
            "messages": [message(t) for t in request.turns],
            "max_tokens": s.max_output_tokens,
        }
        if s.output_mode == "json":
            body["response_format"] = {"type": "json_object"}
        elif s.output_mode == "schema":
            body["response_format"] = {
                "type": "json_schema", "json_schema": {"name": "output", "strict": True, "schema": s.json_schema},
            }
        if request.tools:
            body["tools"] = [tool(spec) for spec in request.tools]
            body["tool_choice"] = tool_choice(s.tool_choice)
        if self.routing is not None:
            body["provider"] = self.routing.block()
            if self.routing.tier:
                body["service_tier"] = self.routing.tier
        return body

    def _post(self, request: ModelRequest, body: dict, billed: list[float]) -> ModelResult:
        """One HTTP try. A failed try that reported a cost appends it to `billed`."""
        s = request.settings
        started = datetime.now(UTC)
        t0 = time.monotonic()
        response = self._http.post("/chat/completions", json=body)
        latency_ms = int((time.monotonic() - t0) * 1000)
        if response.status_code == 401:
            raise AuthenticationRequired("OpenRouter rejected the key (401)")
        if response.status_code != 200:
            raise OpenRouterError(response.status_code, redact.clip(response.text),
                                  retry_after(response.headers.get("Retry-After")))
        data = response.json()
        if "error" in data:  # some upstream failures arrive as 200 with an error body
            if (data.get("usage") or {}).get("cost"):
                billed.append(float(data["usage"]["cost"]))
            raise OpenRouterError(int(data["error"].get("code", 502)), redact.clip(str(data["error"].get("message"))))
        route = f"openrouter:{data.get('provider') or 'unknown'}" if self.routing is None else self.routing.served(data)
        key = exchange_key(request)
        self.routes.setdefault(key, []).append(route)
        self.served.append((key, route))
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        calls = tuple(
            ToolCall(id=c["id"], name=c["function"]["name"], arguments=redact.scrub(c["function"]["arguments"]))
            for c in choice["message"].get("tool_calls") or ()
        )
        if s.output_mode != "text" and not text.strip() and not calls:  # billed like a 200 error body, then raised
            if (data.get("usage") or {}).get("cost"):
                billed.append(float(data["usage"]["cost"]))
            raise OutputNotJSON("empty reply in JSON mode")
        usage = data.get("usage", {})
        cost = usage.get("cost")
        return ModelResult(
            text=redact.scrub(text),
            finish_reason=FINISH.get(choice.get("finish_reason"), "unknown"),
            resolved_model=data.get("model", s.model),
            usage=TokenUsage(
                input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"), raw=usage,
            ),
            cost_status="provider_reported" if cost is not None else "unavailable",
            cost_usd=cost,
            latency_ms=latency_ms,
            started_at=started,
            completed_at=datetime.now(UTC),
            tool_calls=calls,
        )

    def close(self) -> None:
        self._http.close()


def get(url: str, *, headers: dict[str, str] | None = None, policy: Policy = DEFAULT) -> dict:
    """A GET of the model list or the key, under the shared retry policy."""
    def once() -> dict:
        response = httpx.get(url, headers=headers, timeout=30.0)
        if not response.is_success:
            raise HttpError.of("OpenRouter", response)
        return response.json()

    return policy.call(once)


def prices(models: list[str]) -> dict[str, Price]:
    """Per-token prices from the public model list (no key needed). CallBudget refuses a model with no price."""
    fetched = datetime.now(UTC)
    rows = get(f"{API}/models")["data"]
    out = {}
    for row in rows:
        if row["id"] in models:
            out[row["id"]] = Price(
                model=row["id"], prompt_usd_per_token=float(row["pricing"]["prompt"]),
                completion_usd_per_token=float(row["pricing"]["completion"]), fetched_at=fetched, source=f"{API}/models",
            )
    missing = set(models) - set(out)
    if missing:
        raise KeyError(f"OpenRouter lists no price for {sorted(missing)}")
    return out


def key_usage(api_key: str) -> float:
    """All-time credits used by this key, in USD (GET /key). Read it before and after a paid step."""
    return float(get(f"{API}/key", headers={"Authorization": f"Bearer {api_key}"})["data"]["usage"])


BATCH_ENDPOINT = "/v1/chat/completions"  # the batch runs the sync endpoint's bodies
CUSTOM_ID = re.compile(r"[a-zA-Z0-9_-]{1,64}")  # OpenRouter's custom_id rule; also the batch id rule here


def submit_batch(api_key: str, model: str, requests: list[ModelRequest]) -> str:
    """Submit `requests` as one batch (POST /batches, G15-SPIKE §1.3) and return its id. Each body is the sync body
    (`OpenRouter.body`) under the normal model slug, no `:batch` suffix; its `custom_id` is the request's
    `metadata["item_id"]`. Bad or repeated ids and a request for another model are refused before any request. Sent
    once, never retried: a retried submit could start a second paid batch."""
    ids = [request.metadata.get("item_id") for request in requests]
    bad = [i for i in ids if not isinstance(i, str) or not CUSTOM_ID.fullmatch(i)]
    if not requests or bad or len(set(ids)) != len(ids):
        raise ValueError(f"a batch needs unique custom_ids matching {CUSTOM_ID.pattern}; refused: "
                         f"{bad or sorted({i for i in ids if ids.count(i) > 1}) or 'an empty batch'}")
    others = sorted({r.settings.model for r in requests} - {model})
    if others:
        raise ValueError(f"one model per batch ({model}); refused: {others}")
    adapter = OpenRouter(api_key)
    try:
        body = {"model": model, "endpoint": BATCH_ENDPOINT,
                "requests": [{"custom_id": i, "body": adapter.body(r)} for i, r in zip(ids, requests, strict=True)]}
        response = adapter._http.post("/batches", json=body)
    finally:
        adapter.close()
    if response.status_code == 401:
        raise AuthenticationRequired("OpenRouter rejected the key (401)")
    if response.status_code != 202:
        raise OpenRouterError(response.status_code, redact.clip(response.text),
                              retry_after(response.headers.get("Retry-After")))
    return response.json()["id"]


def get_batch(api_key: str, batch_id: str) -> dict:
    """The batch as OpenRouter holds it (GET /batches/{id}): its status, `usage` and, once completed, `results`."""
    if not CUSTOM_ID.fullmatch(batch_id):
        raise ValueError(f"not a batch id: {batch_id!r}")
    return get(f"{API}/batches/{batch_id}", headers={"Authorization": f"Bearer {api_key}"})
