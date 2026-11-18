"""The served route is provenance (the teacher terms filter and the training set need who served every turn): it is
keyed by the exchange's first user turn and aggregated over all its turns. The week 4 recorded two-turn tool exchange
(tests/fixtures/week4/) is replayed at the HTTP transport; a test that needs another provider edits an in-memory copy
of a reply, never the fixture file."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from gigai_core.providers import CallSettings, ModelRequest, ToolCall, ToolSpec, Turn
from pydantic import ValidationError

from factories import analysis, thesis
from tradingresearch.providers.openrouter import API, OpenRouter, Routing
from tradingresearch.records import clean_route

WEEK4 = Path(__file__).parent / "fixtures" / "week4"


def load(name: str) -> dict:
    return json.loads((WEEK4 / f"{name}.json").read_text())


REQUESTS = [load("turn1.request"), load("turn2.request")]
REPLIES = [load("turn1.reply"), load("turn2.reply")]  # served by Azure, then Google
PROMPT = next(m["content"] for m in REQUESTS[0]["messages"] if m["role"] == "user")  # the item prompt


def request(body: dict) -> ModelRequest:
    """The recorded wire body as the ModelRequest that sends it."""
    turns = tuple(
        Turn(role=m["role"], content=m["content"] or "", tool_call_id=m.get("tool_call_id"),
             tool_calls=tuple(ToolCall(id=c["id"], name=c["function"]["name"], arguments=c["function"]["arguments"])
                              for c in m.get("tool_calls") or ()))
        for m in body["messages"]
    )
    tools = tuple(ToolSpec(name=t["function"]["name"], description=t["function"]["description"],
                           parameters=t["function"]["parameters"]) for t in body["tools"])
    settings = CallSettings(model=body["model"], max_output_tokens=body["max_tokens"], output_mode="schema",
                            json_schema=body["response_format"]["json_schema"]["schema"],
                            tool_choice=body["tool_choice"])
    return ModelRequest(settings=settings, turns=turns, tools=tools)


def replaying(provider: OpenRouter, replies: list[dict]) -> list[dict]:
    """Answer each POST with the next reply; returns the bodies sent."""
    sent, queue = [], list(replies)

    def handler(r: httpx.Request) -> httpx.Response:
        sent.append(json.loads(r.content))
        return httpx.Response(200, json=queue.pop(0))

    provider._http = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return sent


def provided(reply: dict, provider: str | None) -> dict:
    """A copy of a recorded reply naming another provider (None: no provider field)."""
    out = {k: v for k, v in reply.items() if k != "provider"}
    return out if provider is None else out | {"provider": provider}


def exchange(provider: OpenRouter, replies: list[dict]) -> list[dict]:
    """Turn 1, then turn 2 (whose last turn is the tool result) through the real adapter."""
    sent = replaying(provider, replies)
    for body in REQUESTS:
        provider.invoke(request(body))
    return sent


def test_turn_two_of_a_tool_loop_ends_with_a_tool_turn():
    assert REQUESTS[1]["messages"][-1]["role"] == "tool" and REQUESTS[1]["messages"][-1]["content"] != PROMPT


def test_a_two_turn_exchange_from_one_provider_has_that_route():
    provider = OpenRouter("not-a-real-key")
    sent = exchange(provider, [REPLIES[0], provided(REPLIES[1], "Azure")])
    assert sent == REQUESTS  # the replay sends the recorded bodies
    assert provider.route_for(PROMPT) == "openrouter:Azure"
    assert provider.served == [(PROMPT, "openrouter:Azure"), (PROMPT, "openrouter:Azure")]


def test_a_two_turn_exchange_from_two_providers_is_mixed():
    provider = OpenRouter("not-a-real-key")
    exchange(provider, REPLIES)  # as recorded
    assert provider.route_for(PROMPT) == "openrouter:mixed(Azure+Google)"
    assert provider.served == [(PROMPT, "openrouter:Azure"), (PROMPT, "openrouter:Google")]


@pytest.mark.parametrize("missing", [0, 1])
def test_one_reply_without_a_provider_makes_the_exchange_unknown(missing):
    replies = [provided(r, None) if i == missing else r for i, r in enumerate(REPLIES)]
    provider = OpenRouter("not-a-real-key")
    exchange(provider, replies)
    assert provider.route_for(PROMPT) == "openrouter:unknown"


def test_a_null_provider_field_is_unknown_too():
    provider = OpenRouter("not-a-real-key")
    exchange(provider, [r | {"provider": None} for r in REPLIES])
    assert provider.route_for(PROMPT) == "openrouter:unknown"
    assert clean_route("openrouter:Unknown") is False


def test_no_record_is_unknown():
    assert OpenRouter("not-a-real-key").route_for(PROMPT) == "openrouter:unknown"


def test_a_fresh_request_starts_a_new_exchange_for_its_prompt():
    provider = OpenRouter("not-a-real-key")
    exchange(provider, REPLIES)
    replaying(provider, [provided(REPLIES[0], "Google")])
    provider.invoke(request(REQUESTS[0]))
    assert provider.route_for(PROMPT) == "openrouter:Google"
    assert len(provider.served) == 3  # the per-turn log keeps every call


def test_two_pinned_arms_do_not_see_each_others_routes():
    base = OpenRouter("not-a-real-key")
    azure, google = base.routed(Routing(only=("azure",))), base.routed(Routing(only=("google",)))
    replaying(azure, [REPLIES[0]])
    azure.invoke(request(REQUESTS[0]))
    assert azure.route_for(PROMPT) == "openrouter:azure"
    assert google.route_for(PROMPT) == base.route_for(PROMPT) == "openrouter:unknown"
    assert google.served == base.served == []


@pytest.mark.parametrize("route", ["openrouter:mixed(Azure+Google)", "openrouter:unknown", "unknown"])
def test_a_trainable_record_needs_a_clean_route(route):
    with pytest.raises(ValidationError, match="one known provider"):
        analysis(arm="teacher", terms_class="trainable", provider_route=route)
    with pytest.raises(ValidationError, match="one known provider"):
        thesis("an_0", arm="teacher", terms_class="trainable", provider_route=route)


def test_a_clean_trainable_record_and_an_unknown_restricted_one_are_accepted():
    a = analysis(arm="teacher", terms_class="trainable", provider_route="openrouter:deepinfra/fp8/flex")
    t = thesis(a.analysis_id, arm="teacher", terms_class="trainable", provider_route="openrouter:deepinfra/fp8/flex")
    assert (a.provider_route, t.provider_route) == ("openrouter:deepinfra/fp8/flex",) * 2
    assert analysis(provider_route="openrouter:mixed(Azure+Google)").terms_class == "restricted"


@pytest.mark.parametrize(("route", "clean"), [
    ("openrouter:Azure", True),
    ("openrouter:deepinfra/fp8/flex", True),
    ("openrouter", False),  # a bare client name is no provider
    ("openrouter:unknown", False),
    ("openrouter:unknown/flex", False),
    ("unknown", False),
    ("", False),
    ("openrouter:mixed(Azure+Google)", False),
])
def test_clean_route(route, clean):
    assert clean_route(route) is clean
