"""Week-7 guards (GUARDS-SPIKE §7.2, §1.2, §3.3): the rule registry the learner's detectors plug into, the text
normaliser `analyze.one_line` runs first, and the one writer of `<data_dir>/audit.jsonl`.

A rule is a small class with an id, a version, a stage and an action. `fetched` rules see one untrusted row after
`normalise` and may flag or drop it (`scan`); `thesis` rules see one reply item and may flag or reject it (`judge`).
The built-in thesis rule (`thesis.ThesisRules`, today's `check_thesis`) always runs; a learner rule runs only when a
guards list names it. Every decision a caller takes on a violation is written to the audit log as ids and digests,
never the untrusted text itself.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Literal, Protocol

from gigai_core import CoreModel
from pydantic import AwareDatetime, StringConstraints, ValidationError

from .hashing import new_id

if TYPE_CHECKING:
    from .records import Analysis
    from .thesis import Written

Stage = Literal["fetched", "thesis"]
Action = Literal["flag", "drop", "reject"]
ACTIONS: dict[str, tuple[str, ...]] = {"fetched": ("flag", "drop"), "thesis": ("flag", "reject")}
BUILTIN_VERSION = "1"  # version of the checks thesis.py runs outside a registered rule (horizon, not_a_thesis, ...)
AUDIT_FILE = "audit.jsonl"
DETAIL_CHARS = 160
MAX_MARKS = 2  # combining marks kept on one base character (§1.2: 50 stacked marks fit the 200-character cap)
BARS = {"\u2502": "/", "\u2223": "/", "\u01c0": "/"}  # look like `|`, which NFKC does not fold them to
# Cyrillic and Greek letters drawn like an ASCII letter (Unicode confusables, the common subset). NFKC keeps them, so
# "ignоre" with a Cyrillic о would slip past an ASCII pattern. Turkish ı and Latin ɡ are real letters, not listed.
LOOKALIKES = str.maketrans(
    "АВЕКМНОРСТХЅІЈԚԜҮаеорсухѕіјԁԛԝһΑΒΕΖΗΙΚΜΝΟΡΤΥΧον",
    "ABEKMHOPCTXSIJQWYaeopcyxsijdqwhABEZHIKMNOPTYXov",
)
LOOKALIKE_CHARS = frozenset(chr(c) for c in LOOKALIKES)
WORD = re.compile(r"[^\W\d_]+")


def _latin(match: re.Match[str]) -> str:
    """A mixed-script word (at least one ASCII letter, the rest ASCII or lookalikes) read as the Latin it shows; a
    word with no ASCII letter (СССР, ΚΑΙ) is left as written."""
    word = match.group()
    if any(c.isascii() for c in word) and all(c.isascii() or c in LOOKALIKE_CHARS for c in word):
        return word.translate(LOOKALIKES)
    return word


def normalise(text: str) -> str:
    """Untrusted text folded to what it looks like (§1.2): NFKC (fullwidth `｜` to `|`, Hangul fillers to U+1160),
    curly quotes to `'`, divider bars to `/`, at most two combining marks per letter, and lookalike letters to Latin in
    a mixed-script word (one with an ASCII letter). Invisible characters are `analyze.one_line`'s job."""
    out: list[str] = []
    marks = 0
    for c in unicodedata.normalize("NFKC", text):
        category = unicodedata.category(c)
        marks = marks + 1 if category in ("Mn", "Me") else 0
        if marks <= MAX_MARKS:
            out.append("'" if category in ("Pi", "Pf") else BARS.get(c, c))
    return WORD.sub(_latin, "".join(out))


@dataclass(frozen=True)
class Fetched:
    """One untrusted row as the model would see it, its text already through `normalise`."""

    kind: Literal["headline", "filing_chunk"]
    source_id: str
    text: str
    ticker: str
    session: date


@dataclass(frozen=True)
class ThesisContext:
    """What a thesis rule may read besides the reply item (`thesis.validate` builds it)."""

    analysis: Analysis
    written: Written
    playbook_ids: frozenset[str] | None


@dataclass(frozen=True)
class Violation:
    """One rule hit. `detail` is written by the rule, never the untrusted text; the audit keeps 160 characters."""

    rule: str
    version: str
    action: Action
    detail: str


class Rule(Protocol):
    """A guard: `check` gets a Fetched row (ctx None) or a reply item dict (ctx a ThesisContext)."""

    id: ClassVar[str]
    version: ClassVar[str]
    stage: ClassVar[Stage]
    action: ClassVar[Action]

    def check(self, subject: Any, ctx: Any) -> Violation | None: ...


RULES: dict[str, type[Rule]] = {}
BUILTIN: list[str] = []


def rule[R: type[Rule]](cls: R) -> R:
    """Register a rule class under its id; a duplicate id, an unknown stage or an action its stage cannot take raises."""
    if cls.id in RULES:
        raise ValueError(f"guard rule {cls.id!r} is already registered")
    if cls.stage not in ACTIONS:
        raise ValueError(f"guard rule {cls.id!r}: stage must be one of {', '.join(ACTIONS)}, got {cls.stage!r}")
    if cls.action not in ACTIONS[cls.stage]:
        raise ValueError(f"guard rule {cls.id!r}: a {cls.stage} rule may {' or '.join(ACTIONS[cls.stage])}, "
                         f"not {cls.action!r}")
    RULES[cls.id] = cls
    return cls


def builtin[R: type[Rule]](cls: R) -> R:
    """Register a shipped rule that always runs at its stage; no guards list turns it off."""
    rule(cls)
    BUILTIN.append(cls.id)
    return cls


def resolve(ids: Sequence[str], stage: Stage) -> list[Rule]:
    """The rules a guards list names, in order; an unknown id or one of another stage raises before any call."""
    unknown = [i for i in ids if i not in RULES]
    if unknown:
        raise ValueError(f"unknown guard rule(s) {', '.join(unknown)}; registered: {', '.join(sorted(RULES))}")
    wrong = [i for i in ids if RULES[i].stage != stage]
    if wrong:
        raise ValueError(f"guard rule(s) {', '.join(wrong)} are not {stage} rules")
    return [RULES[i]() for i in ids]


def scan(rows: Iterable[Fetched], ids: Sequence[str]) -> tuple[list[Fetched], list[tuple[Fetched, Violation]]]:
    """Each row through the named fetched rules: a drop hit removes it, a flag keeps it; every hit comes back with its
    row so the caller can audit it."""
    rules = resolve(ids, "fetched")
    kept: list[Fetched] = []
    hits: list[tuple[Fetched, Violation]] = []
    for row in rows:
        found = [v for r in rules if (v := r.check(row, None)) is not None]
        hits += [(row, v) for v in found]
        if not any(v.action == "drop" for v in found):
            kept.append(row)
    return kept, hits


def judge(item: Any, ctx: ThesisContext, ids: Sequence[str] = ()) -> list[Violation]:
    """The built-in thesis rules, then the named ones, in order: flags collect and the first reject ends the list, so a
    rejected item's reject is its last violation. The caller audits them all."""
    names = [i for i in BUILTIN if RULES[i].stage == "thesis"] + [i for i in ids if i not in BUILTIN]
    found: list[Violation] = []
    for r in resolve(names, "thesis"):
        violation = r.check(item, ctx)
        if violation is not None:
            found.append(violation)
            if violation.action == "reject":
                break
    return found


def sha256(value: Any) -> str:
    """`sha256:<hex>` of any parsed reply value; plain sorted JSON, since canonical JSON refuses some reply values."""
    text = json.dumps(value, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


SAFE_ID = re.compile(r"(cl|pb)_[0-9a-f]{16}")  # claim and playbook ids: hex only, so they cannot carry words


def shown_id(value: object) -> str:
    """A reply-written id as detail text: a well-formed claim or playbook id as is, anything else as a digest prefix."""
    text = str(value)
    return text if SAFE_ID.fullmatch(text) else sha256(text)[:19]


Detail = Annotated[str, StringConstraints(max_length=DETAIL_CHARS)]


class AuditSubject(CoreModel):
    """What a decision was about: an id and a digest, never the text."""

    kind: Literal["thesis_item", "thesis", "headline", "filing_chunk", "span"]
    id: str
    sha256: str


class AuditRecord(CoreModel):
    """One line of audit.jsonl (§3.3)."""

    audit_id: str
    at: AwareDatetime
    stage: Literal["fetched", "thesis", "store", "redact"]
    decision: Literal["reject", "flag", "drop", "redact"]
    rule: str
    rule_version: str
    subject: AuditSubject
    ticker: str | None
    session: date | None
    horizon: str | None
    run_id: str | None
    arm: str | None
    guards: tuple[str, ...]
    input_hash: str | None
    detail: Detail


def audit(record: AuditRecord, data_dir: Path) -> None:
    """Append one line to `<data_dir>/audit.jsonl`, opened and closed per line so a later crash keeps it."""
    path = Path(data_dir) / AUDIT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json() + "\n")


def read_audit(data_dir: Path) -> tuple[list[AuditRecord], int]:
    """Every readable audit line, oldest first, and the count of lines that do not parse (a write torn by a crash);
    a missing file is an empty log."""
    path = Path(data_dir) / AUDIT_FILE
    if not path.exists():
        return [], 0
    records, bad = [], 0
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                records.append(AuditRecord.model_validate_json(line))
            except ValidationError:
                bad += 1
    return records, bad


@dataclass(frozen=True)
class Auditor:
    """The fields every audit line of one call shares; `write` adds the per-decision part and appends the line."""

    data_dir: Path
    ticker: str | None = None
    session: date | None = None
    run_id: str | None = None
    arm: str | None = None
    guards: tuple[str, ...] = ()
    input_hash: str | None = None

    def write(self, stage: str, decision: str, rule: str, version: str, subject: AuditSubject, detail: str,
              horizon: str | None = None) -> AuditRecord:
        """Append one decision; the detail is cut to 160 characters. A failed write warns on stderr and carries on:
        the paid call's theses are stored after it."""
        record = AuditRecord(
            audit_id=new_id("au"), at=datetime.now(UTC), stage=stage, decision=decision, rule=rule,  # type: ignore[arg-type]
            rule_version=version, subject=subject, ticker=self.ticker, session=self.session, horizon=horizon,
            run_id=self.run_id, arm=self.arm, guards=self.guards, input_hash=self.input_hash,
            detail=detail[:DETAIL_CHARS])
        try:
            audit(record, self.data_dir)
        except OSError as exc:
            print(f"warning: audit line not written ({type(exc).__name__}: {exc.strerror or exc}); {rule} {decision} "
                  f"on {subject.id} kept going", file=sys.stderr)
        return record
