"""`tr screen`: the code-only daily screen (SPIKE §4.2). Points from §5 values, an ATR filter, no model call."""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
from gigai_core import CoreModel

from . import alpaca, indicators, journal, sessions
from .edgar import Edgar

CODE_VERSION = f"screen-1+{indicators.CODE_VERSION}"
HISTORY = 300  # sessions fetched, as gather: SPY's regime needs about 267
MIN_BARS = 61  # 60-session levels and 20 previous sessions for high_20, low_20 and rel_volume
LEVEL_ATR = 0.5
REL_VOLUME = 1.5
ATR_PCT = (0.8, 5.0)  # SPIKE §4.2: the move can pay for costs without being erratic
HORIZONS = {"day", "short", "swing"}

Trigger = dict[str, float | int | str]


class ScreenResult(CoreModel):
    """One ticker in one run. Every universe ticker gets a row; only unfiltered tickers with points get a rank."""

    session: date
    ticker: str
    points: int
    triggers: dict[str, Trigger]
    filtered_out: str | None
    rank: int | None
    code_version: str


@dataclass(frozen=True)
class Scored:
    """A ticker before ranking. rel_volume breaks ties even when it is below the 1.5 trigger."""

    ticker: str
    points: int
    triggers: dict[str, Trigger]
    filtered_out: str | None
    rel_volume: float


def read_universe(path: Path) -> list[str]:
    """One ticker per line, `#` starts a comment, duplicates dropped. SPY is the regime input, never screened."""
    tickers: list[str] = []
    for line in path.read_text().splitlines():
        ticker = line.split("#", 1)[0].strip().upper()
        if ticker and ticker != "SPY" and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def fetch_missing(conn: sqlite3.Connection, http: httpx.Client, tickers: list[str], day: date, feed: str) -> list[str]:
    """Fetch and store, in one request, the tickers that lack any of the last HISTORY sessions up to `day`."""
    start = sessions.recent(HISTORY, day)[0]
    have = dict(conn.execute(
        "SELECT ticker, count(*) FROM bars_daily WHERE feed = ? AND adjustment = 'split' AND session BETWEEN ? AND ? "
        "GROUP BY ticker", (feed, start.isoformat(), day.isoformat()),
    ).fetchall())
    missing = [t for t in tickers if have.get(t, 0) < HISTORY]
    if missing:
        alpaca.store_daily(conn, alpaca.daily_bars(http, missing, start, day, feed=feed), feed=feed, adjustment="split")
    return missing


def code_triggers(bars: pd.DataFrame) -> tuple[dict[str, Trigger], dict[str, float]]:
    """The four bar triggers at the last bar, and the §5.1 values they came from."""
    values = indicators.snapshot_values(bars)
    close, atr_now = values["close"], values["atr_14"]
    fired: dict[str, Trigger] = {}
    near = [lv for lv in indicators.levels(bars) if abs(lv.distance_atr) <= LEVEL_ATR]
    if near:
        best = min(near, key=lambda lv: abs(lv.distance_atr))
        fired["level"] = {"kind": best.kind, "price": best.price, "distance_atr": best.distance_atr}
    zone = indicators.congestion(bars, atr_now)  # None unless it spans 5 or more sessions
    if zone or values["nr7"]:
        fired["congestion"] = {"sessions": zone.sessions if zone else 0, "nr7": int(values["nr7"])}
    if close > values["high_20"]:
        fired["breakout"] = {"side": "high", "close": close, "level": values["high_20"]}
    elif close < values["low_20"]:
        fired["breakout"] = {"side": "low", "close": close, "level": values["low_20"]}
    if values["rel_volume"] >= REL_VOLUME:
        fired["rel_volume"] = {"rel_volume": values["rel_volume"]}
    return fired, values


def score(ticker: str, bars: pd.DataFrame, day: date, filings: list[dict], live: set[str]) -> Scored:
    """Points for one ticker on `day`. Filtered tickers keep their points so learn can see what was dropped."""
    if bars.empty or bars["session"].iloc[-1].date() != day:
        return Scored(ticker, 0, {}, "no_bar", 0.0)
    if len(bars) < MIN_BARS:
        return Scored(ticker, 0, {}, "short_history", 0.0)
    fired, values = code_triggers(bars)
    if filings:
        fired["8k"] = {"count": len(filings), "accepted": filings[-1]["acceptanceDateTime"],
                       "accession": ",".join(f["accessionNumber"] for f in filings)}
    reason = None
    if live >= HORIZONS:
        reason = "live_all_horizons"
    elif values["atr_pct"] < ATR_PCT[0]:
        reason = "atr_pct_low"
    elif values["atr_pct"] > ATR_PCT[1]:
        reason = "atr_pct_high"
    return Scored(ticker, len(fired), fired, reason, values["rel_volume"])


def rank(scored: list[Scored], day: date) -> list[ScreenResult]:
    """Rank unfiltered tickers with points by points, then relative volume (ticker last, so ties are stable)."""
    eligible = sorted((s for s in scored if s.filtered_out is None and s.points > 0),
                      key=lambda s: (-s.points, -s.rel_volume, s.ticker))
    ranks = {s.ticker: n for n, s in enumerate(eligible, start=1)}
    return [
        ScreenResult(session=day, ticker=s.ticker, points=s.points, triggers=s.triggers, filtered_out=s.filtered_out,
                     rank=ranks.get(s.ticker), code_version=CODE_VERSION)
        for s in scored
    ]


def run(conn: sqlite3.Connection, edgar: Edgar, universe: list[str], day: date, since: date,
        feed: str) -> list[ScreenResult]:
    """Score every universe ticker from stored bars and EDGAR 8-Ks, rank, and store the run.

    8-Ks count when accepted after the close of `since` and up to the close of `day`: each one is counted in exactly
    one run, nothing after the bar is seen, and an earnings 8-K filed at 16:30 lands in the next session's run.
    """
    after, until = sessions.open_close(since)[1], sessions.open_close(day)[1]
    scored = []
    for ticker in universe:
        bars = alpaca.load_daily(conn, ticker, day, feed=feed)
        filings: list[dict] = []
        if not bars.empty and bars["session"].iloc[-1].date() == day:
            try:
                filings = edgar.recent_8k(ticker, after, until)
            except KeyError as error:  # not an SEC filer under this ticker: the 8-K trigger cannot fire
                print(f"warning: {error.args[0]}; 8-K trigger skipped", file=sys.stderr)
        scored.append(score(ticker, bars, day, filings, journal.live_horizons(conn, ticker)))
    results = rank(scored, day)
    journal.add_screen_results(conn, [r.model_dump(mode="json") for r in results])
    return results


def stored(conn: sqlite3.Connection, day: date) -> list[ScreenResult]:
    """The run already stored for `day` at this code version (empty if none)."""
    rows = journal.screen_results(conn, day, CODE_VERSION)
    return [ScreenResult.model_validate(row | {"session": date.fromisoformat(row["session"])}) for row in rows]


def regime(conn: sqlite3.Connection, day: date, feed: str) -> str:
    """SPY's §5.4 regime tag on `day`, or why it cannot be computed."""
    try:
        return indicators.regime(alpaca.load_daily(conn, "SPY", day, feed=feed))
    except (ValueError, IndexError) as error:
        return f"unknown ({error})"


def describe(name: str, t: Trigger) -> str:
    """One fired trigger as short text for the shortlist line."""
    if name == "level":
        return f"level {t['kind']} {t['price']:.2f} ({t['distance_atr']:+.2f} ATR)"
    if name == "congestion":
        return f"congestion {t['sessions']}d" if t["sessions"] else "nr7"
    if name == "breakout":
        return f"breakout {t['side']} {t['level']:.2f}"
    if name == "rel_volume":
        return f"rel_volume {t['rel_volume']:.2f}"
    return f"8-K x{t['count']} accepted {t['accepted']}"


def render(results: list[ScreenResult], top: int) -> list[str]:
    """The shortlist (rank <= top) as `rank ticker points triggers`, then the filtered and zero-point counts."""
    shortlist = sorted((r for r in results if r.rank is not None and r.rank <= top), key=lambda r: r.rank or 0)
    lines = ["rank ticker points triggers"]
    lines += [f"{r.rank:>4} {r.ticker:<6} {r.points:>6} " + "; ".join(describe(k, v) for k, v in r.triggers.items())
              for r in shortlist]
    if not shortlist:
        lines.append("nothing set up")
    filtered = [r for r in results if r.filtered_out]
    reasons = sorted({r.filtered_out for r in filtered if r.filtered_out})
    detail = ", ".join(f"{reason} {sum(r.filtered_out == reason for r in filtered)}" for reason in reasons)
    lines.append(f"filtered {len(filtered)}" + (f" ({detail})" if detail else ""))
    lines.append(f"zero points {sum(r.points == 0 and not r.filtered_out for r in results)}")
    return lines
