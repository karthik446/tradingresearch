"""Observe for lab w5l4: what your embargo floor, split.register and the derived sets do ($0, no network).

    python labs/w5/tools/observe_split.py

Three blocks on fixed dates, so the output does not move with the clock (`tr split register` reads the real clock):

  1. records: SWING_ENTRY_SESSIONS, MIN_EMBARGO, EMBARGO_WHY, and a TrainingSplit one session under the floor.
  2. register on an in-memory journal at 2026-10-30 22:00 UTC (after that session's close): the chapter's cutoff
     2026-12-29 with embargo 22, the same split three days later, then a short embargo, Thanksgiving, the last
     completed session, a cutoff whose session has opened, and an evening registration for the next session.
  3. the 2026-12-29 split's embargo window and the sets it puts seven sessions in, then `tr split show`'s lines.

Exits 0: it shows what your code does, the exercise's check decides. The offline guard (tools/offline.py) is installed
before your code is imported; a guarded call it tried is named in a `note:` line at the end.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline  # noqa: E402

offline.install()  # before your code is imported
from gigai_core.records import Prereg  # noqa: E402
from pydantic import ValidationError  # noqa: E402

NOW = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)
CUTOFF = date(2026, 12, 29)
DAYS = [date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 27), date(2026, 12, 28), date(2026, 12, 29),
        date(2026, 12, 30), date(2026, 11, 24)]
PROBES = [  # (what, cutoff, embargo, now)
    ("embargo 21", CUTOFF, 21, NOW),
    ("Thanksgiving", date(2026, 11, 26), 22, NOW),
    ("the last completed session", date(2026, 10, 30), 22, NOW),
    ("cutoff 2026-11-02, now 10:00 New York that day", date(2026, 11, 2), 22, datetime(2026, 11, 2, 15, 0, tzinfo=UTC)),
    ("cutoff 2026-11-03, now 21:00 New York the evening before", date(2026, 11, 3), 22,
     datetime(2026, 11, 3, 2, 0, tzinfo=UTC)),
]


def failed(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}".splitlines()[0]


def floor() -> None:
    from tradingresearch import records
    names = ("SWING_ENTRY_SESSIONS", "MIN_EMBARGO", "EMBARGO_WHY")
    print("records: " + ", ".join(f"{name}: {getattr(records, name, '(missing)')!r}" for name in names))
    under = getattr(records, "MIN_EMBARGO", 22) - 1
    prereg = Prereg(primary_metric="claims_valid", pass_rule="r", margin=0.15, n_planned=40, registered_at=NOW)
    try:
        records.TrainingSplit(split_id="sp_observe", cutoff_session=CUTOFF, embargo_sessions=under, prereg=prereg,
                              registered_at=NOW)
        print(f"  TrainingSplit(embargo_sessions={under}): accepted")
    except ValidationError as exc:
        print(f"  TrainingSplit(embargo_sessions={under}): refused: {exc.errors()[0]['msg']}")


def register(split, journal):
    conn = journal.connect(":memory:")
    rows = lambda: conn.execute("SELECT count(*) FROM training_split").fetchone()[0]  # noqa: E731
    stored = None
    for label, now in (("register", NOW), ("three days later", NOW + timedelta(days=3))):
        try:
            got = split.register(conn, CUTOFF, 22, split.gate_prereg(now), now)
            print(f"{label}: {got.split_id} cutoff {got.cutoff_session} embargo {got.embargo_sessions} registered "
                  f"{got.registered_at.isoformat()} (rows {rows()})")
            stored = stored or got
        except Exception as exc:
            print(f"{label}: split.register raised {failed(exc)}")
    for what, cutoff, embargo, now in PROBES:
        try:
            got = split.register(conn, cutoff, embargo, split.gate_prereg(now), now)
            print(f"  {what}: stored {got.split_id}, registered {got.registered_at.isoformat()} (rows {rows()})")
        except split.Refused as exc:
            print(f"  {what}: refused: {exc}")
        except Exception as exc:
            print(f"  {what}: split.register raised {failed(exc)}")
    return stored


def derived(split, record) -> None:
    if record is None:
        print("no split stored: block 3 needs register")
        return
    try:
        window = split.embargo_window(record)
        print(f"embargo window: {len(window)} sessions, {window[0]} to {window[-1]}")
    except Exception as exc:
        print(f"split.embargo_window raised {failed(exc)}")
    try:
        parts = split.partition(record, DAYS)
    except Exception as exc:
        print(f"split.partition raised {failed(exc)}")
        return
    print(f"partition of {', '.join(map(str, DAYS))}:")
    for name in ("train_val_sessions", "embargoed_sessions", "test_sessions"):
        print(f"  {name}: {', '.join(map(str, getattr(parts, name))) or 'none'}")
    try:
        print("\n".join(split.render(record, parts, 1)))
    except Exception as exc:
        print(f"split.render raised {failed(exc)}")


def main() -> int:
    try:
        floor()
    except Exception as exc:
        print(f"tradingresearch.records: {failed(exc)}")
        return 0
    try:
        from tradingresearch import journal, split
    except Exception as exc:  # before w5l4.2 installs it, or a half-written file: show it, stop
        shown = failed(exc)
        if isinstance(exc, ImportError) and exc.path:  # the message ends with the package's path, a temp folder
            shown = shown.replace(f" ({exc.path})", "")
        print(f"tradingresearch.split does not import: {shown}")
        return 0
    print()
    record = register(split, journal)
    print()
    derived(split, record)
    return 0


if __name__ == "__main__":
    code = main()
    if offline.HITS:
        print(f"note: your code tried {', '.join(dict.fromkeys(offline.HITS))}: blocked, the week-5 labs open no "
              f"connection and start no process")
    raise SystemExit(code)
