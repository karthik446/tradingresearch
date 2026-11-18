"""The OpenRouter adapter's wire bodies are byte-identical to master `18a7209`, before the move into `providers/`.
The golden files were captured from the unmodified `tradingresearch/openrouter.py`; a mismatch
means the move changed what OpenRouter is sent. Re-capture only on a deliberate wire change, never to make this pass."""

from pathlib import Path

import httpx
import pytest
from gigai_core.providers import CallSettings, ModelRequest, ToolCall, ToolSpec, Turn

from tradingresearch.providers.openrouter import OpenRouter, Routing

GOLDEN = Path(__file__).parent / "fixtures" / "providers" / "openrouter"
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["claims"],
          "properties": {"claims": {"type": "array", "items": {"type": "string"}}}}
SYSTEM = Turn(role="system", content="You write claims — each one cites a source.")
USER = Turn(role="user", content="AAPL 2026-11-16: close 231.40, 20d high 233.10 (≈ -0.7%).")
TOOL = ToolSpec(name="get_close", description="The last daily close of a US stock, in USD.", parameters={
    "type": "object", "additionalProperties": False, "required": ["ticker"],
    "properties": {"ticker": {"type": "string", "description": "The ticker, e.g. AAPL."}},
})
REPLY = {"id": "gen-1", "model": "m", "provider": "DeepInfra", "service_tier": "flex",
         "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "cost": 0.0}}


def requests() -> dict[str, tuple[ModelRequest, Routing | None]]:
    """Every request shape the code sends: analyze/thesis (schema), json, the judge (text), a tool loop turn, and the
    teacher pins (one flex slug; two slugs with no tier)."""
    schema = CallSettings(model="anthropic/claude-sonnet-5.5", max_output_tokens=4000, output_mode="schema",
                          json_schema=SCHEMA)
    call = ToolCall(id="call_1", name="get_close", arguments='{"ticker":"AAPL"}')
    return {
        "schema": (ModelRequest(settings=schema, turns=(SYSTEM, USER)), None),
        "json": (ModelRequest(settings=CallSettings(model="anthropic/claude-sonnet-5.5", max_output_tokens=3000,
                                                    output_mode="json"), turns=(SYSTEM, USER)), None),
        "judge": (ModelRequest(settings=CallSettings(model="openai/gpt-6-sol", max_output_tokens=800),
                               turns=(USER,)), None),
        "tools": (ModelRequest(settings=CallSettings(model="openai/gpt-4.1-nano", max_output_tokens=64,
                                                     tool_choice="get_close"),
                               turns=(SYSTEM, USER, Turn(role="assistant", content="", tool_calls=(call,)),
                                      Turn(role="tool", content='{"close": 231.4}', tool_call_id="call_1")),
                               tools=(TOOL,)), None),
        "teacher_flex": (ModelRequest(settings=schema.model_copy(update={"model": "deepseek/deepseek-v4-pro"}),
                                      turns=(SYSTEM, USER)),
                         Routing(only=("deepinfra/fp8/flex",), allow_fallbacks=False,
                                 quantizations=("fp8", "bf16"))),
        "teacher_two": (ModelRequest(settings=schema.model_copy(update={"model": "qwen/qwen3-235b-a22b-2507"}),
                                     turns=(SYSTEM, USER)),
                        Routing(only=("deepinfra/fp8", "novita/fp8"), allow_fallbacks=False)),
    }


def wire(request: ModelRequest, routing: Routing | None) -> bytes:
    """The exact bytes `invoke` POSTs for `request`, caught at the HTTP transport."""
    provider = OpenRouter("FAKEA")
    if routing is not None:
        provider = provider.routed(routing)
    sent: list[bytes] = []

    def handler(r: httpx.Request) -> httpx.Response:
        sent.append(r.content)
        return httpx.Response(200, json=REPLY | {"provider": "DeepInfra"})

    provider._http = httpx.Client(base_url=str(provider._http.base_url), transport=httpx.MockTransport(handler))
    try:
        provider.invoke(request)
    except Exception:  # noqa: BLE001 - a route check on the canned reply may refuse; the body was already sent
        pass
    return sent[0]


@pytest.mark.parametrize("case", sorted(requests()))
def test_the_openrouter_wire_body_is_byte_identical_to_master(case):
    request, routing = requests()[case]
    assert wire(request, routing) == (GOLDEN / f"{case}.body").read_bytes()
