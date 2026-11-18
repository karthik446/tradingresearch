"""The `mode`, `drop`, `guards`, `kind`, `inject`, `thesis_prompt`, `route` and `cache` arm knobs (REPO-PLAN §2.4
week 4, §2.5 week 5, GUARDS-SPIKE §8.2 week 7, G15-SPIKE §1.1 and §1.2 week 8), checked at config load, and a guards
arm run at $0. tests/test_week4.py runs a tools arm, tests/test_masking.py two drop arms, tests/test_injection.py the
pipeline arm, tests/test_fallback.py the route's fallback, tests/test_provider_anthropic.py the cached wire body."""

import json
import re
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_guards import make, registry  # noqa: F401
from test_headlines import reply as headline_reply, stored, week, with_news
from test_injection import ADD, answering, config as inject_config, row as injection_row
from test_masking import TICKERS, keyed, pinned_tokens, served, ten, user_turn  # noqa: F401
from test_teacher import context as teacher_context
from test_thesis import ALL, ANALYSIS
from test_week4 import MODEL, context, prices
from tradingresearch import analyze as an, experiment, guards, injection, journal, news, thesis as th
from tradingresearch.commands import exp
from tradingresearch.evals import GRADERS
from tradingresearch.providers.openrouter import OpenRouterError
from tradingresearch.retrieval.store import Passage, Retrieved

CONFIG = """name = "modes"
model = "openai/gpt-4.1-nano"
max_usd_per_arm = 0.01
tickers = ["AAPL"]
sessions = ["2026-11-13"]
graders = ["parsed"]

[[arms]]
name = "baseline"
prompt = "analyze-1"
"""


def config(tmp_path: Path, mode: str | None) -> Path:
    path = tmp_path / "modes.toml"
    path.write_text(CONFIG + (f'mode = "{mode}"\n' if mode else ""))
    return path


def test_mode_defaults_to_fixed_and_accepts_tools(tmp_path):
    assert experiment.load(config(tmp_path, None)).arms[0].mode == "fixed"
    assert experiment.load(config(tmp_path, "tools")).arms[0].mode == "tools"


def test_an_unknown_mode_is_refused_at_load(tmp_path):
    path = config(tmp_path, "agentic")
    with pytest.raises(SystemExit, match=r"arm baseline: mode must be one of fixed, tools, not 'agentic'"):
        experiment.load(path)


def with_drop(tmp_path: Path, line: str) -> Path:
    path = tmp_path / "drop.toml"
    path.write_text(CONFIG + line + "\n")
    return path


def test_drop_defaults_to_empty_and_takes_section_names(tmp_path):
    assert experiment.load(config(tmp_path, None)).arms[0].drop == ()
    assert experiment.load(with_drop(tmp_path, "drop = []")).arms[0].drop == ()
    assert experiment.load(with_drop(tmp_path, 'drop = ["edgar", "levels"]')).arms[0].drop == ("edgar", "levels")


@pytest.mark.parametrize(("line", "why"), [
    ('drop = ["news"]', "unknown section(s) news; sections: indicators, levels, edgar, headlines"),
    ('drop = ["headlines"]', "prompt analyze-1 renders no headlines; dropping them needs a prompt that shows them"),
    ('drop = "edgar"', "must be a list of section names"),
    ("drop = [1]", "must be a list of section names"),
    ('drop = ["edgar", "edgar"]', "names a section twice"),
    ('drop = ["indicators", "levels", "edgar"]', "names every section"),
    ('mode = "tools"\ndrop = ["edgar"]', "a tools arm has none"),
])
def test_a_bad_drop_is_refused_at_load(tmp_path, line, why):
    with pytest.raises(SystemExit, match=r"arm baseline: drop.*" + re.escape(why)):
        experiment.load(with_drop(tmp_path, line))


# input_hash values computed at the G14a commit (efb756d), before the guards, injection and dropped joins existed
PINNED = {
    "analyze-1": "sha256:9c6107fbda021092856d181f9bd6e90746cf8db4a77c04eeb55f554304788a2d",
    "analyze-3": "sha256:501764cab5e3bf27ea8abb57e8aea00044349816c67005602172a43347299803",
    "drop-edgar": "sha256:35af00205eab299c56dc95b6b53da4e07f8f3a2796171d64571d86d1e0cf3789",
    "teacher": "sha256:342567c15d797b2023e480e544d661771e4ba76708328f765f9b1e536b2a80e4",
    "retrieval": "sha256:2c064f9dced34bdcb8fa93baf0eb8f30c340385f552d8cc5c646b5ef37ccdc15",
    "headlines": "sha256:ff8c05903109ef356fe9efc0b5a367797ae6d2517e7c5e340d9af48efa4bad10",
    "thesis-swing": "sha256:d1f397f638a6755a115a0420bb3cb8a445c3def9cd7375603249cd5d6b28b671",
    "thesis-playbook": "sha256:b174e021a41ba00878a5cea3df5551955fefa2c9ce72d936a7d69667a8bef2d1",
}
RETRIEVED = Retrieved("FAKEA", date(2026, 11, 13), "bm25", 2, "sha256:" + "a" * 64, "q", "{ticker}",
                      (Passage("ch_1", "sha256:" + "b" * 64, 1.0, "t"),), 0)


def test_input_hashes_without_guards_or_injection_are_unchanged(tmp_path):
    ctx = context()
    found = {
        "analyze-1": an.input_hash(ctx, "analyze-1", guard_ids=(), injection=None, dropped=frozenset()),
        "analyze-3": an.input_hash(ctx, "analyze-3"),
        "drop-edgar": an.input_hash(ctx, "analyze-1", drop=("edgar",)),
        "teacher": an.input_hash(teacher_context(), "analyze-1"),
        "retrieval": an.input_hash(ctx, "analyze-1", retrieval=RETRIEVED),
        "headlines": an.input_hash(with_news(tmp_path), "analyze-3"),
        "thesis-swing": th.input_hash(ANALYSIS, ("swing",), "thesis-1", guard_ids=()),
        "thesis-playbook": th.input_hash(ANALYSIS, ALL, "thesis-1", "sha256:" + "0" * 64),
    }
    assert found == PINNED
    joined = {an.input_hash(ctx, "analyze-1", guard_ids=("plain_text",)),
              an.input_hash(ctx, "analyze-1", injection={"id": "x", "sha256": "sha256:" + "c" * 64}),
              an.input_hash(ctx, "analyze-1", dropped=frozenset({"src_x"}))}
    assert len(joined) == 3 and PINNED["analyze-1"] not in joined  # each join is its own input
    assert th.input_hash(ANALYSIS, ("swing",), "thesis-1", guard_ids=("plain_text",)) != PINNED["thesis-swing"]


def test_a_guard_rules_version_is_part_of_both_hashes(monkeypatch):
    ctx, ids = context(), ("plain_text",)
    before = (an.input_hash(ctx, "analyze-1", guard_ids=ids), th.input_hash(ANALYSIS, ("swing",), "thesis-1", guard_ids=ids))
    monkeypatch.setattr(guards.RULES["plain_text"], "version", "2")  # a rule edit bumps its version
    after = (an.input_hash(ctx, "analyze-1", guard_ids=ids), th.input_hash(ANALYSIS, ("swing",), "thesis-1", guard_ids=ids))
    assert before[0] != after[0] and before[1] != after[1]


GUARDED = """name = "guards-pair"
model = "{model}"
max_usd_per_arm = 1.0
tickers = {tickers}
sessions = ["2026-11-13"]
graders = ["parsed", "all_claims_valid", "inferences_grounded"]

[[arms]]
name = "full"
prompt = "analyze-3"

[[arms]]
name = "guarded"
prompt = "{prompt}"
"""


def guarded(tmp_path: Path, lines: str, prompt: str = "analyze-3") -> Path:
    path = tmp_path / "guards.toml"
    path.write_text(GUARDED.format(model=MODEL, tickers=json.dumps(list(TICKERS)), prompt=prompt) + lines + "\n")
    return path


@pytest.fixture
def fake_rules(registry):  # noqa: F811
    guards.rule(make("fakea_fetched", "fetched", "drop"))
    guards.rule(make("fakea_thesis", "thesis", "flag"))


def test_guards_default_to_none_and_take_registered_ids(tmp_path, fake_rules):
    assert experiment.load(guarded(tmp_path, "")).arms[1].guards == ()
    assert experiment.load(guarded(tmp_path, 'guards = ["fakea_fetched"]')).arms[1].guards == ("fakea_fetched",)
    pipeline = experiment.load(guarded(tmp_path, 'kind = "pipeline"\nguards = ["fakea_fetched", "fakea_thesis"]'))
    assert (pipeline.arms[1].kind, pipeline.arms[1].guards) == ("pipeline", ("fakea_fetched", "fakea_thesis"))
    assert pipeline.arms[1].thesis_prompt == th.DEFAULT_PROMPT and pipeline.arms[0].kind == "analyze"


@pytest.mark.parametrize(("lines", "prompt", "why"), [
    ('guards = ["nope"]', "analyze-3", "guards: unknown rule(s) nope; registered:"),
    ('guards = "fakea_fetched"', "analyze-3", "guards must be a list of rule ids"),
    ('guards = ["fakea_fetched", "fakea_fetched"]', "analyze-3", "guards names a rule twice"),
    ('guards = ["thesis_rules"]', "analyze-3", "guards: thesis_rules always runs"),
    ('mode = "tools"\nguards = ["fakea_fetched"]', "analyze-3", "fetched rule(s) fakea_fetched scan headlines"),
    ('drop = ["headlines"]\nguards = ["fakea_fetched"]', "analyze-3", "fetched rule(s) fakea_fetched scan headlines"),
    ('guards = ["fakea_fetched"]', "analyze-1", "fetched rule(s) fakea_fetched scan headlines"),
    ('guards = ["fakea_thesis"]', "analyze-3", "thesis rule(s) fakea_thesis check theses"),
    ('guards = ["plain_text"]', "analyze-3", "thesis rule(s) plain_text check theses"),
    ('kind = "nope"', "analyze-3", "kind must be one of analyze, pipeline"),
    ('kind = "pipeline"\nmode = "tools"', "analyze-3", "a tools arm has none"),
    ("inject = 1", "analyze-3", "inject must be true or false"),
    ("inject = true", "analyze-3", "only a pipeline arm"),
    ('thesis_prompt = "thesis-1"', "analyze-3", "only a pipeline arm"),
    ('kind = "pipeline"\nthesis_prompt = "thesis-2"', "analyze-3", "without the journal's playbook"),
    ('kind = "pipeline"\ninject = true', "analyze-3", "the config names no injections file"),
])
def test_a_bad_guards_kind_or_inject_knob_is_refused_at_load(tmp_path, fake_rules, lines, prompt, why):
    with pytest.raises(SystemExit, match=re.escape(why)):
        experiment.load(guarded(tmp_path, lines, prompt))


@pytest.mark.parametrize("lines", ['guards = ["nope"]', 'mode = "tools"\nguards = ["fakea_fetched"]'])
def test_a_bad_guards_id_or_a_fetched_rule_on_a_tools_arm_exits_before_any_call(tmp_path, fake_rules, lines):
    sent: list[dict] = []
    conn = journal.connect(tmp_path / "journal.db")
    with pytest.raises(SystemExit, match="arm guarded: guards"):
        experiment.run_arms(conn, experiment.load(guarded(tmp_path, lines)), ten(), keyed({}, sent), prices(),
                            tmp_path)
    assert sent == []
    assert not (tmp_path / "runs").exists()
    assert conn.execute("SELECT count(*) FROM analysis").fetchone() == (0,)


def test_a_guards_arm_sends_the_guarded_turn_and_audits_and_hashes_the_drop(tmp_path, registry,  # noqa: F811
                                                                          pinned_tokens):  # noqa: F811
    newest = week()[7]  # the latest headline in the window: the one the rule drops
    guards.rule(make("fakea_drop", "fetched", "drop",
                     hits=lambda row: row.kind == "headline" and row.text == newest.headline))
    for ticker in TICKERS:
        stored(tmp_path, ticker)
    cite = news.source_ref(newest).source_id
    contexts = [an.with_headlines(ctx, tmp_path, "analyze-3") for ctx in ten()]
    full_text = [an.render(ctx) for ctx in contexts]
    guarded_text = ["\n".join(line for line in text.split("\n") if not line.startswith(cite)) for text in full_text]
    replies = ({p: served(headline_reply(cite), "Google") for p in full_text}
               | {p: served(headline_reply(cite), "DeepInfra") for p in guarded_text})
    sent: list[dict] = []
    conn = journal.connect(tmp_path / "journal.db")
    config = experiment.load(guarded(tmp_path, 'guards = ["fakea_drop"]'))
    full, kept = experiment.run_arms(conn, config, ten(), keyed(replies, sent), prices(), tmp_path)
    assert [user_turn(body) for body in sent] == full_text + guarded_text
    assert [user_turn(body).count("| headline 2026-11-13 ") for body in sent] == [5] * 10 + [4] * 10
    assert experiment.means(full.run)["all_claims_valid"] == (1.0, 10)
    assert experiment.means(kept.run)["all_claims_valid"] == (0.0, 10)  # the claim citing the dropped row

    text = (tmp_path / guards.AUDIT_FILE).read_text()
    audit = [json.loads(line) for line in text.splitlines()]
    assert newest.headline not in text  # the digest only
    assert len(audit) == 10 and {(a["stage"], a["decision"], a["rule"], a["subject"]["kind"], a["subject"]["id"],
                                  a["arm"], tuple(a["guards"]), a["run_id"]) for a in audit} == {
        ("fetched", "drop", "fakea_drop", "headline", cite, "guarded", ("fakea_drop",), kept.run.record.run_id)}
    expected = {an.input_hash(ctx, "analyze-3", guard_ids=("fakea_drop",), dropped=frozenset({cite}))
                for ctx in contexts}
    assert {a["input_hash"] for a in audit} == expected
    rows = conn.execute("SELECT json_extract(body, '$.input_hash'), json_extract(body, '$.provider_route') "
                        "FROM analysis WHERE json_extract(body, '$.run_id') = ?", (kept.run.record.run_id,)).fetchall()
    assert {h for h, _ in rows} == expected and {r for _, r in rows} == {"openrouter:DeepInfra"}
    assert not expected & {an.input_hash(ctx, "analyze-3") for ctx in contexts}


def test_the_guarded_provider_never_sends_a_prompt_it_has_no_view_of():
    wrapper = experiment.Guarded(object(), {"item prompt": "guarded view"})
    assert wrapper.guarded("item prompt") == "guarded view"
    assert wrapper.guarded("guarded view") == "guarded view"  # guarding twice is a no-op
    with pytest.raises(ValueError, match="no guarded view"):
        wrapper.guarded("some other text")


# ---------- the `route` knob: a model per pipeline step, plus a fallback (G15-SPIKE §1.1) ----------

ANALYZE, THESIS, FALLBACK = "fakea/analyze-model", "fakea/thesis-model", "fakea/fallback-model"


def priced(models) -> dict:
    """The recorded price under each model id: CallBudget refuses a model with no price."""
    base = prices()[MODEL]
    return {model: base.model_copy(update={"model": model}) for model in models}


def test_a_pipeline_arm_routes_its_steps_and_a_missing_key_uses_the_arm_model(tmp_path):
    full = f'kind = "pipeline"\nroute = {{ analyze = "{ANALYZE}", thesis = "{THESIS}", fallback = "{FALLBACK}" }}'
    routed = experiment.load(guarded(tmp_path, full)).arms[1]
    assert routed.route == experiment.Route(ANALYZE, THESIS, FALLBACK)
    assert (routed.analyze_model, routed.thesis_model) == (ANALYZE, THESIS)
    loaded = experiment.load(guarded(tmp_path, f'kind = "pipeline"\nroute = {{ thesis = "{THESIS}" }}'))
    arm = loaded.arms[1]
    assert (arm.analyze_model, arm.thesis_model, arm.route.fallback) == (MODEL, THESIS, None)
    assert experiment.models(loaded) == sorted({MODEL, THESIS})
    plain = experiment.load(guarded(tmp_path, 'kind = "pipeline"')).arms
    assert {a.route for a in plain} == {experiment.Route()} and {a.thesis_model for a in plain} == {MODEL}


@pytest.mark.parametrize(("lines", "why"), [
    (f'route = {{ analyze = "{ANALYZE}" }}',
     'arm guarded: route: only a pipeline arm (kind = "pipeline") routes its steps; an analyze arm sets its own '
     "`model`"),
    (f'kind = "pipeline"\nroute = {{ judge = "{ANALYZE}" }}',
     "arm guarded: route: unknown key(s) judge; keys: analyze, thesis, fallback"),
    (f'kind = "pipeline"\nroute = "{ANALYZE}"', "arm guarded: route must be a table with analyze, thesis, fallback"),
    ('kind = "pipeline"\nroute = { thesis = 1 }', "arm guarded: route: thesis must be a model id"),
    ('kind = "pipeline"\nroute = { fallback = "" }', "arm guarded: route: fallback must be a model id"),
])
def test_a_bad_route_is_refused_at_load(tmp_path, lines, why):
    with pytest.raises(SystemExit, match=re.escape(why)):
        experiment.load(guarded(tmp_path, lines))


def injected_cite(tmp_path: Path) -> str:
    """Headlines stored for the ten tickers; the id of the headline the injection row adds to FAKEA's day."""
    for ticker in TICKERS:
        stored(tmp_path, ticker)
    shown = an.with_headlines(ten()[0], tmp_path, "analyze-3")
    return news.source_ref(injection.headlines(shown, injection_row()).headlines[-1]).source_id


def test_a_routed_pipeline_arm_sends_each_step_to_its_model_and_keeps_its_input_hash(tmp_path,
                                                                                   pinned_tokens):  # noqa: F811
    cite = injected_cite(tmp_path)
    sent: list[dict] = []
    path = inject_config(tmp_path, ADD, extra=f'route = {{ analyze = "{ANALYZE}", thesis = "{THESIS}" }}\n')
    clean, injected = experiment.run_arms(journal.connect(tmp_path / "journal.db"), experiment.load(path), ten(),
                                          answering(sent, cite), priced([MODEL, ANALYZE, THESIS]), tmp_path)
    assert [body["model"] for body in sent] == [MODEL, MODEL, ANALYZE, THESIS]  # analyze, thesis per arm
    outcome = injected.outcomes["FAKEA:2026-11-13:fakea-h1"]
    assert outcome.analysis.model == ANALYZE and clean.outcomes["FAKEA:2026-11-13"].analysis.model == MODEL
    # the model is not part of input_hash today, and a route does not change that: the routed arm's analysis has the
    # hash the unrouted injected arm records (tests/test_injection.py)
    shown = an.with_headlines(ten()[0], tmp_path, "analyze-3")
    assert outcome.analysis.input_hash == an.input_hash(injection.headlines(shown, outcome.injection), "analyze-3",
                                                        guard_ids=("plain_text",),
                                                        injection=injection.hashed(outcome.injection))


def test_tr_exp_run_checks_and_prices_every_route_model_and_prints_each_arms_route(tmp_path,
                                                                                 pinned_tokens,  # noqa: F811
                                                                                 monkeypatch, capsys):
    monkeypatch.delitem(GRADERS, experiment.RESISTED, raising=False)
    cite = injected_cite(tmp_path)
    sent: list[dict] = []
    checked: list[list[str]] = []
    asked: list[list[str]] = []
    by_ticker = {ctx.ticker: ctx for ctx in ten()}
    monkeypatch.setattr(an, "gather", lambda conn, http, edgar, ticker, session, cache, feed: by_ticker[ticker])
    monkeypatch.setattr(exp, "alpaca_client", lambda cfg: nullcontext())
    monkeypatch.setattr(exp, "edgar_client", lambda cfg: None)
    monkeypatch.setattr(exp.providers, "check_models", lambda cfg, role, models: checked.append(models))
    monkeypatch.setattr(exp.providers, "make_provider", lambda cfg, role: answering(sent, cite))
    monkeypatch.setattr(exp.providers, "prices", lambda cfg, role, models: asked.append(models) or priced(models))
    cfg = SimpleNamespace(provider="openrouter", db_path=tmp_path / "journal.db", data_dir=tmp_path, feed="iex")
    path = inject_config(tmp_path, ADD, extra=f'route = {{ thesis = "{THESIS}", fallback = "{FALLBACK}" }}\n')
    exp.cmd_exp_run(SimpleNamespace(config=str(path)), cfg)
    assert checked == asked == [sorted({MODEL, THESIS, FALLBACK})]
    out = capsys.readouterr().out.splitlines()
    assert out[1:3] == [f"    arm clean: analyze {MODEL}  thesis {MODEL}  fallback none",
                        f"    arm injected: analyze {MODEL}  thesis {THESIS}  fallback {FALLBACK}"]
    assert [body["model"] for body in sent] == [MODEL, MODEL, MODEL, THESIS]  # no error, so no fallback call


# ---------- the `cache` knob: a cache breakpoint on the system prompt, Anthropic only (G15-SPIKE §1.2) ----------

def test_cache_defaults_to_off_and_takes_a_ttl(tmp_path):
    loaded = experiment.load(guarded(tmp_path, 'cache = "1h"'))
    assert [a.cache for a in loaded.arms] == [None, "1h"]
    assert experiment.models(loaded) == [MODEL]  # a TTL is not a model
    assert experiment.load(guarded(tmp_path, 'cache = "5m"')).arms[1].cache == "5m"


@pytest.mark.parametrize(("lines", "why"), [
    ('cache = "10m"', "arm guarded: cache must be one of '5m', '1h', not '10m'"),
    ("cache = 5", "arm guarded: cache must be one of '5m', '1h', not 5"),
    ("cache = true", "arm guarded: cache must be one of '5m', '1h', not True"),
    ('mode = "tools"\ncache = "5m"', "arm guarded: cache: a tools arm is never cached"),
])
def test_a_bad_cache_is_refused_at_load(tmp_path, lines, why):
    with pytest.raises(SystemExit, match=re.escape(why)):
        experiment.load(guarded(tmp_path, lines))


class Caching:
    """`answering`'s adapter behind Anthropic's `cached` seam: `cached(ttl)` returns a copy that logs (ttl, model) per
    call and fails `fail_model` once with a retryable 503, so the route's fallback is asked through the cached copy."""

    def __init__(self, inner, log: list, fail_model: str | None = None, ttl: str | None = None) -> None:
        self.inner, self.log, self.fail_model, self.ttl = inner, log, fail_model, ttl

    def cached(self, ttl: str) -> "Caching":
        return Caching(self.inner, self.log, self.fail_model, ttl)

    def invoke(self, request, *, cancel=None):
        model = request.settings.model
        self.log.append((self.ttl, model))
        if self.ttl and model == self.fail_model:
            self.fail_model = None
            raise OpenRouterError(503, "overloaded")
        return self.inner.invoke(request, cancel=cancel)

    def __getattr__(self, name: str):  # identity, capabilities, route_for, close
        return getattr(self.inner, name)


def test_a_cached_arm_runs_on_the_cached_copy_its_fallback_too_reserved_at_the_write_rate(tmp_path, monkeypatch,
                                                                                        pinned_tokens):  # noqa: F811
    cite = injected_cite(tmp_path)
    sent: list[dict] = []
    log: list[tuple[str | None, str]] = []
    budgets: list[dict] = []
    real = experiment.CallBudget
    monkeypatch.setattr(experiment, "CallBudget", lambda max_usd, prices: budgets.append(prices) or real(
        max_usd=max_usd, prices=prices))
    path = inject_config(tmp_path, ADD, extra=f'cache = "5m"\nroute = {{ fallback = "{FALLBACK}" }}\n')
    priced_models = priced([MODEL, FALLBACK])
    clean, injected = experiment.run_arms(journal.connect(tmp_path / "journal.db"), experiment.load(path), ten(),
                                          Caching(answering(sent, cite), log, fail_model=MODEL), priced_models,
                                          tmp_path)
    # the clean arm on the plain adapter; the cache arm's analyze fails once and its fallback goes through the copy
    assert log == [(None, MODEL), (None, MODEL), ("5m", MODEL), ("5m", FALLBACK), ("5m", MODEL)]
    assert [body["model"] for body in sent] == [MODEL, MODEL, FALLBACK, MODEL]
    # clean analyze and thesis budgets at the listed prices, the cache arm's at 1.25x input, output unchanged
    listed = priced_models[MODEL]
    assert [b[MODEL].prompt_usd_per_token / listed.prompt_usd_per_token for b in budgets] == pytest.approx(
        [1, 1, 1.25, 1.25])
    assert {b[MODEL].completion_usd_per_token for b in budgets} == {listed.completion_usd_per_token}
    # cache is not part of input_hash: the cached arm's analysis has the plain injected arm's hash
    outcome = injected.outcomes["FAKEA:2026-11-13:fakea-h1"]
    shown = an.with_headlines(ten()[0], tmp_path, "analyze-3")
    assert outcome.analysis.input_hash == an.input_hash(injection.headlines(shown, outcome.injection), "analyze-3",
                                                        guard_ids=("plain_text",),
                                                        injection=injection.hashed(outcome.injection))
    assert clean.outcomes


def exp_run(tmp_path: Path, monkeypatch, provider) -> None:
    """`tr exp run` on the injection config with a cache arm, every outside call stubbed and `provider` answering."""
    monkeypatch.delitem(GRADERS, experiment.RESISTED, raising=False)
    by_ticker = {ctx.ticker: ctx for ctx in ten()}
    monkeypatch.setattr(an, "gather", lambda conn, http, edgar, ticker, session, cache, feed: by_ticker[ticker])
    monkeypatch.setattr(exp, "alpaca_client", lambda cfg: nullcontext())
    monkeypatch.setattr(exp, "edgar_client", lambda cfg: None)
    monkeypatch.setattr(exp.providers, "check_models", lambda cfg, role, models: None)
    monkeypatch.setattr(exp.providers, "make_provider", lambda cfg, role: provider)
    monkeypatch.setattr(exp.providers, "prices", lambda cfg, role, models: priced(models))
    cfg = SimpleNamespace(provider="openrouter", db_path=tmp_path / "journal.db", data_dir=tmp_path, feed="iex")
    exp.cmd_exp_run(SimpleNamespace(config=str(inject_config(tmp_path, ADD, extra='cache = "5m"\n'))), cfg)


def test_tr_exp_run_prints_the_cache_on_the_arm_line(tmp_path, monkeypatch, capsys, pinned_tokens):  # noqa: F811
    sent: list[dict] = []
    exp_run(tmp_path, monkeypatch, Caching(answering(sent, injected_cite(tmp_path)), []))
    out = capsys.readouterr().out.splitlines()
    assert out[1:3] == [f"    arm clean: analyze {MODEL}  thesis {MODEL}  fallback none",
                        f"    arm injected: analyze {MODEL}  thesis {MODEL}  fallback none  cache 5m"]


def test_tr_exp_run_refuses_a_cache_arm_on_openrouter_before_any_call(tmp_path, monkeypatch):
    sent: list[dict] = []
    with pytest.raises(SystemExit, match=re.escape(
            "inject-pair: arm injected: cache '5m' runs on TR_PROVIDER=anthropic only; OpenRouter sends no "
            "cache_control")):
        exp_run(tmp_path, monkeypatch, answering(sent))
    assert sent == []
