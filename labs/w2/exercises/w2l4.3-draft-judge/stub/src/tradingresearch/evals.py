"""The eval registry: every grader an experiment config can name. A new grader is a `@grader` class plus a test."""

from __future__ import annotations

import re
from collections.abc import Callable

from gigai_core.graders.protocol import CannotGrade
from gigai_core.score import Score
from pydantic import ValidationError

from . import checks, thesis as th
from .analyze import ClaimsValid, snapshot_rows, validate_claims
from .records import Analysis, Thesis


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


# TODO(w2l4.3) the draft P1 judge: a @grader class P1Judge with id "p1_judge", version "1", kind "model" and
#   validated = False. Nobody has checked a judge's verdicts against human labels yet, so its grade makes no model
#   call: it refuses with CannotGrade, saying why: it is a draft (no model call until closed trades in week 3).
#   Spec: evals/specs/p1_judge.md.


def graders(names: list[str]) -> list:
    unknown = [name for name in names if name not in GRADERS]
    if unknown:
        raise SystemExit(f"unknown grader(s) {unknown}; registered: {sorted(GRADERS)}")
    return [GRADERS[name]() for name in names]
