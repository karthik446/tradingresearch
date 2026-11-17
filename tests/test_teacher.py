"""The teacher arm (SPIKE §9.4, P12): the DeepInfra pin on the wire, the host check, the experiment knob, the stored
records and the CLI refusals. The model reply is the recorded real DeepSeek V4 Pro call of 2026-11-16 (served by
DeepInfra at the flex tier), replayed at the HTTP transport; no fake model."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from gigai_core.budget import Price
from gigai_core.providers import ModelRequest, Turn

from tradingresearch import analyze as an, experiment, journal, teacher as tc, thesis as th
from tradingresearch.cli import main
from tradingresearch.commands.thesis import analysis_for
from tradingresearch.openrouter import API, OpenRouter, RouteMismatch, Routing
from tradingresearch.records import Analysis, IndicatorSnapshot, SourceRef

FIXTURES = Path(__file__).parent / "fixtures"
TEACHER = tc.get("deepseek/deepseek-v4-pro")
REQUEST = json.loads((FIXTURES / "teacher" / "AAPL_2026-11-16.deepseek-v4-pro.request.json").read_text())
REPLY = json.loads((FIXTURES / "teacher" / "AAPL_2026-11-16.deepseek-v4-pro.reply.json").read_text())
RAW_CONTEXT = json.loads((FIXTURES / "teacher" / "AAPL_2026-11-16.context.json").read_text())
PRICE = Price(model=TEACHER.model, prompt_usd_per_token=1.04e-6, completion_usd_per_token=2.08e-6,  # flex listing
              fetched_at=datetime(2026, 11, 16, tzinfo=UTC), source=f"{API}/models/{TEACHER.model}/endpoints")
LIVE_CONTEXT_TOKENS = 1894  # the student tokenizer's count on the live run; it downloads from the HF hub, so pinned
PIN = {"only": ["deepinfra/fp8/flex"], "allow_fallbacks": False, "quantizations": ["fp8", "bf16"]}


def context() -> an.Context:
    """The context the real call was asked about (gathered from Alpaca and EDGAR, 2026-11-16)."""
    raw = RAW_CONTEXT
    return an.Context(raw["ticker"], date.fromisoformat(raw["session"]),
                      IndicatorSnapshot.model_validate_json(json.dumps(raw["snapshot"])),
                      [SourceRef.model_validate_json(json.dumps(s)) for s in raw["sources"]],
                      [an.Row(**r) for r in raw["rows"]])


def replaying(reply: dict, seen: list[dict], routing: Routing | None = TEACHER.routing) -> OpenRouter:
    """The real adapter, its HTTP transport answering with `reply`; `seen` collects the request bodies sent."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=reply)

    provider = OpenRouter("not-a-real-key", routing=routing)
    provider._http = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return provider


def request() -> ModelRequest:
    return ModelRequest(settings=an.call_settings(TEACHER.model),
                        turns=tuple(Turn(role=m["role"], content=m["content"]) for m in REQUEST["messages"]))


@pytest.fixture
def pinned_tokens(monkeypatch):
    monkeypatch.setattr(an, "context_tokens", lambda system, prompt: LIVE_CONTEXT_TOKENS)


def test_every_teacher_is_pinned_to_one_deepinfra_endpoint_without_fallback_or_fp4():
    assert set(tc.TEACHERS) == {"deepseek/deepseek-v4-pro", "qwen/qwen3.5-397b-a17b", "openai/gpt-oss-120b"}
    for t in tc.TEACHERS.values():
        block = t.routing.block()
        assert block["only"] == [t.slug] and t.slug.startswith("deepinfra/") and block["allow_fallbacks"] is False
        assert block["quantizations"] == ["fp8", "bf16"] and t.terms_class == "trainable"
    assert [t.routing.tier for t in tc.TEACHERS.values()] == ["flex", "flex", None]  # gpt-oss has no flex endpoint
    with pytest.raises(SystemExit, match="not a teacher"):
        tc.get("anthropic/claude-sonnet-5.5")


def test_a_teacher_analyze_sends_the_pinned_request_and_stores_a_trainable_teacher_record(tmp_path, pinned_tokens):
    seen: list[dict] = []
    conn = journal.connect(":memory:")
    result = an.analyze(conn, context(), replaying(REPLY, seen), model=TEACHER.model, max_usd=0.10,
                        prices={TEACHER.model: PRICE}, data_dir=tmp_path, arm="teacher",
                        terms_class=TEACHER.terms_class)
    [body] = seen
    assert body == REQUEST  # byte-for-byte the body the live call sent
    assert body["provider"] == PIN and body["service_tier"] == "flex" and "fp4" not in json.dumps(body["provider"])
    a = result.analysis
    assert (a.arm, a.provider_route, a.terms_class, a.model) == (
        "teacher", "openrouter:deepinfra/fp8/flex", "trainable", TEACHER.model)
    assert len(a.claims) + len(result.rejected) == len(json.loads(REPLY["choices"][0]["message"]["content"])["claims"])
    assert journal.get(conn, Analysis, a.analysis_id) == a
    [call] = [json.loads(line)["call"] for line in Path(result.trace_path).read_text().splitlines()
              if json.loads(line).get("call")]
    assert call["resolved_model"] == REPLY["model"] == "deepseek/deepseek-v4-pro"
    assert call["identity"]["provider"] == "openrouter:only=deepinfra/fp8/flex,allow_fallbacks=false,quantizations=fp8+bf16"
    assert call["cost_usd"] == REPLY["usage"]["cost"]


@pytest.mark.parametrize("changes", [{"provider": "SiliconFlow"}, {"provider": "Novita"}, {"service_tier": "default"},
                                     {"service_tier": None}])
def test_a_reply_from_another_host_or_tier_is_an_error_never_a_reroute(changes):
    altered = {**REPLY, **changes}
    seen: list[dict] = []
    with pytest.raises(RouteMismatch, match="pinned to") as refused:
        replaying(altered, seen).invoke(request())
    assert refused.value.code == "route_mismatch" and not refused.value.retryable


def test_the_analyze_run_fails_on_a_wrong_host_after_one_call(tmp_path, pinned_tokens):
    seen: list[dict] = []
    with pytest.raises(SystemExit, match="model call failed: route_mismatch"):
        an.analyze(journal.connect(":memory:"), context(), replaying({**REPLY, "provider": "SiliconFlow"}, seen),
                   model=TEACHER.model, max_usd=0.10, prices={TEACHER.model: PRICE}, data_dir=tmp_path,
                   arm="teacher", terms_class="trainable")
    assert len(seen) == 1  # not retried, not sent elsewhere


def test_without_a_routing_the_request_is_the_plain_claude_route_request():
    seen: list[dict] = []
    provider = replaying(REPLY, seen, routing=None)
    provider.invoke(request())
    assert set(seen[0]) == {"model", "messages", "max_tokens", "response_format"}
    assert provider.identity.provider == "openrouter"
    assert provider.route_for(REQUEST["messages"][-1]["content"]) == "openrouter:DeepInfra"


def config(tmp_path, provider: str) -> Path:
    path = tmp_path / "exp.toml"
    path.write_text(f'name = "x"\nmodel = "{TEACHER.model}"\nmax_usd_per_arm = 0.1\ntickers = ["AAPL"]\n'
                    'sessions = ["2026-11-16"]\ngraders = ["parsed", "claims_valid"]\n'
                    f'[[arms]]\nname = "teacher"\nprompt = "analyze-1"\n{provider}')
    return path


def test_an_experiment_arm_provider_table_reaches_the_request_and_the_run_record(tmp_path, pinned_tokens):
    path = config(tmp_path, '[arms.provider]\nonly = ["deepinfra/fp8/flex"]\nallow_fallbacks = false\n'
                            'quantizations = ["fp8", "bf16"]\n')
    loaded = experiment.load(path)
    assert loaded.arms[0].provider == TEACHER.routing
    seen: list[dict] = []
    conn = journal.connect(":memory:")
    [r] = experiment.run_arms(conn, loaded, [context()], replaying(REPLY, seen, routing=None),
                              {TEACHER.model: PRICE}, tmp_path)
    assert seen[0]["provider"] == PIN and seen[0]["service_tier"] == "flex"
    assert r.run.record.provider.provider.startswith("openrouter:only=deepinfra/fp8/flex,")
    stored = conn.execute("SELECT body FROM analysis").fetchone()[0]
    assert json.loads(stored)["provider_route"] == "openrouter:deepinfra/fp8/flex"
    assert experiment.load(config(tmp_path, "")).arms[0].provider is None


@pytest.mark.parametrize(("table", "error"), [
    ('order = ["deepinfra"]', "unknown provider key"),
    ('allow_fallbacks = "no"', "allow_fallbacks must be"),
    ('quantizations = ["fp5"]', "quantizations must be"),
    ('only = "deepinfra/fp8/flex"', "only must be a list"),
])
def test_a_bad_experiment_provider_table_fails_at_load_before_any_spend(tmp_path, table, error):
    with pytest.raises(SystemExit, match=f"arm teacher: .*{error}"):
        experiment.load(config(tmp_path, f"[arms.provider]\n{table}\n"))


def test_a_teacher_thesis_record_carries_the_arm_route_and_terms():
    analysis = Analysis.model_validate_json((FIXTURES / "thesis" / "AAPL_2026-11-16.analysis.json").read_text())
    teacher = analysis.model_copy(update={"arm": "teacher", "terms_class": "trainable", "model": TEACHER.model})
    reply = json.loads((FIXTURES / "thesis" / "AAPL_2026-11-16.reply.json").read_text())
    conn = journal.connect(":memory:")
    journal.add_analysis(conn, teacher, sources=[])
    written = th.Written("teacher", datetime(2026, 11, 17, 3, 46, tzinfo=UTC), "trace_test", TEACHER.route,
                         TEACHER.terms_class, "sha256:" + "3" * 64)
    [t] = th.store(conn, th.validate(reply, teacher, ("day", "short", "swing"), written)).theses
    assert (t.arm, t.provider_route, t.terms_class) == ("teacher", "openrouter:deepinfra/fp8/flex", "trainable")


@pytest.mark.parametrize("argv", [
    ["analyze", "AAPL", "--arm", "teacher"],
    ["thesis", "AAPL", "--arm", "teacher"],
    ["analyze", "AAPL", "--teacher", TEACHER.model],
    ["thesis", "AAPL", "--teacher", TEACHER.model],
    ["analyze", "AAPL", "--arm", "teacher", "--teacher", TEACHER.model, "--model", "anthropic/claude-opus-5.5"],
])
def test_the_teacher_flags_are_refused_together_wrong_before_any_call(argv, tmp_path, monkeypatch):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "verify.env"))
    with pytest.raises(SystemExit, match="--arm teacher|--teacher|--model is for"):
        main(argv)
    assert not (tmp_path / "journal.db").exists()  # refused before the journal, the market data or the model


def test_a_teacher_thesis_needs_an_analysis_by_the_same_teacher():
    analysis = Analysis.model_validate_json((FIXTURES / "thesis" / "AAPL_2026-11-16.analysis.json").read_text())
    teacher = analysis.model_copy(update={"arm": "teacher", "terms_class": "trainable", "model": TEACHER.model})
    conn = journal.connect(":memory:")
    journal.add_analysis(conn, teacher, sources=[])
    args = SimpleNamespace(ticker="AAPL", session="2026-11-16", analysis=teacher.analysis_id, arm="teacher",
                           teacher=TEACHER.model)
    assert analysis_for(conn, args) == teacher
    with pytest.raises(SystemExit, match="written by deepseek/deepseek-v4-pro, not qwen/qwen3.5-397b-a17b"):
        analysis_for(conn, SimpleNamespace(**{**vars(args), "teacher": "qwen/qwen3.5-397b-a17b"}))


def test_the_teacher_prompt_is_analyze3_with_the_headlines_withheld(tmp_path, pinned_tokens):
    from tradingresearch import news
    ctx = context()
    retrieved = datetime(2026, 11, 16, 22, 0, tzinfo=UTC)
    article = {"id": 7, "headline": "Placeholder headline", "url": "https://x.test", "source": "benzinga",
               "symbols": ["AAPL"], "created_at": "2026-11-16T15:00:00Z"}
    news.store(tmp_path, "AAPL", [news.normalise(article, retrieved)])  # in the store, so only the drop keeps it out
    assert an.with_headlines(ctx, tmp_path, "analyze-3").headlines != ()
    seen: list[dict] = []
    conn = journal.connect(":memory:")
    result = an.analyze(conn, ctx, replaying(REPLY, seen), model=TEACHER.model, max_usd=0.10,
                        prices={TEACHER.model: PRICE}, data_dir=tmp_path, arm="teacher",
                        terms_class=TEACHER.terms_class, prompt_version=tc.PROMPT, drop=tc.DROP)
    [body] = seen
    system, user = (m["content"] for m in body["messages"])
    assert (tc.PROMPT, tc.DROP) == ("analyze-3", ("headlines",))
    assert system == an.system_prompt("analyze-3") and "| headline " not in user and user == an.render(ctx)
    a = result.analysis
    assert a.prompt_version == "analyze-3" and a.arm == "teacher"
    assert a.input_hash == an.input_hash(ctx, "analyze-3", drop=tc.DROP) != an.input_hash(ctx, "analyze-3")
    assert conn.execute("SELECT count(*) FROM source_ref WHERE kind = 'news'").fetchone() == (0,)
    assert th.cited_headlines(conn, a, tmp_path) == ()  # the thesis step sees no untrusted headline either


@pytest.mark.parametrize(("prompt", "drop"), [("analyze-1", ("headlines",)), ("analyze-3", ("edgar",)),
                                              ("analyze-3", ("headlines", "edgar"))])
def test_analyze_drops_only_the_headlines_and_only_on_a_prompt_that_shows_them(tmp_path, prompt, drop):
    with pytest.raises(ValueError, match="only"):
        an.analyze(journal.connect(":memory:"), context(), replaying(REPLY, []), model=TEACHER.model, max_usd=0.10,
                   prices={TEACHER.model: PRICE}, data_dir=tmp_path, prompt_version=prompt, drop=drop)
