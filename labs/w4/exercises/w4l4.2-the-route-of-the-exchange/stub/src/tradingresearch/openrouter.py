"""OpenRouter as a gigai-core ModelProvider (gigai-core ships no OpenRouter adapter), plus prices and key spend.

A `Routing` pins which hosts may serve a call (the teacher arm's DeepInfra pin, week 2 section 5, P12); without one the
request is the plain Claude-route request. Every request runs under the shared retry policy (`retry.py`). Tools travel
as gigai-core's own `ToolSpec` / `ToolCall` types (week 4 plumbing: no tool loop here). The served route is logged per
exchange (its first user turn), so a tool loop's route covers every turn: it is provenance (runbook, "Provenance")."""

from __future__ import annotations

import copy
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

from .records import clean_route
from .retry import DEFAULT, HttpError, Policy

API = "https://openrouter.ai/api/v1"
UNKNOWN = "openrouter:unknown"
FINISH = {"stop": "stop", "length": "length", "tool_calls": "tool_calls", "content_filter": "content_filter"}
QUANTIZATIONS = ("int4", "int8", "fp4", "fp6", "fp8", "fp16", "bf16", "fp32", "unknown")  # OpenRouter's filter values
ROUTING_KEYS = ("only", "allow_fallbacks", "quantizations")


class OpenRouterError(ProviderError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"OpenRouter {status}: {message}")
        self.code = {402: "insufficient_credits", 429: "rate_limited"}.get(status, f"http_{status}")
        self.retryable = status == 429 or status >= 500


class RouteMismatch(ProviderError):
    """The reply came from a host or tier the routing does not allow: never reroute silently (week 2 section 5)."""

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
    # TODO(w4l4.2) every request of one tool loop must share this key, and two items must not. Today it is the last
    #   turn, which in a follow-up is the tool result, so the item prompt keeps only its first turn's route.
    return request.turns[-1].content


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
        # TODO(w4l4.2) the copy still shares this client's route log, so one arm's routes show up under another's
        return pinned

    def route_for(self, prompt: str) -> str:
        """The exchange's route (Analysis.provider_route): its one route, `openrouter:mixed(a+b)` when turns were
        served by different routes, unknown when any turn's provider is (or nothing was served)."""
        routes = self.routes.get(prompt)
        # TODO(w4l4.2) one route for the whole exchange: unknown when nothing was served or any turn's route is not
        #   clean, the route itself when every turn agrees, else mixed with each provider named once, in sorted order.
        return routes[-1] if routes else UNKNOWN

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
        # TODO(w4l4.2) a request that carries no assistant or tool turn starts a new exchange for its key: the routes
        #   of the last exchange under that key must not leak into this one, even when this one fails.
        failures: list[Exception] = []
        billed: list[float] = []  # usage.cost of failed tries (a 200 carrying an error body may have billed)

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
            raise OpenRouterError(response.status_code, response.text[:300])
        data = response.json()
        if "error" in data:  # some upstream failures arrive as 200 with an error body
            if (data.get("usage") or {}).get("cost"):
                billed.append(float(data["usage"]["cost"]))
            raise OpenRouterError(int(data["error"].get("code", 502)), str(data["error"].get("message"))[:300])
        # TODO(w4l4.2) a reply whose provider is null is unknown too, not the provider named None
        route = f"openrouter:{data.get('provider', 'unknown')}" if self.routing is None else self.routing.served(data)
        key = exchange_key(request)
        self.routes.setdefault(key, []).append(route)
        self.served.append((key, route))
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        calls = tuple(
            ToolCall(id=c["id"], name=c["function"]["name"], arguments=c["function"]["arguments"])
            for c in choice["message"].get("tool_calls") or ()
        )
        if s.output_mode != "text" and not text.strip() and not calls:
            raise OutputNotJSON("empty reply in JSON mode")
        usage = data.get("usage", {})
        cost = usage.get("cost")
        return ModelResult(
            text=text,
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
