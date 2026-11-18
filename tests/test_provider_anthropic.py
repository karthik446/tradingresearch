"""The Anthropic adapter, provider selection and the env file (ADR-014), on hand-written fixture replies: no key, no
network. Every failure case is checked against the one taxonomy in `providers/errors.py`."""

from __future__ import annotations

import json
import random
from pathlib import Path

import httpx
import pytest
from gigai_core.providers import (
    AuthenticationRequired, CallSettings, ModelRequest, OutputNotJSON, ToolCall, ToolSpec, Turn,
    UnsupportedRequestField,
)

from tradingresearch import config
from tradingresearch.config import Secret, Settings, read_env_file
from tradingresearch.providers import Anthropic, OpenRouter, check_models, errors, make_provider, prices
from tradingresearch.providers import anthropic
from tradingresearch.providers.anthropic import AnthropicError, WrongProvider, cost, wire_model
from tradingresearch.providers.openrouter import OpenRouterError
from tradingresearch.records import clean_route
from tradingresearch.retry import Policy

FIXTURES = Path(__file__).parent / "fixtures" / "providers"
REPLIES = json.loads((FIXTURES / "anthropic" / "replies.json").read_text())
MODEL = "anthropic/claude-sonnet-5.5"  # the config id; the adapter sends claude-sonnet-5-5
SCHEMA = {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}


def request(mode: str = "schema", **settings) -> ModelRequest:
    extra = {"json_schema": SCHEMA} if mode == "schema" else {}
    return ModelRequest(settings=CallSettings(model=MODEL, max_output_tokens=4000, output_mode=mode,
                                              **extra, **settings),
                        turns=(Turn(role="system", content="You are the analyst."),
                               Turn(role="user", content="Analyze FAKEA.")))


def replying(*names: str, tries: int = 1):
    """An adapter whose HTTP client answers with the named fixtures in order; returns it, the requests it sent and the
    seconds the retry policy slept."""
    sent: list[httpx.Request] = []
    slept: list[float] = []
    queue = list(names)

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(req)
        reply = REPLIES[queue.pop(0)]
        return httpx.Response(reply["status"], headers=reply["headers"], json=reply["body"])

    provider = Anthropic("FAKEA", policy=Policy(tries=tries, sleep=slept.append, rng=random.Random(0)))
    provider._http = httpx.Client(base_url=str(provider._http.base_url), headers=provider._http.headers,
                                  transport=httpx.MockTransport(handler))
    return provider, sent, slept


def cfg(provider: str = "openrouter", **keys: str) -> Settings:
    return Settings(data_dir=Path("data-dev"), alpaca_key_id=Secret(""), alpaca_secret=Secret(""),
                    openrouter_key=Secret(keys.get("openrouter", "")), sec_user_agent="", feed="sip",
                    provider=provider, anthropic_key=Secret(keys.get("anthropic", "")))


# --- model ids ---------------------------------------------------------------------------------------------------

def test_the_config_id_maps_to_the_api_id_and_openrouter_keeps_its_own():
    assert wire_model("anthropic/claude-sonnet-5.5") == "claude-sonnet-5-5"
    assert wire_model("anthropic/claude-opus-5.5") == "claude-opus-5-5"
    assert wire_model("claude-sonnet-5-5") == "claude-sonnet-5-5"
    # OpenRouter's wire body still carries the config id unchanged (the golden fixture is the 18a7209 capture)
    assert json.loads((FIXTURES / "openrouter" / "json.body").read_bytes())["model"] == MODEL


@pytest.mark.parametrize("model", ["deepseek/deepseek-v4-pro", "openai/gpt-6-sol", "anthropic/other-model"])
def test_another_vendor_is_refused_before_any_call(model):
    with pytest.raises(WrongProvider, match="TR_PROVIDER=openrouter"):
        wire_model(model)


# --- request -----------------------------------------------------------------------------------------------------

def test_the_request_is_a_messages_body_with_the_key_in_x_api_key():
    provider, sent, _ = replying("success")
    provider.invoke(request())
    assert len(sent) == 1
    req = sent[0]
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == "FAKEA"
    assert req.headers["anthropic-version"] == anthropic.VERSION
    assert "authorization" not in req.headers
    assert json.loads(req.content) == {
        "model": "claude-sonnet-5-5", "max_tokens": 4000, "system": "You are the analyst.",
        "messages": [{"role": "user", "content": "Analyze FAKEA."}],
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
    }


def test_json_mode_sends_no_format_and_tools_map_to_input_schema():
    provider = Anthropic("FAKEA")
    assert "output_config" not in provider.body(request("json"))
    spec = ToolSpec(name="bars", description="daily bars", parameters={"type": "object", "properties": {}})
    loop = ModelRequest(settings=CallSettings(model=MODEL, tool_choice="required"), tools=(spec,), turns=(
        Turn(role="user", content="Analyze FAKEA."),
        Turn(role="assistant", content="", tool_calls=(ToolCall(id="t1", name="bars", arguments='{"n": 1}'),
                                                       ToolCall(id="t2", name="bars", arguments="{}"))),
        Turn(role="tool", content="[1]", tool_call_id="t1"),
        Turn(role="tool", content="[2]", tool_call_id="t2"),
    ))
    body = provider.body(loop)
    assert body["tools"] == [{"name": "bars", "description": "daily bars", "input_schema": spec.parameters}]
    assert body["tool_choice"] == {"type": "any"}
    assert body["messages"][1] == {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t1", "name": "bars", "input": {"n": 1}},
        {"type": "tool_use", "id": "t2", "name": "bars", "input": {}}]}
    assert body["messages"][2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "[1]"},
        {"type": "tool_result", "tool_use_id": "t2", "content": "[2]"}]}
    assert anthropic.tool_choice("bars") == {"type": "tool", "name": "bars"}
    provider.close()


@pytest.mark.parametrize("field", [{"temperature": 0.2}, {"top_p": 0.9}, {"seed": 1}])
def test_sampling_knobs_are_refused_before_the_call(field):
    provider, sent, _ = replying()
    with pytest.raises(UnsupportedRequestField):
        provider.invoke(request(**field))
    assert sent == []


def test_no_key_is_refused():
    with pytest.raises(AuthenticationRequired):
        Anthropic("")


# --- success -----------------------------------------------------------------------------------------------------

def test_success_records_usage_with_the_cache_cost_and_route():
    provider, _, _ = replying("success")
    result = provider.invoke(request())
    assert result.text == '{"ticker": "FAKEA", "claims": []}'
    assert result.finish_reason == "stop"
    assert result.resolved_model == "claude-sonnet-5-5"
    assert result.usage.input_tokens == 1200 + 1000 + 4000  # uncached + cache writes + cache hits
    assert result.usage.output_tokens == 300
    assert result.usage.raw["response_id"] == "msg_fake_1"
    assert result.usage.raw["cache_read_input_tokens"] == 4000
    assert result.cost_status == "derived"
    # $2 in, $10 out, $2.50 5m write, $4 1h write, $0.10 hit per MTok
    assert result.cost_usd == pytest.approx((1200 * 2 + 300 * 10 + 600 * 2.5 + 400 * 4 + 4000 * 0.1) / 1e6)
    assert result.retry_count == 0
    assert provider.route_for("Analyze FAKEA.") == "anthropic:claude-sonnet-5-5"
    assert clean_route(provider.route_for("Analyze FAKEA."))
    assert provider.identity.provider == "anthropic"


def test_tool_use_reply_returns_calls_and_a_geo_route():
    provider, _, _ = replying("tool_use")
    result = provider.invoke(request("text"))
    assert result.finish_reason == "tool_calls"
    assert result.tool_calls == (ToolCall(id="toolu_fake", name="bars", arguments='{"ticker": "FAKEA"}'),)
    assert result.text == "Looking up the bars."
    assert provider.route_for("Analyze FAKEA.") == "anthropic:claude-sonnet-5-5/us"


def test_routes_and_prices():
    assert clean_route("anthropic:claude-sonnet-5-5")
    assert not clean_route("anthropic:unknown")
    assert not clean_route("anthropic:mixed(a+b)")
    priced = anthropic.prices([MODEL])
    assert priced[MODEL].prompt_usd_per_token == pytest.approx(2 / 1e6)
    assert priced[MODEL].completion_usd_per_token == pytest.approx(10 / 1e6)
    with pytest.raises(KeyError, match="PRICES"):
        anthropic.prices(["anthropic/claude-haiku-9"])
    assert cost("claude-unpriced", {"input_tokens": 1}) is None


# --- failures, each mapped into the taxonomy ---------------------------------------------------------------------

def test_429_honours_retry_after_then_succeeds():
    provider, sent, slept = replying("rate_limited", "success", tries=2)
    result = provider.invoke(request())
    assert len(sent) == 2
    assert slept == [7.0]
    assert result.retry_count == 1
    assert result.last_error_class == "AnthropicError"


@pytest.mark.parametrize(("name", "kind", "code", "retryable"), [
    ("rate_limited", errors.RATE_LIMITED, "rate_limited", True),
    ("billing", errors.CREDIT_EXHAUSTED, "insufficient_credits", False),
    ("credit_balance", errors.CREDIT_EXHAUSTED, "insufficient_credits", False),
    ("overloaded", errors.UPSTREAM_5XX, "http_529", True),
    ("server_error", errors.UPSTREAM_5XX, "http_500", True),
    ("bad_request", errors.REJECTED, "http_400", False),
])
def test_http_failures_map_to_the_taxonomy(name, kind, code, retryable):
    provider, sent, _ = replying(name)
    with pytest.raises(AnthropicError) as caught:
        provider.invoke(request())
    error = caught.value
    assert errors.kind(error) == kind
    assert (error.code, error.retryable) == (code, retryable)
    assert error.retry_after == (7.0 if name == "rate_limited" else None)
    assert REPLIES[name]["body"]["error"]["type"] in str(error)
    assert len(sent) == 1


def test_a_non_retryable_failure_is_tried_once():
    provider, sent, slept = replying("billing", tries=4)
    with pytest.raises(AnthropicError):
        provider.invoke(request())
    assert (len(sent), slept) == (1, [])


def test_not_json_is_output_not_json_and_not_retried():
    provider, sent, _ = replying("not_json", tries=4)
    with pytest.raises(OutputNotJSON) as caught:
        provider.invoke(request())
    assert errors.kind(caught.value) == errors.OUTPUT_NOT_JSON
    assert caught.value.code == "model_output_not_json"
    assert len(sent) == 1


def test_refusal_is_refused_names_the_billed_amount_and_is_not_retried():
    provider, sent, _ = replying("refusal", tries=4)
    with pytest.raises(errors.Refused) as caught:
        provider.invoke(request())
    assert errors.kind(caught.value) == errors.REFUSED
    assert caught.value.code == "model_refused"
    assert "cyber" in str(caught.value) and "billed $0.000250" in str(caught.value)
    assert len(sent) == 1
    assert provider.route_for("Analyze FAKEA.") == anthropic.UNKNOWN


def test_openrouter_errors_share_the_taxonomy():
    assert errors.kind(OpenRouterError(402, "no credit")) == errors.CREDIT_EXHAUSTED
    assert OpenRouterError(402, "no credit").code == "insufficient_credits"
    assert errors.kind(OpenRouterError(503, "down")) == errors.UPSTREAM_5XX
    limited = OpenRouterError(429, "slow down", retry_after=3.0)
    assert (errors.kind(limited), limited.code, limited.retry_after) == (errors.RATE_LIMITED, "rate_limited", 3.0)


# --- selection ---------------------------------------------------------------------------------------------------

def test_tr_provider_picks_the_adapter_and_only_its_key_is_needed():
    champion = make_provider(cfg("anthropic", anthropic="FAKEA"), "champion")
    assert isinstance(champion, Anthropic)
    champion.close()
    teacher = make_provider(cfg("anthropic", openrouter="FAKEA"), "teacher")  # teachers stay on OpenRouter
    assert isinstance(teacher, OpenRouter)
    teacher.close()
    with pytest.raises(SystemExit, match="^ANTHROPIC_API_KEY is not set"):
        make_provider(cfg("anthropic", openrouter="FAKEA"), "champion")
    with pytest.raises(SystemExit, match="^OPENROUTER_API_KEY is not set"):
        make_provider(cfg("openrouter", anthropic="FAKEA"), "judge")


def test_a_model_the_provider_cannot_serve_exits_before_any_call():
    check_models(cfg("anthropic"), "champion", [MODEL])
    check_models(cfg("openrouter"), "judge", ["openai/gpt-6-sol"])
    with pytest.raises(SystemExit, match="openai/gpt-6-sol"):
        check_models(cfg("anthropic"), "judge", ["openai/gpt-6-sol"])
    with pytest.raises(SystemExit, match="deepseek"):
        prices(cfg("anthropic"), "experiment", ["deepseek/deepseek-v4-pro"])
    assert MODEL in prices(cfg("anthropic"), "champion", [MODEL])


# --- env file ----------------------------------------------------------------------------------------------------

def test_the_default_env_file_is_the_repo_root_dot_env():
    root = Path(__file__).resolve().parents[1]
    assert config.DEFAULT_ENV_FILE == root / ".env"
    assert (root / ".env.example").exists()


def test_env_example_names_every_variable_and_holds_no_value(tmp_path, monkeypatch):
    example = Path(__file__).resolve().parents[1] / ".env.example"
    names = read_env_file(example)
    for name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
                 "TR_SEC_USER_AGENT", "TR_PROVIDER", "TR_FEED"):
        assert name in names
    for key in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        assert names[key] == "", f"{key} must be empty in .env.example"
    filled = tmp_path / ".env"
    filled.write_text(example.read_text().replace("ANTHROPIC_API_KEY=", "ANTHROPIC_API_KEY=FAKEA")
                      .replace("TR_PROVIDER=openrouter", "TR_PROVIDER=anthropic"))
    for name in ("TR_PROVIDER", "TR_SEC_USER_AGENT", "TR_FEED", "TR_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TR_ENV_FILE", str(filled))
    loaded = config.settings()
    assert loaded.provider == "anthropic"
    assert loaded.anthropic_key.reveal() == "FAKEA"
    assert loaded.sec_user_agent == names["TR_SEC_USER_AGENT"] and " " in loaded.sec_user_agent  # quotes stripped
    monkeypatch.setenv("TR_PROVIDER", "openai")
    with pytest.raises(SystemExit, match="TR_PROVIDER must be one of openrouter, anthropic"):
        config.settings()
