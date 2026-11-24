"""The eval registry: every grader an experiment config can name. A new grader is a class here plus a test."""

from __future__ import annotations

import re

from gigai_core.graders.protocol import CannotGrade
from gigai_core.score import Score

from .analyze import ClaimsValid, validate_claims


class Parsed:
    """1 if the reply parsed against the output schema, else 0."""

    id = "parsed"
    version = "1"
    kind = "code"

    def grade(self, sample, expected) -> Score:
        return Score(value=1.0 if sample.parse_status == "ok" else 0.0, explanation=sample.parse_status)


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


# TODO(w1l3.6) register InferencesGrounded, so experiment configs and graders() can name it.
GRADERS = {grader.id: grader for grader in (Parsed, ClaimsValid, AllClaimsValid)}


def graders(names: list[str]) -> list:
    unknown = [name for name in names if name not in GRADERS]
    if unknown:
        raise SystemExit(f"unknown grader(s) {unknown}; registered: {sorted(GRADERS)}")
    return [GRADERS[name]() for name in names]
