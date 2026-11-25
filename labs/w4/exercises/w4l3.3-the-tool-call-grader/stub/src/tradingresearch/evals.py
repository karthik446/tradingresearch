"""The eval registry: every grader an experiment config can name. A new grader is a `@grader` class plus a test.

`p1_judge` is the P1 judge on one closed trade (SPIKE §7.2 row P1, ADR-003, evals/specs/p1_judge.md); it runs
from `tr grade --judge`, not from an experiment config.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from gigai_core import CallBudget, CallSettings, Dataset, DatasetItem, run as run_eval
from gigai_core.budget import Price
from gigai_core.graders.judge import last_json_object, llm_judge
from gigai_core.graders.protocol import CannotGrade
from gigai_core.providers import Turn
from gigai_core.sample import Sample
from gigai_core.score import JudgeNote, Score, ScoreRecord
from gigai_core.trace import ModelExchange
from pydantic import ValidationError

from . import analyze as an, checks, journal, label, thesis as th
from .analyze import ClaimsValid, snapshot_rows, validate_claims
from .hashing import new_id
from .reconcile_run import BarSource
from .records import Analysis, Thesis
from .tools import TOOLS

RUBRICS = Path(__file__).resolve().parents[2] / "evals" / "rubrics"
JUDGE_MODEL = "openai/gpt-6-sol"  # ADR-003: a different vendor from the thesis writer
JUDGE_MAX_TOKENS = 4000  # ADR-003 estimates about 500 output tokens per trade; this bounds a runaway reply


GRADERS: dict[str, type] = {}


def grader(cls: type) -> type:
    """Register a grader class under its `id`; a duplicate id would silently shadow a grader, so it raises."""
    if cls.id in GRADERS:
        raise ValueError(f"grader id {cls.id!r} is already registered by {GRADERS[cls.id].__name__}")
    GRADERS[cls.id] = cls
    return cls


@grader
class Parsed:
    """1 if the reply parsed against the output schema, else 0."""

    id = "parsed"
    version = "1"
    kind = "code"

    def grade(self, sample, expected) -> Score:
        return Score(value=1.0 if sample.parse_status == "ok" else 0.0, explanation=sample.parse_status)


grader(ClaimsValid)  # defined in analyze.py beside validate_claims


@grader
class AllClaimsValid:
    """1 if every claim in the reply passes validate_claims, else 0. Binary, so compare uses McNemar."""

    id = "all_claims_valid"
    version = "1"
    kind = "code"

    def grade(self, sample, expected) -> Score:
        if sample.parse_status != "ok":
            raise CannotGrade("output did not parse")
        _, rejected = validate_claims(sample.output_parsed, expected["values"], "an_grade")
        return Score(value=0.0 if rejected else 1.0, explanation=", ".join(sorted({r.reason for r in rejected})) or None)


@grader
class InferencesGrounded:
    """1 if every inference names only indicators its parents cite (through derived_from, recursively), else 0.

    Spec: evals/specs/inferences_grounded.md. Only table names with an underscore count (sma_20, high_20), so plain
    words such as "close" never match; dist_<name>_atr in a parent also grounds <name>.
    """

    id = "inferences_grounded"
    version = "1"
    kind = "code"

    def grade(self, sample, expected) -> Score:
        if sample.parse_status != "ok":
            raise CannotGrade("output did not parse")
        names: dict[str, str] = expected["names"]
        claims = {c.get("id"): c for c in sample.output_parsed.get("claims", []) if isinstance(c, dict)}
        vocab = sorted({name for name in names.values() if "_" in name}, key=len, reverse=True)

        def cited(claim_id: str, seen: frozenset = frozenset()) -> set[str]:
            claim = claims.get(claim_id)
            if claim is None or claim_id in seen:
                return set()
            found = {names.get(source, "") for source in claim.get("source_ids") or []}
            found |= {name[5:-4] for name in found if name.startswith("dist_") and name.endswith("_atr")}
            for parent in claim.get("derived_from") or []:
                found |= cited(parent, seen | {claim_id})
            return found

        ungrounded = []
        for claim_id, claim in claims.items():
            if claim.get("tag") != "inference":
                continue
            allowed = set().union(*(cited(parent) for parent in claim.get("derived_from") or []))
            words = f"{claim.get('text') or ''} {claim.get('steps') or ''}"
            used = {name for name in vocab if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", words)}
            if extra := sorted(used - allowed):
                ungrounded.append(f"{claim_id}: {', '.join(extra)}")
        return Score(value=0.0 if ungrounded else 1.0, explanation="; ".join(ungrounded) or None)


@grader
class ToolCallsOk:
    """1 if the tool loop used its tools cleanly, else 0 with the first fault: tool_error, repeated_call or
    too_many_calls. No tool calls (the fixed arm) is 1.0, so `compare` does not drop the grader for a missing arm."""

    id = "tool_calls_ok"
    version = "1"
    kind = "code"
    # TODO(w4l3.3) the cap: every tool once plus one follow-up each (tools.TOOLS); more is a loop, not a lookup.
    max_calls = 0

    def grade(self, sample, expected) -> Score:
        spans = sample.tool_spans
        # TODO(w4l3.3) walk the calls in order and stop at the first fault, value 0.0 with the reason first:
        #   tool_error (the call raised, or its result is an {"error": ...} object, parsed or as JSON text),
        #   repeated_call (the same tool with the same arguments, compared after key order and spacing),
        #   then too_many_calls past max_calls. A clean loop, or none at all, is 1.0.
        return Score(value=1.0, explanation=f"{len(spans)} tool calls")


def built_theses(sample, expected) -> tuple[Analysis, list[Thesis]]:
    """The items of a thesis-run sample that build into a Thesis (`thesis.build`), with their analysis. A P2-P4 check
    needs a whole thesis, so an item that does not build is not graded here (`theses_valid` counts it)."""
    if sample.parse_status != "ok":
        raise CannotGrade("output did not parse")
    analysis = Analysis.model_validate_json(expected["analysis"])
    written = th.Written(expected["arm"], sample.recorded_at, sample.trace_id, "grade", "unknown", "grade")
    items = sample.output_parsed.get("theses") if isinstance(sample.output_parsed, dict) else None
    built = []
    for item in items if isinstance(items, list) else []:
        try:
            built.append(th.build(item, analysis, written))
        except (ValidationError, KeyError, TypeError, ValueError):
            continue
    if not built:
        raise CannotGrade("no item builds into a thesis")
    return analysis, built


def every_thesis(theses: list[Thesis], passes: Callable[[Thesis], bool]) -> Score:
    """1 if every thesis passes, else 0 (binary, so compare uses McNemar); the explanation names the failing horizons."""
    failed = [t.horizon for t in theses if not passes(t)]
    return Score(value=0.0 if failed else 1.0, explanation=f"fails: {', '.join(failed)}" if failed else None)


@grader
class EvidenceValid:
    """P2: every evidence id is a fact or inference whose numbers match the thesis prompt's source table.

    Spec: evals/specs/p2_evidence_valid.md. The table is the snapshot rows only, so a fact citing only EDGAR fails.
    """

    id = "p2_evidence_valid"
    version = "1"
    kind = "code"

    def grade(self, sample, expected) -> Score:
        analysis, theses = built_theses(sample, expected)
        values = {row.source_id: row.value for row in snapshot_rows(analysis.snapshot)[1]}
        return every_thesis(theses, lambda t: checks.p2_evidence_valid(t, analysis.claims, values))


@grader
class InvalidationTestable:
    """P3: the invalidation price lies between entry and stop. Spec: evals/specs/p3_invalidation_testable.md."""

    id = "p3_invalidation_testable"
    version = "1"
    kind = "code"

    def grade(self, sample, expected) -> Score:
        analysis, theses = built_theses(sample, expected)
        close = analysis.snapshot.values["close"]
        return every_thesis(theses, lambda t: checks.p3_invalidation_testable(t, close))


@grader
class LevelsCoherent:
    """P4: stop beyond the nearest level, target at or before the next one. Spec: evals/specs/p4_levels_coherent.md."""

    id = "p4_levels_coherent"
    version = "1"
    kind = "code"

    def grade(self, sample, expected) -> Score:
        analysis, theses = built_theses(sample, expected)
        snap = analysis.snapshot
        return every_thesis(theses, lambda t: checks.p4_levels_coherent(t, snap.levels, snap.values["atr_14"],
                                                                       snap.values["close"]))


@grader
class P1Judge:
    """P1, did the mechanism in `reason` happen: registered but unvalidated (evals/specs/p1_judge.md).

    The judge runs on closed trades through `p1_judge` below (gigai-core `llm_judge` with
    evals/rubrics/p1_thesis_quality.md); `validated` turns True only by an ADR that records kappa on the operator's
    labels (SPIKE §7.3).
    """

    id = "p1_judge"
    version = "1"
    kind = "model"
    validated = False

    def grade(self, sample, expected) -> Score:
        raise CannotGrade("p1_judge is a draft judge of closed trades (`tr grade --judge`), not of experiment samples")


def p1_verdict(reply: str) -> tuple[str, str]:
    """(verdict, reason) by the rubric's "Verdict format": the last JSON object wins, `unknown` becomes `fail` with
    `unknown: ` (ADR-003). A reply with no verdict is CannotGrade, not an abstain."""
    verdict = last_json_object(reply, "verdict")
    if verdict not in ("pass", "fail", "unknown"):
        raise CannotGrade(f"the judge's reply has no pass/fail/unknown verdict: {reply[:200]!r}")
    explanation = last_json_object(reply, "explanation")
    reason = explanation if isinstance(explanation, str) else ""
    if verdict == "unknown":
        return "fail", reason if reason.startswith("unknown:") else f"unknown: {reason}"
    return verdict, reason


def judged_sample(t: Thesis, shown: str) -> Sample:
    """What `llm_judge` renders: INPUT is the cited claims and the summary, OUTPUT the thesis text (prompt file)."""
    return Sample(trace_id=f"tr_{t.thesis_id}", run_id=P1Judge.id, item_id=t.thesis_id, item_version="1",
                  cluster_id=t.ticker, repeat_index=0, input=(Turn(role="user", content=shown),),
                  output_text=f"prediction: {t.prediction}\nreason: {t.reason}\ninvalidation_text: {t.invalidation_text}",
                  output_parsed=None, parse_status="not_parsed", outcome="succeeded", error=None,
                  recorded_at=datetime.now(UTC))


def p1_judge(conn: sqlite3.Connection, bars: BarSource, thesis_id: str, provider, *, prices: dict[str, Price],
             data_dir: Path, max_usd: float) -> Score:
    """Judge one graded champion or challenger thesis with one call; store its verdict and ScoreRecord together.

    Teacher theses and theses with no Grade (never entered, not closed) are CannotGrade before any call. A failed
    call or a reply with no verdict is CannotGrade after it: the cost is in the run file, nothing is stored."""
    try:
        t, g = label.labelable(conn, thesis_id)
    except label.Refused as exc:
        raise CannotGrade(str(exc)) from None
    analysis = journal.get(conn, Analysis, t.analysis_id)
    shown = "\n".join(["cited claims (claim_id | tag | text)", *label.cited(analysis, t.evidence), "",
                       "post-trade summary (code-written)", label.summary(conn, bars, t, g)])
    rubric = (RUBRICS / "p1_judge_prompt.txt").read_text().replace("{rubric}",
                                                                   (RUBRICS / "p1_thesis_quality.md").read_text())
    settings = CallSettings(model=JUDGE_MODEL, max_output_tokens=JUDGE_MAX_TOKENS)
    judge = llm_judge(provider, rubric=rubric, settings=settings, grader_id=P1Judge.id)
    item = DatasetItem(id=t.thesis_id, cluster_id=t.ticker, prompt=judge.render(judged_sample(t, shown), None),
                       expected=None)
    run = run_eval(Dataset.of(P1Judge.id, [item]), provider, [], settings=settings,
                   budget=CallBudget(max_usd=max_usd, prices=prices), trace_dir=data_dir / "traces", tag=P1Judge.id)
    run_path = an.save(run, data_dir)
    sample = run.samples[0]
    if sample.outcome != "succeeded":
        raise CannotGrade(f"judge call failed: {sample.error.code if sample.error else '?'} (run {run_path})")
    verdict, reason = p1_verdict(sample.output_text)
    spans = sample.model_spans
    calls = tuple(ModelExchange(**{name: getattr(span, name) for name in ModelExchange.model_fields}) for span in spans)
    score = Score(value=1.0 if verdict == "pass" else 0.0, explanation=reason, answer=verdict,
                  judge=JudgeNote(model=JUDGE_MODEL, prompt_sha256=judge.prompt_sha256, calls=calls))
    record = ScoreRecord(score_id=new_id("sc"), trace_id=sample.trace_id, grader_id=P1Judge.id,
                         grader_version=P1Judge.version, kind="model", value=score.value, explanation=reason,
                         judge_model=JUDGE_MODEL, judge_prompt_sha256=judge.prompt_sha256,
                         judge_span_ids=tuple(span.span_id for span in spans), recorded_at=datetime.now(UTC))
    journal.add_judge_score(conn, t.thesis_id, record, verdict, reason)
    return score


def graders(names: list[str]) -> list:
    unknown = [name for name in names if name not in GRADERS]
    if unknown:
        raise SystemExit(f"unknown grader(s) {unknown}; registered: {sorted(GRADERS)}")
    return [GRADERS[name]() for name in names]
