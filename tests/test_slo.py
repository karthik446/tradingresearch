"""`slo_check.py` / `tr slo` (PLAN-60 week 3): finish by 17:30 ET, zero missed sessions, fresh data, and (COST-6) the
session's first paid run within the cost budget; live sessions only (from `sessions.FIRST_SESSION`). Rows are written
with chosen `created_at` times and costs; no model, no network."""

import argparse
from datetime import UTC, date, datetime, timedelta

import pytest

from tradingresearch import journal, slo_check
from tradingresearch.cli import main
from tradingresearch.config import settings

SESSION = date(2026, 11, 18)
ON_TIME = datetime(2026, 11, 18, 21, 40, tzinfo=UTC)  # 16:40 ET


def row(conn, session: date, step: str, at: datetime, status: str = "ok", reason: str = "", daily_id: str = "dy_1",
        ticker: str | None = None, usd: float = 0.0) -> None:
    conn.execute("INSERT INTO daily_run (daily_id, session, step, ticker, status, reason, ids, cost_usd, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?)",
                 (daily_id, session.isoformat(), step, ticker, status, reason, usd, at.isoformat()))
    conn.commit()


def evening(conn, session: date, finish: datetime, daily_id: str = "dy_1") -> None:
    """A complete run: screen, then reconcile and grade, the last row at `finish`."""
    row(conn, session, "screen", finish.replace(minute=0), daily_id=daily_id)
    row(conn, session, "reconcile", finish, daily_id=daily_id, reason="reconcile ...")


def screened(conn, session: date, tickers: list[str], barred: list[str]) -> None:
    for t in tickers:
        conn.execute("INSERT INTO screen_result (session, ticker, points, triggers, filtered_out, rank, code_version, "
                     "created_at) VALUES (?, ?, 1, '[]', NULL, 1, 'screen-1', '2026-11-18T21:20:00+00:00')",
                     (session.isoformat(), t))
    for t in barred:
        conn.execute("INSERT INTO bars_daily (ticker, session, o, h, l, c, v, feed, adjustment, fetched_at) "
                     "VALUES (?, ?, 1, 1, 1, 1, 1, 'sip', 'raw', '2026-11-18T22:00:00+00:00')", (t, session.isoformat()))
    conn.commit()


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    yield c
    c.close()


def verdicts(slos: list[slo_check.Slo]) -> dict[str, bool]:
    return {s.name: s.ok for s in slos}


def test_an_on_time_complete_fresh_run_meets_every_slo(conn):
    evening(conn, SESSION, ON_TIME)
    row(conn, SESSION, "analyze", datetime(2026, 11, 18, 21, 31, tzinfo=UTC), ticker="AAPL", usd=0.017924)
    row(conn, SESSION, "thesis", datetime(2026, 11, 18, 23, 50, tzinfo=UTC), reason="teacher m: accepted 1")  # untimed
    screened(conn, SESSION, ["AAPL", "MSFT"], ["AAPL", "MSFT", "SPY"])
    slos = slo_check.check(conn, SESSION, "sip")
    assert verdicts(slos) == {"finished": True, "missed": True, "fresh": True, "cost": True}
    assert slo_check.render(SESSION, slos) == [
        "ok     finished dy_1 finished 2026-11-18 16:40 ET  (target: by 17:30 ET on 2026-11-18)",
        "ok     missed   0 of the last 1 sessions since 2026-11-18  (target: 0 in the last 10 sessions)",
        "ok     fresh    2 of 2 screened tickers have 2026-11-18 bars  (target: a screen result for 2026-11-18 and "
        "sip daily bars for every screened ticker)",
        "ok     cost     dy_1 spent $0.017924 of $0.60 (teacher steps $0.000000 more)  (target: at most $0.60 for "
        "the session's first paid run, teacher steps apart)",
        "slo 2026-11-18: 4/4 met"]


def test_a_late_finish_and_an_injected_delay_breach(conn):
    evening(conn, SESSION, ON_TIME)
    late = slo_check.finished(conn, SESSION, timedelta(minutes=51))
    assert not late.ok and late.measured == "dy_1 finished 2026-11-18 17:31 ET (+51 min injected)"
    assert slo_check.finished(conn, SESSION, timedelta(minutes=50)).ok  # 17:30 itself is on time
    other = date(2026, 11, 19)
    evening(conn, other, datetime(2026, 11, 20, 4, 21, tzinfo=UTC), daily_id="dy_2")  # 23:21 ET
    evening(conn, other, datetime(2026, 11, 19, 21, 0, tzinfo=UTC), daily_id="dy_3")  # a later rerun does not count
    assert slo_check.finished(conn, other).measured == "dy_2 finished 2026-11-19 23:21 ET"
    row(conn, date(2026, 11, 20), "screen", ON_TIME, status="failed", daily_id="dy_4")
    assert not slo_check.finished(conn, date(2026, 11, 20)).ok  # no reconcile row: not a completed run


def test_missed_sessions_count_recorded_misses_and_sessions_with_no_row(conn):
    evening(conn, date(2026, 11, 12), ON_TIME, daily_id="dy_0")  # the first run
    row(conn, date(2026, 11, 13), "screen", ON_TIME, status="missed", daily_id="dy_1")
    evening(conn, date(2026, 11, 16), ON_TIME, daily_id="dy_1")
    evening(conn, SESSION, ON_TIME, daily_id="dy_2")  # 2026-11-17 has no row at all
    slo = slo_check.missed(conn, SESSION)
    assert not slo.ok  # only live sessions count: 2026-11-13 predates the live stream
    assert slo.measured == "1 of the last 2 sessions since 2026-11-17: 2026-11-17"
    every = slo_check.missed(conn, SESSION, since=None)
    assert every.measured == "2 of the last 5 sessions since 2026-11-12: 2026-11-13, 2026-11-17"
    assert slo_check.missed(conn, SESSION, window=1).ok  # only 2026-11-18 itself


def test_freshness_breaches_without_a_screen_or_with_a_ticker_missing_bars(conn):
    evening(conn, SESSION, ON_TIME)
    assert slo_check.fresh(conn, SESSION, "sip").measured == "no screen result for 2026-11-18"
    screened(conn, SESSION, ["AAPL", "MSFT"], ["AAPL"])
    slo = slo_check.fresh(conn, SESSION, "sip")
    assert not slo.ok and slo.measured == "1 of 2 screened tickers have 2026-11-18 bars; no bars for MSFT"
    assert not slo_check.fresh(conn, SESSION, "iex").ok  # bars on another feed do not count


def test_cost_reads_the_first_paid_run_against_the_budget_and_no_paid_row_is_no_data(conn):
    none = slo_check.cost(conn, SESSION)
    assert none.ok is None and none.measured == "no data: no tr daily run for 2026-11-18"
    evening(conn, SESSION, ON_TIME)  # screen and reconcile cost $0
    unpaid = slo_check.cost(conn, SESSION)
    assert unpaid.ok is None and unpaid.measured == "no data: 1 tr daily run(s) for 2026-11-18, none with a paid step"
    assert unpaid.target == "at most $0.60 for the session's first paid run, teacher steps apart"
    at = datetime(2026, 11, 18, 21, 35, tzinfo=UTC)
    row(conn, SESSION, "analyze", at, ticker="HD", usd=0.017924)
    row(conn, SESSION, "thesis", at, ticker="HD", status="failed", reason="rate_limited", usd=0.021766)  # billed too
    row(conn, SESSION, "thesis", at, ticker="HD", reason="teacher deepseek/deepseek-v4-pro: accepted 1", usd=0.003016)
    met = slo_check.cost(conn, SESSION)
    assert met.ok and met.measured == "dy_1 spent $0.039690 of $0.60 (teacher steps $0.003016 more)"
    evening(conn, SESSION, datetime(2026, 11, 19, 2, 0, tzinfo=UTC), daily_id="dy_2")  # the 21:00 ET catch-up
    row(conn, SESSION, "analyze", at, ticker="JPM", daily_id="dy_2", usd=0.9)
    assert slo_check.cost(conn, SESSION) == met  # a later rerun, whatever it cost, does not change the reading
    over = slo_check.cost(conn, SESSION, budget=0.03)
    assert over.ok is False and over.measured == "dy_1 spent $0.039690 of $0.03 (teacher steps $0.003016 more)"
    assert slo_check.cost(conn, SESSION, budget=0.03969).ok  # the budget itself is met
    other = date(2026, 11, 19)
    row(conn, other, "screen", ON_TIME, daily_id="dy_3")  # a $0 rehearsal first, then the run that paid
    row(conn, other, "analyze", ON_TIME, ticker="HD", daily_id="dy_4", usd=0.7)
    breach = slo_check.cost(conn, other)
    assert breach.ok is False and breach.measured.startswith("dy_4 spent $0.700000 of $0.60")


def test_render_and_the_exit_code_treat_no_data_as_neither_met_nor_breached(tmp_path, monkeypatch, capsys):
    none = slo_check.Slo("cost", None, "no data: no tr daily run for 2026-11-18", "at most $0.60")
    assert slo_check.render(SESSION, [slo_check.Slo("fresh", True, "m", "t"), none]) == [
        "ok     fresh    m  (target: t)",
        "n/a    cost     no data: no tr daily run for 2026-11-18  (target: at most $0.60)",
        "slo 2026-11-18: 1/1 met; no data: cost"]
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    conn = journal.connect(tmp_path / "journal.db")
    evening(conn, SESSION, ON_TIME)
    screened(conn, SESSION, ["AAPL"], ["AAPL"])
    row(conn, SESSION, "analyze", ON_TIME, ticker="AAPL", usd=0.5)
    conn.close()
    main(["slo"])  # $0.50 of $0.60: met
    assert capsys.readouterr().out.rstrip().endswith("slo 2026-11-18: 4/4 met")
    with pytest.raises(SystemExit) as breach:
        main(["slo", "--budget-usd", "0.45"])
    assert breach.value.code == 1
    out = capsys.readouterr().out
    assert "BREACH cost     dy_1 spent $0.500000 of $0.45 (teacher steps $0.000000 more)  (target: at most $0.45 " in out
    assert out.rstrip().endswith("slo 2026-11-18: 3/4 met")


def slo(argv: list[str], now: datetime) -> int:
    """`tr slo` at a chosen wall-clock time (only the no-live-run path reads the clock)."""
    parser = argparse.ArgumentParser()
    slo_check.add_arguments(parser)
    return slo_check.run(parser.parse_args(argv), settings(), now)


def test_the_command_exits_1_on_a_breach_and_0_when_met(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    assert slo([], datetime(2026, 11, 17, 20, 0, tzinfo=UTC)) == 0  # 15:00 ET on the first live session
    assert capsys.readouterr().out == "slo: no live session yet: the live stream starts 2026-11-17\n"
    assert slo([], datetime(2026, 11, 18, 23, 0, tzinfo=UTC)) == 1  # 18:00 ET a day later: two deadlines passed
    assert capsys.readouterr().out.splitlines() == [
        "BREACH missed   2 of the last 2 sessions since 2026-11-17: 2026-11-17, 2026-11-18  "
        "(target: 0 in the last 10 sessions)",
        "slo: no tr daily run for any live session"]
    conn = journal.connect(tmp_path / "journal.db")
    evening(conn, SESSION, ON_TIME)
    screened(conn, SESSION, ["AAPL"], ["AAPL"])
    conn.close()
    assert slo_check.main([]) == 0
    main(["slo"])  # met: returns normally
    with pytest.raises(SystemExit) as breach:
        main(["slo", "--inject-delay-minutes", "60"])
    assert breach.value.code == 1
    out = capsys.readouterr().out
    assert "BREACH finished dy_1 finished 2026-11-18 17:40 ET (+60 min injected)" in out
    assert out.rstrip().endswith("slo 2026-11-18: 2/3 met; no data: cost")  # $0 rows: cost has nothing to measure


def test_a_journal_of_only_the_pre_live_dev_run_has_no_live_session_and_session_names_it(tmp_path, monkeypatch,
                                                                                          capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    dev = date(2026, 11, 16)
    conn = journal.connect(tmp_path / "journal.db")
    evening(conn, dev, datetime(2026, 11, 17, 4, 21, tzinfo=UTC), daily_id="dy_dev")  # 23:21 ET: a real breach
    screened(conn, dev, ["AAPL"], [])
    conn.close()
    assert slo([], datetime(2026, 11, 17, 15, 0, tzinfo=UTC)) == 0  # 10:00 ET on the first live session
    assert capsys.readouterr().out == ("slo: no live session yet: the live stream starts 2026-11-17; the latest tr "
                                       "daily run (2026-11-16) predates it and is not checked\n")
    assert slo(["--session", "2026-11-16"], datetime(2026, 11, 17, 15, 0, tzinfo=UTC)) == 1
    assert capsys.readouterr().out.splitlines() == [
        "pre-live: 2026-11-16 predates the live stream (from 2026-11-17); a dev run, checked because --session "
        "named it",
        "BREACH finished dy_dev finished 2026-11-16 23:21 ET  (target: by 17:30 ET on 2026-11-16)",
        "ok     missed   0 of the last 1 sessions since 2026-11-16  (target: 0 in the last 10 sessions)",
        "BREACH fresh    0 of 1 screened tickers have 2026-11-16 bars; no bars for AAPL  (target: a screen result for "
        "2026-11-16 and sip daily bars for every screened ticker)",
        "n/a    cost     no data: 1 tr daily run(s) for 2026-11-16, none with a paid step  (target: at most $0.60 for "
        "the session's first paid run, teacher steps apart)",
        "slo 2026-11-16: 1/3 met; no data: cost"]


def test_a_live_run_is_checked_and_the_pre_live_run_before_it_is_not_a_miss(conn):
    evening(conn, date(2026, 11, 16), datetime(2026, 11, 17, 4, 21, tzinfo=UTC), daily_id="dy_dev")
    assert slo_check.latest_session(conn) is None and slo_check.latest_session(conn, since=None) == date(2026, 11, 16)
    evening(conn, date(2026, 11, 17), datetime(2026, 11, 17, 21, 40, tzinfo=UTC), daily_id="dy_live")
    assert slo_check.latest_session(conn) == date(2026, 11, 17)
    assert slo_check.missed(conn, date(2026, 11, 17)).measured == "0 of the last 1 sessions since 2026-11-17"
    assert slo_check.overdue(datetime(2026, 11, 17, 22, 29, tzinfo=UTC)) == []  # 17:29 ET
    assert slo_check.overdue(datetime(2026, 11, 17, 22, 30, tzinfo=UTC)) == [date(2026, 11, 17)]
