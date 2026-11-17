"""`slo_check.py` / `tr slo` (PLAN-60 week 3): finish by 17:30 ET, zero missed sessions, fresh data. Rows are written
with chosen `created_at` times; no model, no network."""

from datetime import UTC, date, datetime, timedelta

import pytest

from tradingresearch import journal, slo_check
from tradingresearch.cli import main

SESSION = date(2026, 11, 18)
ON_TIME = datetime(2026, 11, 18, 21, 40, tzinfo=UTC)  # 16:40 ET


def row(conn, session: date, step: str, at: datetime, status: str = "ok", reason: str = "", daily_id: str = "dy_1",
        ticker: str | None = None) -> None:
    conn.execute("INSERT INTO daily_run (daily_id, session, step, ticker, status, reason, ids, cost_usd, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, '[]', 0.0, ?)",
                 (daily_id, session.isoformat(), step, ticker, status, reason, at.isoformat()))
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
    row(conn, SESSION, "thesis", datetime(2026, 11, 18, 23, 50, tzinfo=UTC), reason="teacher m: accepted 1")  # untimed
    screened(conn, SESSION, ["AAPL", "MSFT"], ["AAPL", "MSFT", "SPY"])
    slos = slo_check.check(conn, SESSION, "sip")
    assert verdicts(slos) == {"finished": True, "missed": True, "fresh": True}
    assert slo_check.render(SESSION, slos) == [
        "ok     finished dy_1 finished 2026-11-18 16:40 ET  (target: by 17:30 ET on 2026-11-18)",
        "ok     missed   0 of the last 1 sessions since 2026-11-18  (target: 0 in the last 10 sessions)",
        "ok     fresh    2 of 2 screened tickers have 2026-11-18 bars  (target: a screen result for 2026-11-18 and "
        "sip daily bars for every screened ticker)",
        "slo 2026-11-18: 3/3 met"]


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
    assert not slo.ok
    assert slo.measured == "2 of the last 5 sessions since 2026-11-12: 2026-11-13, 2026-11-17"
    assert slo_check.missed(conn, SESSION, window=1).ok  # only 2026-11-18 itself


def test_freshness_breaches_without_a_screen_or_with_a_ticker_missing_bars(conn):
    evening(conn, SESSION, ON_TIME)
    assert slo_check.fresh(conn, SESSION, "sip").measured == "no screen result for 2026-11-18"
    screened(conn, SESSION, ["AAPL", "MSFT"], ["AAPL"])
    slo = slo_check.fresh(conn, SESSION, "sip")
    assert not slo.ok and slo.measured == "1 of 2 screened tickers have 2026-11-18 bars; no bars for MSFT"
    assert not slo_check.fresh(conn, SESSION, "iex").ok  # bars on another feed do not count


def test_the_command_exits_1_on_a_breach_and_0_when_met(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(tmp_path / "none.env"))
    assert slo_check.main([]) == 1 and capsys.readouterr().out == "BREACH no tr daily run in the journal\n"
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
    assert out.rstrip().endswith("slo 2026-11-18: 2/3 met")
