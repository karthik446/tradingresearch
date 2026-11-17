"""`tr daily`: full run, rerun with no call, a failed ticker, a budget stop, missed sessions, dry run (G4a), and the
`--teachers` step (G6c).

The steps are injected: analyze stores the recorded real AAPL analysis and saves the recorded real analyze run file
(so `usage.run_cost` reads its real cost), thesis checks and stores the recorded real reply, reconcile is the real
runner (the thesis waits for its window, so no bars are read). No network, no model. The teacher steps are the real
`an.analyze` / `th.thesis` over a replaying HTTP transport: the recorded DeepSeek V4 Pro thesis reply of 2026-11-16
(its analysis stored as recorded, since the reply cites its claim ids) and OpenRouter's recorded 400 for a bad slug.
"""

import json
import shutil
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from gigai_core.budget import Price

from factories import T0, analysis
from test_teacher import API, PRICE, REPLY as TEACHER_ANALYZE_REPLY, TEACHER, context, pinned_tokens  # noqa: F401
from tradingresearch import analyze as an, daily, journal, reconcile_run, sessions, teacher as tc, thesis as th
from tradingresearch.cli import build_parser, main
from tradingresearch.commands.thesis import horizons_to_ask
from tradingresearch.config import require, settings
from tradingresearch.openrouter import OpenRouter, Routing
from tradingresearch.records import Analysis, NoTrade
from tradingresearch.screen import CODE_VERSION, ScreenResult

FIXTURES = Path(__file__).parent / "fixtures"
ANALYSIS = Analysis.model_validate_json((FIXTURES / "thesis" / "AAPL_2026-11-16.analysis.json").read_text())
REPLY = json.loads((FIXTURES / "thesis" / "AAPL_2026-11-16.reply.json").read_text())
ANALYZE_RUN = FIXTURES / "usage" / "runs" / "run_10fc0a886ddb42a2.jsonl"  # a real `tr analyze` run, $0.017304
SESSION = date(2026, 11, 16)
NOW = datetime(2026, 11, 17, 3, 46, tzinfo=UTC)  # after the close, before the next open (14:30 UTC)
TEACHER_ANALYSIS = Analysis.model_validate_json(
    (FIXTURES / "teacher" / "AAPL_2026-11-16.deepseek-v4-pro.analysis.json").read_text())
TEACHER_THESIS_REPLY = json.loads((FIXTURES / "teacher" / "AAPL_2026-11-16.deepseek-v4-pro.thesis.reply.json").read_text())
TEACHER_THESIS_REQUEST = json.loads(
    (FIXTURES / "teacher" / "AAPL_2026-11-16.deepseek-v4-pro.thesis.request.json").read_text())
BAD_SLUG = json.loads((FIXTURES / "teacher" / "nonexistent-slug.error.json").read_text())  # OpenRouter's real 400
TEACHER_PRICES = {PRICE.model: PRICE} | {  # the pinned DeepInfra listings in experiments/bakeoff-prereg.toml
    model: Price(model=model, prompt_usd_per_token=p, completion_usd_per_token=c, fetched_at=PRICE.fetched_at,
                 source="experiments/bakeoff-prereg.toml")
    for model, p, c in (("qwen/qwen3.5-397b-a17b", 0.36e-6, 2.40e-6), ("openai/gpt-oss-120b", 0.037e-6, 0.17e-6))}


def ranked(*tickers: str) -> list[ScreenResult]:
    return [ScreenResult(session=SESSION, ticker=t, points=2, triggers={}, filtered_out=None, rank=n,
                         code_version=CODE_VERSION) for n, t in enumerate(tickers, start=1)]


class Recorded:
    """The step table over recorded results; it counts the calls each paid step got."""

    def __init__(self, conn, runs_dir: Path, screen: list[ScreenResult], fail: tuple[str, ...] = ()) -> None:
        self.conn, self.runs_dir, self.screen_rows, self.fail = conn, runs_dir, screen, fail
        self.analyzed: list[str] = []
        self.thesised: list[str] = []
        self.reconciled: list[bool] = []

    def screen(self, day: date) -> list[ScreenResult]:
        return self.screen_rows

    def analyze(self, ticker: str, day: date) -> an.Result:
        self.analyzed.append(ticker)
        if ticker in self.fail:
            raise SystemExit("model call failed: parse_error (run run_x)")
        journal.add_analysis(self.conn, ANALYSIS, [])
        shutil.copy(ANALYZE_RUN, self.runs_dir / ANALYZE_RUN.name)
        return an.Result(ANALYSIS, [], 0.017304, str(self.runs_dir / ANALYZE_RUN.name), "")

    def horizons(self, a: Analysis, now: datetime) -> tuple[str, ...]:
        return horizons_to_ask(self.conn, a, "champion", now)

    def thesis(self, a: Analysis, asked: tuple[str, ...]) -> th.Result:
        self.thesised.append(a.ticker)
        written = th.Written("champion", NOW, "trace_test", "openrouter:test", "restricted", "sha256:" + "3" * 64)
        return th.Result(th.store(self.conn, th.validate(REPLY, a, asked, written)), 0.0, "", "")

    def reconcile(self, day: date, dry_run: bool) -> reconcile_run.Report:
        self.reconciled.append(dry_run)
        return reconcile_run.run(self.conn, None, day, dry_run=dry_run, now=NOW)

    def steps(self) -> daily.Steps:
        return daily.Steps(self.screen, self.analyze, self.horizons, self.thesis, self.reconcile)


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def runs_dir(tmp_path):
    path = tmp_path / "runs"
    path.mkdir()
    return path


def run(conn, steps: Recorded, runs_dir: Path, **kw) -> daily.Daily:
    options = {"top": 10, "max_usd": 1.0, "now": NOW} | kw
    return daily.run(conn, steps.steps(), SESSION, runs_dir=runs_dir, **options)


def statuses(conn) -> list[tuple[str, str | None, str]]:
    return [(r["step"], r["ticker"], r["status"]) for r in journal.daily_runs(conn, SESSION)]


def test_a_full_run_screens_analyzes_writes_theses_and_reconciles(conn, runs_dir, capsys):
    steps = Recorded(conn, runs_dir, ranked("AAPL"))
    report = run(conn, steps, runs_dir)
    assert (steps.analyzed, steps.thesised, steps.reconciled, report.screen_failed) == (["AAPL"], ["AAPL"], [False], False)
    assert statuses(conn) == [("screen", None, "ok"), ("analyze", "AAPL", "ok"), ("thesis", "AAPL", "ok"),
                              ("reconcile", None, "ok")]
    rows = journal.daily_runs(conn, SESSION)
    assert rows[1]["ids"] == [ANALYSIS.analysis_id] and rows[1]["cost_usd"] == 0.017304
    [t] = [t for t, _ in journal.open_theses(conn)]
    assert rows[2]["ids"] == [t.thesis_id] and rows[2]["reason"] == "accepted 1, no_trade 2, rejected 0"
    assert report.spent_usd == 0.017304
    out = capsys.readouterr().out
    assert "waiting: the entry window opens on 2026-11-17" in out
    assert "daily 2026-11-16: 2 ok, 0 failed, 0 skipped, 0 stopped; 2 model steps, spent $0.0173 of $1.00" in out


def test_a_rerun_for_the_same_session_makes_no_model_call(conn, runs_dir, capsys):
    steps = Recorded(conn, runs_dir, ranked("AAPL"))
    run(conn, steps, runs_dir)
    capsys.readouterr()
    again = run(conn, steps, runs_dir)
    assert (steps.analyzed, steps.thesised, again.spent_usd) == (["AAPL"], ["AAPL"], 0.0)
    out = capsys.readouterr().out
    assert f"analyze   AAPL   skipped already done ({ANALYSIS.analysis_id})" in out
    assert "daily 2026-11-16: already done, no model call" in out
    assert statuses(conn)[-4:] == [("screen", None, "ok"), ("analyze", "AAPL", "skipped"),
                                   ("thesis", "AAPL", "skipped"), ("reconcile", None, "ok")]


def test_a_failed_ticker_is_recorded_and_the_loop_continues(conn, runs_dir):
    steps = Recorded(conn, runs_dir, ranked("MSFT", "AAPL"), fail=("MSFT",))
    report = run(conn, steps, runs_dir)
    assert (steps.analyzed, steps.thesised, report.screen_failed) == (["MSFT", "AAPL"], ["AAPL"], False)
    failed = [r for r in journal.daily_runs(conn, SESSION) if r["status"] == "failed"]
    assert [(r["step"], r["ticker"], r["reason"]) for r in failed] == [
        ("analyze", "MSFT", "model call failed: parse_error (run run_x)")]


def test_the_budget_stops_before_the_call_that_would_pass_max_usd(conn, runs_dir, capsys):
    steps = Recorded(conn, runs_dir, ranked("AAPL", "MSFT"))
    report = run(conn, steps, runs_dir, max_usd=0.03)  # AAPL analyze fits (0 + 0.02); then 0.0173 + 0.02 > 0.03
    assert (steps.analyzed, steps.thesised, report.stopped) == (["AAPL"], [], True)
    assert statuses(conn)[1:4] == [("analyze", "AAPL", "ok"), ("analyze", "MSFT", "stopped"),
                                   ("thesis", "AAPL", "stopped")]
    assert "budget: spent $0.0173 + ≈$0.02 would pass --max-usd $0.03" in capsys.readouterr().out


def test_missed_sessions_are_listed_and_stored_once_and_only_since_the_first_run(conn, runs_dir, capsys):
    steps = Recorded(conn, runs_dir, ranked())
    assert daily.missed_sessions(conn, SESSION, NOW) == []  # first evening ever: nothing before it is a miss
    journal.add_daily_run(conn, {"daily_id": "dy_0", "session": "2026-11-09", "step": "screen", "ticker": None,
                                 "status": "ok", "reason": "", "ids": [], "cost_usd": 0.0})
    run(conn, steps, runs_dir)
    out = capsys.readouterr().out
    missed = ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    assert [line for line in out.splitlines() if line.startswith("missed:")] == [f"missed: {d}" for d in missed]
    stored = [r["session"] for r in journal.daily_runs(conn) if r["status"] == "missed"]
    assert stored == missed
    run(conn, steps, runs_dir)
    assert "missed:" not in capsys.readouterr().out


def test_a_dry_run_calls_no_model_writes_no_rows_and_estimates_the_cost(conn, runs_dir, capsys):
    steps = Recorded(conn, runs_dir, ranked("AAPL", "MSFT"))
    report = run(conn, steps, runs_dir, dry_run=True)
    assert (steps.analyzed, steps.thesised, steps.reconciled, journal.daily_runs(conn)) == ([], [], [True], [])
    out = capsys.readouterr().out
    assert "would analyze AAPL (≈$0.02), then thesis (≈$0.03)" in out
    assert ("daily 2026-11-16 (dry run): would analyze 2, thesis 2, estimated $0.10 (≈$0.02 per analyze, $0.03 per "
            "thesis); nothing written to daily_run") in out
    assert not report.screen_failed


def test_no_model_and_a_late_run_skip_the_paid_steps(conn, runs_dir):
    steps = Recorded(conn, runs_dir, ranked("AAPL"))
    run(conn, steps, runs_dir, no_model=True)
    late = datetime(2026, 11, 17, 15, 0, tzinfo=UTC)  # the entry window after 2026-11-16 opened at 14:30 UTC
    run(conn, steps, runs_dir, now=late)
    reasons = [r["reason"] for r in journal.daily_runs(conn, SESSION) if r["step"] == "analyze"]
    assert reasons == ["--no-model", "late: the entry window after 2026-11-16 opened at 2026-11-17 14:30 UTC"]
    assert (steps.analyzed, steps.reconciled) == ([], [False, False])


def test_a_failed_screen_ends_the_run_and_is_recorded(conn, runs_dir):
    steps = Recorded(conn, runs_dir, [])

    def no_universe(day):
        raise SystemExit("no universe file at data/universe.txt")

    steps.screen = no_universe
    report = run(conn, steps, runs_dir)
    assert report.screen_failed and steps.reconciled == []
    assert [(r["step"], r["status"], r["reason"]) for r in journal.daily_runs(conn)] == [
        ("screen", "failed", "no universe file at data/universe.txt")]


def test_daily_run_rows_are_append_only(conn):
    journal.add_daily_run(conn, {"daily_id": "dy_0", "session": "2026-11-16", "step": "screen", "ticker": None,
                                 "status": "ok", "reason": "", "ids": [], "cost_usd": 0.0})
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE daily_run SET status = 'failed'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM daily_run")


def test_the_command_refuses_a_session_that_is_not_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    upcoming = th.next_session(sessions.last_completed())
    with pytest.raises(SystemExit, match="is not complete yet"):
        main(["daily", "--session", upcoming.isoformat()])


# ---------- --teachers (G6c) ----------

def answering(status: int, body: dict, sent: list[dict], routing: Routing) -> OpenRouter:
    """The real adapter, its HTTP transport answering `status` with `body`; `sent` collects the request bodies."""
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(status, json=body)

    provider = OpenRouter("not-a-real-key", routing=routing)
    provider._http = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return provider


class Teachers:
    """The teacher step table: models in `fail` get OpenRouter's recorded 400 through the real `an.analyze`. Otherwise
    DeepSeek's analysis is stored as recorded, unless `real_analyze` sends every analyze through `an.analyze` too."""

    def __init__(self, conn, data_dir: Path, fail: tuple[str, ...] = (), real_analyze: bool = False) -> None:
        self.conn, self.data_dir, self.fail, self.real_analyze = conn, data_dir, fail, real_analyze
        self.calls: list[tuple[str, str, float]] = []  # (step, model, the max_usd it was given)
        self.sent: list[dict] = []  # request bodies that reached the HTTP transport

    def provider(self, t: tc.Teacher, reply: dict) -> OpenRouter:
        if t.model in self.fail:
            return answering(BAD_SLUG["status"], BAD_SLUG["body"], self.sent, t.routing)
        return answering(200, reply, self.sent, t.routing)

    def analyze(self, ticker: str, day: date, t: tc.Teacher, max_usd: float) -> an.Result:
        self.calls.append(("analyze", t.model, max_usd))
        if t.model == TEACHER.model and not self.real_analyze and t.model not in self.fail:
            journal.add_analysis(self.conn, TEACHER_ANALYSIS, [])
            return an.Result(TEACHER_ANALYSIS, [], 0.0, "", "")
        return an.analyze(self.conn, context(), self.provider(t, TEACHER_ANALYZE_REPLY), model=t.model,
                          max_usd=max_usd, prices=TEACHER_PRICES, data_dir=self.data_dir, arm="teacher",
                          terms_class=t.terms_class)

    def thesis(self, a: Analysis, t: tc.Teacher, max_usd: float) -> th.Result:
        self.calls.append(("thesis", t.model, max_usd))
        return th.thesis(self.conn, a, self.provider(t, TEACHER_THESIS_REPLY),
                         asked=horizons_to_ask(self.conn, a, "teacher", NOW), arm="teacher", model=t.model,
                         max_usd=max_usd, prices=TEACHER_PRICES, data_dir=self.data_dir, terms=t.terms_class)

    def steps(self) -> daily.TeacherSteps:
        return daily.TeacherSteps(self.analyze, self.thesis)


def done_by(conn, model: str) -> Analysis:
    """A teacher's analysis of AAPL and its no-trade, stored by an earlier run."""
    found = analysis(ticker="AAPL", session=SESSION, arm="teacher", model=model, terms_class="trainable")
    journal.add_analysis(conn, found, [])
    journal.add(conn, NoTrade(analysis_id=found.analysis_id, horizon="day", reason="no setup", created_at=T0))
    return found


def teacher_rows(conn) -> list[dict]:
    return [r for r in journal.daily_runs(conn, SESSION) if r["reason"].startswith("teacher ")]


MAIN_ROWS = [("screen", None, "ok"), ("analyze", "AAPL", "ok"), ("thesis", "AAPL", "ok"), ("reconcile", None, "ok")]
MAIN_SUMMARY = "daily 2026-11-16: 2 ok, 0 failed, 0 skipped, 0 stopped; 2 model steps, spent $0.0173 of $1.00"


def test_without_teachers_the_teacher_step_never_runs(conn, runs_dir, capsys):
    run(conn, Recorded(conn, runs_dir, ranked("AAPL")), runs_dir)
    out = capsys.readouterr().out
    assert "teachers 2026" not in out and "with teacher" not in out and teacher_rows(conn) == []
    args = build_parser().parse_args(["daily"])
    assert (args.teachers, args.teacher_max_usd) == (False, daily.TEACHER_MAX_USD) == (False, 0.40)


def test_the_teacher_step_runs_after_the_evening_and_skips_what_is_stored(conn, runs_dir, capsys):
    for model in ("qwen/qwen3.5-397b-a17b", "openai/gpt-oss-120b"):
        done_by(conn, model)
    teachers = Teachers(conn, runs_dir.parent)
    report = run(conn, Recorded(conn, runs_dir, ranked("AAPL")), runs_dir, teachers=teachers.steps())
    assert (report.screen_failed, report.spent_usd) == (False, 0.017304)  # the evening's own cost, untouched
    assert statuses(conn) == MAIN_ROWS + [("analyze", "AAPL", "ok"), ("thesis", "AAPL", "ok")] + [
        ("analyze", "AAPL", "skipped"), ("thesis", "AAPL", "skipped")] * 2
    assert [(step, model) for step, model, _ in teachers.calls] == [("analyze", TEACHER.model), ("thesis", TEACHER.model)]
    [body] = teachers.sent
    assert body == TEACHER_THESIS_REQUEST  # the request the recorded reply answered, DeepInfra pin included
    assert body["model"] == TEACHER.model and body["provider"]["only"] == ["deepinfra/fp8/flex"]
    thesis_row = teacher_rows(conn)[1]
    assert thesis_row["reason"] == f"teacher {TEACHER.model}: accepted 1, no_trade 2, rejected 0"
    assert thesis_row["cost_usd"] == 0.003016  # the recorded call's real cost, read from its run file
    out = capsys.readouterr().out
    evening, teacher_part = out.split(f"{MAIN_SUMMARY}\n")
    assert "teachers 2026" not in evening and "teacher " + TEACHER.model not in evening
    assert teacher_part.rstrip().endswith(
        "teachers 2026-11-16: 1 names (AAPL) x 3 teachers; 2 ok, 0 failed, 4 skipped, 0 stopped; 2 model steps, "
        "spent $0.0030 this run, $0.0030 of $0.40 this session")


def test_a_teacher_rerun_makes_no_model_call(conn, runs_dir, capsys):
    for model in ("qwen/qwen3.5-397b-a17b", "openai/gpt-oss-120b"):
        done_by(conn, model)
    teachers = Teachers(conn, runs_dir.parent)
    steps = Recorded(conn, runs_dir, ranked("AAPL"))
    run(conn, steps, runs_dir, teachers=teachers.steps())
    capsys.readouterr()
    run(conn, steps, runs_dir, teachers=teachers.steps())
    assert len(teachers.calls) == 2 and len(teachers.sent) == 1  # the first run's two; none on the rerun
    out = capsys.readouterr().out
    assert f"thesis    AAPL   skipped teacher {TEACHER.model}: already done ({TEACHER_ANALYSIS.analysis_id})" in out
    assert "teachers 2026-11-16: 1 names (AAPL) x 3 teachers; already done, no model call" in out


def test_a_failed_teacher_call_is_a_row_and_the_evening_still_succeeds(conn, runs_dir, capsys, pinned_tokens):
    done_by(conn, "openai/gpt-oss-120b")
    teachers = Teachers(conn, runs_dir.parent, fail=(TEACHER.model, "qwen/qwen3.5-397b-a17b"))
    report = run(conn, Recorded(conn, runs_dir, ranked("AAPL")), runs_dir, teachers=teachers.steps())
    assert not report.screen_failed and statuses(conn)[:4] == MAIN_ROWS
    failed = [r for r in teacher_rows(conn) if r["status"] == "failed"]
    assert [r["step"] for r in failed] == ["analyze", "analyze"] and len(teachers.sent) == 2  # both reached the wire
    assert failed[0]["reason"].startswith(f"teacher {TEACHER.model}: model call failed: http_400 (run ")
    assert "1 names (AAPL) x 3 teachers; 0 ok, 2 failed, 2 skipped, 0 stopped" in capsys.readouterr().out


def test_a_journal_failure_in_the_teacher_step_is_printed_not_raised(conn, runs_dir, capsys):
    def broken(*args):
        raise sqlite3.OperationalError("disk I/O error")

    report = run(conn, Recorded(conn, runs_dir, ranked("AAPL")), runs_dir, teachers=daily.TeacherSteps(broken, broken))
    assert not report.screen_failed and statuses(conn) == MAIN_ROWS
    assert capsys.readouterr().out.rstrip().endswith("teachers 2026-11-16: stopped: disk I/O error")


def test_the_teacher_cap_stops_the_step_before_any_request(conn, runs_dir, capsys, pinned_tokens):
    journal.add_daily_run(conn, {"daily_id": "dy_0", "session": SESSION.isoformat(), "step": "thesis",
                                 "ticker": "AAPL", "status": "ok", "reason": f"teacher {TEACHER.model}: an earlier run",
                                 "ids": [], "cost_usd": 0.395})
    teachers = Teachers(conn, runs_dir.parent, real_analyze=True)
    run(conn, Recorded(conn, runs_dir, ranked("AAPL")), runs_dir, teachers=teachers.steps())  # default cap $0.40
    assert teachers.calls == [("analyze", TEACHER.model, 0.005)] and teachers.sent == []  # core refused it
    rows = teacher_rows(conn)[1:]
    assert [(r["step"], r["status"]) for r in rows] == [("analyze", "stopped")] * 3
    assert "does not fit the remaining $0.005000 of max_usd=0.005" in rows[0]["reason"]
    assert rows[0]["reason"].endswith("; $0.3950 of --teacher-max-usd $0.40 spent this session")
    assert "0 ok, 0 failed, 0 skipped, 3 stopped; 0 model steps" in capsys.readouterr().out


def test_a_dry_run_prints_the_teacher_plan_and_calls_nothing(conn, runs_dir, capsys):
    teachers = Teachers(conn, runs_dir.parent)
    run(conn, Recorded(conn, runs_dir, ranked("AAPL")), runs_dir, dry_run=True, teachers=teachers.steps())
    assert (teachers.calls, journal.daily_runs(conn)) == ([], [])
    out = capsys.readouterr().out
    assert f"would analyze AAPL with teacher {TEACHER.model}, then thesis" in out
    assert ("teachers 2026-11-16 (dry run): 1 names (AAPL) x 3 teachers; would analyze 3, thesis 3; each call's worst "
            "case must fit what is left of --teacher-max-usd $0.40 ($0.0000 spent this session); nothing written") in out


@pytest.mark.live
def test_live_openrouter_refuses_a_nonexistent_teacher_slug_and_the_evening_still_succeeds(conn, runs_dir, capsys,
                                                                                         monkeypatch, pinned_tokens):
    bogus = tc.Teacher(BAD_SLUG["model"], TEACHER.slug)
    monkeypatch.setattr(tc, "TEACHERS", {bogus.model: bogus})
    provider = OpenRouter(require(settings().openrouter_key, "OPENROUTER_API_KEY"))
    price = PRICE.model_copy(update={"model": bogus.model})  # core plans with a price; OpenRouter lists none for it

    def analyze(ticker, day, t, max_usd):
        return an.analyze(conn, context(), provider.routed(t.routing), model=t.model, max_usd=max_usd,
                          prices={t.model: price}, data_dir=runs_dir.parent, arm="teacher", terms_class=t.terms_class)

    try:
        report = run(conn, Recorded(conn, runs_dir, ranked("AAPL")), runs_dir,
                     teachers=daily.TeacherSteps(analyze, lambda *args: pytest.fail("no analysis, so no thesis")))
    finally:
        provider.close()
    assert not report.screen_failed and statuses(conn)[:4] == MAIN_ROWS
    [row] = teacher_rows(conn)
    assert (row["step"], row["status"]) == ("analyze", "failed") and "model call failed: http_4" in row["reason"]
    assert "0 ok, 1 failed, 0 skipped, 0 stopped; 1 model steps, spent $0.0000" in capsys.readouterr().out
