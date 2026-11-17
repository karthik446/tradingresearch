"""The playbook (SPIKE §8.1): code-computed statistics per (horizon, setup_type) over graded theses of one arm, the
table `tr learn` prints and week 5 puts into the thesis prompt as computed facts. Reuses the `tr report` statistics
(Wilson, session-cluster bootstrap, P1 sources); no model call, no network.

Cells with fewer than THIN closed trades are flagged, never hidden: a 5-trade cell is where in-sample lessons overfit.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date
from typing import get_args

from gigai_core.stats import ClusterBootstrap, WilsonInterval, wilson_interval

from . import journal, report, sessions
from .records import SetupType, Thesis

THIN = 5  # n below this is flagged `thin`
SOURCE_URI = "tradingresearch:playbook.py#compute"


@dataclass(frozen=True)
class Row:
    """One (horizon, setup_type) cell and its graded trades."""

    horizon: str
    setup_type: str
    trades: tuple[report.Trade, ...]

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def thin(self) -> bool:
        return self.n < THIN

    @property
    def wins(self) -> WilsonInterval:
        return wilson_interval(sum(t.r_net > 0 for t in self.trades), self.n)

    @property
    def mean_r(self) -> float:
        return statistics.fmean(t.r_net for t in self.trades)

    @property
    def mean_r_ci(self) -> ClusterBootstrap | None:
        """None below MIN_CLUSTERS entry sessions (§7.5 "insufficient")."""
        return report.mean_r(self.trades)

    @property
    def shadow_delta(self) -> float | None:
        """Mean real - shadow r_net over trades whose shadow has an outcome; None when none has."""
        pairs = report.paired(self.trades)
        return statistics.fmean(t.r_net - t.shadow_r_net for t in pairs) if pairs else None

    @property
    def p1(self) -> tuple[int, int, int]:
        """(met, met + not met, unknown) over trades with a P1 result."""
        met = sum(t.p1 == "met" for t in self.trades)
        decided = sum(t.p1 in ("met", "not_met") for t in self.trades)
        return met, decided, sum(t.p1 == "unknown" for t in self.trades)

    @property
    def median_mfe(self) -> float:
        return statistics.median(t.mfe_r for t in self.trades)

    @property
    def median_mae(self) -> float:
        return statistics.median(t.mae_r for t in self.trades)


@dataclass(frozen=True)
class Playbook:
    """The cells of one arm as of one session, in horizon then setup-type order."""

    session: date
    arm: str
    rows: tuple[Row, ...]


def compute(conn: sqlite3.Connection, session: date, arm: str = "champion") -> Playbook:
    """Graded theses of `arm` whose CLOSED event is on or before `session` (what was known by then), one row per
    (horizon, setup_type) that has any. Teacher theses never enter (TRAINING-SPIKE §7.2 row 8)."""
    if arm not in report.ARMS:
        raise ValueError(f"arm {arm!r} has no playbook: only {', '.join(report.ARMS)}")
    cells: dict[tuple[str, str], list[report.Trade]] = {}
    for (body,) in conn.execute("SELECT body FROM thesis WHERE arm = ? ORDER BY rowid", (arm,)).fetchall():
        t = Thesis.model_validate_json(body)
        events = journal.events_for(conn, t.thesis_id)
        opened = next((e for e in events if e.state == "OPEN"), None)
        closed = next((e for e in events if e.state == "CLOSED"), None)
        grade = report.graded(conn, t.thesis_id)
        if grade is None or opened is None or closed is None or closed.at.astimezone(sessions.NY).date() > session:
            continue
        cells.setdefault((t.horizon, t.setup_type), []).append(report.trade(conn, grade, opened))
    rows = tuple(Row(h, s, tuple(cells[h, s])) for h in report.HORIZONS for s in get_args(SetupType) if (h, s) in cells)
    return Playbook(session, arm, rows)


def p1_text(row: Row) -> str:
    met, decided, unknown = row.p1
    if not decided:
        return f"P1: none met or not met ({unknown} unknown)" if unknown else "P1: no judged trades"
    return f"P1 met {report.ratio(met, decided)}; {unknown} unknown excluded"


def render(playbook: Playbook) -> list[str]:
    """The playbook as text: a header, then one block per cell; an honest line when there is no cell."""
    head = (f"playbook: {playbook.arm} theses graded and closed by {playbook.session}, one row per (horizon, "
            f"setup_type), never pooled; cells with n < {THIN} are thin (few trades overfit)")
    if not playbook.rows:
        return [head, f"  no graded {playbook.arm} theses closed by {playbook.session} yet: nothing to learn from"]
    lines = [head]
    for row in playbook.rows:
        w, delta = row.wins, row.shadow_delta
        shadow = (f"real - shadow {delta:+.2f} R over {len(report.paired(row.trades))} pairs" if delta is not None
                  else "real - shadow: no shadow outcome yet")
        lines += [f"{row.horizon} {row.setup_type}: n {row.n} closed" + (" THIN" if row.thin else ""),
                  f"  win rate {report.ratio(w.successes, w.n)}, 95% CI [{w.ci.lower:.1%}, {w.ci.upper:.1%}] (Wilson)",
                  f"  mean r_net {row.mean_r:+.2f} R, 95% CI {report.interval(row.mean_r_ci, row.trades)}",
                  f"  {shadow}; {p1_text(row)}",
                  f"  median MFE {row.median_mfe:+.2f} R, median MAE {row.median_mae:+.2f} R"]
    return lines


def as_facts(playbook: Playbook) -> list[dict]:
    """Each row as a dict ready to become a computed-source fact claim in week 5 (SourceRef kind="computed")."""
    facts = []
    for row in playbook.rows:
        ci, met = row.mean_r_ci, row.p1
        facts.append({
            "kind": "computed", "uri": SOURCE_URI, "session": playbook.session.isoformat(), "arm": playbook.arm,
            "horizon": row.horizon, "setup_type": row.setup_type, "n": row.n, "thin": row.thin,
            "win_rate": row.wins.proportion, "win_rate_ci": (row.wins.ci.lower, row.wins.ci.upper),
            "mean_r_net": row.mean_r, "mean_r_net_ci": (ci.ci.lower, ci.ci.upper) if ci else None,
            "entry_sessions": report.cluster_count(row.trades), "shadow_delta": row.shadow_delta,
            "p1_met": met[0], "p1_judged": met[1], "p1_unknown": met[2],
            "median_mfe_r": row.median_mfe, "median_mae_r": row.median_mae,
        })
    return facts
