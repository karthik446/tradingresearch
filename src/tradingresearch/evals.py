"""The eval registry: every grader an experiment config can name. A new grader is a class here plus a test."""

from __future__ import annotations

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


GRADERS = {grader.id: grader for grader in (Parsed, ClaimsValid, AllClaimsValid)}


def graders(names: list[str]) -> list:
    unknown = [name for name in names if name not in GRADERS]
    if unknown:
        raise SystemExit(f"unknown grader(s) {unknown}; registered: {sorted(GRADERS)}")
    return [GRADERS[name]() for name in names]
