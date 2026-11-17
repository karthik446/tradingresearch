"""The teacher bake-off report (SPIKE §9.4, P12; TRAINING-SPIKE §7.1): the pre-registered pick rule's inputs per
teacher, read offline from the journal and the saved runs. It prints each teacher's eligibility and never picks.

The bake-off is the first ten sessions on or after FIRST_SESSION (the first live session, `sessions.py`) with a stored
teacher analysis; its items are each session's four drawn names (`teacher.draw` over the screen's shortlist of ten).
A teacher's item counts as `parse_ok` when its analysis and a thesis-step decision (a teacher thesis or a no-trade)
from it are stored, so a failed or missing call fails the item. P2-P4 run on each stored teacher thesis with its
analysis (`grade.code_checks`), so they count before any thesis settles.
"""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from gigai_core import open_run
from gigai_core.records import Prereg

from . import daily, grade, journal, screen, teacher, trace, usage
from .records import Analysis, TeacherOutcome, Thesis
from .sessions import FIRST_SESSION

SHORTLIST = 10  # the screen's top N the draw picks from (SPIKE §4.2)
N_PLANNED = 40  # items per teacher: 4 names x 10 sessions (SPIKE §9.4)
SESSIONS = N_PLANNED // teacher.BAKEOFF_NAMES
PARSE_OK_MIN = 38  # eligible at parse_ok >= 38/40 ...
FACT_VALID_MIN = 0.90  # ... and >= 90% of fact claims valid (TRAINING-SPIKE §7.1)
MISSING_SESSIONS_MAX = 2  # amendment 1: a teacher missing (endpoint) in more than 2 sessions is out of the pick
# A failed teacher step the model did not cause: the pinned endpoint did not answer (429, 5xx, timeout, wrong route).
ENDPOINT_FAILURE = re.compile(r"model call failed: (?:rate_limited|http_5\d\d|model_call_timed_out|route_mismatch)\b")
STATES = ("CLOSED", "CANCELLED", "EXPIRED", "OPEN", "PROPOSED")


def prereg(path: Path) -> Prereg:
    """The bake-off's pre-registration from a flat TOML file, checked by gigai-core's Prereg record."""
    return Prereg.model_validate(tomllib.loads(path.read_text()))


@dataclass(frozen=True)
class Plan:
    """The bake-off sessions, their drawn items, and the sessions that have no stored screen to draw from."""

    sessions: tuple[date, ...]
    items: tuple[tuple[date, str], ...]
    unscreened: tuple[date, ...]


@dataclass(frozen=True)
class TeacherRow:
    """One teacher's pick-rule inputs. `facts_total` is None when a stored analysis's run file is missing. `missing`
    counts the items with no analysis or no thesis-step decision after every run because the endpoint failed
    (amendment 1): reported, and not a parse failure; `missing_sessions` is the sessions holding any such item."""

    model: str
    items: int
    parse_ok: int
    facts_valid: int
    facts_total: int | None
    cost: usage.Usage | None
    states: dict[str, int]
    p2_p4: float | None  # the share of items passing P2-P4; None before any item is drawn
    missing: int = 0
    missing_sessions: int = 0

    @property
    def fact_share(self) -> float | None:
        return self.facts_valid / self.facts_total if self.facts_total else None

    @property
    def verdict(self) -> str:
        """Eligibility under the pre-registered rule; `incomplete` until all planned items are in."""
        failed = []
        if self.items - self.missing - self.parse_ok > N_PLANNED - PARSE_OK_MIN:
            failed.append(f"parse_ok {self.parse_ok}/{self.items}" + (f" ({self.missing} missing)" if self.missing else ""))
        if self.missing_sessions > MISSING_SESSIONS_MAX:
            failed.append(f"endpoint missing in {self.missing_sessions} of {SESSIONS} sessions")
        share = self.fact_share
        if self.items >= N_PLANNED and share is not None and share < FACT_VALID_MIN:
            failed.append(f"fact claims valid {share:.1%}")
        if failed:
            return "not eligible: " + ", ".join(failed)
        if self.items < N_PLANNED:
            return f"incomplete: {self.items}/{N_PLANNED} items"
        return "eligible" if share is not None else "unknown: fact-claim share n/a"


def plan(conn) -> Plan:
    """The first SESSIONS sessions from FIRST_SESSION with a stored teacher analysis and each one's drawn names."""
    found = conn.execute("SELECT DISTINCT session FROM analysis WHERE arm = 'teacher' AND session >= ? "
                         "ORDER BY session", (FIRST_SESSION.isoformat(),)).fetchall()
    sessions = tuple(date.fromisoformat(day) for (day,) in found[:SESSIONS])
    items, unscreened = [], []
    for day in sessions:
        results = screen.stored(conn, day)
        if not results:
            unscreened.append(day)
            continue
        items += [(day, name) for name in teacher.draw(day, daily.shortlist(results, SHORTLIST))]
    return Plan(sessions, tuple(items), tuple(unscreened))


def report(conn, data_dir: Path) -> tuple[Plan, list[TeacherRow]]:
    """Every pinned teacher's row over the planned items, in `teacher.TEACHERS` order."""
    bakeoff = plan(conn)
    costs = calls_by_teacher(data_dir, set(bakeoff.items))
    return bakeoff, [row(conn, data_dir, model, bakeoff.items, costs.get(model, [])) for model in teacher.TEACHERS]


def row(conn, data_dir: Path, model: str, items: tuple[tuple[date, str], ...], calls: list[trace.Call]) -> TeacherRow:
    analyses = first_analyses(conn, model)
    failures = last_failures(conn, model)
    parse_ok = facts_valid = 0
    facts_total: int | None = 0
    states: Counter[str] = Counter()
    theses_by_item: list[list[str] | None] = []
    missing: set[tuple[date, str]] = set()
    for item in items:
        analysis = analyses.get(item)
        if analysis is None:
            theses_by_item.append(None)
            if endpoint_failed(failures.get((*item, "analyze"))):
                missing.add(item)
            continue
        theses = [tid for (tid,) in conn.execute(
            "SELECT thesis_id FROM thesis WHERE analysis_id = ? AND arm = 'teacher'", (analysis.analysis_id,))]
        ok = decided(conn, analysis.analysis_id)
        parse_ok += ok
        theses_by_item.append(theses if ok else None)
        if not ok and endpoint_failed(failures.get((*item, "thesis"))):
            missing.add(item)
        states.update(state(conn, tid) for tid in theses)
        facts_valid += sum(claim.tag == "fact" for claim in analysis.claims)
        replied = reply_facts(data_dir, analysis)
        facts_total = None if facts_total is None or replied is None else facts_total + replied
    cost = usage.summarize(model, calls) if calls else None
    return TeacherRow(model, len(items), parse_ok, facts_valid, facts_total, cost, dict(states),
                      p2_p4(conn, theses_by_item), len(missing), len({day for day, _ in missing}))


def last_failures(conn, model: str) -> dict[tuple[date, str, str], str]:
    """The reason of each (session, name, step)'s LAST non-skipped `tr daily` row for `model`, kept only when it
    failed: a later run that answered, or a later success, replaces it, so this is the final state, not the attempts."""
    prefix = f"{daily.TEACHER} {model}: "
    last: dict[tuple[date, str, str], str | None] = {}
    for r in journal.daily_runs(conn):
        if r["step"] in ("analyze", "thesis") and r["reason"].startswith(prefix) and r["status"] != "skipped":
            last[(date.fromisoformat(r["session"]), r["ticker"], r["step"])] = r["reason"] if r["status"] == "failed" else None
    return {key: reason for key, reason in last.items() if reason}


def endpoint_failed(reason: str | None) -> bool:
    return reason is not None and ENDPOINT_FAILURE.search(reason) is not None


def decided(conn, analysis_id: str) -> bool:
    """A thesis-step decision from this teacher analysis is stored: a teacher thesis or a no-trade."""
    query = ("SELECT 1 FROM thesis WHERE analysis_id = ? AND arm = 'teacher' "
             "UNION ALL SELECT 1 FROM no_trade WHERE analysis_id = ? LIMIT 1")
    return conn.execute(query, (analysis_id, analysis_id)).fetchone() is not None


def first_analyses(conn, model: str) -> dict[tuple[date, str], Analysis]:
    """Each item's first stored teacher analysis by `model`: a later rerun does not replace the first answer."""
    found: dict[tuple[date, str], Analysis] = {}
    for (body,) in conn.execute("SELECT body FROM analysis WHERE arm = 'teacher' ORDER BY created_at, rowid"):
        analysis = Analysis.model_validate_json(body)
        if analysis.model == model:
            found.setdefault((analysis.session, analysis.ticker), analysis)
    return found


def state(conn, thesis_id: str) -> str:
    """A teacher thesis's terminal state from its TeacherOutcome, else its last lifecycle event."""
    outcome = conn.execute("SELECT body FROM teacher_outcome WHERE thesis_id = ?", (thesis_id,)).fetchone()
    if outcome:
        return TeacherOutcome.model_validate_json(outcome[0]).final_state
    last = conn.execute("SELECT state FROM event WHERE subject_id = ? ORDER BY seq DESC LIMIT 1", (thesis_id,)).fetchone()
    return last[0] if last else "PROPOSED"


def reply_facts(data_dir: Path, analysis: Analysis) -> int | None:
    """The fact claims the model wrote, valid or not, from the analysis's run file; None if the file is gone."""
    path = data_dir / "runs" / f"{analysis.run_id}.jsonl"
    if not path.exists():
        return None
    item_id = f"{analysis.ticker}:{analysis.session}"
    for sample in open_run(path).samples:
        if sample.item_id == item_id and isinstance(sample.output_parsed, dict):
            claims = sample.output_parsed.get("claims")
            return sum(isinstance(c, dict) and c.get("tag") == "fact" for c in claims) if isinstance(claims, list) else 0
    return None


def p2_p4(conn, theses_by_item: list[list[str] | None]) -> float | None:
    """The share of drawn items that parsed, wrote at least one thesis, and whose every thesis passes P2, P3 and P4;
    None with no items."""
    if not theses_by_item:
        return None
    passed = sum(bool(theses) and all(passes(conn, tid) for tid in theses)
                 for theses in theses_by_item if theses is not None)
    return passed / len(theses_by_item)


def passes(conn, thesis_id: str) -> bool:
    t = journal.get(conn, Thesis, thesis_id)
    return all(grade.code_checks(t, journal.get(conn, Analysis, t.analysis_id)).values())


def calls_by_teacher(data_dir: Path, items: set[tuple[date, str]]) -> dict[str, list[trace.Call]]:
    """Every saved `tr analyze`/`tr thesis` call a pinned teacher made on a planned item, failed calls included."""
    found: dict[str, list[trace.Call]] = {}
    if not (data_dir / "runs").exists():
        return found
    for record, path in trace.iter_runs(data_dir):
        if trace.kind(record) not in ("analyze", "thesis"):
            continue
        for call in trace.calls(path):
            ticker, day, *rest = call.item_id.split(":")
            if call.model in teacher.TEACHERS and rest in ([], ["teacher"]) and (date.fromisoformat(day), ticker) in items:
                found.setdefault(call.model, []).append(call)
    return found


def render(bakeoff: Plan, rows: list[TeacherRow]) -> str:
    """The per-teacher table and the eligibility table; the pick itself is left to the learner."""
    span = f"{bakeoff.sessions[0]}..{bakeoff.sessions[-1]}" if bakeoff.sessions else "none yet"
    lines = [f"bake-off sessions {span} ({len(bakeoff.sessions)} of {SESSIONS}), {len(bakeoff.items)} drawn items "
             f"(n_planned {N_PLANNED})"]
    lines += [f"  {day}: no stored screen, nothing drawn (run `tr screen --session {day}`)" for day in bakeoff.unscreened]
    lines += ["", f"{'teacher':<28}{'items':>6}{'parse_ok':>10}{'missing':>9}{'facts valid':>19}{'cost_usd':>11}  states"]
    for r in rows:
        facts = f"{r.facts_valid}/{r.facts_total} ({r.fact_share:.1%})" if r.fact_share is not None else "n/a"
        cost = "n/a" if r.cost is None else f"{'>=' if r.cost.prices_missing else ''}{r.cost.cost_usd:.4f}"
        states = " ".join(f"{s}={r.states[s]}" for s in STATES if r.states.get(s)) or "-"
        missing = f"{r.missing}/{r.missing_sessions}s" if r.missing else "0"
        lines.append(f"{r.model:<28}{r.items:>6}{f'{r.parse_ok}/{r.items}':>10}{missing:>9}{facts:>19}{cost:>11}  {states}")
    lines += ["", f"eligibility: parse_ok >= {PARSE_OK_MIN}/{N_PLANNED} and fact claims valid >= {FACT_VALID_MIN:.0%}; "
                  f"'missing' = items the endpoint never served after the last run (n items/n sessions): not parse "
                  f"failures, but more than {MISSING_SESSIONS_MAX} sessions out of the pick (amendment 1)",
              f"{'teacher':<28}{'verdict':<36}p2_p4_pass"]
    for r in rows:
        p2 = "n/a" if r.p2_p4 is None else f"{r.p2_p4:.1%}"
        lines.append(f"{r.model:<28}{r.verdict:<36}{p2}")
    lines += ["", "no automatic pick: the leader on p2_p4_pass wins unless a cheaper eligible teacher is within the "
                  "margin (experiments/bakeoff-prereg.toml)"]
    return "\n".join(lines)
