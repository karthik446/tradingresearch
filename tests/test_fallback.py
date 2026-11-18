"""`providers.with_fallback` (G15-SPIKE §1.1): one more call on the route's fallback model once the adapter has spent
its retries on a retryable error (`retry.retryable`: 429, 5xx, connection, timeout); never after a refusal (a billed
reply, returned not raised), an authentication error or any other error. The real Anthropic adapter on the fixture
replies of tests/test_provider_anthropic.py: no key, no network."""

from __future__ import annotations

import json
import random

import httpx
import pytest
from gigai_core.budget import BudgetExceeded
from gigai_core.providers import AuthenticationRequired

from test_provider_anthropic import MODEL, REPLIES, request
from tradingresearch.analyze import _model_span
from tradingresearch.providers import errors, with_fallback
from tradingresearch.providers.anthropic import Anthropic, AnthropicError
from tradingresearch.retry import Policy

FALLBACK = "anthropic/claude-haiku-5.5"  # the config id; the adapter sends claude-haiku-5-5
UNAUTHORIZED = {"status": 401, "headers": {},
                "body": {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}}


def answering(*names: str, tries: int):
    """The adapter answering with the named fixtures in order; a 200 reply names the model it was asked, as the API
    does, so the served model is the asked one. Returns it and the API model id of each request sent."""
    asked: list[str] = []
    queue = list(names)

    def handler(req: httpx.Request) -> httpx.Response:
        model = json.loads(req.content)["model"]
        asked.append(model)
        reply = UNAUTHORIZED if (name := queue.pop(0)) == "unauthorized" else REPLIES[name]
        body = {**reply["body"], "model": model} if reply["status"] == 200 else reply["body"]
        return httpx.Response(reply["status"], headers=reply["headers"], json=body)

    provider = Anthropic("FAKEA", policy=Policy(tries=tries, sleep=lambda seconds: None, rng=random.Random(0)))
    provider._http = httpx.Client(base_url=str(provider._http.base_url), headers=provider._http.headers,
                                  transport=httpx.MockTransport(handler))
    return provider, asked


@pytest.mark.parametrize("error", ["server_error", "overloaded", "rate_limited"])
def test_a_retryable_error_after_the_adapters_retries_asks_the_fallback_once(error):
    provider, asked = answering(error, error, error, "success", tries=3)
    span = _model_span(with_fallback(provider, FALLBACK), request(), "parent")
    assert asked == ["claude-sonnet-5-5"] * 3 + ["claude-haiku-5-5"]  # three tries on the asked model, then one
    assert span.error is None and span.call.settings.model == MODEL  # the span keeps what was asked ...
    assert span.call.resolved_model == "claude-haiku-5-5"  # ... and the model that served it: the fallback shows
    # the fallback's price on the success fixture's usage: $0.10 in, $0.50 out, $0.125 5m write, $0.20 1h, $0.01 hit
    assert span.call.cost_usd == pytest.approx((1200 * 0.10 + 300 * 0.50 + 600 * 0.125 + 400 * 0.20 + 4000 * 0.01)
                                               / 1e6)
    assert provider.route_for("Analyze FAKEA.") == "anthropic:claude-haiku-5-5"


def test_a_failing_fallback_is_one_more_invoke_with_the_adapters_retries_then_raises_its_own_error():
    provider, asked = answering("server_error", "server_error", "overloaded", "overloaded", "success", tries=2)
    with pytest.raises(AnthropicError) as caught:
        with_fallback(provider, FALLBACK).invoke(request())
    assert asked == ["claude-sonnet-5-5"] * 2 + ["claude-haiku-5-5"] * 2  # never a third model, never a second round
    assert caught.value.code == "http_529" and caught.value.__context__.code == "http_500"  # the first error kept


def test_a_refusal_comes_back_without_a_fallback_call():
    provider, asked = answering("refusal", "success", tries=4)
    result = with_fallback(provider, FALLBACK).invoke(request())
    assert errors.kind(result) == errors.REFUSED and result.resolved_model == "claude-sonnet-5-5"
    assert asked == ["claude-sonnet-5-5"]


@pytest.mark.parametrize(("name", "raised"), [
    ("unauthorized", AuthenticationRequired),
    ("billing", AnthropicError),
    ("credit_balance", AnthropicError),
    ("spend_limit", AnthropicError),
    ("bad_request", AnthropicError),
])
def test_an_authentication_credit_or_rejected_error_is_raised_without_a_fallback_call(name, raised):
    provider, asked = answering(name, "success", tries=4)
    with pytest.raises(raised):
        with_fallback(provider, FALLBACK).invoke(request())
    assert asked == ["claude-sonnet-5-5"]


class OverBudget:
    """An inner provider whose call is refused by a budget cap, the error a budgeted subject raises before a call."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def invoke(self, request, *, cancel=None):
        self.asked.append(request.settings.model)
        raise BudgetExceeded("the arm's cap would be passed")


def test_a_budget_error_is_raised_without_a_fallback_call():
    inner = OverBudget()
    with pytest.raises(BudgetExceeded):
        with_fallback(inner, FALLBACK).invoke(request())
    assert inner.asked == [MODEL]


def test_the_wrapper_keeps_the_inner_identity_capabilities_and_routes():
    provider, _ = answering("success", tries=1)
    wrapped = with_fallback(provider, FALLBACK)
    wrapped.invoke(request())
    assert (wrapped.identity, wrapped.capabilities) == (provider.identity, provider.capabilities)
    assert wrapped.route_for("Analyze FAKEA.") == "anthropic:claude-sonnet-5-5"
