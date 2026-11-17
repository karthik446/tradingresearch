"""`tr daily`: full run, rerun with no call, a failed ticker, a budget stop, missed sessions, dry run (G4a).

The steps are injected: analyze stores the recorded real AAPL analysis and saves the recorded real analyze run file
(so `usage.run_cost` reads its real cost), thesis checks and stores the recorded real reply, reconcile is the real
runner (the thesis waits for its window, so no bars are read). No network, no model.
"""

import json
import shutil
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tradingresearch import analyze as an, daily, journal, reconcile_run, sessions, thesis as th
from tradingresearch.cli import main
from tradingresearch.commands.thesis import horizons_to_ask
from tradingresearch.records import Analysis
from tradingresearch.screen import CODE_VERSION, ScreenResult

FIXTURES = Path(__file__).parent / "fixtures"
ANALYSIS = Analysis.model_validate_json((FIXTURES / "thesis" / "AAPL_2026-11-16.analysis.json").read_text())
REPLY = json.loads((FIXTURES / "thesis" / "AAPL_2026-11-16.reply.json").read_text())
ANALYZE_RUN = FIXTURES / "usage" / "runs" / "run_10fc0a886ddb42a2.jsonl"  # a real `tr analyze` run, $0.017304
SESSION = date(2026, 11, 16)
NOW = datetime(2026, 11, 17, 3, 46, tzinfo=UTC)  # after the close, before the next open (14:30 UTC)


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
