"""Trace and usage layer: per-call rows, sums per run, arm, day, step, model and tag, run_cost, `tr usage` (with
`--all-dirs` over the ledger) and the cost ledger row `save` appends per run (G7, G15-SPIKE §3, COST-SPIKE §2.2, §2.4).

The fixtures are real week-1 runs from `data/`: run_10fc0a886ddb42a2 (`tr analyze`, 1 call) whole, and
run_c40caab0968e44a3 (`exp run` arm observe:baseline) cut to its first 2 samples, with `calls_made` and `spent_usd`
in its header set to those 2 calls. Each has its `data/traces` file, cut to the same spans. The cost-table tests write
a two-step pipeline arm at test time with gigai-core `run` and a fake provider (no key, no network).
"""

import json
import os
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from gigai_core import CallBudget, CallSettings, Dataset, DatasetItem, read_spans, run as run_eval
from gigai_core.providers import ModelResult, ProviderIdentity, TokenUsage
from gigai_core.trace import ModelSpan

from tradingresearch import usage
from tradingresearch.analyze import input_hash, save
from tradingresearch.cli import main
from tradingresearch.commands import usage as usage_cmd
from tradingresearch.config import settings
from tradingresearch.providers import openrouter
from tradingresearch.trace import cache_tokens, calls, iter_runs, kind
from test_openrouter import KEY, account_api, recorded, replaying, tool_request
from test_teacher import context

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
    total = usage.total(rows)
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
    assert [(r.key, r.calls) for r in usage.by_step(rows)] == [("analyze", 3)]
    for view in (usage.by_run, usage.by_call, usage.by_arm, usage.by_day, usage.by_step, usage.by_model):
        found = view(rows)
        assert (sum(r.calls for r in found), sum(r.tokens_in for r in found), sum(r.tokens_out for r in found)) == (
            total.calls, total.tokens_in, total.tokens_out)
        assert round(sum(r.cost_usd for r in found), 6) == total.cost_usd


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
    assert usage.total([*calls(ANALYZE), *calls(path)]).prices_missing


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


# ---------- --account: the key's counters and the account's credits against the traces (COST-3b) ----------

KEY_LINE = ("openrouter key usage $64.697878 (today $0.500000, this week $2.250000); credits $70.00 bought, "
            "$64.697878 used, $5.302122 left\n")


@pytest.fixture
def account_env(tr_env, monkeypatch):
    """`tr usage --account` with the key set and a settled read that fails the test if it sleeps; tests that want
    the wait replace `SLEEP` again."""
    tr_env.write_text(f"OPENROUTER_API_KEY={KEY}\n")
    monkeypatch.setattr(usage_cmd, "SLEEP", lambda s: pytest.fail(f"slept {s} s"))
    return tr_env


def previous_reading(at: str, usage_usd: float) -> Path:
    path = Path(os.environ["TR_LEDGER"])
    with path.open("a") as f:
        f.write(json.dumps({"kind": "key_reading", "at": at, "usage": usage_usd, "usage_daily": 0.0,
                            "usage_weekly": 0.0, "total_credits": 70.0}) + "\n")
    return path


def key_data(usage_usd: float) -> dict:
    return {"label": "tr", "usage": usage_usd, "usage_daily": 0.5, "usage_weekly": 2.25, "limit": None}


def test_tr_usage_account_prints_the_balance_and_appends_the_first_key_reading(account_env, monkeypatch, capsys):
    seen = account_api(monkeypatch, key_data(64.697878), {"total_credits": 70.0, "total_usage": 64.697878})
    main(["usage", "--account"])
    ledger_path = Path(os.environ["TR_LEDGER"])
    out = capsys.readouterr().out
    assert out == RUN_TABLE + KEY_LINE + (
        f"no previous key_reading in {ledger_path}: the gap is checked from the next --account run\n"
        f"key_reading appended to {ledger_path}\n")
    assert KEY not in out and seen == ["/api/v1/key", "/api/v1/credits"]
    [row] = ledger()
    assert row == {"kind": "key_reading", "at": row["at"], "usage": 64.697878, "usage_daily": 0.5,
                   "usage_weekly": 2.25, "total_credits": 70.0}
    assert row["at"].endswith("+00:00")
    assert usage.read_ledger(ledger_path) == [] and len(usage.read_key_readings(ledger_path)) == 1


def test_tr_usage_account_reports_the_gap_since_the_previous_reading_and_no_alert_under_the_threshold(
        account_env, monkeypatch, capsys):
    previous_reading("2026-11-01T00:00:00+00:00", 64.637332)  # the three fixture calls ($0.050546) came after it
    account_api(monkeypatch, key_data(64.697878), {"total_credits": 70.0, "total_usage": 64.697878})
    main(["usage", "--account"])
    out = capsys.readouterr().out
    assert out == RUN_TABLE + KEY_LINE + (
        "since 2026-11-01 00:00:00Z: traced $0.050546 vs key delta $0.060546, gap $0.010000 (--alert-usd 0.025)\n"
        f"key_reading appended to {os.environ['TR_LEDGER']}\n")
    assert len(usage.read_key_readings(Path(os.environ["TR_LEDGER"]))) == 2


def test_tr_usage_account_alerts_on_a_settled_gap_and_a_low_balance(account_env, monkeypatch, capsys):
    previous_reading("2026-11-01T00:00:00+00:00", 64.597332)  # key delta $0.100546 against $0.050546 traced
    slept: list[float] = []
    monkeypatch.setattr(usage_cmd, "SLEEP", slept.append)
    seen = account_api(monkeypatch, key_data(64.697878), {"total_credits": 65.0, "total_usage": 64.697878})
    with pytest.raises(SystemExit) as alerted:
        main(["usage", "--account"])
    assert alerted.value.code == 1 and slept == [60.0]
    assert seen == ["/api/v1/key", "/api/v1/credits", "/api/v1/key"]  # the second /key read settles the gap
    lines = capsys.readouterr().out.splitlines()
    assert lines[-4].startswith("since 2026-11-01 00:00:00Z: traced $0.050546 vs key delta $0.100546, gap $0.050000")
    assert lines[-3].startswith("ALERT gap $0.050000 over --alert-usd 0.025: two /key reads 60 s apart agree")
    assert lines[-2].startswith("ALERT credits $0.302122 left under --min-credit-usd 1.80: top up")
    assert len(usage.read_key_readings(Path(os.environ["TR_LEDGER"]))) == 2


def test_tr_usage_account_does_not_alert_an_unsettled_gap_and_keeps_the_later_read(account_env, monkeypatch, capsys):
    previous_reading("2026-11-01T00:00:00+00:00", 64.597332)
    monkeypatch.setattr(usage_cmd, "SLEEP", lambda s: None)
    account_api(monkeypatch, [key_data(64.697878), key_data(64.707878)],
                {"total_credits": 70.0, "total_usage": 64.707878})
    main(["usage", "--account"])  # exit 0
    out = capsys.readouterr().out
    assert "unsettled: the key moved from $64.697878 to $64.707878 between two reads 60 s apart" in out
    assert "ALERT" not in out
    assert usage.read_key_readings(Path(os.environ["TR_LEDGER"]))[-1].usage == 64.707878


def test_the_account_read_waits_until_the_last_traced_call_is_a_minute_old(account_env, monkeypatch, capsys):
    account_api(monkeypatch, key_data(64.697878), {"total_credits": 70.0, "total_usage": 64.697878})
    slept: list[float] = []
    calls_made = every_call()
    now = max(call.started_at for call in calls_made) + timedelta(seconds=20)
    assert usage_cmd.account(settings(), calls_made, [], alert_usd=0.025, min_credit_usd=1.8, clock=lambda: now,
                             sleep=slept.append) == 0
    assert slept == [pytest.approx(40.0)]
    assert capsys.readouterr().out.startswith("waiting 40 s: the last traced call is under 60 s old\n")


class Clock:
    """A wall clock the sleeps advance, so the row's `at` can be checked against the waits."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at

    def sleep(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


def test_the_key_reading_row_is_stamped_after_the_last_read_not_before_the_waits(account_env, monkeypatch):
    previous_reading("2026-11-01T00:00:00+00:00", 64.597332)  # gap $0.05 over the threshold: a second read follows
    account_api(monkeypatch, key_data(64.697878), {"total_credits": 70.0, "total_usage": 64.697878})
    calls_made = every_call()
    clock = Clock(max(call.started_at for call in calls_made) + timedelta(seconds=20))
    started = clock.at
    code = usage_cmd.account(settings(), calls_made, [], alert_usd=0.025, min_credit_usd=1.8, clock=clock.now,
                             sleep=clock.sleep)
    assert code == 1  # the two reads agree: a settled gap
    [_, row] = usage.read_key_readings(settings().ledger)
    assert row.at == started + timedelta(seconds=40 + 60)  # after the pre-wait and the settle wait, not `started`


def test_tr_usage_account_without_a_key_or_under_anthropic_writes_no_row(tr_env, monkeypatch, capsys):
    seen = account_api(monkeypatch, key_data(1.0), {"total_credits": 1.0, "total_usage": 0.0})
    main(["usage", "--account"])
    assert capsys.readouterr().out == RUN_TABLE + (
        "OPENROUTER_API_KEY is not set: key usage and the reconcile line are skipped (trace tables only)\n")
    tr_env.write_text(f"OPENROUTER_API_KEY={KEY}\n")
    monkeypatch.setenv("TR_PROVIDER", "anthropic")
    main(["usage", "--account"])
    assert capsys.readouterr().out.splitlines()[-1] == (
        "TR_PROVIDER=anthropic: Anthropic has no account endpoint, so --account is skipped (no key_reading row)")
    assert seen == [] and ledger() == []


def test_tr_usage_views_leave_key_reading_rows_out_of_the_ledger_join(tr_env, capsys):
    previous_reading("2026-11-01T00:00:00+00:00", 1.0)
    main(["usage", "--by", "step"])
    assert "key_reading" not in capsys.readouterr().out


# ---------- the cost table: --by step / --by model (G15-SPIKE §3) ----------

ANALYZE_MODEL, THESIS_MODEL = "anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5"
ITEMS = ["AAPL:2026-11-12", "MSFT:2026-11-12", "NVDA:2026-11-12", "AMZN:2026-11-12"]
LATENCY = dict(zip(ITEMS, [100, 200, 300, 400]))  # per step, so the per-item sums are 200/400/600/800
ANALYZE_COST = dict(zip(ITEMS, [0.0101, 0.0102, 0.0103, 0.0104]))
THESIS_COST = 0.0051
# the raw Anthropic cache fields on 3 of the 4 analyze calls: one 5m write, then two reads of it
CACHE = {ITEMS[0]: {"cache_creation_input_tokens": 600, "cache_read_input_tokens": 0},
         ITEMS[1]: {"cache_creation_input_tokens": 0, "cache_read_input_tokens": 600},
         ITEMS[2]: {"cache_creation_input_tokens": 0, "cache_read_input_tokens": 600}}


class Fake:
    """Answers each item with its known latency, cost and usage; the served model is a dated id of the asked one."""

    identity = ProviderIdentity(provider="fake", endpoint="none", adapter="test_usage")
    capabilities = frozenset({"text", "system"})

    def __init__(self, cost: dict[str, float], cache: dict[str, dict[str, int]]) -> None:
        self.cost, self.cache = cost, cache

    def invoke(self, request, *, cancel=None):
        item = request.turns[-1].content
        started = datetime(2026, 11, 12, 21, 0, tzinfo=UTC)
        cache = self.cache.get(item, {})
        prompt = 1000 + sum(cache.values())  # input tokens including the cache, as anthropic.py records them
        return ModelResult(text="{}", finish_reason="stop", resolved_model=f"{request.settings.model}-20261101",
                           usage=TokenUsage(input_tokens=prompt, output_tokens=200, total_tokens=prompt + 200,
                                            raw={"input_tokens": 1000, "output_tokens": 200, **cache}),
                           cost_status="derived", cost_usd=self.cost[item], latency_ms=LATENCY[item],
                           started_at=started, completed_at=started)

    def close(self) -> None:
        pass


def write_pipeline_arm(data_dir: Path) -> None:
    """`routing:sonnet` as `exp run` saves a pipeline arm: an analyze run and a thesis run over the same items."""
    for dataset_id, model, tag, provider in [
        ("routing", ANALYZE_MODEL, "routing:sonnet:analyze-3", Fake(ANALYZE_COST, CACHE)),
        ("routing:sonnet:thesis", THESIS_MODEL, "routing:sonnet:thesis-1", Fake(dict.fromkeys(ITEMS, THESIS_COST), {})),
    ]:
        items = [DatasetItem(id=item, cluster_id=item.split(":")[0], prompt=item, expected=None) for item in ITEMS]
        save(run_eval(Dataset.of(dataset_id, items), provider, [],
                      settings=CallSettings(model=model, max_output_tokens=500), budget=CallBudget(), tag=tag),
             data_dir)


@pytest.fixture
def arm_dir(tmp_path):
    write_pipeline_arm(tmp_path)
    return tmp_path


def arm_calls(data_dir: Path):
    return [call for _, path in iter_runs(data_dir) for call in calls(path)]


def test_a_pipeline_arm_is_one_row_with_items_cost_per_ticker_day_and_per_item_latency(arm_dir):
    [row] = usage.by_arm(arm_calls(arm_dir))
    cost = sum(ANALYZE_COST.values()) + 4 * THESIS_COST
    assert (row.key, row.calls, row.items) == ("routing:sonnet", 8, 4)
    assert (row.cost_usd, row.usd_per_item) == (round(cost, 6), round(cost / 4, 6)) == (0.0614, 0.01535)
    assert (row.p50_ms, row.p95_ms) == (400, 800)  # nearest rank over the per-item sums 200/400/600/800
    assert (row.cache_write, row.cache_read) == (600, 1200)
    assert (row.tokens_in, row.tokens_out) == (8 * 1000 + 1800, 8 * 200)


def test_by_step_splits_the_arm_into_analyze_and_thesis_and_adds_up_to_it(arm_dir):
    rows = arm_calls(arm_dir)
    analyze, thesis = usage.by_step(rows)
    assert (analyze.key, analyze.calls, analyze.items, analyze.cost_usd) == ("analyze", 4, 4, 0.041)
    assert (analyze.cache_write, analyze.cache_read, analyze.usd_per_item) == (600, 1200, 0.01025)
    assert (analyze.p50_ms, analyze.p95_ms) == (200, 400)
    assert (thesis.key, thesis.calls, thesis.items, thesis.cost_usd, thesis.usd_per_item) == (
        "thesis", 4, 4, 0.0204, 0.0051)
    assert (thesis.cache_write, thesis.cache_read) == (None, None)  # no call reported the cache fields
    # the total comes from the same calls as the arm row, so it equals the arm row field for field
    assert usage.total(rows).model_dump(exclude={"key"}) == usage.by_arm(rows)[0].model_dump(exclude={"key"})


def test_by_model_keys_on_the_requested_model_not_the_served_one(arm_dir):
    rows = arm_calls(arm_dir)
    assert {call.provider_route for call in rows} == {f"{ANALYZE_MODEL}-20261101", f"{THESIS_MODEL}-20261101"}
    assert [(r.key, r.calls, r.cost_usd) for r in usage.by_model(rows)] == [
        (ANALYZE_MODEL, 4, 0.041), (THESIS_MODEL, 4, 0.0204)]


def test_cache_tokens_read_anthropic_and_openrouter_usage_and_none_where_absent():
    assert cache_tokens({"cache_creation_input_tokens": 600, "cache_read_input_tokens": 0}) == (600, 0)
    assert cache_tokens({"prompt_tokens": 900, "prompt_tokens_details": {"cached_tokens": 512}}) == (None, 512)
    assert cache_tokens({"input_tokens": 10, "output_tokens": 5}) == (None, None)


@pytest.mark.parametrize(("dataset_id", "tag", "step"), [
    ("analyze", "analyze-3", "analyze"), ("thesis", "thesis-1", "thesis"), ("p1_judge", "p1_judge", "judge"),
    ("scratch", "probe", "other"), ("scratch", None, "other"),
], ids=["tr_analyze", "tr_thesis", "judge", "unknown_tag", "no_tag"])
def test_a_run_s_step_comes_from_its_tag_or_dataset_and_an_unknown_one_is_other_not_dropped(
        tmp_path, dataset_id, tag, step):
    item = DatasetItem(id=ITEMS[0], cluster_id="AAPL", prompt=ITEMS[0], expected=None)
    save(run_eval(Dataset.of(dataset_id, [item]), Fake(ANALYZE_COST, {}), [],
                  settings=CallSettings(model=ANALYZE_MODEL, max_output_tokens=500), budget=CallBudget(), tag=tag),
         tmp_path)
    assert [(r.key, r.calls) for r in usage.by_step(arm_calls(tmp_path))] == [(step, 1)]
    assert [(row["step"], row["calls"]) for row in ledger()] == [(step, 1)]


def test_tr_usage_by_step_prints_the_cost_table_with_dashes_for_unreported_cache(arm_dir, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(arm_dir))
    monkeypatch.setenv("TR_ENV_FILE", str(arm_dir / "verify.env"))
    main(["usage", "--by", "step"])
    assert capsys.readouterr().out.splitlines()[:4] == [
        "step     calls  items  tokens in  cache write  cache read  tokens out       cost     $/item     p50     p95",
        "analyze      4      4       5800          600        1200         800  $0.041000  $0.010250  200 ms  400 ms",
        "thesis       4      4       4000            -           -         800  $0.020400  $0.005100  200 ms  400 ms",
        "total        8      4       9800          600        1200        1600  $0.061400  $0.015350  400 ms  800 ms",
    ]


DATA_DEV = Path(__file__).parent.parent / "data-dev"


@pytest.mark.skipif(not (DATA_DEV / "runs").is_dir(), reason="no data-dev runs in this checkout")
def test_by_step_and_by_run_totals_agree_on_the_data_dev_runs(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(DATA_DEV))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "verify.env"))
    total = {}
    for view in ("run", "step"):
        main(["usage", "--by", view])
        total[view] = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("total")).split()
    # run: total calls, tokens in, tokens out, cost; step: total calls, items, tokens in, cache write, cache read,
    # tokens out, cost, $/item, p50, p95
    assert total["run"][1:5] == [total["step"][i] for i in (1, 3, 6, 7)]
    rows = [call for _, path in iter_runs(DATA_DEV) for call in calls(path)]
    steps, runs = usage.by_step(rows), usage.by_run(rows)
    for field in ("calls", "tokens_in", "tokens_out"):
        assert sum(getattr(r, field) for r in steps) == sum(getattr(r, field) for r in runs) == getattr(
            usage.total(rows), field)
    for view in (steps, runs):  # each row's cost is rounded to the micro-dollar, so row sums may differ by that much
        assert sum(r.cost_usd for r in view) == pytest.approx(usage.total(rows).cost_usd, abs=1e-6 * len(view))


# ---------- the cost ledger: one row per saved run, outside the data dir (COST-SPIKE §2.2, COST-1) ----------


def ledger(path: Path | None = None) -> list[dict]:
    """The rows of this test's ledger (`TR_LEDGER`, set per test by conftest)."""
    path = path or Path(os.environ["TR_LEDGER"])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def save_one(data_dir: Path, provider=None, dataset_id: str = "analyze", tag: str | None = "analyze-3") -> Path:
    item = DatasetItem(id=ITEMS[0], cluster_id="AAPL", prompt=ITEMS[0], expected=None)
    return save(run_eval(Dataset.of(dataset_id, [item]), provider or Fake(ANALYZE_COST, {}), [],
                         settings=CallSettings(model=ANALYZE_MODEL, max_output_tokens=500), budget=CallBudget(),
                         tag=tag), data_dir)


def test_a_pipeline_arm_writes_one_row_per_run_with_the_run_cost_numbers_and_the_experiment_arm(arm_dir):
    rows = ledger()
    assert [(r["step"], r["experiment"], r["arm"], r["session"], r["cost_tag"], r["purpose"]) for r in rows] == [
        ("analyze", "routing", "sonnet", "2026-11-12", None, None),
        ("thesis", "routing", "sonnet", "2026-11-12", None, None)]
    for row, (_, path) in zip(rows, iter_runs(arm_dir)):
        cost = usage.run_cost(path)
        assert row["run_id"] == cost.key and row["data_dir"] == str(arm_dir.resolve())
        assert (row["calls"], row["tokens_in"], row["tokens_out"], row["spent_usd"], row["calls_without_cost"]) == (
            cost.calls, cost.tokens_in, cost.tokens_out, cost.cost_usd, 0)
        assert (row["cached_tokens"], row["reasoning_tokens"]) == (cost.cache_read, None)
    assert [r["models"] for r in rows] == [[f"{ANALYZE_MODEL}-20261101"], [f"{THESIS_MODEL}-20261101"]]
    assert rows[0]["created_at"].endswith("+00:00")


def test_tr_cost_tag_overrides_the_step_and_is_kept_whole_as_the_cost_tag(tmp_path, monkeypatch):
    monkeypatch.setenv("TR_COST_TAG", "worker:G99")
    save_one(tmp_path / "scratch")
    [row] = ledger()
    assert (row["step"], row["purpose"], row["cost_tag"]) == ("worker", "G99", "worker:G99")


def test_the_row_outlives_its_scratch_dir_with_the_spend_it_recorded(tmp_path):
    scratch = tmp_path / "data-dev" / "g99-capture"
    run_path = save_one(scratch)
    spent = usage.run_cost(run_path).cost_usd
    shutil.rmtree(scratch)
    [row] = ledger()
    assert not scratch.exists() and row["spent_usd"] == spent == ANALYZE_COST[ITEMS[0]]
    assert row["data_dir"] == str(scratch.resolve())


def test_the_tag_changes_neither_the_wire_body_nor_the_input_hash(monkeypatch):
    untagged = input_hash(context(), "analyze-3")
    monkeypatch.setenv("TR_COST_TAG", "worker:G99")
    provider = openrouter.OpenRouter("sk-test")
    sent = replaying(provider, httpx.Response(200, json=recorded("reply")))
    provider.invoke(tool_request())
    assert sent == [recorded("request")]
    assert input_hash(context(), "analyze-3") == untagged


def test_a_call_without_cost_is_counted_and_an_unwritable_ledger_is_a_warning_not_a_failed_run(
        tmp_path, monkeypatch, capsys):
    written = Path(os.environ["TR_LEDGER"])
    run_path = save_one(tmp_path, Fake(dict.fromkeys(ITEMS), {}))
    [row] = ledger(written)
    assert (row["spent_usd"], row["calls_without_cost"]) == (0.0, 1)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setenv("TR_LEDGER", str(blocker / "cost-ledger.jsonl"))
    saved = save_one(tmp_path)
    assert saved.exists() and saved != run_path and usage.run_cost(saved).cost_usd == ANALYZE_COST[ITEMS[0]]
    err = capsys.readouterr().err
    assert err.startswith(f"warning: cost ledger {blocker / 'cost-ledger.jsonl'} not written (") and "is saved" in err
    assert len(ledger(written)) == 1


# ---------- the ledger read back: --by tag, --tag/--step, --all-dirs (COST-SPIKE §2.4, COST-2b) ----------


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A repo-shaped tmp tree: `tr` points at `data/`, `--all-dirs` at `data/` and `data-dev/` under tmp_path, the
    ledger at `tmp_path/cost-ledger.jsonl` (conftest), no key."""
    roots = (tmp_path / "data", tmp_path / "data-dev")
    monkeypatch.setattr(usage_cmd, "ROOTS", roots)
    monkeypatch.setenv("TR_DATA_DIR", str(roots[0]))
    return tmp_path


def lines(capsys) -> list[str]:
    return capsys.readouterr().out.splitlines()


def test_all_dirs_counts_a_ledger_row_whose_scratch_dir_was_deleted_and_names_it_in_call_views(tree, capsys):
    save_one(tree / "data")
    scratch = tree / "data-dev" / "g99-capture"
    gone = save_one(scratch, dataset_id="thesis", tag="thesis-1")
    shutil.rmtree(scratch)
    main(["usage", "--by", "step", "--all-dirs"])
    assert lines(capsys)[:4] == [  # the thesis row is the ledger's: its calls, tokens and cost, no items or latency
        "step     calls  items  tokens in  cache write  cache read  tokens out       cost     $/item     p50     p95",
        "analyze      1      1       1000            -           -         200  $0.010100  $0.010100  100 ms  100 ms",
        "thesis       1      0       1000            -           -         200  $0.010100  $0.000000    0 ms    0 ms",
        "total        2      1       2000            -           -         400  $0.020200  $0.010100  100 ms  100 ms",
    ]
    main(["usage", "--by", "run", "--all-dirs", "--run", gone.stem])
    assert lines(capsys)[1].split() == [gone.stem, "ledger", "-", "1", "1000", "200", "$0.010100"]
    for view in ("call", "model", "arm"):
        main(["usage", "--by", view, "--all-dirs"])
        out = lines(capsys)
        assert out[0].startswith(view) and out[-1].startswith("OPENROUTER_API_KEY is not set")
        assert out[-2] == ("1 ledger-only run(s) (run file not found) left out of --by " + view + ": a ledger row has "
                           "no per-call detail; --by run, step, tag or day counts them")
    main(["usage", "--by", "day", "--all-dirs"])  # the ledger-only run's day is its created_at; counted once
    out = lines(capsys)
    assert out[-2].split() == ["total", "2", "2000", "400", "$0.020200", "100", "ms"]
    assert not any("left out" in line for line in out)
    main(["usage", "--by", "step"])  # without --all-dirs the ledger row is not counted
    assert lines(capsys)[-2].split()[:2] == ["total", "1"]


def test_all_dirs_reads_every_runs_directory_below_the_roots_once_per_run_id_and_skips_dot_dirs(tree, capsys):
    run_path = save_one(tree / "data")
    copies = [tree / "data-dev" / "scratch" / "runs" / run_path.name, tree / "data" / ".venv" / "runs" / run_path.name,
              tree / "data" / ".git" / "runs" / ANALYZE.name]  # a different run id, so only the dot-dir hides it
    for source, copy in zip([run_path, run_path, ANALYZE], copies):
        copy.parent.mkdir(parents=True)
        shutil.copy(source, copy)
    runs, orphans = usage.all_runs(usage_cmd.ROOTS, usage.read_ledger(Path(os.environ["TR_LEDGER"])))
    assert [path for _, path in runs] == [run_path] and orphans == []
    main(["usage", "--all-dirs"])
    out = lines(capsys)
    assert out[1].split()[:4] == [run_path.stem, "analyze", "-", "1"] and out[2].split()[:2] == ["total", "1"]


def test_all_dirs_reads_the_run_file_at_the_ledger_row_s_own_data_dir_outside_the_roots(tree, tmp_path, capsys):
    elsewhere = save_one(tmp_path / "elsewhere")
    runs, orphans = usage.all_runs(usage_cmd.ROOTS, usage.read_ledger(Path(os.environ["TR_LEDGER"])))
    assert [path for _, path in runs] == [elsewhere] and orphans == []


def test_by_tag_groups_on_the_ledger_tag_with_an_untagged_row_and_the_tag_and_step_filters(tree, monkeypatch, capsys):
    plain = save_one(tree / "data")
    monkeypatch.setenv("TR_COST_TAG", "worker:G99")
    tagged = [save_one(tree / "data"), save_one(tree / "data")]
    monkeypatch.delenv("TR_COST_TAG")
    main(["usage", "--by", "tag"])
    assert lines(capsys)[:4] == [
        "tag         calls  tokens in  tokens out       cost  mean latency",
        "(untagged)      1       1000         200  $0.010100        100 ms",
        "worker:G99      2       2000         400  $0.020200        100 ms",
        "total           3       3000         600  $0.030300        100 ms",
    ]
    main(["usage", "--tag", "worker:G99"])
    assert [line.split()[0] for line in lines(capsys)[1:4]] == [tagged[0].stem, tagged[1].stem, "total"]
    main(["usage", "--by", "step", "--step", "worker"])  # the ledger's step (the tag's) wins over trace.step
    assert [line.split()[:2] for line in lines(capsys)[1:3]] == [["worker", "2"], ["total", "2"]]
    main(["usage", "--by", "run", "--step", "analyze"])
    assert [line.split()[0] for line in lines(capsys)[1:3]] == [plain.stem, "total"]
    main(["usage", "--by", "run", "--tag", "nobody"])
    assert lines(capsys)[0] == f"no model calls under {tree / 'data' / 'runs'}"
    assert [(r.key, r.calls) for r in usage.by_tag(every_call())] == [(usage.UNTAGGED, 3)]  # no ledger: no tag


def test_a_call_without_cost_puts_the_star_and_a_no_cost_column_on_run_file_and_ledger_only_rows(tree, capsys):
    priced = save_one(tree / "data")
    scratch = tree / "data-dev" / "unpriced"
    unpriced = save_one(scratch, Fake(dict.fromkeys(ITEMS), {}))
    shutil.rmtree(scratch)
    main(["usage", "--all-dirs"])
    assert lines(capsys)[:5] == [
        "run                   kind     arm  calls  tokens in  tokens out        cost  no-cost",
        f"{priced.stem}  analyze  -        1       1000         200   $0.010100        0",
        f"{unpriced.stem}  ledger   -        1       1000         200  $0.000000*        1",
        "total                                   2       2000         400  $0.010100*        1",
        "* a call in this row has no recorded cost, so the cost is a lower bound",
    ]
    main(["usage", "--by", "tag", "--all-dirs"])
    assert lines(capsys)[1:3] == [
        "(untagged)      2       2000         400  $0.010100*        1        100 ms",
        "total           2       2000         400  $0.010100*        1        100 ms",
    ]


def test_the_ledger_adds_no_column_to_the_default_output_when_every_call_has_a_cost(tree, monkeypatch, capsys):
    monkeypatch.setenv("TR_COST_TAG", "worker:G99")
    write_pipeline_arm(tree / "data")
    main(["usage"])
    with_ledger = capsys.readouterr().out
    Path(os.environ["TR_LEDGER"]).unlink()
    main(["usage"])
    assert capsys.readouterr().out == with_ledger
    assert with_ledger.splitlines()[0] == "run                   kind  arm             calls  tokens in  tokens out       cost"
