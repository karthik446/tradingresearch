"""The OpenRouter adapter's week 4 plumbing: tool specs and tool calls on the wire, and the shared retry policy inside
`invoke`. The tool reply is the recorded real gpt-4.1-nano call (re-record with `uv run pytest -m live
tests/test_openrouter.py`), replayed at the HTTP transport; no fake model."""

import json
import random
from pathlib import Path

import httpx
import pytest
from gigai_core.providers import CallSettings, ModelRequest, ToolCall, ToolSpec, Turn

from tradingresearch.config import require, settings
from tradingresearch.openrouter import OpenRouter, OpenRouterError, message
from tradingresearch.retry import Policy

TOOLS = Path(__file__).parent / "fixtures" / "tools"
NAME = "get_close"
MODEL = "openai/gpt-4.1-nano"  # cheap and tool-capable


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
