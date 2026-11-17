"""Trace and usage layer: per-call rows, sums per run, arm and day, run_cost, and `tr usage` (G7).

The fixtures are real week-1 runs from `data/`: run_10fc0a886ddb42a2 (`tr analyze`, 1 call) whole, and
run_c40caab0968e44a3 (`exp run` arm observe:baseline) cut to its first 2 samples, with `calls_made` and `spent_usd`
in its header set to those 2 calls. Each has its `data/traces` file, cut to the same spans.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from gigai_core import read_spans
from gigai_core.trace import ModelSpan

from tradingresearch import openrouter, usage
from tradingresearch.cli import main
from tradingresearch.trace import calls, iter_runs, kind

DATA = Path(__file__).parent / "fixtures" / "usage"
ANALYZE = DATA / "runs" / "run_10fc0a886ddb42a2.jsonl"
EXP = DATA / "runs" / "run_c40caab0968e44a3.jsonl"


def every_call():
    return [call for _, path in iter_runs(DATA) for call in calls(path)]


def test_iter_runs_lists_saved_runs_oldest_first_with_their_kind():
    runs = list(iter_runs(DATA))
    assert [(record.run_id, kind(record)) for record, _ in runs] == [
        ("run_10fc0a886ddb42a2", "analyze"), ("run_c40caab0968e44a3", "exp")]
    assert [path for _, path in runs] == [ANALYZE, EXP]


def test_calls_are_typed_rows_of_what_the_span_recorded():
    first, second = calls(EXP)
    assert (first.run_id, first.item_id, first.arm) == ("run_c40caab0968e44a3", "AAPL:2026-11-12", "observe:baseline")
    assert (first.model, first.provider_route) == ("anthropic/claude-sonnet-5.5", "anthropic/claude-sonnet-5.5")
    assert (first.prompt_tokens, first.completion_tokens, first.cost_usd, first.latency_ms) == (2472, 1150, 0.016444, 10399)
    assert (first.status, first.error) == ("succeeded", None)
    assert (second.item_id, second.cost_usd) == ("MSFT:2026-11-12", 0.016798)
    assert [call.arm for call in calls(ANALYZE)] == [None]


@pytest.mark.parametrize("run", [ANALYZE, EXP], ids=["analyze", "exp"])
def test_the_run_file_holds_the_same_model_calls_as_the_trace_file(run):
    spans = [span for span in read_spans(DATA / "traces" / run.name) if isinstance(span, ModelSpan)]
    assert [(c.started_at, c.cost_usd, c.prompt_tokens) for c in calls(run)] == [
        (s.started_at, s.call.cost_usd, s.call.usage.input_tokens) for s in spans]


def test_sums_per_run_arm_and_day_equal_the_hand_added_numbers():
    rows = every_call()
    total = usage.total(usage.by_run(rows))
    assert (total.calls, total.tokens_in, total.tokens_out) == (3, 2672 + 2472 + 2604, 1196 + 1150 + 1159)
    assert total.cost_usd == round(0.017304 + 0.016444 + 0.016798, 6)
    assert total.mean_latency_ms == pytest.approx((8267 + 10399 + 9175) / 3)
    assert not total.prices_missing
    assert [(r.key, r.calls, r.cost_usd) for r in usage.by_run(rows)] == [
        ("run_10fc0a886ddb42a2", 1, 0.017304), ("run_c40caab0968e44a3", 2, 0.033242)]
    assert [(r.key, r.calls) for r in usage.by_arm(rows)] == [("-", 1), ("observe:baseline", 2)]
    assert [(r.key, r.calls) for r in usage.by_call(rows)] == [
        ("run_10fc0a886ddb42a2 MSFT:2026-11-13", 1), ("run_c40caab0968e44a3 AAPL:2026-11-12", 1),
        ("run_c40caab0968e44a3 MSFT:2026-11-12", 1)]
    for view in (usage.by_call, usage.by_arm, usage.by_day):
        assert usage.total(view(rows)) == total


def test_a_day_is_the_new_york_date_so_an_evening_run_stays_on_its_day():
    # The exp calls started 2026-11-17 01:04Z, which is 20:04 on 2026-11-16 in New York.
    assert [(r.key, r.calls) for r in usage.by_day(every_call())] == [("2026-11-16", 3)]


def test_run_cost_sums_the_calls_and_matches_the_recorded_spend():
    cost = usage.run_cost(EXP)
    assert (cost.key, cost.calls, cost.cost_usd, cost.prices_missing) == ("run_c40caab0968e44a3", 2, 0.033242, False)
    assert cost.cost_usd == {record.run_id: record.spent_usd for record, _ in iter_runs(DATA)}[cost.key]


def test_a_call_with_no_cost_flags_prices_missing(tmp_path):
    lines = [json.loads(line) for line in EXP.read_text().splitlines()]
    sample = [line for line in lines if line["kind"] == "sample"][1]["sample"]
    call = next(span for span in sample["spans"] if span["kind"] == "model_call")["call"]
    call["cost_usd"], call["cost_status"] = None, "unavailable"
    path = tmp_path / EXP.name
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    cost = usage.run_cost(path)
    assert (cost.cost_usd, cost.prices_missing) == (0.016444, True)
    assert usage.total([usage.run_cost(ANALYZE), cost]).prices_missing


@pytest.fixture
def tr_env(monkeypatch, tmp_path):
    """`tr` pointed at the fixture runs, with an env file that has no OpenRouter key unless a test writes one."""
    env_file = tmp_path / "verify.env"
    monkeypatch.setenv("TR_DATA_DIR", str(DATA))
    monkeypatch.setenv("TR_ENV_FILE", str(env_file))
    return env_file


RUN_TABLE = """\
run                   kind     arm               calls  tokens in  tokens out       cost
run_10fc0a886ddb42a2  analyze  -                     1       2672        1196  $0.017304
run_c40caab0968e44a3  exp      observe:baseline      2       5076        2309  $0.033242
total                                                3       7748        3505  $0.050546
"""


def test_tr_usage_without_a_key_prints_the_trace_table_and_a_note(tr_env, capsys):
    main(["usage"])
    assert capsys.readouterr().out == RUN_TABLE + (
        "OPENROUTER_API_KEY is not set: key usage and the reconcile line are skipped (trace tables only)\n")


def test_tr_usage_with_a_key_ends_with_the_key_line_and_the_reconcile_line(tr_env, monkeypatch, capsys):
    tr_env.write_text("OPENROUTER_API_KEY=placeholder-not-a-key\n")
    monkeypatch.setattr(openrouter, "key_usage", lambda key: 61.778267)  # the free GET /key read, not a model call
    main(["usage"])
    assert capsys.readouterr().out == RUN_TABLE + (
        "openrouter key usage $61.778267\n"
        f"trace total $0.050546 vs key lifetime $61.778267 (the key also paid for runs outside {DATA / 'runs'}, "
        "so the key is ≥ the trace total)\n")


def test_tr_usage_by_arm_filtered_to_one_run(tr_env, capsys):
    main(["usage", "--by", "arm", "--run", "run_c40caab0968e44a3"])
    assert capsys.readouterr().out.splitlines()[:3] == [
        "arm               calls  tokens in  tokens out       cost  mean latency",
        "observe:baseline      2       5076        2309  $0.033242       9787 ms",
        "total                 2       5076        2309  $0.033242       9787 ms",
    ]


def test_tr_usage_since_a_later_day_shows_no_calls(tr_env, capsys):
    main(["usage", "--by", "day", "--since", str(date(2026, 11, 17))])
    assert capsys.readouterr().out.splitlines()[0] == f"no model calls under {DATA / 'runs'}"


def test_tr_usage_refuses_an_unknown_run(tr_env):
    with pytest.raises(SystemExit, match="no saved run run_nope"):
        main(["usage", "--run", "run_nope"])
