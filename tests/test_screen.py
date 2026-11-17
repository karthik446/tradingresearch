"""`tr screen` (SPIKE §4.2): one trigger per synthetic bar set, the filter, the live skip, the journal, a golden run.

The base history is a zigzag 100 -> 109 -> 110 -> 101 ... (period 20, 4 cycles) then 100..104, every bar h = c + 1,
l = c - 1, v = 1e6. Every true range is 2, so ATR(14) is 2 before the last bar; high_20 = pivot high = 111,
low_20 = pivot low = 99; no volume node sits near the close. The last bar decides which trigger fires.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest
from factories import analysis, event, thesis

from tradingresearch import alpaca, journal, screen, sessions
from tradingresearch.edgar import Edgar
from tradingresearch.records import HOLD_RANGE

FIXTURES = Path(__file__).parent / "fixtures" / "screen"
DAY = date(2026, 11, 10)
HISTORY = [c for _ in range(4) for c in (*range(100, 110), *range(110, 100, -1))] + list(range(100, 105))
BASE = (105, 106.2, 103.8, 105)  # TR 2.4: ATR (13*2 + 2.4)/14 = 2.0286, atr_pct 1.93, 2.96 ATR from 111 and 99
LEVEL = (110.2, 111.0, 108.6, 110.2)  # TR 7: ATR 33/14, (110.2 - 111)/(33/14) = -0.339 ATR from the 111 pivot
BREAKOUT = (113, 113.5, 104, 113)  # close above high_20 111; TR 9.5: ATR 2.536, 0.79 ATR from 111 (no level point)
NR7 = (105, 105.5, 104.5, 105)  # range 1 is the narrowest of the last 7 (every other range is 2)
FLAT = [(105, 105.5, 104.5, 105, 200_000)] * 5  # with a last bar of range 1.2: congestion of 6 sessions, not NR7


def bars(last=BASE, *, last_volume=1_000_000, offset=0.0, flat=()) -> pd.DataFrame:
    """History plus `flat` bars plus `last`, ending on DAY, in load_daily's shape."""
    rows = [(c, c + 1, c - 1, c, 1_000_000) for c in HISTORY] + list(flat) + [(*last, last_volume)]
    frame = pd.DataFrame(rows, columns=["o", "h", "l", "c", "v"])
    frame[["o", "h", "l", "c"]] += offset
    frame.insert(0, "session", pd.to_datetime(sessions.recent(len(rows), DAY)))
    return frame


def filings() -> list[dict]:
    """The real AAPL 8-K accepted 2026-11-09 21:30:40Z (an 8.01 item), from the trimmed submissions fixture."""
    recent = json.loads((FIXTURES / "submissions_CIK0000320193.json").read_text())["filings"]["recent"]
    rows = [dict(zip(recent, values)) for values in zip(*recent.values())]
    return [r for r in rows if r["accessionNumber"] == "0001140361-26-042798"]


@pytest.fixture
def conn():
    return journal.connect(":memory:")


@pytest.mark.parametrize(("frame", "news", "fired"), [
    (bars(), [], set()),
    (bars(LEVEL), [], {"level"}),
    (bars(BASE, flat=FLAT, last_volume=200_000), [], {"congestion"}),
    (bars(NR7), [], {"congestion"}),
    (bars(BREAKOUT), [], {"breakout"}),
    (bars(last_volume=2_000_000), [], {"rel_volume"}),
    (bars(), filings(), {"8k"}),
], ids=["none", "level", "congestion", "nr7", "breakout", "rel_volume", "8k"])
def test_each_trigger_fires_alone_for_one_point(frame, news, fired):
    scored = screen.score("AAA", frame, DAY, news, set())
    assert set(scored.triggers) == fired
    assert scored.points == len(fired)
    assert scored.filtered_out is None


def test_trigger_details_match_the_hand_arithmetic():
    level = screen.score("AAA", bars(LEVEL), DAY, [], set()).triggers["level"]
    assert level["kind"] == "pivot_high" and level["price"] == 111.0
    assert level["distance_atr"] == pytest.approx(-0.8 / (33 / 14))
    zone = screen.score("AAA", bars(BASE, flat=FLAT, last_volume=200_000), DAY, [], set()).triggers["congestion"]
    assert zone == {"sessions": 6, "nr7": 0}  # a 7th session (h 105, l 103) makes the range 2.6 > 1.5 ATR (2.52)
    assert screen.score("AAA", bars(NR7), DAY, [], set()).triggers["congestion"] == {"sessions": 0, "nr7": 1}
    assert screen.score("AAA", bars(BREAKOUT), DAY, [], set()).triggers["breakout"] == {
        "side": "high", "close": 113.0, "level": 111.0}


@pytest.mark.parametrize(("offset", "reason"), [(300, "atr_pct_low"), (-70, "atr_pct_high")])
def test_atr_pct_outside_the_band_is_filtered_but_keeps_its_points(offset, reason):
    """+300: ATR 2.03 on a 405 close is 0.50 %; -70: 2.03 on 35 is 5.80 %."""
    scored = screen.score("AAA", bars(last_volume=2_000_000, offset=offset), DAY, [], set())
    assert (scored.filtered_out, scored.points) == (reason, 1)
    assert screen.rank([scored], DAY)[0].rank is None


def test_missing_bar_and_short_history_are_filtered():
    assert screen.score("AAA", bars().iloc[:-1], DAY, [], set()).filtered_out == "no_bar"
    assert screen.score("AAA", bars().iloc[-60:], DAY, [], set()).filtered_out == "short_history"


def test_zero_points_is_never_shortlisted():
    results = screen.rank([screen.score("AAA", bars(), DAY, [], set())], DAY)
    assert results[0].points == 0 and results[0].rank is None
    assert screen.render(results, 10) == ["rank ticker points triggers", "nothing set up", "filtered 0",
                                          "zero points 1"]


def live(conn, horizons, state="PROPOSED"):
    a = analysis()
    journal.add_analysis(conn, a, sources=[])
    for horizon in horizons:
        t = thesis(a.analysis_id, horizon=horizon, hold_sessions=HOLD_RANGE[horizon][0])
        journal.add(conn, t, event(t.thesis_id, state))


def test_a_ticker_live_on_every_horizon_is_skipped(conn):
    live(conn, ["day", "short", "swing"])
    assert journal.live_horizons(conn, "AAPL") == {"day", "short", "swing"}
    scored = screen.score("AAPL", bars(LEVEL), DAY, [], journal.live_horizons(conn, "AAPL"))
    assert scored.filtered_out == "live_all_horizons"


def test_a_free_horizon_or_a_closed_thesis_keeps_the_ticker(conn):
    live(conn, ["day", "short"])
    assert screen.score("AAPL", bars(LEVEL), DAY, [], journal.live_horizons(conn, "AAPL")).filtered_out is None
    other = analysis(ticker="MSFT")
    journal.add_analysis(conn, other, sources=[])
    t = thesis(other.analysis_id, ticker="MSFT", horizon="swing")
    journal.add(conn, t, event(t.thesis_id, "PROPOSED"), event(t.thesis_id, "EXPIRED", reason="window_missed"))
    assert journal.live_horizons(conn, "MSFT") == set()


def test_golden_shortlist_of_five_tickers():
    """BBB 3 (breakout, rel_volume 3.0, the 8-K), AAA 2 (level, 2.0), DDD 1 (1.6) before CCC 1 (nr7, rel_volume 1.0)
    on the tie-break; EEE has a rel_volume point but ATR 2.03 on a 35 close (5.80 %) filters it out."""
    scored = [
        screen.score("AAA", bars(LEVEL, last_volume=2_000_000), DAY, [], set()),
        screen.score("BBB", bars(BREAKOUT, last_volume=3_000_000), DAY, filings(), set()),
        screen.score("CCC", bars(NR7), DAY, [], set()),
        screen.score("DDD", bars(last_volume=1_600_000), DAY, [], set()),
        screen.score("EEE", bars(last_volume=2_000_000, offset=-70), DAY, [], set()),
    ]
    results = screen.rank(scored, DAY)
    assert [(r.ticker, r.rank) for r in results] == [("AAA", 2), ("BBB", 1), ("CCC", 4), ("DDD", 3), ("EEE", None)]
    assert "\n".join(screen.render(results, 10)) + "\n" == (FIXTURES / "shortlist.txt").read_text()
    assert screen.render(results, 2)[1:3] == screen.render(results, 10)[1:3] and len(screen.render(results, 2)) == 5


def test_screen_results_are_append_only_and_a_rerun_adds_nothing(conn):
    results = screen.rank([screen.score("AAA", bars(LEVEL), DAY, [], set())], DAY)
    rows = [r.model_dump(mode="json") for r in results]
    assert journal.add_screen_results(conn, rows) == 1
    assert journal.add_screen_results(conn, [rows[0] | {"points": 9}]) == 0
    assert screen.stored(conn, DAY) == results
    for statement in ("UPDATE screen_result SET points = 9", "DELETE FROM screen_result"):
        with pytest.raises(sqlite3.IntegrityError, match="screen_result is append-only"):
            conn.execute(statement)
    assert journal.last_screened(conn, date(2026, 11, 11)) == DAY
    assert journal.last_screened(conn, DAY) is None


def test_universe_file_drops_comments_duplicates_and_spy(tmp_path):
    path = tmp_path / "universe.txt"
    path.write_text("# mine\naapl\nMSFT  # cloud\n\nSPY\nAAPL\nbrk.b\n")
    assert screen.read_universe(path) == ["AAPL", "MSFT", "BRK.B"]


def edgar_with(tmp_path, calls: list[str]) -> Edgar:
    """A real Edgar whose HTTP layer serves the trimmed AAPL submissions fixture and records each URL."""
    (tmp_path / "company_tickers.json").write_text((FIXTURES / "company_tickers.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=(FIXTURES / "submissions_CIK0000320193.json").read_bytes())

    client = Edgar("tradingresearch test@example.com", tmp_path)
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_recent_8k_filters_by_acceptance_time_and_caches_for_the_day(tmp_path):
    calls: list[str] = []
    client = edgar_with(tmp_path, calls)
    close = sessions.open_close
    found = client.recent_8k("AAPL", close(date(2026, 11, 9))[1], close(DAY)[1])
    assert [f["accessionNumber"] for f in found] == ["0001140361-26-042798"]  # 21:30Z is after the 21:00Z close
    both = client.recent_8k("AAPL", datetime(2026, 11, 1, tzinfo=UTC))
    assert [f["acceptanceDateTime"][:10] for f in both] == ["2026-11-02", "2026-11-09"]
    assert calls == ["https://data.sec.gov/submissions/CIK0000320193.json"]  # the second read hit the cache
    yesterday = time.time() - 86_400
    os.utime(tmp_path / "submissions" / "CIK0000320193.json", (yesterday, yesterday))
    client.recent_8k("AAPL", datetime(2026, 11, 1, tzinfo=UTC))
    assert len(calls) == 2
    assert client.cik("BRK.B") == 1067983


def store(conn, ticker: str, frame: pd.DataFrame) -> None:
    alpaca.store_daily(conn, frame.assign(ticker=ticker, session=frame["session"].dt.date, n=1, vw=frame["c"]),
                       feed="sip", adjustment="split")


def test_run_scores_stores_and_warns_without_a_cik(conn, tmp_path, capsys):
    store(conn, "AAPL", bars(BREAKOUT, last_volume=3_000_000))
    store(conn, "ZZZZ", bars(NR7))
    results = screen.run(conn, edgar_with(tmp_path, []), ["AAPL", "ZZZZ"], DAY, date(2026, 11, 9), "sip")
    assert [(r.ticker, r.points, r.rank) for r in results] == [("AAPL", 3, 1), ("ZZZZ", 1, 2)]
    assert results[0].triggers["8k"]["accession"] == "0001140361-26-042798"
    assert "no CIK for ZZZZ" in capsys.readouterr().err
    assert screen.stored(conn, DAY) == results
    assert journal.add_screen_results(conn, [r.model_dump(mode="json") for r in results]) == 0
