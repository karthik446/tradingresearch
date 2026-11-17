"""`tr thesis`: one stored Analysis becomes 0–3 theses (one per horizon) or NoTrade rows; code checks every thesis
against the SPIKE §1.1 Thesis rules and the §6.6 stop floor before anything is written (SPIKE §6.2, §6.7, P5).
The thesis-2 prompt also shows the playbook (SPIKE §8.1) as computed sources a thesis may cite in `playbook`.
Those checks are the built-in guard rule (GUARDS-SPIKE §7.2); a live call audits every rejection (§3.3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

import pandas as pd
from gigai_core import CallBudget, CallSettings, Dataset, DatasetItem, run as run_eval
from gigai_core.graders.protocol import CannotGrade
from gigai_core.score import Score
from pydantic import ValidationError

from . import analyze as an, guards, journal, news, sessions
from .hashing import digest, new_id
from .records import (HOLD_RANGE, RULES_VERSION, Analysis, EntryRule, Event, NoTrade, SetupType, SourceRef, Thesis,
                      clean_route)

if TYPE_CHECKING:
    from .playbook import Playbook

DEFAULT_PROMPT = "thesis-1"
PLAYBOOK_PROMPTS = ("thesis-2",)  # prompts whose user turn ends with the PLAYBOOK block
DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"  # SPIKE §9.1, thesis row
HORIZONS = ("day", "short", "swing")
ITEM_KEYS = frozenset({"horizon", "direction", "setup_type", "prediction", "reason", "entry_kind", "entry_price",
                       "stop", "target", "hold_sessions", "invalidation_price", "invalidation_text", "evidence",
                       "playbook"})  # keys a reply item is read by; a KeyError names one of them, never reply text
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
PLAYBOOK_ITEM = {  # thesis-2: playbook row ids go here, never in `evidence` (P2 reads evidence as analysis claims)
    **THESIS_ITEM,
    "required": [*THESIS_ITEM["required"], "playbook"],
    "properties": {**THESIS_ITEM["properties"], "playbook": {"type": "array", "items": {"type": "string"}}},
}
PLAYBOOK_SCHEMA = {**OUTPUT_SCHEMA,
                   "properties": {**OUTPUT_SCHEMA["properties"], "theses": {"type": "array", "items": PLAYBOOK_ITEM}}}


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


def check_thesis(item: dict, analysis: Analysis, written: Written,
                 playbook_ids: frozenset[str] | None = None) -> tuple[str, str] | None:
    """The first broken Thesis rule as (reason, detail), or None. Rules the record checks alone are re-checked here
    so each failure gets its own reason in the run output."""
    if (written.arm == "teacher") != (analysis.arm == "teacher"):  # rule 6
        return "arm_mismatch", f"a {written.arm} thesis cannot reference a {analysis.arm} analysis"
    claims = {claim.claim_id: claim for claim in analysis.claims}
    evidence = list(item["evidence"])
    if not evidence:
        return "no_evidence", "evidence is empty"
    unknown = [guards.shown_id(e) for e in evidence if e not in claims]
    if unknown:
        return "unknown_evidence", f"not a claim of {analysis.analysis_id}: {', '.join(unknown)}"
    if all(claims[e].tag == "opinion" for e in evidence):  # rule 2
        return "opinion_only_evidence", "evidence needs at least one fact or inference claim"
    if playbook_ids is not None:  # thesis-2: a cited playbook row must be one the block showed
        invented = [guards.shown_id(p) for p in item["playbook"] if p not in playbook_ids]
        if invented:
            return "unknown_playbook_row", f"not a row of the PLAYBOOK block: {', '.join(invented)}"
    horizon, direction, hold = item["horizon"], item["direction"], item["hold_sessions"]
    lo, hi = HOLD_RANGE[horizon]
    if not (isinstance(hold, int) and lo <= hold <= hi):  # rule 3
        return "hold_sessions", f"{horizon} needs {lo}-{hi}, got {hold if isinstance(hold, int) else 'a non-integer'}"
    entry, stop, target = reference_price(item, analysis), float(item["stop"]), float(item["target"])
    invalidation = float(item["invalidation_price"])
    sign = 1 if direction == "long" else -1
    side = direction if direction in ("long", "short") else "?"  # a detail never carries a reply-written string
    if sign * (entry - stop) <= 0:  # rule 1
        return "stop_side", f"{side}: entry {entry:g}, stop {stop:g}"
    if sign * (target - entry) <= 0:
        return "target_side", f"{side}: entry {entry:g}, target {target:g}"
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


@guards.builtin
class ThesisRules:
    """Today's Thesis checks (`check_thesis`) as the built-in thesis rule; a violation is named after the check that
    broke (stop_floor, invalidation, ...), so the audit log and stdout give the same reason."""

    id = "thesis_rules"
    version = "1"
    stage = "thesis"
    action = "reject"

    def check(self, item: dict, ctx: guards.ThesisContext) -> guards.Violation | None:
        problem = check_thesis(item, ctx.analysis, ctx.written, ctx.playbook_ids)
        return None if problem is None else guards.Violation(problem[0], self.version, "reject", problem[1])


@guards.rule
class PlainText:
    """GUARDS-SPIKE §2.3 S2, off by default: the free-text fields a later reader trusts stay one plain line, so a
    reply cannot smuggle a second channel (a newline, an invisible character or Hangul filler, a URL) into a record."""

    id = "plain_text"
    version = "1"
    stage = "thesis"
    action = "reject"
    fields = ("prediction", "reason", "invalidation_text")

    def check(self, item: dict, ctx: guards.ThesisContext) -> guards.Violation | None:
        for name in self.fields:
            value = item.get(name)
            if not isinstance(value, str):
                continue  # a missing or non-text field is the built-in rules' to reject
            if any(an.invisible(c) for c in value):
                return guards.Violation(self.id, self.version, self.action, f"{name}: newline or invisible character")
            if "://" in value or "www." in value.lower():
                return guards.Violation(self.id, self.version, self.action, f"{name}: url")
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


def horizon_of(item: object) -> str:
    """A reply item's horizon if it is one of HORIZONS, else `?`: a Rejection and the audit never carry reply text."""
    horizon = item.get("horizon") if isinstance(item, dict) else None
    return horizon if horizon in HORIZONS else "?"


def failure(exc: Exception) -> str:
    """Why a reply item could not be built, by field and error type, never by a reply value (GUARDS-SPIKE §3.3)."""
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        return f"{exc.error_count()} error(s), {'.'.join(map(str, first['loc']))}: {first['type']}"
    if isinstance(exc, KeyError) and exc.args and exc.args[0] in ITEM_KEYS:
        return f"missing {exc.args[0]}"
    return f"{type(exc).__name__}: a value of the wrong type or form"


def audit_item(auditor: guards.Auditor | None, analysis: Analysis, horizon: str, item: object,
               violation: guards.Violation) -> None:
    """One decision on a reply item, audited by its analysis id, horizon and digest when the call has an auditor."""
    if auditor is not None:
        subject = guards.AuditSubject(kind="thesis_item", id=f"{analysis.analysis_id}:{horizon}",
                                      sha256=guards.sha256(item))
        auditor.write("thesis", violation.action, violation.rule, violation.version, subject, violation.detail,
                      horizon)


def audit_thesis(auditor: guards.Auditor | None, stage: str, t: Thesis, rejection: Rejection,
                 version: str = guards.BUILTIN_VERSION) -> None:
    """A built thesis refused later (a challenger's filter at its diff_ref, the one_live trigger), audited by its id
    and digest."""
    if auditor is not None:
        subject = guards.AuditSubject(kind="thesis", id=t.thesis_id, sha256=digest(t))
        auditor.write(stage, "reject", rejection.reason, version, subject, rejection.detail, t.horizon)


def validate(raw: object, analysis: Analysis, asked: tuple[str, ...], written: Written,
             playbook_ids: frozenset[str] | None = None, *, guard_ids: tuple[str, ...] = (),
             auditor: guards.Auditor | None = None) -> Checked:
    """Every reply item becomes a Thesis, a NoTrade or a Rejection with a reason; nothing is dropped silently.
    `playbook_ids` are the PLAYBOOK block's source ids for a thesis-2 reply, None for a prompt without the block.
    Each item goes through `guards.judge`: the built-in `ThesisRules`, then the thesis rules `guard_ids` names (an
    unknown id raises). With an `auditor` every Rejection and flag is audited; the grader's re-run passes none."""
    guards.resolve(guard_ids, "thesis")
    out = Checked([], [], [])

    def refuse(horizon: str, reason: str, detail: str, item: object, version: str = guards.BUILTIN_VERSION) -> None:
        out.rejected.append(Rejection(horizon, reason, detail))
        audit_item(auditor, analysis, horizon, item, guards.Violation(reason, version, "reject", detail))

    if not (isinstance(raw, dict) and isinstance(raw.get("theses"), list) and isinstance(raw.get("no_trade"), list)):
        refuse("-", "not_json_theses", "output needs 'theses' and 'no_trade' lists", raw)
        return out
    ctx = guards.ThesisContext(analysis, written, playbook_ids)
    seen: set[str] = set()
    for item in raw["theses"]:
        horizon = horizon_of(item)
        problem = horizon_problem(horizon, asked, seen)
        seen.add(horizon)
        if problem is not None:
            refuse(horizon, *problem, item)
            continue
        try:
            found = guards.judge(item, ctx, guard_ids)
            if found and found[-1].action == "reject":
                *flags, reject = found
                refuse(horizon, reject.rule, reject.detail, item, reject.version)
            else:
                flags = found
                out.theses.append(build(item, analysis, written))
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            refuse(horizon, "not_a_thesis", failure(exc), item)
            continue
        for flag in flags:
            audit_item(auditor, analysis, horizon, item, flag)
    for item in raw["no_trade"]:
        horizon = horizon_of(item)
        problem = horizon_problem(horizon, asked, seen)
        if problem:
            refuse(horizon, *problem, item)
            continue
        seen.add(horizon)
        try:
            out.no_trades.append(NoTrade(analysis_id=analysis.analysis_id, horizon=horizon,
                                         reason=str(item.get("reason")), created_at=written.created_at))
        except ValidationError as exc:  # a reason past the S1 bound
            refuse(horizon, "not_a_no_trade", failure(exc), item)
    for h in asked:
        if h not in seen:
            refuse(h, "horizon_missing", "no thesis and no no_trade", None)
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
        ids = expected.get("playbook")  # present only for a thesis-2 item
        checked = validate(sample.output_parsed, analysis, tuple(expected["horizons"]), written,
                           None if ids is None else frozenset(ids))
        failed = [r for r in checked.rejected if r.reason != "horizon_missing"]
        total = len(checked.theses) + len(failed)
        why = "; ".join(f"{r.horizon} {r.reason}: {r.detail}" for r in checked.rejected)
        return Score(value=len(checked.theses) / total if total else 1.0, explanation=why or None)


# ---------- prompt ----------

def source_block(analysis: Analysis, headlines: tuple[news.Headline, ...] = ()) -> str:
    """The analysis's SOURCES table as `analyze.render` writes it, rebuilt from the stored snapshot (same ids), plus
    the headline rows its claims cite, rendered by analyze (same cleaning, same ids)."""
    sources, rows = an.snapshot_rows(analysis.snapshot)
    ctx = an.Context(analysis.ticker, analysis.session, analysis.snapshot, sources, rows, headlines)
    return an.render(ctx).rsplit("\n\n", 1)[0]  # drop analyze's closing instruction


def cited_headlines(conn: sqlite3.Connection, analysis: Analysis, data_dir) -> tuple[news.Headline, ...]:
    """The stored headlines the analysis's claims cite, oldest first, so a thesis sees every row a claim stands on.
    An analysis whose prompt shows none reads nothing (its thesis prompt is unchanged); a cited headline missing from
    the news store is refused before the call."""
    if not an.shows_headlines(analysis.prompt_version):
        return ()
    cited = sorted({sid for claim in analysis.claims for sid in claim.source_ids})
    marks = ", ".join("?" * len(cited))
    wanted = {row[0] for row in conn.execute(
        f"SELECT source_id FROM source_ref WHERE kind = 'news' AND source_id IN ({marks})", cited)}
    stored = news.headlines_for(data_dir, analysis.ticker, analysis.session)
    found = tuple(h for h in stored if news.source_ref(h).source_id in wanted)
    if missing := sorted(wanted - {news.source_ref(h).source_id for h in found}):
        raise SystemExit(f"{analysis.analysis_id} cites headline(s) {', '.join(missing)} that are not in the news "
                         f"store ({data_dir}/news/{analysis.ticker}/); the thesis would not see them")
    return found


def cited_in(analysis: Analysis, headlines: tuple[news.Headline, ...]) -> tuple[news.Headline, ...]:
    """The given headlines the analysis's claims cite, in their order: the in-memory twin of `cited_headlines` for the
    pipeline arm (GUARDS-SPIKE §8.5), whose injected rows are never in the news store."""
    cited = {sid for claim in analysis.claims for sid in claim.source_ids}
    return tuple(h for h in headlines if news.source_ref(h).source_id in cited)


def render(analysis: Analysis, asked: tuple[str, ...], playbook_block: str | None = None,
           headlines: tuple[news.Headline, ...] = ()) -> str:
    """The thesis user turn; a thesis-2 call gets the PLAYBOOK block after the horizons, before the closing line."""
    close, atr = analysis.snapshot.values["close"], analysis.snapshot.values["atr_14"]
    lines = [source_block(analysis, headlines), "", "CLAIMS (claim_id | tag | text | cites)"]
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
    if playbook_block is not None:
        lines += ["", playbook_block]
    lines += ["", "Write the JSON with the keys \"theses\" and \"no_trade\"."]
    return "\n".join(lines)


def input_hash(analysis: Analysis, asked: tuple[str, ...], prompt_version: str,
               playbook_digest: str | None = None, *, guard_ids: tuple[str, ...] = ()) -> str:
    """The playbook digest joins only when a block was shown, so every thesis-1 hash is unchanged; a guards list joins
    as sorted `id@version` tags only when non-empty (GUARDS-SPIKE §8.2)."""
    fields = {"analysis_id": analysis.analysis_id, "analysis_input": analysis.input_hash,
              "horizons": list(asked), "prompt_version": prompt_version}
    if playbook_digest is not None:
        fields |= {"playbook": playbook_digest}
    if guard_ids:
        fields |= {"guards": an.guard_versions(guard_ids)}
    return digest(fields)


def playbook_for(conn: sqlite3.Connection, analysis: Analysis, prompt_version: str,
                 playbook: Playbook | None) -> tuple[str, list[SourceRef]] | None:
    """The PLAYBOOK block and its sources for a thesis-2 call: the given playbook, else the champion's as of the
    analysed session (what was closed by then). None for a prompt without the block, which refuses a playbook."""
    if prompt_version not in PLAYBOOK_PROMPTS:
        if playbook is not None:
            raise ValueError(f"prompt {prompt_version} shows no playbook (only {', '.join(PLAYBOOK_PROMPTS)} do)")
        return None
    from . import playbook as pb  # imported here: playbook -> report -> daily -> thesis is an import cycle
    return pb.prompt_block(playbook if playbook is not None else pb.compute(conn, analysis.session))


# ---------- the command ----------

@dataclass
class Result:
    checked: Checked
    spent_usd: float
    run_path: str
    trace_path: str


def call_settings(model: str, prompt_version: str = DEFAULT_PROMPT) -> CallSettings:
    schema = PLAYBOOK_SCHEMA if prompt_version in PLAYBOOK_PROMPTS else OUTPUT_SCHEMA
    return CallSettings(model=model, max_output_tokens=3000, output_mode="schema", json_schema=schema)


def item_for(analysis: Analysis, asked: tuple[str, ...], arm: str,
             playbook: tuple[str, list[SourceRef]] | None = None,
             headlines: tuple[news.Headline, ...] = ()) -> DatasetItem:
    """One analysis as a gigai-core dataset item; `expected` holds what ThesesValid needs to re-run the checks
    (the playbook ids only when the block is shown, so a thesis-1 item is unchanged)."""
    expected = {"analysis": analysis.model_dump_json(), "horizons": list(asked), "arm": arm}
    if playbook is not None:
        expected["playbook"] = [s.source_id for s in playbook[1]]
    return DatasetItem(id=f"{analysis.ticker}:{analysis.session}:{arm}", cluster_id=analysis.ticker,
                       prompt=render(analysis, asked, None if playbook is None else playbook[0], headlines),
                       tags=(analysis.ticker, arm), expected=expected)


def terms_class(model: str) -> str:
    return "restricted" if model.startswith("anthropic/") else "unknown"


def store(conn: sqlite3.Connection, checked: Checked, auditor: guards.Auditor | None = None) -> Checked:
    """Each accepted thesis with its PROPOSED event in one transaction; the one_live trigger is the last guard, and
    a thesis it refuses is audited when the call has an auditor."""
    kept: list[Thesis] = []
    for t in checked.theses:
        written = Event(event_id=new_id("ev"), subject_id=t.thesis_id, state="PROPOSED", at=t.created_at,
                        recorded_at=datetime.now(UTC), price=None, reason="written", bars_source_id=None,
                        rules_version=RULES_VERSION)
        try:
            journal.add(conn, t, written)
            kept.append(t)
        except sqlite3.IntegrityError as exc:
            rejection = Rejection(t.horizon, "one_live", str(exc))
            checked.rejected.append(rejection)
            audit_thesis(auditor, "store", t, rejection)
    journal.add(conn, *checked.no_trades)
    return Checked(kept, checked.no_trades, checked.rejected)


def filtered(checked: Checked, post: Callable[[Checked], Checked], auditor: guards.Auditor,
             version: str = guards.BUILTIN_VERSION) -> Checked:
    """A challenger rule's filter (rules.py) applied, each thesis it drops audited at `version` (its diff_ref)."""
    out = post(checked)
    by_horizon = {t.horizon: t for t in checked.theses}
    for rejection in out.rejected[len(checked.rejected):]:
        audit_thesis(auditor, "thesis", by_horizon[rejection.horizon], rejection, version)
    return out


def thesis(conn: sqlite3.Connection, analysis: Analysis, provider, *, asked: tuple[str, ...], arm: str, model: str,
           max_usd: float, prices: dict, data_dir, prompt_version: str = DEFAULT_PROMPT,
           terms: str | None = None, post: Callable[[Checked], Checked] | None = None,
           playbook: Playbook | None = None, guard_ids: tuple[str, ...] = (),
           post_version: str = guards.BUILTIN_VERSION) -> Result:
    """One model call, checked and stored; `terms` None means `terms_class(model)`, the teacher arm passes trainable.
    `post` is a challenger rule's filter (rules.py), applied before the store because stored theses never go away;
    `post_version` (its diff_ref) is the version its drops are audited at. `playbook` is for thesis-2 only (default:
    computed from the journal, see `playbook_for`). `guard_ids` names the learner's thesis guards (none by default);
    every rejection is audited in `<data_dir>/audit.jsonl`."""
    guards.resolve(guard_ids, "thesis")  # an unknown guard: refused before the call
    shown = playbook_for(conn, analysis, prompt_version, playbook)
    item = item_for(analysis, asked, arm, shown, cited_headlines(conn, analysis, data_dir))  # refusal: before the call
    run = run_eval(Dataset.of("thesis", [item]), provider, [ThesesValid()],
                   settings=call_settings(model, prompt_version),
                   budget=CallBudget(max_usd=max_usd, prices=prices), system=an.system_prompt(prompt_version),
                   trace_dir=data_dir / "traces", tag=prompt_version)
    run_path = an.save(run, data_dir)
    sample = run.samples[0]
    if sample.outcome != "succeeded":
        raise SystemExit(f"model call failed: {sample.error.code if sample.error else '?'} (run {run_path})")
    route = provider.route_for(item.prompt) if hasattr(provider, "route_for") else "unknown"
    if (terms or terms_class(model)) == "trainable" and not clean_route(route):
        raise SystemExit(f"route lost provenance ({route}): a trainable thesis needs one known provider ({run_path})")
    written = Written(arm, datetime.now(UTC), sample.trace_id, route, terms or terms_class(model),
                      input_hash(analysis, asked, prompt_version, None if shown is None else digest(shown[0]),
                                 guard_ids=guard_ids))
    ids = None if shown is None else frozenset(s.source_id for s in shown[1])
    auditor = guards.Auditor(data_dir, analysis.ticker, analysis.session, run.record.run_id, arm, guard_ids,
                             written.input_hash)
    checked = validate(sample.output_parsed, analysis, asked, written, ids, guard_ids=guard_ids, auditor=auditor)
    checked = store(conn, checked if post is None else filtered(checked, post, auditor, post_version), auditor)
    return Result(checked, run.record.spent_usd, str(run_path), str(run.record.trace_path))
