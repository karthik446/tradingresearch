"""Week 4 reference behaviour beyond the contract in test_week4.py: what each tool returns, the loop's failure paths,
the tools arm next to a fixed arm, and the first RuleChange's filter (REPO-PLAN week 4, SPIKE §8.2)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from gigai_core.providers import ProviderError
from gigai_core.trace import ModelSpan, ToolSpan, TrialSpan

from factories import analysis, snapshot, thesis
from test_week4 import (CONFIG, LIVE_CONTEXT_TOKENS, MODEL, PROMPT, RULE_CHANGE, context, load, prices, recorded,
                        replaying)
from tradingresearch import analyze as an, experiment, journal, rules, tools
from tradingresearch.records import RuleChange


@pytest.fixture
def pinned_tokens(monkeypatch):
    """The student tokenizer downloads from the HF hub; the stored context_tokens is pinned instead."""
    monkeypatch.setattr(an, "context_tokens", lambda system, prompt: LIVE_CONTEXT_TOKENS)


def rows_of(text: str) -> list[dict]:
    parsed = json.loads(text)
    assert "error" not in parsed, parsed
    return parsed["rows"]


def error_text(text: str) -> str:
    parsed = json.loads(text)
    assert isinstance(parsed.get("error"), str) and parsed["error"], parsed
    return parsed["error"]


# ---------- the tools ----------

def test_the_three_tools_split_the_context_rows_with_no_row_lost_or_shared():
    """Every Context row comes back from exactly one tool, so nothing the fixed table shows is out of reach."""
    ctx = context()
    returned = [r["source_id"] for spec in tools.TOOLS for r in rows_of(tools.run_tool(ctx, spec.name, "{}"))]
    assert sorted(returned) == sorted(row.source_id for row in ctx.rows)


def test_each_tool_returns_its_kind_of_row():
    ctx = context()
    levels = {r["name"] for r in rows_of(tools.run_tool(ctx, "get_levels", ""))}
    assert {"level_hvn_1", "dist_level_hvn_1_atr", "congestion_low"} <= levels
    facts = {r["name"] for r in rows_of(tools.run_tool(ctx, "get_fundamentals", "{}"))}
    assert facts == {"revenue_CY2026Q2", "revenue_CY2026Q3", "net_income_CY2026Q2", "net_income_CY2026Q3",
                     "eps_diluted_CY2026Q3"}
    indicators = {r["name"] for r in rows_of(tools.run_tool(ctx, "get_indicators", "{}"))}
    assert {"close", "rsi_14", "regime_spy"} <= indicators and not indicators & (levels | facts)


def test_a_row_shows_the_value_the_fixed_table_shows_and_the_regime_its_label():
    ctx = context()
    rows = rows_of(tools.run_tool(ctx, "get_indicators", '{"names": ["close", "regime_spy"]}'))
    by_name = {r["name"]: r for r in rows}
    close = next(row for row in ctx.rows if row.name == "close")
    assert by_name["close"] == {"source_id": close.source_id, "name": "close", "unit": close.unit,
                                "value": float(an.plain(close.value))}
    assert by_name["regime_spy"]["label"] == "bull-normal"


def test_the_filters_pick_rows_by_name_and_by_metric():
    ctx = context()
    assert [r["name"] for r in rows_of(tools.run_tool(ctx, "get_indicators", '{"names": ["rsi_14"]}'))] == ["rsi_14"]
    eps = rows_of(tools.run_tool(ctx, "get_fundamentals", '{"metrics": ["eps_diluted"]}'))
    assert [r["name"] for r in eps] == ["eps_diluted_CY2026Q3"]
    assert rows_of(tools.run_tool(ctx, "get_fundamentals", '{"metrics": ["revenue_annual"]}')) == []


@pytest.mark.parametrize(("name", "arguments", "says"), [
    ("get_indicators", '{"names": ["rsi_99"]}', "rsi_14"),
    ("get_indicators", '{"names": "close"}', "non-empty list of strings"),
    ("get_indicators", '{"names": []}', "non-empty list of strings"),
    ("get_fundamentals", '{"metrics": ["ebitda"]}', "eps_diluted"),
    ("get_levels", '{"names": ["close"]}', "allowed: none"),
], ids=["unknown_name_lists_the_names", "string_not_list", "empty_list", "unknown_metric_lists_metrics",
        "levels_takes_no_arguments"])
def test_an_error_tells_the_model_how_to_call_again(name, arguments, says):
    assert says in error_text(tools.run_tool(context(), name, arguments))


# ---------- the loop's failure paths ----------

class Failing:
    """A provider whose every call fails, as a timeout would."""

    def __init__(self, identity):
        self.identity = identity

    def invoke(self, request):
        raise ProviderError("upstream timed out")


def test_a_provider_error_is_a_failed_sample_with_a_failed_span():
    sample = an.analyze_with_tools(context(), Failing(recorded([]).identity), model=MODEL, prompt_version=PROMPT)
    assert sample.outcome == "failed" and sample.error.code == "provider_failed"
    [span] = sample.model_spans
    assert span.error == sample.error and span.finish_reason == "error"


def test_a_crashing_tool_is_recorded_and_answered_and_the_loop_goes_on(monkeypatch):
    def crash(ctx, name, arguments):
        raise KeyError("boom")

    monkeypatch.setattr(tools, "run_tool", crash)
    sent: list[dict] = []
    sample = an.analyze_with_tools(context(), recorded(sent), model=MODEL, prompt_version=PROMPT)
    assert sample.outcome == "succeeded" and len(sent) == 2
    [span] = sample.tool_spans
    assert span.error.code == "tool_exception" and "error" in span.result
    assert json.loads(sent[1]["messages"][-1]["content"]) == span.result


def test_the_cap_error_says_why_and_the_trial_span_is_first():
    sample = an.analyze_with_tools(context(), replaying([load("turn1.reply")], []), model=MODEL,
                                   prompt_version=PROMPT, max_turns=2)
    assert sample.error.code == "max_tool_turns" and sample.parse_status == "not_parsed"
    assert isinstance(sample.spans[0], TrialSpan) and sample.spans[0].outcome == "failed"


# ---------- a tools arm beside a fixed arm ----------

PAIR = f"""name = "week4-pair"
model = "{MODEL}"
max_usd_per_arm = 1.0
tickers = ["FAKEA", "AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "UNH", "HD", "KO"]  # 10 clusters; one context runs
sessions = ["2026-11-13"]
graders = ["parsed", "all_claims_valid", "tool_calls_ok"]

[[arms]]
name = "fixed"
prompt = "{PROMPT}"
mode = "fixed"

[[arms]]
name = "tools"
prompt = "{PROMPT}"
mode = "tools"
"""


def config_of(tmp_path: Path, text: str) -> experiment.Config:
    path = tmp_path / "pair.toml"
    path.write_text(text)
    return experiment.load(path)


def scores_of(result: experiment.ArmResult) -> dict[str, tuple[float, str | None]]:
    return {s.grader_id: (s.value, s.explanation) for s in result.run.scores}


def test_both_arms_share_one_dataset_and_tool_calls_ok_scores_each(tmp_path, pinned_tokens):
    """The fixed arm scores 1.0 (no tool calls), so `compare` keeps the grader; the replayed `get_sources` call is an
    unknown tool here, so the tools arm scores tool_error."""
    sent: list[dict] = []
    provider = replaying([load("turn2.reply"), load("turn1.reply"), load("turn2.reply")], sent)
    conn = journal.connect(tmp_path / "journal.db")
    fixed, with_tools = experiment.run_arms(conn, config_of(tmp_path, PAIR), [context()], provider, prices(), tmp_path)
    assert fixed.run.record.dataset == with_tools.run.record.dataset
    assert ["tools" in body for body in sent] == [False, True, True]
    assert scores_of(fixed)["tool_calls_ok"] == (1.0, "no tool calls")
    value, why = scores_of(with_tools)["tool_calls_ok"]
    assert value == 0.0 and why.startswith("tool_error")
    assert scores_of(with_tools)["parsed"][0] == 1.0
    assert (fixed.analyses, with_tools.analyses) == (1, 1)
    routes = dict(conn.execute("SELECT json_extract(body, '$.run_id'), json_extract(body, '$.provider_route') "
                               "FROM analysis"))
    assert routes[fixed.run.record.run_id] == "openrouter:Google"
    assert routes[with_tools.run.record.run_id] == "openrouter:mixed(Azure+Google)", "the route covers both turns"


def test_the_tools_arm_writes_its_trace_and_records_the_loop_cost(tmp_path, pinned_tokens):
    sent: list[dict] = []
    conn = journal.connect(tmp_path / "journal.db")
    config = config_of(tmp_path, PAIR.replace('name = "fixed"\nprompt = "analyze-1"\nmode = "fixed"\n\n[[arms]]\n', ""))
    [result] = experiment.run_arms(conn, config, [context()], recorded(sent), prices(), tmp_path)
    record = result.run.record
    lines = [json.loads(line) for line in Path(record.trace_path).read_text().splitlines()]
    kinds = [line["kind"] for line in lines]
    model, tool, trial = (cls.model_fields["kind"].default for cls in (ModelSpan, ToolSpan, TrialSpan))
    assert kinds == [model, tool, model, trial]
    assert record.calls_made == 2 and record.spent_usd == round(sum(s.call.cost_usd for s in
                                                                    result.run.samples[0].model_spans), 6)
    assert record.tag == "week4-pair:tools:analyze-1"


def test_a_judge_grader_is_refused_for_a_tools_arm_before_any_call(tmp_path):
    sent: list[dict] = []
    conn = journal.connect(tmp_path / "journal.db")
    config = config_of(tmp_path, PAIR.replace('"tool_calls_ok"]', '"tool_calls_ok", "p1_judge"]'))
    with pytest.raises(SystemExit, match="p1_judge"):
        experiment.run_arms(conn, config, [context()], recorded(sent), prices(), tmp_path)
    assert sent == []


def test_the_shipped_config_names_only_code_graders():
    config = experiment.load(CONFIG)
    assert all(g.kind == "code" for g in experiment.registry(list(config.graders)))


# ---------- rule-change-1 ----------

def change() -> RuleChange:
    return RuleChange.model_validate(tomllib.loads(RULE_CHANGE.read_text()))


@pytest.mark.parametrize(("horizon", "direction", "dist", "dropped"), [
    ("short", "long", -0.4, True), ("short", "long", 0.4, False), ("short", "short", 0.4, True),
    ("short", "short", -0.4, False), ("swing", "long", -0.4, False), ("short", "long", None, True),
])
def test_the_challenger_drops_short_theses_against_the_sma50_trend(horizon, direction, dist, dropped):
    rule = rules.resolve(change().diff_ref)
    assert isinstance(rule, rules.Filter)
    values = {"close": 230.0, "atr_14": 4.0} | ({} if dist is None else {"dist_sma_50_atr": dist})
    a = analysis(snapshot=snapshot(values=values))
    prices_ = {} if direction == "long" else {"stop": 238.0, "target": 220.0, "invalidation_price": 238.0}
    t = thesis(a.analysis_id, horizon=horizon, direction=direction, **prices_)
    assert (rule.refuse(t, a) is not None) == dropped


def test_rule_change_1_registers_in_a_journal_and_answers_the_next_session(tmp_path):
    conn = journal.connect(tmp_path / "journal.db")
    rules.register(conn, change())
    [stored] = journal.rule_changes(conn, "pending")
    assert stored == change()
    assert rules.pending_for(conn, change().prereg.registered_at.date()) == change()
