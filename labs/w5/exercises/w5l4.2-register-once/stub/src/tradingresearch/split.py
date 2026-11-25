"""The training split (SPIKE §1.1 `TrainingSplit`, TRAINING-SPIKE §7.2 row 4, §7.3): a held-out later period,
registered before it starts. No model call.

A split is three numbers and a Prereg; the sessions it holds are derived on read, never stored on rows. Its id is the
digest of (cutoff, embargo, Prereg without `registered_at`), so registering the same split twice writes nothing, and
a different split is a new row: the table is append-only. The latest registered split governs when no id is named;
a dataset names the split id it was cut from (TRAINING-SPIKE §7.4, DATASHEET).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from gigai_core.records import Prereg
from pydantic import ValidationError

from . import journal, sessions
from .hashing import digest
from .records import EMBARGO_WHY, MIN_EMBARGO, TrainingSplit  # the floor and its reason live with the record

# TRAINING-SPIKE §7.3: the gate the test sessions are scored by, pre-registered with the split.
GATE_METRIC = "claims_valid"
GATE_PASS = "NoWorseThan(claims_valid, bound=ci_lower) >= -0.15"
GATE_MARGIN = 0.15
GATE_N = 40  # test sessions (400 items)
GATE_GUARD = "parse_ok Wilson lower bound >= 0.95"


class Refused(Exception):
    """A split `register` will not store, or an id `show` cannot find, with the reason."""


@dataclass(frozen=True)
class Split:
    """The journal's sessions as one split sees them; `embargo_window` is the calendar sessions in neither set."""

    train_val_sessions: tuple[date, ...]
    test_sessions: tuple[date, ...]
    embargoed_sessions: tuple[date, ...]
    embargo_window: tuple[date, ...]


# ---------- the Prereg ----------

def gate_prereg(registered_at: datetime, hypothesis: str | None = None) -> Prereg:
    """The §7.3 gate pre-registration, so nobody types the metric strings by hand."""
    return Prereg(primary_metric=GATE_METRIC, pass_rule=GATE_PASS, margin=GATE_MARGIN, n_planned=GATE_N,
                  registered_at=registered_at.astimezone(sessions.NY), guard_metric=GATE_GUARD, hypothesis=hypothesis)


def prereg_from(text: str | None, note: str | None, now: datetime) -> Prereg:
    """The gate Prereg, or one from a JSON object of Prereg fields; the clock sets `registered_at`, `note` is the
    hypothesis."""
    if text is None:
        return gate_prereg(now, note)
    try:
        fields = json.loads(text)
    except json.JSONDecodeError as e:
        raise Refused(f"prereg JSON does not parse: {e}") from None
    if not isinstance(fields, dict) or "registered_at" in fields:
        raise Refused("prereg JSON is an object of Prereg fields without registered_at (the clock sets it)")
    if note is not None:
        if fields.get("hypothesis"):
            raise Refused("the hypothesis is given twice: --note and the prereg JSON's hypothesis")
        fields["hypothesis"] = note
    try:
        return Prereg.model_validate({**fields, "registered_at": now.astimezone(sessions.NY)})
    except ValidationError as e:
        raise Refused(f"prereg JSON is not a gigai-core Prereg: {e}") from None


# ---------- register ----------

def split_id_for(cutoff_session: date, embargo_sessions: int, prereg: Prereg) -> str:
    """`sp_` + 16 hex of the split's parameters; `registered_at` is left out, so the same split has one id."""
    # TODO(w5l4.2) the id: "sp_" + the first 16 hex of the digest of {"cutoff_session": ISO date, "embargo_sessions",
    #   "prereg": the Prereg as JSON without registered_at}.
    raise NotImplementedError


def register(conn: sqlite3.Connection, cutoff_session: date, embargo_sessions: int, prereg: Prereg,
             now: datetime) -> TrainingSplit:
    """Store the split once, or return the stored one with the same parameters. Refused: an embargo under
    MIN_EMBARGO, a cutoff that is not an NYSE session, and a cutoff that is not still ahead (after the last completed
    session and not yet open), for the record and for its Prereg."""
    # TODO(w5l4.3) refuse with Refused, in this order: an embargo under MIN_EMBARGO (before the lookup), then a cutoff
    #   that is not an NYSE session, one not after the last completed session, and one whose session opens no later
    #   than now or the prereg's registered_at.
    # TODO(w5l4.2) return the stored split with this id; else store a TrainingSplit registered at now, in New York
    #   time, and return it.
    raise NotImplementedError


# ---------- read and derive ----------

def splits(conn: sqlite3.Connection) -> list[TrainingSplit]:
    """Every registered split, in registration order."""
    return [TrainingSplit.model_validate_json(body)
            for (body,) in conn.execute("SELECT body FROM training_split ORDER BY rowid")]


def find(conn: sqlite3.Connection, split_id: str) -> TrainingSplit | None:
    try:
        return journal.get(conn, TrainingSplit, split_id)
    except KeyError:
        return None


def governing(conn: sqlite3.Connection, split_id: str | None = None) -> TrainingSplit:
    """The named split, or the latest registered one; Refused when there is none."""
    if split_id is not None:
        found = find(conn, split_id)
        if found is None:
            raise Refused(f"no training split {split_id}")
        return found
    registered = splits(conn)
    if not registered:
        raise Refused(f"no training split registered yet: `tr split register --cutoff YYYY-MM-DD --embargo "
                      f"{MIN_EMBARGO}`")
    return registered[-1]


def journal_sessions(conn: sqlite3.Connection) -> list[date]:
    """The sessions the journal holds analyses for (every arm), oldest first."""
    rows = conn.execute("SELECT DISTINCT session FROM analysis ORDER BY session")
    return [date.fromisoformat(day) for (day,) in rows]


def embargo_window(split: TrainingSplit) -> tuple[date, ...]:
    """The `embargo_sessions` NYSE sessions right before the cutoff."""
    # TODO(w5l4.4) the embargo_sessions NYSE sessions right before the cutoff session, oldest first.
    raise NotImplementedError


def partition(split: TrainingSplit, days: list[date]) -> Split:
    """train/val = sessions before the embargo window; test = sessions on or after the cutoff; the window's sessions
    are in neither (SPIKE §1.1)."""
    # TODO(w5l4.4) each distinct day once, in date order: train/val before the window, embargoed from the window's
    #   first session up to the cutoff, test on or after the cutoff; the window as embargo_window.
    raise NotImplementedError


def derive(conn: sqlite3.Connection, split_id: str) -> Split:
    """The split's sets over the journal's sessions today: a pure function of the row, the calendar and the journal."""
    return partition(governing(conn, split_id), journal_sessions(conn))


def _days(days: tuple[date, ...]) -> str:
    return ", ".join(map(str, days)) if days else "none"


def render(split: TrainingSplit, parts: Split, registered: int) -> list[str]:
    """The split, its Prereg, the embargo window and each derived set with its count."""
    p = split.prereg
    window = parts.embargo_window
    return [f"split {split.split_id}: cutoff {split.cutoff_session}, embargo {split.embargo_sessions} sessions, "
            f"registered {split.registered_at.isoformat(timespec='minutes')} (New York)",
            f"  prereg: {p.primary_metric}, pass {p.pass_rule}, margin {p.margin:g}, n_planned {p.n_planned}"
            + (f", guard {p.guard_metric}" if p.guard_metric else "")
            + (f", hypothesis: {p.hypothesis}" if p.hypothesis else ""),
            f"  embargo window: {window[0]} to {window[-1]} ({len(window)} NYSE sessions, in neither set)",
            f"  train/val: {len(parts.train_val_sessions)} sessions: {_days(parts.train_val_sessions)}",
            f"  embargoed: {len(parts.embargoed_sessions)} sessions: {_days(parts.embargoed_sessions)}",
            f"  test (on or after the cutoff): {len(parts.test_sessions)} sessions: {_days(parts.test_sessions)}",
            f"  sessions are the journal's analysis sessions, derived on read; {registered} split(s) registered, the "
            "latest governs when no id is named"]
