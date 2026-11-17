"""`tr grade`: shadow baselines and grades for closed theses (SPIKE §7.1, §7.2, §7.4; §6.8 CLOSED → GRADED).

Free: stored events, raw bars and the pure `reconcile.settle`; no model call. A champion or challenger thesis gets
its shadow once OPEN (§7.4: same entry, same stop distance, direction from close vs sma_20, target 2R, same time
exit), and its Grade once both it and its shadow are CLOSED: the §7.1 OutcomeGrade, a gigai-core ScoreRecord of it,
P2-P4 from checks.py, and a GRADED event, in one transaction. P1 (the judge, ADR-003) reads `post_trade_summary`
through `label.summary`; `judge` at the end is the opt-in `tr grade --judge`, the one paid call, one per graded thesis.

The outcome is the one `settle` gives on replay of the recorded events: reconcile stores no OutcomeGrade for
champion theses, and the replay is the same computation over the same bars (a data revision makes it wait).
The shadow settles through `settle` as a market_open thesis whose window starts at the real fill minute, with that
bar's open set to E; like any market_open fill, the whole fill bar counts toward its MFE/MAE and stop check.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import median

import pandas as pd
from gigai_core.budget import BudgetExceeded
from gigai_core.score import ScoreRecord

from . import alpaca, checks, journal, reconcile, sessions, trace
from .analyze import plain, snapshot_rows
from .hashing import digest
from .reconcile_run import ADJUSTMENT, PRICES, TERMINAL, BarSource, revision_notes
from .records import RULES_VERSION, Analysis, EntryRule, Event, Grade, OutcomeGrade, Shadow, SourceRef, Thesis

GRADER_ID = "outcome_r_net"  # the outcome ScoreRecord: value = r_net (§7.1)
GRADER_VERSION = "1"
P2_P4 = ("p2_evidence_valid", "p3_invalidation_testable", "p4_levels_coherent")
FILL_MINUTE = timedelta(minutes=1)
LEVEL_ROWS = ("high_20", "low_20", "sma_20", "sma_50", "sma_200", "ema_9", "ema_21", "vwap_session",
              "congestion_low", "congestion_high")  # snapshot rows that are prices a close can be compared with


@dataclass(frozen=True)
class Item:
    """One thesis after a run: its shadow, what was (or a dry run would be) written, or why it waits."""

    thesis: Thesis
    state: str
    shadow: Shadow | None = None
    created: bool = False
    shadow_events: tuple[Event, ...] = ()
    shadow_outcome: OutcomeGrade | None = None
    outcome: OutcomeGrade | None = None
    grade: Grade | None = None
    waiting: str | None = None
    notes: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class Report:
    session: date
    items: tuple[Item, ...]
    dry_run: bool


def run(conn, bars: BarSource | None, session: date, *, dry_run: bool = False, now: datetime | None = None) -> Report:
    """Shadows and grades up to `session` for every ungraded champion or challenger thesis; teachers get neither.
    `bars` is read only when a thesis is OPEN or CLOSED."""
    now = now or datetime.now(UTC)
    items = tuple(grade_one(conn, bars, t, state, session, now, dry_run) for t, state in journal.ungraded_theses(conn))
    return Report(session, items, dry_run)


def grade_one(conn, bars: BarSource | None, t: Thesis, state: str, session: date, now: datetime,
              dry_run: bool) -> Item:
    """The shadow (created if missing, then settled), then the grade once the thesis and its shadow are CLOSED."""
    if state == "PROPOSED":
        return Item(t, state, waiting="PROPOSED: not filled yet")
    if t.rules_version != RULES_VERSION:
        return Item(t, state, waiting=f"written under {t.rules_version}, this engine is {RULES_VERSION}")
    events = journal.events_for(conn, t.thesis_id)
    opened = next((e for e in events if e.state == "OPEN"), None)
    if opened is None or opened.price is None:
        return Item(t, state, waiting=f"{state} with no filled OPEN event")
    if session < opened.at.astimezone(sessions.NY).date():
        return Item(t, state, waiting=f"--session {session} is before the fill at {opened.at:%Y-%m-%d %H:%M} UTC")
    analysis = journal.get(conn, Analysis, t.analysis_id)
    shadow = journal.shadow_of(conn, t.thesis_id)
    created = shadow is None
    if shadow is None:
        built = shadow_for(t, opened, analysis)
        if isinstance(built, str):
            return Item(t, state, waiting=built)
        shadow = built
    stored = journal.shadow_outcome(conn, shadow.shadow_id)
    recorded = () if created else journal.events_for(conn, shadow.shadow_id)
    if stored is None and recorded and recorded[-1].state in TERMINAL:
        last = recorded[-1]
        return Item(t, state, shadow, waiting=f"shadow {shadow.shadow_id} {last.state} ({last.reason}): no shadow "
                                              "outcome, so this thesis cannot be graded")
    if stored is not None and state != "CLOSED":
        return Item(t, state, shadow, shadow_outcome=stored, waiting="OPEN: not closed yet")
    if bars is None:
        raise ValueError(f"{t.thesis_id} is {state}: grading it needs a bar source")
    first = t.entry.window_start.astimezone(sessions.NY).date()
    frame, source = daily_frame(bars, t.ticker, first, session)
    if frame is None or source is None:
        return Item(t, state, None if created else shadow,
                    waiting=f"no {bars.feed} daily bars for {first}..{session}")
    new, outcome_s, notes = (), stored, []
    if stored is None:
        settled, outcome_s, notes = settle_shadow(bars, shadow, t, recorded, frame, source, now)
        if settled is None:
            return Item(t, state, waiting="the shadow cannot share the thesis's fill", notes=tuple(notes))
        new = settled
        if not dry_run:
            if created:
                journal.add(conn, shadow, written(shadow, now))
            if new:
                journal.add_settlement(conn, list(new), [source], outcome_s)
    item = Item(t, state, shadow, created, new, outcome_s, notes=tuple(notes))
    if state != "CLOSED":
        return replace(item, waiting="OPEN: not closed yet")
    result = reconcile.settle(t, events, frame, lambda day: bars.minutes(t.ticker, day), sessions.xnys(),
                              RULES_VERSION)
    notes += [*revision_notes(conn, events, frame[PRICES], t.ticker, bars.feed), *result.notes]
    if result.outcome is None:
        return replace(item, waiting=f"the replay to {session} gives no outcome", notes=tuple(notes))
    item = replace(item, outcome=result.outcome, notes=tuple(notes))
    if outcome_s is None:
        last = new[-1].state if new else recorded[-1].state if recorded else "PROPOSED"
        return replace(item, waiting=f"shadow {shadow.shadow_id} {last}: the grade waits for it to close")
    built = build_grade(t, analysis, result.outcome, shadow, now)
    if not dry_run:
        journal.add_grade(conn, *built)
    return replace(item, grade=built[0])


def code_checks(t: Thesis, analysis: Analysis) -> dict[str, bool]:
    """P2-P4 on a stored thesis, from its analysis's claims and snapshot read the way evals' graders read them."""
    snap = analysis.snapshot
    values = {row.source_id: row.value for row in snapshot_rows(snap)[1]}
    close = snap.values["close"]
    return {
        "p2_evidence_valid": checks.p2_evidence_valid(t, analysis.claims, values),
        "p3_invalidation_testable": checks.p3_invalidation_testable(t, close),
        "p4_levels_coherent": checks.p4_levels_coherent(t, snap.levels, snap.values["atr_14"], close),
    }


# ---------- shadow (§7.4) ----------

def shadow_for(t: Thesis, opened: Event, analysis: Analysis) -> Shadow | str:
    """d = sign(close − sma_20) at the analysis; E and its time from the OPEN event; stop E − d·|E − S|, target
    E + d·2·|E − S|; the thesis's hold. A str says why there is no shadow."""
    close, sma = analysis.snapshot.values.get("close"), analysis.snapshot.values.get("sma_20")
    if close is None or sma is None:
        return "no shadow: the snapshot has no close or sma_20"
    if close == sma:
        return f"no shadow: close {plain(close)} equals sma_20, so no direction"
    entry = opened.price
    assert entry is not None
    dist = abs(entry - t.stop)
    if dist == 0:
        return f"no shadow: the fill {plain(entry)} equals the stop"
    d = 1 if close > sma else -1
    return Shadow(
        shadow_id="sh_" + digest({"thesis": t.thesis_id}).removeprefix("sha256:")[:16], thesis_id=t.thesis_id,
        direction="long" if d == 1 else "short", entry_price=entry, entry_at=opened.at, stop=entry - d * dist,
        target=entry + d * 2 * dist, hold_sessions=t.hold_sessions, rule_version=RULES_VERSION,
    )


def subject(shadow: Shadow, t: Thesis) -> Thesis:
    """The shadow as a thesis `settle` walks: a market_open entry in the fill minute; the invalidation is the stop,
    so only stop, target and the thesis's time exit can close it."""
    entry = EntryRule(kind="market_open", price=None, window_start=shadow.entry_at,
                      window_end=shadow.entry_at + FILL_MINUTE)
    return Thesis.model_validate(t.model_dump() | {
        "thesis_id": shadow.shadow_id, "direction": shadow.direction, "entry": entry, "stop": shadow.stop,
        "target": shadow.target, "invalidation_price": shadow.stop, "evidence": ("shadow",)})


def fill_minutes(bars: BarSource, shadow: Shadow, ticker: str) -> reconcile.MinuteBars:
    """The ticker's minutes with the fill bar's open set to E, so the market_open entry fills at E at entry_at."""
    def minutes(day: date) -> pd.DataFrame | None:
        frame = bars.minutes(ticker, day)
        if frame is None or frame.empty:
            return frame
        at = pd.to_datetime(frame["t"], utc=True) == pd.Timestamp(shadow.entry_at)
        return frame.assign(o=frame["o"].where(~at, shadow.entry_price))

    return minutes


def settle_shadow(bars: BarSource, shadow: Shadow, t: Thesis, recorded: tuple[Event, ...], frame: pd.DataFrame,
                  source: SourceRef, now: datetime) -> tuple[tuple[Event, ...] | None, OutcomeGrade | None, list[str]]:
    """New shadow events (stamped) and its OutcomeGrade once CLOSED. None for the events, with a note, when the
    first fill is not OPEN at E at entry_at: that shadow would not share the thesis's entry."""
    result = reconcile.settle(subject(shadow, t), recorded, frame, fill_minutes(bars, shadow, t.ticker),
                              sessions.xnys(), RULES_VERSION)
    notes = list(result.notes)
    events = tuple(e.model_copy(update={"recorded_at": now, "bars_source_id": source.source_id})
                   for e in result.events)
    if not any(e.state == "OPEN" for e in recorded) and events:
        fill = events[0]
        if (fill.state, fill.at, fill.price) != ("OPEN", shadow.entry_at, shadow.entry_price):
            notes.append(f"shadow fill: {fill.state} {fill.reason} at {fill.at:%Y-%m-%d %H:%M} UTC, not OPEN at "
                         f"{plain(shadow.entry_price)} at {shadow.entry_at:%Y-%m-%d %H:%M} UTC")
            return None, None, notes
    return events, result.outcome, notes


def written(shadow: Shadow, now: datetime) -> Event:
    """The shadow's PROPOSED event, so `journal.open_shadow_ids` lists it; `settle` skips `written` events."""
    identity = {"subject": shadow.shadow_id, "state": "PROPOSED", "reason": "written",
                "at": shadow.entry_at.isoformat(), "price": None}
    return Event(event_id="ev_" + digest(identity).removeprefix("sha256:")[:16], subject_id=shadow.shadow_id,
                 state="PROPOSED", at=shadow.entry_at, recorded_at=now, price=None, reason="written",
                 bars_source_id=None, rules_version=RULES_VERSION)


def daily_frame(bars: BarSource, ticker: str, first: date,
                session: date) -> tuple[pd.DataFrame | None, SourceRef | None]:
    """The daily bars `settle` reads, built as reconcile_run builds them, with the SourceRef the events cite."""
    daily = bars.daily(ticker, first, session)
    if daily.empty:
        return None, None
    prices = daily[PRICES].reset_index(drop=True)
    source = alpaca.bars_source(prices, ticker=ticker, feed=bars.feed, adjustment=ADJUSTMENT)
    flagged = sorted(bars.corporate_action_days(ticker, first, session))
    return prices.assign(corporate_action=prices["session"].isin(flagged)), source


# ---------- grade (§7.1, §7.2) ----------

def build_grade(t: Thesis, analysis: Analysis, outcome: OutcomeGrade, shadow: Shadow,
                now: datetime) -> tuple[Grade, ScoreRecord, Event]:
    """The Grade, the outcome ScoreRecord it points at, and the GRADED event; ids come from the thesis, so a second
    write is a duplicate-id error."""
    key = digest({"thesis": t.thesis_id}).removeprefix("sha256:")[:16]
    score = ScoreRecord(
        score_id=f"sc_{key}", trace_id=t.sample_trace_id, grader_id=GRADER_ID, grader_version=GRADER_VERSION,
        kind="code", value=outcome.r_net, recorded_at=now,
        explanation=f"{outcome.exit_reason}: r_gross {outcome.r_gross:.4f} - cost_r {outcome.cost_r:.4f}",
    )
    grade = Grade(grade_id=f"gr_{key}", thesis_id=t.thesis_id, outcome=outcome, outcome_score_id=score.score_id,
                  process_score_id=None, code_checks=code_checks(t, analysis), shadow_id=shadow.shadow_id)
    graded = Event(event_id=f"ev_{key}", subject_id=t.thesis_id, state="GRADED", at=now, recorded_at=now,
                   price=None, reason="graded", bars_source_id=None, rules_version=RULES_VERSION)
    return grade, score, graded


# ---------- post-trade summary (evals/specs/p1_judge.md "Inputs") ----------

def post_trade_summary(t: Thesis, analysis: Analysis, events: tuple[Event, ...], daily_bars: pd.DataFrame,
                       outcome: OutcomeGrade) -> str:
    """What the P1 judge sees about the trade, code-written: exit, MFE/MAE, trigger-day rel_volume, closes against
    the levels the thesis cites and the congestion. `daily_bars` (session, c, v) reaches 20 sessions before the fill;
    only closes and one volume ratio come out, never raw bars."""
    opened = next(e for e in events if e.state == "OPEN")
    closed = next(e for e in events if e.state == "CLOSED")
    fill_day, exit_day = (e.at.astimezone(sessions.NY).date() for e in (opened, closed))
    bars = daily_bars.sort_values("session").reset_index(drop=True)
    held = bars[(bars["session"] >= fill_day) & (bars["session"] <= exit_day)]
    closes = list(zip(held["session"], held["c"], strict=True))
    lines = [
        f"exit: {outcome.exit_reason} at {plain(outcome.exit_price)} on {exit_day}, filled at "
        f"{plain(outcome.entry_price)} on {fill_day}; r_net {outcome.r_net:+.2f}, MFE {outcome.mfe_r:+.2f}R, "
        f"MAE {outcome.mae_r:+.2f}R, {outcome.sessions_held} session(s) held after the fill day",
        f"trigger day {fill_day}: rel_volume {rel_volume(bars, fill_day)}",
        "closes: " + ", ".join(f"{day} {plain(c)}" for day, c in closes),
    ]
    sign = 1 if t.direction == "long" else -1
    side = "above" if sign == 1 else "below"
    levels = {**cited_levels(t, analysis), "invalidation": t.invalidation_price}
    for name, level in levels.items():
        n = sum(sign * (c - level) >= 0 for _, c in closes)
        lines.append(f"vs {name} {plain(level)}: closed at or {side} it on {n} of {len(closes)} sessions")
    cg = analysis.snapshot.congestion
    if cg is None:
        lines.append("congestion: none in the snapshot")
    else:
        held_on = {k: sum(sign * (c - v) >= 0 for _, c in closes) for k, v in (("high", cg.high), ("low", cg.low))}
        lines.append(f"congestion {plain(cg.low)}-{plain(cg.high)} ({cg.sessions} sessions): high held on "
                     f"{held_on['high']} of {len(closes)} closes, low held on {held_on['low']} of {len(closes)} "
                     f"(held = closed at or {side} it, the trade's side)")
    return "\n".join(lines)


def rel_volume(bars: pd.DataFrame, day: date) -> str:
    """The day's volume over the median of the 20 sessions before it (indicators.py's rel_volume), or why n/a."""
    at = bars.index[bars["session"] == day]
    if at.empty or at[0] < 20:
        return "n/a (fewer than 20 sessions before it)"
    before = median(bars["v"].iloc[at[0] - 20:at[0]])
    return f"{bars['v'].iloc[at[0]] / before:.2f}" if before else "n/a (no volume before it)"


def cited_levels(t: Thesis, analysis: Analysis) -> dict[str, float]:
    """The snapshot price rows the thesis's evidence cites, directly or through an inference's parents."""
    by_id = {claim.claim_id: claim for claim in analysis.claims}
    rows = {row.source_id: row for row in snapshot_rows(analysis.snapshot)[1]}
    found: dict[str, float] = {}
    seen: set[str] = set()
    stack = list(t.evidence)
    while stack:
        claim = by_id.get(stack.pop())
        if claim is None or claim.claim_id in seen:
            continue
        seen.add(claim.claim_id)
        stack += claim.derived_from
        for row in (rows.get(sid) for sid in claim.source_ids):
            if row and row.value is not None and (row.name in LEVEL_ROWS or row.name.startswith("level_")):
                found[row.name] = row.value
    return dict(sorted(found.items()))


# ---------- output ----------

def render(report: Report) -> list[str]:
    """One line per thesis (id, ticker, horizon, r_net, shadow r_net, P2-P4, what happened), notes, then totals."""
    lines = []
    for it in report.items:
        t = it.thesis
        head = f"{t.ticker:<6} {t.horizon:<5} {t.thesis_id} {it.state:<8}"
        parts = [f"r_net {it.outcome.r_net:+.2f}"] if it.outcome else []
        if it.shadow is not None:
            r = f"r_net {it.shadow_outcome.r_net:+.2f}" if it.shadow_outcome else "open"
            parts.append(f"shadow {it.shadow.shadow_id} {r}")
        if it.grade is not None:
            parts.append(" ".join(f"P{n} {'ok' if it.grade.code_checks[k] else 'fail'}" for n, k in
                                  enumerate(P2_P4, start=2)))
            parts.append(f"{'would grade' if report.dry_run else 'graded'} {it.grade.grade_id}")
        if it.waiting:
            parts.append(f"waiting: {it.waiting}")
        lines.append(head + "  " + "  ".join(parts))
        if it.created and it.shadow is not None:
            s = it.shadow
            lines.append(f"    {'would create' if report.dry_run else 'created'} shadow {s.shadow_id}: {s.direction} "
                         f"E {plain(s.entry_price)} stop {plain(s.stop)} target {plain(s.target)} "
                         f"hold {s.hold_sessions}")
        lines += [f"    shadow → {e.state} {e.reason} {'' if e.price is None else plain(e.price)}".rstrip()
                  for e in it.shadow_events]
        lines += [f"    {note}" for note in it.notes]
    graded = sum(it.grade is not None for it in report.items)
    created = sum(it.created for it in report.items)
    waiting = sum(it.waiting is not None for it in report.items)
    if report.dry_run:
        lines.append(f"grade {report.session} (dry run): would grade {graded}, would create {created} shadow(s), "
                     f"{waiting} waiting; nothing written")
    else:
        lines.append(f"grade {report.session}: {graded} graded, {created} shadow(s) created, {waiting} waiting")
    return lines


def written_ids(report: Report) -> tuple[str, ...]:
    """The grade and new shadow ids a run appended (none for a dry run), for the `tr daily` row."""
    if report.dry_run:
        return ()
    shadows = [it.shadow.shadow_id for it in report.items if it.created and it.shadow]
    return (*shadows, *(it.grade.grade_id for it in report.items if it.grade))


# ---------- the P1 judge (`tr grade --judge`, ADR-003; the only model call here) ----------

JUDGE_MAX_USD = 0.25  # one `tr grade --judge` run's cap; ADR-003 estimates about $0.013 per trade


@dataclass(frozen=True)
class Judged:
    """One thesis after a judge run: its verdict and cost, why it was not judged, or neither (dry run)."""

    thesis: Thesis
    verdict: str | None = None
    reason: str | None = None
    cost_usd: float = 0.0
    error: str | None = None


def to_judge(conn) -> list[Thesis]:
    """Graded champion and challenger theses with no judge verdict yet, oldest first."""
    rows = conn.execute("SELECT t.body FROM thesis t JOIN grade g USING (thesis_id) "
                        "WHERE t.arm IN ('champion', 'challenger') "
                        "AND NOT EXISTS (SELECT 1 FROM judge_verdict v WHERE v.thesis_id = t.thesis_id) "
                        "ORDER BY t.rowid")
    return [Thesis.model_validate_json(body) for (body,) in rows]


def run_files(data_dir: Path) -> set[Path]:
    return set((data_dir / "runs").glob("run_*.jsonl"))


def judge(conn, bars: BarSource | None, provider, *, prices: dict, data_dir: Path, max_usd: float = JUDGE_MAX_USD,
          dry_run: bool = False) -> list[Judged]:
    """P1 on every thesis `to_judge` lists, one call each, under one cap for the whole run. A thesis that cannot be
    judged keeps its error and the run goes on; once the cap cannot cover a call, the rest wait for the next run.
    Cost is each new run file's spent_usd, so a call whose reply held no verdict still counts against the cap."""
    from . import evals  # evals imports label, which imports this module

    out: list[Judged] = []
    spent, capped = 0.0, False
    for t in to_judge(conn):
        if dry_run or capped:
            out.append(Judged(t, error=f"the ${max_usd:.2f} cap is spent; next run" if capped else None))
            continue
        before = run_files(data_dir)
        try:
            score = evals.p1_judge(conn, bars, t.thesis_id, provider, prices=prices, data_dir=data_dir,
                                   max_usd=max_usd - spent)
            judged = Judged(t, verdict=score.answer, reason=score.explanation)
        except BudgetExceeded as exc:
            capped, judged = True, Judged(t, error=f"the ${max_usd:.2f} cap cannot cover the call: {exc}")
        except Exception as exc:  # one thesis's failure (no verdict, a failed call, bars) never stops the run
            judged = Judged(t, error=f"{type(exc).__name__}: {exc}")
        cost = sum(trace.header(path).spent_usd for path in run_files(data_dir) - before)
        spent += cost
        out.append(replace(judged, cost_usd=cost))
    return out


def render_judged(judged: list[Judged], *, dry_run: bool, max_usd: float) -> list[str]:
    """One line per thesis (verdict and cost, or why not judged), then the count and the run's cost in dollars."""
    if not judged:
        return ["judge: nothing to judge (no graded champion or challenger thesis without a verdict)"]
    lines = []
    for j in judged:
        head = f"{j.thesis.ticker:<6} {j.thesis.horizon:<5} {j.thesis.thesis_id} {j.thesis.arm:<10}"
        if dry_run:
            lines.append(f"{head}  would judge")
        elif j.verdict is not None:
            lines.append(f"{head}  P1 {j.verdict} ${j.cost_usd:.6f}: {j.reason}")
        else:
            lines.append(f"{head}  not judged ${j.cost_usd:.6f}: {j.error}")
    if dry_run:
        return lines + [f"judge (dry run): would judge {len(judged)} (cap ${max_usd:.2f}); nothing judged, no call"]
    done = sum(j.verdict is not None for j in judged)
    return lines + [f"judge: {done} judged, {len(judged) - done} not judged, cost "
                    f"${sum(j.cost_usd for j in judged):.6f} (cap ${max_usd:.2f})"]
