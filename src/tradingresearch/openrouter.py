"""OpenRouter as a gigai-core ModelProvider (gigai-core ships no OpenRouter adapter), plus prices and key spend."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import httpx
from gigai_core.budget import Price
from gigai_core.providers import (
    AuthenticationRequired, Capability, ModelRequest, ModelResult, OutputNotJSON, ProviderError, ProviderIdentity,
    TokenUsage, UnsupportedRequestField,
)

API = "https://openrouter.ai/api/v1"
FINISH = {"stop": "stop", "length": "length", "tool_calls": "tool_calls", "content_filter": "content_filter"}


class OpenRouterError(ProviderError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"OpenRouter {status}: {message}")
        self.code = {402: "insufficient_credits", 429: "rate_limited"}.get(status, f"http_{status}")
        self.retryable = status == 429 or status >= 500


class OpenRouter:
    """Chat completions over httpx. No temperature or seed: the Claude 5.5 routes do not accept them."""

    def __init__(self, api_key: str, *, timeout: float = 120.0) -> None:
        if not api_key:
            raise AuthenticationRequired("OPENROUTER_API_KEY is not set")
        self._http = httpx.Client(
            base_url=API, timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "X-Title": "tradingresearch"},
        )
        self.routes: dict[str, str] = {}  # last user turn -> the upstream that served it (Analysis.provider_route)

    def route_for(self, prompt: str) -> str:
        return self.routes.get(prompt, "openrouter:unknown")

    @property
    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(provider="openrouter", endpoint=f"{API}/chat/completions", adapter="tradingresearch/1")

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({"text", "json", "schema", "system", "messages"})

    def invoke(self, request: ModelRequest, *, cancel: threading.Event | None = None) -> ModelResult:
        s = request.settings
        refused = [name for name in ("temperature", "top_p", "seed") if getattr(s, name) is not None]
        if refused:
            raise UnsupportedRequestField(refused)
        body: dict = {
            "model": s.model,
            "messages": [{"role": t.role, "content": t.content} for t in request.turns],
            "max_tokens": s.max_output_tokens,
        }
        if s.output_mode == "json":
            body["response_format"] = {"type": "json_object"}
        elif s.output_mode == "schema":
            body["response_format"] = {
                "type": "json_schema", "json_schema": {"name": "output", "strict": True, "schema": s.json_schema},
            }
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
            raise OpenRouterError(int(data["error"].get("code", 502)), str(data["error"].get("message"))[:300])
        self.routes[request.turns[-1].content] = f"openrouter:{data.get('provider', 'unknown')}"
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        if s.output_mode != "text" and not text.strip():
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
        )

    def close(self) -> None:
        self._http.close()


def prices(models: list[str]) -> dict[str, Price]:
    """Per-token prices from the public model list (no key needed). CallBudget refuses a model with no price."""
    fetched = datetime.now(UTC)
    rows = httpx.get(f"{API}/models", timeout=30.0).raise_for_status().json()["data"]
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
    response = httpx.get(f"{API}/key", headers={"Authorization": f"Bearer {api_key}"}, timeout=30.0)
    return float(response.raise_for_status().json()["data"]["usage"])
