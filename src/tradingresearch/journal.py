"""The SQLite journal (SPIKE §2): append-only record tables, enforced by triggers the database runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import get_args

from gigai_core.records import LabelRecord, Prereg
from gigai_core.score import ScoreRecord
from pydantic import BaseModel

from .hashing import digest
from .records import (
    Analysis, Claim, ClaimLabel, Event, Grade, Horizon, NoTrade, OutcomeGrade, RuleChange, Shadow, SourceRef,
    TeacherOutcome, Thesis, TrainingSplit,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_ref (
  source_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS analysis (
  analysis_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, session TEXT NOT NULL, arm TEXT NOT NULL,
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claim (
  claim_id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL REFERENCES analysis(analysis_id), tag TEXT NOT NULL,
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS thesis (
  thesis_id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL REFERENCES analysis(analysis_id),
  ticker TEXT NOT NULL, horizon TEXT NOT NULL, arm TEXT NOT NULL,
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS no_trade (
  no_trade_id INTEGER PRIMARY KEY, analysis_id TEXT NOT NULL REFERENCES analysis(analysis_id), horizon TEXT NOT NULL,
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event (
  seq INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, subject_id TEXT NOT NULL, state TEXT NOT NULL,
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_by_subject ON event(subject_id, seq);
CREATE TABLE IF NOT EXISTS grade (
  grade_id TEXT PRIMARY KEY, thesis_id TEXT NOT NULL REFERENCES thesis(thesis_id),
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shadow (
  shadow_id TEXT PRIMARY KEY, thesis_id TEXT NOT NULL REFERENCES thesis(thesis_id),
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shadow_outcome (
  subject_id TEXT PRIMARY KEY REFERENCES shadow(shadow_id),
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
-- G8: gigai-core ScoreRecords about one subject (a thesis): the outcome score a Grade points at, later P1.
CREATE TABLE IF NOT EXISTS score (
  score_id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, value REAL NOT NULL,
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS teacher_outcome (
  teacher_outcome_id TEXT PRIMARY KEY, thesis_id TEXT NOT NULL REFERENCES thesis(thesis_id),
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS training_split (
  split_id TEXT PRIMARY KEY,
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claim_label (
  claim_label_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claim(claim_id),
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bars_daily (
  ticker TEXT NOT NULL, session TEXT NOT NULL, o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL,
  v INTEGER NOT NULL, n INTEGER, vw REAL, feed TEXT NOT NULL, adjustment TEXT NOT NULL, fetched_at TEXT NOT NULL,
  PRIMARY KEY (ticker, session, feed, adjustment));
CREATE TABLE IF NOT EXISTS screen_result (
  session TEXT NOT NULL, ticker TEXT NOT NULL, points INTEGER NOT NULL, triggers TEXT NOT NULL,
  filtered_out TEXT, rank INTEGER, code_version TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (session, ticker, code_version));

-- REPO-PLAN G4a: one row per (session, step, ticker) of each `tr daily` run; `missed` rows feed the week-3 SLO.
CREATE TABLE IF NOT EXISTS daily_run (
  seq INTEGER PRIMARY KEY, daily_id TEXT NOT NULL, session TEXT NOT NULL,
  step TEXT NOT NULL CHECK (step IN ('session', 'screen', 'analyze', 'thesis', 'reconcile')), ticker TEXT,
  status TEXT NOT NULL CHECK (status IN ('ok', 'skipped', 'failed', 'stopped', 'missed')), reason TEXT NOT NULL,
  ids TEXT NOT NULL, cost_usd REAL NOT NULL, created_at TEXT NOT NULL);

-- G9b: the operator's blind P1 labels (gigai-core LabelRecord, item_id = thesis id); a relabel is a new row.
CREATE TABLE IF NOT EXISTS label (
  label_id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES thesis(thesis_id),
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
-- G9b: the P1 judge's verdicts, one row per judge call; the latest (highest seq) per thesis wins.
CREATE TABLE IF NOT EXISTS judge_verdict (
  seq INTEGER PRIMARY KEY, thesis_id TEXT NOT NULL REFERENCES thesis(thesis_id),
  verdict TEXT NOT NULL CHECK (verdict IN ('pass', 'fail')), reason TEXT NOT NULL, score_id TEXT,
  created_at TEXT NOT NULL);

-- SPIKE §6.7: at most one PROPOSED-or-OPEN thesis per (ticker, horizon, arm) for champion and challenger.
-- The latest event is the one with the highest seq (ids are random hex, so they cannot order events).
CREATE TRIGGER IF NOT EXISTS one_live BEFORE INSERT ON thesis
WHEN new.arm IN ('champion', 'challenger') AND EXISTS (
  SELECT 1 FROM thesis t
  WHERE t.ticker = new.ticker AND t.horizon = new.horizon AND t.arm = new.arm
    AND (SELECT e.state FROM event e WHERE e.subject_id = t.thesis_id ORDER BY e.seq DESC LIMIT 1)
        IN ('PROPOSED', 'OPEN'))
BEGIN SELECT RAISE(ABORT, 'one live thesis per (ticker, horizon, arm)'); END;

-- G11a: SPIKE §8.2 rule changes. The pre-registration columns never change; `decided` moves once, from pending to
-- adopted, rejected or insufficient (§8.3), and a row is never deleted. At most one change is pending at a time.
CREATE TABLE IF NOT EXISTS rule_change (
  change_id TEXT PRIMARY KEY, horizon TEXT NOT NULL, registered_at TEXT NOT NULL,
  decided TEXT NOT NULL CHECK (decided IN ('pending', 'adopted', 'rejected', 'insufficient')), decided_at TEXT,
  body TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_rule_change ON rule_change(decided) WHERE decided = 'pending';
CREATE TRIGGER IF NOT EXISTS rule_change_starts_pending BEFORE INSERT ON rule_change
WHEN new.decided != 'pending' OR new.decided_at IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'rule_change is stored pending'); END;
CREATE TRIGGER IF NOT EXISTS rule_change_decided_once BEFORE UPDATE ON rule_change
WHEN old.decided != 'pending' OR new.decided NOT IN ('adopted', 'rejected', 'insufficient') OR new.decided_at IS NULL
  OR new.change_id IS NOT old.change_id OR new.horizon IS NOT old.horizon OR new.registered_at IS NOT old.registered_at
  OR new.body IS NOT old.body OR new.record_sha256 IS NOT old.record_sha256 OR new.created_at IS NOT old.created_at
BEGIN SELECT RAISE(ABORT, 'rule_change: only a pending decision changes, once'); END;
CREATE TRIGGER IF NOT EXISTS rule_change_no_delete BEFORE DELETE ON rule_change
BEGIN SELECT RAISE(ABORT, 'rule_change is append-only'); END;
"""

IMMUTABLE = (
    "source_ref", "analysis", "claim", "thesis", "no_trade", "event", "grade", "shadow", "shadow_outcome", "score",
    "teacher_outcome", "training_split", "claim_label", "screen_result", "daily_run", "label", "judge_verdict",
)

# record type -> (table, columns copied out of the record for queries and triggers)
TABLES: dict[type[BaseModel], tuple[str, tuple[str, ...]]] = {
    SourceRef: ("source_ref", ("source_id", "kind")),
    Analysis: ("analysis", ("analysis_id", "ticker", "session", "arm")),
    Claim: ("claim", ("claim_id", "analysis_id", "tag")),
    Thesis: ("thesis", ("thesis_id", "analysis_id", "ticker", "horizon", "arm")),
    NoTrade: ("no_trade", ("analysis_id", "horizon")),
    Event: ("event", ("event_id", "subject_id", "state")),
    Grade: ("grade", ("grade_id", "thesis_id")),
    Shadow: ("shadow", ("shadow_id", "thesis_id")),
    OutcomeGrade: ("shadow_outcome", ("subject_id",)),
    TeacherOutcome: ("teacher_outcome", ("teacher_outcome_id", "thesis_id")),
    TrainingSplit: ("training_split", ("split_id",)),
    ClaimLabel: ("claim_label", ("claim_label_id", "claim_id")),
    LabelRecord: ("label", ("label_id", "item_id")),
}


def append_only_triggers(table: str) -> str:
    return (
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;\n"
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;\n"
    )


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the journal and create what is missing. Every connection turns recursive triggers on."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    # Without this, INSERT OR REPLACE deletes the old row WITHOUT firing the BEFORE DELETE trigger.
    # The setting is per connection and off by default, so it lives here, not in the schema.
    conn.execute("PRAGMA recursive_triggers = ON")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA + "".join(append_only_triggers(t) for t in IMMUTABLE))
    return conn


def _insert(conn: sqlite3.Connection, record: BaseModel) -> None:
    table, columns = TABLES[type(record)]
    values = [str(getattr(record, column)) for column in columns]
    names = (*columns, "body", "record_sha256", "created_at")
    marks = ", ".join("?" for _ in names)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({marks})",
        (*values, record.model_dump_json(), digest(record), datetime.now(UTC).isoformat()),
    )


def add(conn: sqlite3.Connection, *records: BaseModel) -> None:
    """Insert records in one transaction. A duplicate id is an error, never a silent replace."""
    with conn:
        for record in records:
            _insert(conn, record)


def get[T: BaseModel](conn: sqlite3.Connection, kind: type[T], record_id: str) -> T:
    """Read one record back by its id column (the first promoted column)."""
    table, columns = TABLES[kind]
    row = conn.execute(f"SELECT body FROM {table} WHERE {columns[0]} = ?", (record_id,)).fetchone()
    if row is None:
        raise KeyError(f"{table}: no row with {columns[0]} = {record_id!r}")
    return kind.model_validate_json(row[0])


def add_analysis(conn: sqlite3.Connection, analysis: Analysis, sources: list[SourceRef]) -> None:
    """One analysis, its claims and its sources in a single transaction (all or nothing).

    Source ids are content-addressed (`src_` + digest), so a source already in the journal is the same number
    from an earlier run and is skipped; the first stored retrieved_at stays.
    """
    with conn:
        for source in sources:
            if conn.execute("SELECT 1 FROM source_ref WHERE source_id = ?", (source.source_id,)).fetchone() is None:
                _insert(conn, source)
        _insert(conn, analysis)
        for claim in analysis.claims:
            _insert(conn, claim)


SCREEN_COLUMNS = ("session", "ticker", "points", "triggers", "filtered_out", "rank", "code_version")


def add_screen_results(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """One screen run in one transaction. OR IGNORE keeps a row already stored for (session, ticker, code_version):
    a re-run adds nothing and never replaces (no DELETE happens, so the append-only trigger has nothing to stop)."""
    stamp = datetime.now(UTC).isoformat()
    marks = ", ".join(f":{name}" for name in (*SCREEN_COLUMNS, "created_at"))
    with conn:
        cursor = conn.executemany(
            f"INSERT OR IGNORE INTO screen_result VALUES ({marks})",
            [row | {"triggers": json.dumps(row["triggers"]), "created_at": stamp} for row in rows],
        )
    return cursor.rowcount


def screen_results(conn: sqlite3.Connection, session: date, code_version: str) -> list[dict]:
    """One stored screen run: ranked rows first, by rank, then the unranked by ticker."""
    cursor = conn.execute(
        f"SELECT {', '.join(SCREEN_COLUMNS)} FROM screen_result WHERE session = ? AND code_version = ? "
        "ORDER BY rank IS NULL, rank, ticker",
        (session.isoformat(), code_version),
    )
    rows = [dict(zip(SCREEN_COLUMNS, values)) for values in cursor]
    return [row | {"triggers": json.loads(row["triggers"])} for row in rows]


def last_screened(conn: sqlite3.Connection, before: date) -> date | None:
    """The latest screened session before `before` (any code version): the 8-K trigger counts filings since it."""
    query = "SELECT max(session) FROM screen_result WHERE session < ?"
    found = conn.execute(query, (before.isoformat(),)).fetchone()[0]
    return date.fromisoformat(found) if found else None


LAST_STATE = "(SELECT e.state FROM event e WHERE e.subject_id = t.thesis_id ORDER BY e.seq DESC LIMIT 1)"


def live_horizons(conn: sqlite3.Connection, ticker: str, arm: str | None = None) -> set[str]:
    """Horizons where `ticker` has a PROPOSED or OPEN thesis (latest event by seq, as one_live): for `arm` alone (the
    one_live key) or, by default, for champion or challenger."""
    arms = (arm,) if arm else ("champion", "challenger")
    rows = conn.execute(
        f"SELECT DISTINCT t.horizon FROM thesis t WHERE t.ticker = ? AND t.arm IN ({', '.join('?' for _ in arms)}) "
        f"AND {LAST_STATE} IN ('PROPOSED', 'OPEN')",
        (ticker, *arms),
    )
    return {horizon for (horizon,) in rows}


def latest_analysis(conn: sqlite3.Connection, ticker: str, session: date, arm: str) -> Analysis | None:
    """The newest stored analysis of one ticker-day for one analysis arm (`main` or `teacher`)."""
    row = conn.execute(
        "SELECT body FROM analysis WHERE ticker = ? AND session = ? AND arm = ? ORDER BY created_at DESC LIMIT 1",
        (ticker, session.isoformat(), arm),
    ).fetchone()
    return Analysis.model_validate_json(row[0]) if row else None


def open_theses(conn: sqlite3.Connection, arm: str | None = None) -> list[tuple[Thesis, str]]:
    """Theses whose last event is PROPOSED or OPEN (SPIKE §6.8), oldest first, each with that state."""
    rows = conn.execute(
        f"SELECT t.body, {LAST_STATE} AS state FROM thesis t WHERE state IN ('PROPOSED', 'OPEN') "
        "AND (? IS NULL OR t.arm = ?) ORDER BY t.created_at, t.thesis_id",
        (arm, arm),
    )
    return [(Thesis.model_validate_json(body), state) for body, state in rows]


def open_shadow_ids(conn: sqlite3.Connection) -> list[str]:
    """Shadows whose last event is PROPOSED or OPEN (SPIKE §6.8), oldest first."""
    rows = conn.execute(
        "SELECT s.shadow_id FROM shadow s WHERE (SELECT e.state FROM event e WHERE e.subject_id = s.shadow_id "
        "ORDER BY e.seq DESC LIMIT 1) IN ('PROPOSED', 'OPEN') ORDER BY s.created_at, s.shadow_id"
    )
    return [shadow_id for (shadow_id,) in rows]


def events_for(conn: sqlite3.Connection, subject_id: str) -> tuple[Event, ...]:
    """A subject's events in insertion order (seq): the last one is its state."""
    rows = conn.execute("SELECT body FROM event WHERE subject_id = ? ORDER BY seq", (subject_id,))
    return tuple(Event.model_validate_json(body) for (body,) in rows)


def add_settlement(
    conn: sqlite3.Connection, events: list[Event], sources: list[SourceRef],
    outcome: TeacherOutcome | OutcomeGrade | None = None,
) -> None:
    """One reconcile step of one subject in a single transaction: the bars sources it cites, its events, and the
    TeacherOutcome when a teacher thesis ends (or a shadow's OutcomeGrade when it closes). Sources are
    content-addressed, so one already stored is skipped."""
    with conn:
        for source in sources:
            if conn.execute("SELECT 1 FROM source_ref WHERE source_id = ?", (source.source_id,)).fetchone() is None:
                _insert(conn, source)
        for event in events:
            _insert(conn, event)
        if outcome is not None:
            _insert(conn, outcome)


def ungraded_theses(conn: sqlite3.Connection) -> list[tuple[Thesis, str]]:
    """Champion and challenger theses with no grade whose last event is PROPOSED, OPEN or CLOSED, oldest first."""
    rows = conn.execute(
        f"SELECT t.body, {LAST_STATE} AS state FROM thesis t WHERE t.arm IN ('champion', 'challenger') "
        "AND state IN ('PROPOSED', 'OPEN', 'CLOSED') "
        "AND NOT EXISTS (SELECT 1 FROM grade g WHERE g.thesis_id = t.thesis_id) ORDER BY t.created_at, t.thesis_id"
    )
    return [(Thesis.model_validate_json(body), state) for body, state in rows]


def shadow_of(conn: sqlite3.Connection, thesis_id: str) -> Shadow | None:
    """The thesis's shadow baseline (SPIKE §7.4), if one was created."""
    row = conn.execute("SELECT body FROM shadow WHERE thesis_id = ?", (thesis_id,)).fetchone()
    return Shadow.model_validate_json(row[0]) if row else None


def shadow_outcome(conn: sqlite3.Connection, shadow_id: str) -> OutcomeGrade | None:
    """A closed shadow's OutcomeGrade, if it has one."""
    row = conn.execute("SELECT body FROM shadow_outcome WHERE subject_id = ?", (shadow_id,)).fetchone()
    return OutcomeGrade.model_validate_json(row[0]) if row else None


def _insert_score(conn: sqlite3.Connection, subject_id: str, score: ScoreRecord) -> None:
    conn.execute(
        "INSERT INTO score (score_id, subject_id, kind, name, value, body, record_sha256, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (score.score_id, subject_id, score.kind, score.grader_id, score.value, score.model_dump_json(), digest(score),
         datetime.now(UTC).isoformat()),
    )


def add_grade(conn: sqlite3.Connection, grade: Grade, score: ScoreRecord, graded: Event) -> None:
    """A grade, the outcome ScoreRecord it points at, and the thesis's GRADED event in one transaction (§6.8)."""
    with conn:
        _insert_score(conn, grade.thesis_id, score)
        _insert(conn, grade)
        _insert(conn, graded)


def scores_for(conn: sqlite3.Connection, subject_id: str) -> list[ScoreRecord]:
    """Every ScoreRecord stored about one subject, in insertion order."""
    rows = conn.execute("SELECT body FROM score WHERE subject_id = ? ORDER BY rowid", (subject_id,))
    return [ScoreRecord.model_validate_json(body) for (body,) in rows]


def analyses(conn: sqlite3.Connection, session: date, arm: str) -> list[Analysis]:
    """Every stored analysis of one session for one analysis arm, oldest first."""
    rows = conn.execute("SELECT body FROM analysis WHERE session = ? AND arm = ? ORDER BY created_at, analysis_id",
                        (session.isoformat(), arm))
    return [Analysis.model_validate_json(body) for (body,) in rows]


def has_decision(conn: sqlite3.Connection, analysis_id: str) -> bool:
    """A champion thesis or a no-trade was stored from this analysis: its thesis call is done."""
    query = ("SELECT 1 FROM thesis WHERE analysis_id = ? AND arm = 'champion' "
             "UNION ALL SELECT 1 FROM no_trade WHERE analysis_id = ? LIMIT 1")
    return conn.execute(query, (analysis_id, analysis_id)).fetchone() is not None


DAILY_COLUMNS = ("daily_id", "session", "step", "ticker", "status", "reason", "ids", "cost_usd")


def add_daily_run(conn: sqlite3.Connection, row: dict) -> None:
    """One `tr daily` row, committed at once, so a crash mid-run keeps every row before it."""
    marks = ", ".join(f":{name}" for name in (*DAILY_COLUMNS, "created_at"))
    with conn:
        conn.execute(f"INSERT INTO daily_run ({', '.join(DAILY_COLUMNS)}, created_at) VALUES ({marks})",
                     row | {"ids": json.dumps(list(row["ids"])), "created_at": datetime.now(UTC).isoformat()})


def daily_runs(conn: sqlite3.Connection, session: date | None = None) -> list[dict]:
    """Stored `tr daily` rows in insertion order, for one session or all."""
    cursor = conn.execute(f"SELECT {', '.join(DAILY_COLUMNS)} FROM daily_run WHERE ? IS NULL OR session = ? "
                          "ORDER BY seq", (session and session.isoformat(),) * 2)
    rows = [dict(zip(DAILY_COLUMNS, values)) for values in cursor]
    return [row | {"ids": json.loads(row["ids"])} for row in rows]


def daily_sessions(conn: sqlite3.Connection) -> set[date]:
    """Sessions with any `tr daily` row, `missed` rows included (a missed session is listed once)."""
    return {date.fromisoformat(day) for (day,) in conn.execute("SELECT DISTINCT session FROM daily_run")}


def first_daily_session(conn: sqlite3.Connection) -> date | None:
    """The earliest session `tr daily` actually ran for: sessions before it are not misses."""
    found = conn.execute("SELECT min(session) FROM daily_run WHERE status != 'missed'").fetchone()[0]
    return date.fromisoformat(found) if found else None


VERDICT_COLUMNS = ("thesis_id", "verdict", "reason", "score_id", "created_at")


def _insert_verdict(conn: sqlite3.Connection, thesis_id: str, verdict: str, reason: str, score_id: str | None) -> None:
    conn.execute(f"INSERT INTO judge_verdict ({', '.join(VERDICT_COLUMNS)}) VALUES (?, ?, ?, ?, ?)",
                 (thesis_id, verdict, reason, score_id, datetime.now(UTC).isoformat()))


def add_judge_verdict(conn: sqlite3.Connection, thesis_id: str, verdict: str, reason: str,
                      score_id: str | None = None) -> None:
    """One P1 judge reply (rubric "Verdict format": `pass` or `fail`, unknown = `fail` with `unknown:`), one row per
    call, committed at once; a later row for the same thesis supersedes it."""
    with conn:
        _insert_verdict(conn, thesis_id, verdict, reason, score_id)


def add_judge_score(conn: sqlite3.Connection, thesis_id: str, record: ScoreRecord, verdict: str, reason: str) -> None:
    """The P1 judge's ScoreRecord and the verdict row that points at it, in one transaction."""
    with conn:
        _insert_score(conn, thesis_id, record)
        _insert_verdict(conn, thesis_id, verdict, reason, record.score_id)


def judge_verdicts(conn: sqlite3.Connection) -> dict[str, dict]:
    """The latest judge verdict per thesis (highest seq), keyed by thesis id."""
    cursor = conn.execute(f"SELECT {', '.join(VERDICT_COLUMNS)} FROM judge_verdict ORDER BY seq")
    return {values[0]: dict(zip(VERDICT_COLUMNS, values)) for values in cursor}  # a later row overwrites


def judge_verdict(conn: sqlite3.Connection, thesis_id: str) -> dict | None:
    """One thesis's latest judge verdict, or None when the judge never ran on it."""
    row = conn.execute(f"SELECT {', '.join(VERDICT_COLUMNS)} FROM judge_verdict WHERE thesis_id = ? "
                       "ORDER BY seq DESC LIMIT 1", (thesis_id,)).fetchone()
    return dict(zip(VERDICT_COLUMNS, row)) if row else None


def abstained(verdict: dict) -> bool:
    """The rubric's unknown: a `fail` whose reason starts `unknown:`."""
    return verdict["verdict"] == "fail" and verdict["reason"].startswith("unknown:")


# SPIKE §8.2: the only pre-registration a rule change may carry. gigai-core's Prereg has no unit or horizon field, so
# the unit (one item per session on the affected horizon, holding that arm's summed r_net for the session, 0 when it
# had no trade, clustered by session) is the primary metric with the horizon after the colon.
RULE_METRIC = "session_r_net_delta"  # per-session summed r_net, challenger - champion
RULE_PASS = "delta_ci_lower > 0"  # strict: a lower bound of exactly 0 does not pass
RULE_GUARD = "p1_met_rate"  # per-session P1 met rate, challenger - champion ...
RULE_MARGIN = 0.10  # ... whose lower bound must be >= -0.10
RULE_N = 20  # paired sessions
DECISIONS = ("adopted", "rejected", "insufficient")


def rule_prereg(horizon: str, hypothesis: str, registered_at: datetime) -> Prereg:
    """The §8.2 Prereg of a change on one horizon, so nobody types the metric strings by hand."""
    return Prereg(primary_metric=f"{RULE_METRIC}:{horizon}", pass_rule=RULE_PASS, margin=RULE_MARGIN,
                  n_planned=RULE_N, registered_at=registered_at, guard_metric=RULE_GUARD, hypothesis=hypothesis)


def prereg_horizon(prereg: Prereg) -> str:
    """The affected horizon of a §8.2 Prereg, or ValueError naming the first field that breaks §8.2."""
    metric, _, horizon = prereg.primary_metric.partition(":")
    if metric != RULE_METRIC or horizon not in get_args(Horizon):
        raise ValueError(f"prereg primary_metric must be '{RULE_METRIC}:<day|short|swing>' (the SPIKE §8.2 unit), "
                         f"got {prereg.primary_metric!r}")
    for field, want in {"pass_rule": RULE_PASS, "guard_metric": RULE_GUARD, "margin": RULE_MARGIN,
                        "n_planned": RULE_N}.items():
        if getattr(prereg, field) != want:
            raise ValueError(f"prereg {field} must be {want!r} (SPIKE §8.2), got {getattr(prereg, field)!r}")
    return horizon


def first_challenger_since_decision(conn: sqlite3.Connection) -> datetime | None:
    """When the first challenger thesis after the last decision was stored (row time): a new change would cover it."""
    since = conn.execute("SELECT max(decided_at) FROM rule_change").fetchone()[0] or ""
    found = conn.execute("SELECT min(created_at) FROM thesis WHERE arm = 'challenger' AND created_at > ?",
                         (since,)).fetchone()[0]
    return datetime.fromisoformat(found) if found else None


def add_rule_change(conn: sqlite3.Connection, change: RuleChange) -> None:
    """Store a pre-registered change as pending. Refused: a Prereg that breaks §8.2, a second pending change (one
    challenger at a time, §8.3), and a Prereg registered before the last decision or at/after a challenger thesis it
    would cover (pre-registration comes before any trade under the change)."""
    if change.decided != "pending":
        raise ValueError(f"a rule change is stored pending, got {change.decided!r}")
    horizon = prereg_horizon(change.prereg)
    pending = conn.execute("SELECT change_id FROM rule_change WHERE decided = 'pending'").fetchone()
    if pending:
        raise ValueError(f"one challenger at a time: {pending[0]} is still pending")
    registered = change.prereg.registered_at.astimezone(UTC)
    last = conn.execute("SELECT max(decided_at) FROM rule_change").fetchone()[0]
    if last and registered <= datetime.fromisoformat(last):
        raise ValueError(f"prereg registered_at {registered.isoformat()} is not after the last decision ({last}): "
                         "one challenger at a time")
    first = first_challenger_since_decision(conn)
    if first is not None and registered >= first:
        raise ValueError(f"prereg registered_at {registered.isoformat()} is not before the first challenger thesis "
                         f"it would cover (stored {first.isoformat()}): pre-register before any trade (SPIKE §8.2)")
    with conn:
        conn.execute("INSERT INTO rule_change (change_id, horizon, registered_at, decided, decided_at, body, "
                     "record_sha256, created_at) VALUES (?, ?, ?, 'pending', NULL, ?, ?, ?)",
                     (change.change_id, horizon, registered.isoformat(), change.model_dump_json(), digest(change),
                      datetime.now(UTC).isoformat()))


def decide_rule_change(conn: sqlite3.Connection, change_id: str, decided: str) -> None:
    """Move a pending change to its one final decision (§8.3); a decided change never changes again."""
    if decided not in DECISIONS:
        raise ValueError(f"a decision is one of {', '.join(DECISIONS)}, got {decided!r}")
    row = conn.execute("SELECT decided FROM rule_change WHERE change_id = ?", (change_id,)).fetchone()
    if row is None:
        raise KeyError(f"rule_change: no row with change_id = {change_id!r}")
    if row[0] != "pending":
        raise ValueError(f"{change_id} is already {row[0]}: a decision is final")
    with conn:
        conn.execute("UPDATE rule_change SET decided = ?, decided_at = ? WHERE change_id = ?",
                     (decided, datetime.now(UTC).isoformat(), change_id))


def rule_changes(conn: sqlite3.Connection, decided: str | None = None) -> list[RuleChange]:
    """Stored changes in registration order, each with its current decision; `decided` keeps one status."""
    where = " WHERE decided = ?" if decided else ""
    rows = conn.execute(f"SELECT body, decided FROM rule_change{where} ORDER BY rowid", (decided,) if decided else ())
    return [RuleChange.model_validate_json(body).model_copy(update={"decided": state}) for body, state in rows]


def rule_change_decided_at(conn: sqlite3.Connection, change_id: str) -> datetime | None:
    """When the change was decided; None while pending (or when no such change exists)."""
    row = conn.execute("SELECT decided_at FROM rule_change WHERE change_id = ?", (change_id,)).fetchone()
    return datetime.fromisoformat(row[0]) if row and row[0] else None
