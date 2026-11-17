"""`tr thesis`: one stored Analysis becomes 0–3 theses (one per horizon) or NoTrade rows; code checks every thesis
against the SPIKE §1.1 Thesis rules and the §6.6 stop floor before anything is written (SPIKE §6.2, §6.7, P5)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

import pandas as pd
from gigai_core import CallBudget, CallSettings, Dataset, DatasetItem, run as run_eval
from gigai_core.graders.protocol import CannotGrade
from gigai_core.score import Score
from pydantic import ValidationError

from . import analyze as an, journal, sessions
from .hashing import digest, new_id
from .records import HOLD_RANGE, RULES_VERSION, Analysis, EntryRule, Event, NoTrade, SetupType, Thesis

DEFAULT_PROMPT = "thesis-1"
DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"  # SPIKE §9.1, thesis row
HORIZONS = ("day", "short", "swing")
STOP_FLOOR_BPS = 50.0  # SPIKE §6.6: a stop closer than this, or than 0.25·ATR14, is rejected
STOP_FLOOR_ATR = 0.25
DAY_WINDOW_END = time(11, 30)  # SPIKE §6.2: day entries only 09:30–11:30 ET

THESIS_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["horizon", "direction", "setup_type", "prediction", "reason", "entry_kind", "entry_price", "stop",
                 "target", "hold_sessions", "invalidation_price", "invalidation_text", "evidence"],
    "properties": {
        "horizon": {"type": "string", "enum": list(HORIZONS)},
        "direction": {"type": "string", "enum": ["long", "short"]},
        "setup_type": {"type": "string", "enum": list(SetupType.__args__)},
        "prediction": {"type": "string"},
        "reason": {"type": "string"},
        "entry_kind": {"type": "string", "enum": ["market_open", "stop", "limit"]},
        "entry_price": {"type": ["number", "null"]},
        "stop": {"type": "number"},
        "target": {"type": "number"},
        "hold_sessions": {"type": "integer"},
        "invalidation_price": {"type": "number"},
        "invalidation_text": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
}
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["theses", "no_trade"],
    "properties": {
        "theses": {"type": "array", "items": THESIS_ITEM},
        "no_trade": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["horizon", "reason"],
                "properties": {"horizon": {"type": "string", "enum": list(HORIZONS)}, "reason": {"type": "string"}},
            },
        },
    },
}


@dataclass(frozen=True)
class Written:
    """What code fills on every thesis of one call; the model never writes these."""

    arm: str
    created_at: datetime
    sample_trace_id: str
    provider_route: str
    terms_class: str
    input_hash: str


@dataclass(frozen=True)
class Rejection:
    horizon: str
    reason: str
    detail: str


@dataclass
class Checked:
    theses: list[Thesis]
    no_trades: list[NoTrade]
    rejected: list[Rejection]


# ---------- rules ----------

def next_session(day: date) -> date:
    return sessions.xnys().next_session(pd.Timestamp(day)).date()


def windows(session: date, horizon: str) -> tuple[datetime, datetime]:
    """SPIKE §6.2 entry window for a thesis written after `session`'s close, in UTC."""
    first = next_session(session)
    start, close = sessions.open_close(first)
    if horizon == "day":
        return start, datetime.combine(first, DAY_WINDOW_END, sessions.NY).astimezone(UTC)
    if horizon == "short":
        return start, close
    return start, sessions.open_close(next_session(first))[1]  # swing: the next 2 sessions


def reference_price(item: dict, analysis: Analysis) -> float:
    """The entry price, or the snapshot's last close for a market_open entry (Thesis rule 1)."""
    if item["entry_kind"] == "market_open":
        return analysis.snapshot.values["close"]
    return float(item["entry_price"])


def stop_floor(analysis: Analysis, entry: float) -> float:
    """SPIKE §6.6: the stop sits at least max(50 bps of entry, 0.25·ATR14) away."""
    return max(entry * STOP_FLOOR_BPS / 10_000, STOP_FLOOR_ATR * analysis.snapshot.values["atr_14"])


def check_thesis(item: dict, analysis: Analysis, written: Written) -> tuple[str, str] | None:
    """The first broken Thesis rule as (reason, detail), or None. Rules the record checks alone are re-checked here
    so each failure gets its own reason in the run output."""
    if (written.arm == "teacher") != (analysis.arm == "teacher"):  # rule 6
        return "arm_mismatch", f"a {written.arm} thesis cannot reference a {analysis.arm} analysis"
    claims = {claim.claim_id: claim for claim in analysis.claims}
    evidence = list(item["evidence"])
    if not evidence:
        return "no_evidence", "evidence is empty"
    unknown = [e for e in evidence if e not in claims]
    if unknown:
        return "unknown_evidence", f"not a claim of {analysis.analysis_id}: {', '.join(unknown)}"
    if all(claims[e].tag == "opinion" for e in evidence):  # rule 2
        return "opinion_only_evidence", "evidence needs at least one fact or inference claim"
    horizon, direction, hold = item["horizon"], item["direction"], item["hold_sessions"]
    lo, hi = HOLD_RANGE[horizon]
    if not (isinstance(hold, int) and lo <= hold <= hi):  # rule 3
        return "hold_sessions", f"{horizon} needs {lo}-{hi}, got {hold}"
    entry, stop, target = reference_price(item, analysis), float(item["stop"]), float(item["target"])
    invalidation = float(item["invalidation_price"])
    sign = 1 if direction == "long" else -1
    if sign * (entry - stop) <= 0:  # rule 1
        return "stop_side", f"{direction}: entry {entry:g}, stop {stop:g}"
    if sign * (target - entry) <= 0:
        return "target_side", f"{direction}: entry {entry:g}, target {target:g}"
    floor = stop_floor(analysis, entry)
    if abs(entry - stop) < floor:  # rule 4
        return "stop_floor", f"stop distance {abs(entry - stop):.2f} < floor {floor:.2f} (max of 50 bps, 0.25·ATR14)"
    if not (sign * (entry - invalidation) > 0 and sign * (invalidation - stop) >= 0):  # P3: testable invalidation
        return "invalidation", f"invalidation {invalidation:g} is not between entry {entry:g} and stop {stop:g}"
    start, _ = windows(analysis.session, horizon)
    bound = sessions.open_close(analysis.session)[1] if written.arm == "teacher" else written.created_at
    if start <= bound:  # rule 5
        return "window_passed", f"entry window starts {start.isoformat()}, not after {bound.isoformat()}"
    return None


def build(item: dict, analysis: Analysis, written: Written) -> Thesis:
    start, end = windows(analysis.session, item["horizon"])
    price = item["entry_price"]
    return Thesis(
        thesis_id=new_id("th"), analysis_id=analysis.analysis_id, ticker=analysis.ticker, horizon=item["horizon"],
        direction=item["direction"], setup_type=item["setup_type"], prediction=item["prediction"],
        reason=item["reason"],
        entry=EntryRule(kind=item["entry_kind"], price=None if price is None else float(price), window_start=start,
                        window_end=end),
        stop=float(item["stop"]), target=float(item["target"]), hold_sessions=item["hold_sessions"],
        invalidation_price=float(item["invalidation_price"]), invalidation_text=item["invalidation_text"],
        evidence=tuple(item["evidence"]), regime=analysis.snapshot.regime, arm=written.arm,
        sample_trace_id=written.sample_trace_id, provider_route=written.provider_route,
        terms_class=written.terms_class, rules_version=RULES_VERSION, created_at=written.created_at,
        input_hash=written.input_hash,
    )


def horizon_problem(horizon: str, asked: tuple[str, ...], seen: set[str]) -> tuple[str, str] | None:
    if horizon not in asked:
        return "horizon_not_asked", f"asked {', '.join(asked)}"
    if horizon in seen:
        return "duplicate_horizon", "one thesis or one no_trade per horizon"
    return None


def validate(raw: object, analysis: Analysis, asked: tuple[str, ...], written: Written) -> Checked:
    """Every reply item becomes a Thesis, a NoTrade or a Rejection with a reason; nothing is dropped silently."""
    out = Checked([], [], [])
    if not (isinstance(raw, dict) and isinstance(raw.get("theses"), list) and isinstance(raw.get("no_trade"), list)):
        out.rejected.append(Rejection("-", "not_json_theses", "output needs 'theses' and 'no_trade' lists"))
        return out
    seen: set[str] = set()
    for item in raw["theses"]:
        horizon = str(item.get("horizon")) if isinstance(item, dict) else "?"
        problem = horizon_problem(horizon, asked, seen)
        seen.add(horizon)
        if problem is None:
            try:
                problem = check_thesis(item, analysis, written)
                if problem is None:
                    out.theses.append(build(item, analysis, written))
            except (ValidationError, KeyError, TypeError, ValueError) as exc:
                problem = "not_a_thesis", str(exc).splitlines()[0][:160]
        if problem:
            out.rejected.append(Rejection(horizon, *problem))
    for item in raw["no_trade"]:
        horizon = str(item.get("horizon")) if isinstance(item, dict) else "?"
        problem = horizon_problem(horizon, asked, seen)
        if problem:
            out.rejected.append(Rejection(horizon, *problem))
            continue
        seen.add(horizon)
        out.no_trades.append(NoTrade(analysis_id=analysis.analysis_id, horizon=horizon, reason=str(item.get("reason")),
                                     created_at=written.created_at))
    out.rejected += [Rejection(h, "horizon_missing", "no thesis and no no_trade") for h in asked if h not in seen]
    return out


class ThesesValid:
    """A gigai-core code grader: the share of the model's theses that pass the code checks. The explanation keeps
    each rejection's horizon and reason in the run file (SPIKE §6.6: logged, not silently dropped)."""

    id = "theses_valid"
    version = "1"
    kind = "code"

    def grade(self, sample, expected) -> Score:
        if sample.parse_status != "ok":
            raise CannotGrade("output did not parse")
        analysis = Analysis.model_validate_json(expected["analysis"])
        written = Written(expected["arm"], sample.recorded_at, sample.trace_id, "grade", "unknown", "grade")
        checked = validate(sample.output_parsed, analysis, tuple(expected["horizons"]), written)
        failed = [r for r in checked.rejected if r.reason != "horizon_missing"]
        total = len(checked.theses) + len(failed)
        why = "; ".join(f"{r.horizon} {r.reason}: {r.detail}" for r in checked.rejected)
        return Score(value=len(checked.theses) / total if total else 1.0, explanation=why or None)


# ---------- prompt ----------

def source_block(analysis: Analysis) -> str:
    """The analysis's SOURCES table as `analyze.render` writes it, rebuilt from the stored snapshot (same ids)."""
    sources, rows = an.snapshot_rows(analysis.snapshot)
    ctx = an.Context(analysis.ticker, analysis.session, analysis.snapshot, sources, rows)
    return an.render(ctx).rsplit("\n\n", 1)[0]  # drop analyze's closing instruction


def render(analysis: Analysis, asked: tuple[str, ...]) -> str:
    close, atr = analysis.snapshot.values["close"], analysis.snapshot.values["atr_14"]
    lines = [source_block(analysis), "", "CLAIMS (claim_id | tag | text | cites)"]
    for c in analysis.claims:
        text = c.text.replace("{value}", an.plain(c.value)) if c.value is not None else c.text
        lines.append(f"{c.claim_id} | {c.tag} | {text} | {','.join(c.source_ids or c.derived_from) or '-'}")
    lines += ["", f"REFERENCE PRICE for market_open entries: {an.plain(close)} (the close)",
              f"STOP FLOOR at the close: {stop_floor(analysis, close):.2f} USD "
              f"(max of {STOP_FLOOR_BPS:g} bps of entry = {close * STOP_FLOOR_BPS / 10_000:.2f}, "
              f"{STOP_FLOOR_ATR:g} x atr_14 = {STOP_FLOOR_ATR * atr:.2f})",
              "", "HORIZONS TO ANSWER (exactly one thesis or one no_trade each)"]
    for horizon in asked:
        start, end = windows(analysis.session, horizon)
        lo, hi = HOLD_RANGE[horizon]
        lines.append(f"{horizon}: entry window {start.astimezone(sessions.NY):%Y-%m-%d %H:%M} to "
                     f"{end.astimezone(sessions.NY):%Y-%m-%d %H:%M} ET, hold_sessions {lo}-{hi}")
    lines += ["", "Write the JSON with the keys \"theses\" and \"no_trade\"."]
    return "\n".join(lines)


def input_hash(analysis: Analysis, asked: tuple[str, ...], prompt_version: str) -> str:
    return digest({"analysis_id": analysis.analysis_id, "analysis_input": analysis.input_hash,
                   "horizons": list(asked), "prompt_version": prompt_version})


# ---------- the command ----------

@dataclass
class Result:
    checked: Checked
    spent_usd: float
    run_path: str
    trace_path: str


def call_settings(model: str) -> CallSettings:
    return CallSettings(model=model, max_output_tokens=3000, output_mode="schema", json_schema=OUTPUT_SCHEMA)


def item_for(analysis: Analysis, asked: tuple[str, ...], arm: str) -> DatasetItem:
    """One analysis as a gigai-core dataset item; `expected` holds what ThesesValid needs to re-run the checks."""
    return DatasetItem(id=f"{analysis.ticker}:{analysis.session}:{arm}", cluster_id=analysis.ticker,
                       prompt=render(analysis, asked), tags=(analysis.ticker, arm),
                       expected={"analysis": analysis.model_dump_json(), "horizons": list(asked), "arm": arm})


def terms_class(model: str) -> str:
    return "restricted" if model.startswith("anthropic/") else "unknown"


def store(conn: sqlite3.Connection, checked: Checked) -> Checked:
    """Each accepted thesis with its PROPOSED event in one transaction; the one_live trigger is the last guard."""
    kept: list[Thesis] = []
    for t in checked.theses:
        written = Event(event_id=new_id("ev"), subject_id=t.thesis_id, state="PROPOSED", at=t.created_at,
                        recorded_at=datetime.now(UTC), price=None, reason="written", bars_source_id=None,
                        rules_version=RULES_VERSION)
        try:
            journal.add(conn, t, written)
            kept.append(t)
        except sqlite3.IntegrityError as exc:
            checked.rejected.append(Rejection(t.horizon, "one_live", str(exc)))
    journal.add(conn, *checked.no_trades)
    return Checked(kept, checked.no_trades, checked.rejected)


def thesis(conn: sqlite3.Connection, analysis: Analysis, provider, *, asked: tuple[str, ...], arm: str, model: str,
           max_usd: float, prices: dict, data_dir, prompt_version: str = DEFAULT_PROMPT,
           terms: str | None = None, post: Callable[[Checked], Checked] | None = None) -> Result:
    """One model call, checked and stored; `terms` None means `terms_class(model)`, the teacher arm passes trainable.
    `post` is a challenger rule's filter (rules.py), applied before the store because stored theses never go away."""
    item = item_for(analysis, asked, arm)
    run = run_eval(Dataset.of("thesis", [item]), provider, [ThesesValid()], settings=call_settings(model),
                   budget=CallBudget(max_usd=max_usd, prices=prices), system=an.system_prompt(prompt_version),
                   trace_dir=data_dir / "traces", tag=prompt_version)
    run_path = an.save(run, data_dir)
    sample = run.samples[0]
    if sample.outcome != "succeeded":
        raise SystemExit(f"model call failed: {sample.error.code if sample.error else '?'} (run {run_path})")
    route = provider.route_for(item.prompt) if hasattr(provider, "route_for") else "unknown"
    written = Written(arm, datetime.now(UTC), sample.trace_id, route, terms or terms_class(model),
                      input_hash(analysis, asked, prompt_version))
    checked = validate(sample.output_parsed, analysis, asked, written)
    checked = store(conn, checked if post is None else post(checked))
    return Result(checked, run.record.spent_usd, str(run_path), str(run.record.trace_path))
