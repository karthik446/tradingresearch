"""The OpenRouter adapter's week 4 plumbing: tool specs and tool calls on the wire, and the shared retry policy inside
`invoke`. The tool reply is the recorded real gpt-4.1-nano call (re-record with `uv run pytest -m live
tests/test_openrouter.py`), replayed at the HTTP transport; no fake model. The account reads (GET /key, GET
/credits; COST-3b) are replayed the same way, through `account_api`."""

import json
import random
from pathlib import Path

import httpx
import pytest
from gigai_core.providers import CallSettings, ModelRequest, OutputNotJSON, ToolCall, ToolSpec, Turn

from tradingresearch.config import require, settings
from tradingresearch.providers import openrouter
from tradingresearch.providers.openrouter import OpenRouter, OpenRouterError, message
from tradingresearch.retry import Policy

TOOLS = Path(__file__).parent / "fixtures" / "tools"
NAME = "get_close"
MODEL = "openai/gpt-4.1-nano"  # cheap and tool-capable
KEY = "placeholder-not-a-key"


def tool_request() -> ModelRequest:
    """One forced call of one trivial tool: the smallest request that must come back as a tool call."""
    spec = ToolSpec(name=NAME, description="The last daily close of a US stock, in USD.", parameters={
        "type": "object", "additionalProperties": False, "required": ["ticker"],
        "properties": {"ticker": {"type": "string", "description": "The ticker, e.g. AAPL."}},
    })
    return ModelRequest(
        settings=CallSettings(model=MODEL, max_output_tokens=64, tool_choice=NAME),
        turns=(Turn(role="system", content="Answer stock questions with the tools."),
               Turn(role="user", content="What was AAPL's last close?")),
        tools=(spec,),
    )


def recorded(kind: str) -> dict:
    return json.loads((TOOLS / f"{NAME}.{kind}.json").read_text())


def replaying(provider: OpenRouter, *responses: httpx.Response) -> list[dict]:
    """Answer each POST with the next response; returns the bodies sent."""
    sent, queue = [], list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return queue.pop(0)

    provider._http = httpx.Client(base_url=str(provider._http.base_url), transport=httpx.MockTransport(handler))
    return sent


def no_wait() -> Policy:
    return Policy(sleep=lambda s: None, rng=random.Random(0))


def account_api(monkeypatch, key: dict | list[dict], credits: dict, token: str = KEY) -> list[str]:
    """GET /key and GET /credits answered at the transport, no network: successive /key reads take the next entry of
    `key` (the last one repeats). Returns the paths requested in order; a request without the bearer token fails."""
    readings = list(key) if isinstance(key, list) else [key]
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {token}"
        seen.append(request.url.path)
        if request.url.path == "/api/v1/key":
            return httpx.Response(200, json={"data": readings.pop(0) if len(readings) > 1 else readings[0]})
        if request.url.path == "/api/v1/credits":
            return httpx.Response(200, json={"data": credits})
        return httpx.Response(404, json={"error": {"message": "no such endpoint"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: client.get(url, headers=headers))
    return seen


def test_key_reading_and_credits_are_free_reads_of_the_account_that_never_show_the_key(monkeypatch, capsys):
    seen = account_api(monkeypatch, {"label": "tr", "usage": 64.647332, "usage_daily": 0.5, "usage_weekly": 2.25,
                                     "usage_monthly": 9.0, "limit": None, "is_free_tier": False},
                       {"total_credits": 65.0, "total_usage": 64.647332})
    reading = openrouter.key_reading(KEY)
    assert (reading.usage, reading.usage_daily, reading.usage_weekly) == (64.647332, 0.5, 2.25)
    assert openrouter.key_usage(KEY) == 64.647332
    balance = openrouter.credits(KEY)
    assert (balance.total_credits, balance.total_usage, balance.left) == (65.0, 64.647332, 0.352668)
    assert seen == ["/api/v1/key", "/api/v1/key", "/api/v1/credits"]
    assert KEY not in capsys.readouterr().out


def test_a_failed_account_read_raises_the_http_error_with_its_status(monkeypatch):
    def unauthorized(url, headers=None, timeout=None):
        return httpx.Response(401, json={"error": {"message": "No auth credentials found"}}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", unauthorized)
    with pytest.raises(Exception, match="401"):
        openrouter.credits(KEY)


def test_the_tool_request_matches_the_recorded_wire_body_and_the_reply_parses_to_tool_calls():
    provider = OpenRouter("sk-test")
    reply = recorded("reply")
    sent = replaying(provider, httpx.Response(200, json=reply))
    result = provider.invoke(tool_request())
    assert sent == [recorded("request")]
    assert sent[0]["tool_choice"] == {"type": "function", "function": {"name": NAME}}
    [call] = result.tool_calls
    wire = reply["choices"][0]["message"]["tool_calls"][0]
    assert (call.id, call.name, call.arguments) == (wire["id"], NAME, wire["function"]["arguments"])
    assert json.loads(call.arguments) == {"ticker": "AAPL"}
    assert result.finish_reason == "tool_calls" and result.cost_usd == reply["usage"]["cost"]


def test_a_tool_round_trip_sends_the_assistant_call_and_the_tool_answer_back():
    call = ToolCall(id="call_1", name=NAME, arguments='{"ticker":"AAPL"}')
    assistant = message(Turn(role="assistant", content="", tool_calls=(call,)))
    answer = message(Turn(role="tool", content='{"close": 189.5}', tool_call_id="call_1"))
    assert assistant == {"role": "assistant", "content": "", "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": NAME, "arguments": '{"ticker":"AAPL"}'}}]}
    assert answer == {"role": "tool", "content": '{"close": 189.5}', "tool_call_id": "call_1"}


def test_a_request_without_tools_sends_no_tool_fields():
    provider = OpenRouter("sk-test")
    request = ModelRequest(settings=CallSettings(model=MODEL), turns=(Turn(role="user", content="hi"),))
    assert provider.body(request) == {"model": MODEL, "messages": [{"role": "user", "content": "hi"}],
                                      "max_tokens": 1024}
    assert "tools" in provider.capabilities


def test_a_429_then_success_records_one_retry_and_its_error_class():
    provider = OpenRouter("sk-test", policy=no_wait())
    reply = recorded("reply")
    sent = replaying(provider, httpx.Response(429, text="slow down"), httpx.Response(200, json=reply))
    result = provider.invoke(tool_request())
    assert len(sent) == 2 and sent[0] == sent[1]
    assert (result.retry_count, result.last_error_class) == (1, "OpenRouterError")
    assert result.cost_usd == reply["usage"]["cost"]  # the 429 billed nothing


def test_a_connection_error_is_retried_too():
    provider = OpenRouter("sk-test", policy=no_wait())
    reply, calls = recorded("reply"), []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=reply)

    provider._http = httpx.Client(base_url=str(provider._http.base_url), transport=httpx.MockTransport(handler))
    result = provider.invoke(tool_request())
    assert (result.retry_count, result.last_error_class) == (1, "ConnectError") and len(calls) == 2


def test_a_billed_failed_try_is_added_to_the_cost_once():
    provider = OpenRouter("sk-test", policy=no_wait())
    reply = recorded("reply")
    failed = {"error": {"code": 502, "message": "upstream died"}, "usage": {"cost": 0.002}}
    replaying(provider, httpx.Response(200, json=failed), httpx.Response(200, json=reply))
    result = provider.invoke(tool_request())
    assert result.retry_count == 1 and result.cost_status == "provider_reported"
    assert result.cost_usd == pytest.approx(reply["usage"]["cost"] + 0.002)


def test_a_billed_failure_that_gives_up_names_what_it_billed():
    provider = OpenRouter("sk-test", policy=Policy(tries=2, sleep=lambda s: None, rng=random.Random(0)))
    failed = {"error": {"code": 503, "message": "busy"}, "usage": {"cost": 0.001}}
    replaying(provider, httpx.Response(200, json=failed), httpx.Response(200, json=failed))
    with pytest.raises(OpenRouterError) as raised:
        provider.invoke(tool_request())
    assert str(raised.value) == "OpenRouter 503: busy (gave up after 2 tries) (failed tries billed $0.002000)"


def test_a_billed_empty_json_reply_records_its_cost_then_raises():
    request = ModelRequest(settings=CallSettings(model=MODEL, max_output_tokens=64, output_mode="json"),
                           turns=(Turn(role="user", content="Reply in JSON."),))
    empty = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}], "usage": {"cost": 0.0123}}
    provider = OpenRouter("sk-test", policy=no_wait())
    sent = replaying(provider, httpx.Response(200, json=empty))
    with pytest.raises(OutputNotJSON) as raised:
        provider.invoke(request)
    assert len(sent) == 1 and str(raised.value) == "empty reply in JSON mode (failed tries billed $0.012300)"
    unbilled = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
    replaying(provider, httpx.Response(200, json=unbilled))
    with pytest.raises(OutputNotJSON) as raised:
        provider.invoke(request)
    assert str(raised.value) == "empty reply in JSON mode"


def test_a_400_is_not_retried_and_keeps_its_code():
    provider = OpenRouter("sk-test", policy=no_wait())
    sent = replaying(provider, httpx.Response(400, text="bad model"))
    with pytest.raises(OpenRouterError) as raised:
        provider.invoke(tool_request())
    assert len(sent) == 1 and raised.value.code == "http_400" and str(raised.value) == "OpenRouter 400: bad model"


@pytest.mark.live
def test_live_a_forced_tool_call_comes_back_and_is_recorded():
    """One real call (about $0.00003); writes the request and reply fixtures the offline tests replay."""
    provider = OpenRouter(require(settings().openrouter_key, "OPENROUTER_API_KEY"))
    captured: dict[str, dict] = {}

    def keep(response: httpx.Response) -> None:
        response.read()
        captured["request"] = json.loads(response.request.content)
        captured["reply"] = response.json()

    provider._http.event_hooks["response"] = [keep]
    try:
        result = provider.invoke(tool_request())
    finally:
        provider.close()
    [call] = result.tool_calls
    assert call.name == NAME and json.loads(call.arguments) == {"ticker": "AAPL"}
    TOOLS.mkdir(parents=True, exist_ok=True)
    for kind, body in captured.items():  # bodies only: the headers carry the key
        (TOOLS / f"{NAME}.{kind}.json").write_text(json.dumps(body, indent=2) + "\n")
