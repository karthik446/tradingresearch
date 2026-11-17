"""`tr label`: the operator's blind P1 labels and the judge-agreement report (SPIKE §7.3, ADR-003,
`evals/specs/p1_judge.md`). No model call.

A label is a gigai-core LabelRecord (`blind=True`, item_id = thesis id) of a graded champion or challenger thesis:
the Grade holds the OutcomeGrade the post-trade summary needs. `show` prints the thesis, its cited claims and
grade.py's post-trade summary, never a judge verdict or an earlier label. A relabel is a new record pointing at the
one it replaces; the latest wins. `agree` pairs each latest label with the latest stored judge verdict by
judge_agreement's rules and reads kappa from gigai-core `agreement` (judge_agreement itself needs a gigai-core Run,
and stored verdicts are not one). Nothing here sets `validated`.

`--claims` (TRAINING-SPIKE §7.2 row 5, §7.4): the operator's blind ClaimLabels of teacher claims, the claim tagger's
reference labels (target (b), F15). `show_claim` prints the claim text with its value and the cited source rows, never
the model's tag, its derived_from/steps, a claims_valid verdict or an earlier label. One label per claim.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import get_args

from gigai_core.agreement import MIN_KAPPA, MIN_UNITS, agreement
from gigai_core.records import LabelRecord

from . import grade, journal, sessions
from .analyze import plain
from .hashing import digest, new_id
from .reconcile_run import BarSource
from .records import Analysis, Claim, ClaimLabel, ClaimTag, Grade, SourceRef, Thesis
from .report import graded

DATASET_ID = "p1_thesis_quality"  # the labels answer the P1 rubric's question
RUBRIC = "evals/rubrics/p1_thesis_quality.md"
VERDICTS = {"met": "met", "not_met": "not met", "unknown": "unknown"}  # CLI word -> rubric / gigai-core LabelValue
PROPOSED_N = 30  # ADR-003 step 2: agreement once 30 labels exist
WIDE_NOTE = ("ADR-003: with 30 labels the 95% half-width of kappa is about ±0.29, so a kappa of 0.6 means anywhere "
             "from about 0.31 to 0.89; the threshold separates a working judge from a broken one, it does not rank "
             "judges")


class Refused(Exception):
    """A thesis `show` or `add` will not take, with the reason."""


# ---------- reading ----------

def labels(conn: sqlite3.Connection) -> dict[str, LabelRecord]:
    """Each thesis's latest label (insertion order), keyed by thesis id."""
    rows = conn.execute("SELECT body FROM label ORDER BY rowid")
    return {record.item_id: record for record in (LabelRecord.model_validate_json(body) for (body,) in rows)}


def to_label(conn: sqlite3.Connection) -> list[Thesis]:
    """Graded champion and challenger theses with no label yet, oldest first."""
    rows = conn.execute("SELECT t.body FROM thesis t JOIN grade g USING (thesis_id) "
                        "WHERE t.arm IN ('champion', 'challenger') "
                        "AND NOT EXISTS (SELECT 1 FROM label l WHERE l.item_id = t.thesis_id) ORDER BY t.rowid")
    return [Thesis.model_validate_json(body) for (body,) in rows]


def labelable(conn: sqlite3.Connection, thesis_id: str) -> tuple[Thesis, Grade]:
    """The thesis and its Grade, or Refused: an unknown id, a teacher thesis, or a thesis `tr grade` has not graded
    (the post-trade summary needs the Grade's outcome)."""
    try:
        t = journal.get(conn, Thesis, thesis_id)
    except KeyError:
        raise Refused(f"no thesis {thesis_id}") from None
    if t.arm == "teacher":
        raise Refused(f"{thesis_id} is a teacher thesis: teacher theses are never judged or labelled (ADR-003)")
    g = graded(conn, thesis_id)
    if g is None:
        events = journal.events_for(conn, thesis_id)
        state = events[-1].state if events else "PROPOSED"
        raise Refused(f"{thesis_id} is {state} with no grade: only a CLOSED thesis that `tr grade` graded can be "
                      "labelled")
    return t, g


# ---------- list / show / add ----------

def render_list(conn: sqlite3.Connection) -> list[str]:
    """One line per thesis to label, then the counts; no verdict of any kind."""
    todo, done = to_label(conn), len(labels(conn))
    if not todo:
        return [f"nothing to label: no graded champion or challenger thesis without a label ({done} labelled)"]
    lines = [f"{t.ticker:<6} {t.horizon:<5} {t.arm:<10} {t.thesis_id}" for t in todo]
    return lines + [f"{len(todo)} to label, {done} labelled: `tr label show <thesis_id>`, then "
                    "`tr label add <thesis_id> met|not_met|unknown`"]


def summary(conn: sqlite3.Connection, bars: BarSource, t: Thesis, g: Grade) -> str:
    """grade.py's post-trade summary, over daily bars from 20 sessions before the fill to the exit."""
    events = journal.events_for(conn, t.thesis_id)
    fill_day, exit_day = (next(e for e in events if e.state == state).at.astimezone(sessions.NY).date()
                          for state in ("OPEN", "CLOSED"))
    daily = bars.daily(t.ticker, sessions.recent(21, fill_day)[0], exit_day)
    return grade.post_trade_summary(t, journal.get(conn, Analysis, t.analysis_id), events, daily, g.outcome)


def cited(analysis: Analysis, evidence: tuple[str, ...]) -> list[str]:
    """The thesis's evidence claims with their values filled in, as thesis.py's prompt writes them."""
    by_id = {c.claim_id: c for c in analysis.claims}
    lines = []
    for claim_id in evidence:
        c = by_id.get(claim_id)
        if c is None:
            lines.append(f"{claim_id} | missing from analysis {analysis.analysis_id}")
            continue
        text = c.text.replace("{value}", plain(c.value)) if c.value is not None else c.text
        lines.append(f"{c.claim_id} | {c.tag} | {text}" + (f" (steps: {c.steps})" if c.steps else ""))
    return lines


def show(conn: sqlite3.Connection, bars: BarSource, thesis_id: str) -> list[str]:
    """What the judge sees (p1_judge.md "Inputs"): the thesis text, its cited claims and the post-trade summary.
    Blind: no judge verdict and no earlier label, and nothing is recorded."""
    t, g = labelable(conn, thesis_id)
    return [f"{t.thesis_id} {t.ticker} {t.horizon} {t.direction} {t.setup_type} ({t.arm})",
            f"prediction: {t.prediction}", f"reason: {t.reason}",
            f"invalidation: {t.invalidation_text} ({plain(t.invalidation_price)})",
            "", "cited claims (claim_id | tag | text)", *cited(journal.get(conn, Analysis, t.analysis_id), t.evidence),
            "", "post-trade summary (code-written)", summary(conn, bars, t, g), "",
            f"blind: label it with `tr label add {t.thesis_id} met|not_met|unknown` (rubric {RUBRIC})"]


def add(conn: sqlite3.Connection, thesis_id: str, verdict: str, *, note: str | None = None, relabel: bool = False,
        now: datetime | None = None) -> LabelRecord:
    """Store one blind LabelRecord. A labelled thesis takes a new label only with `relabel`, which points at the
    latest one; a relabel of an unlabelled thesis is refused, so `relabel_of` is never empty on a relabel."""
    if verdict not in VERDICTS:
        raise Refused(f"verdict {verdict!r}: the P1 rubric's verdicts are {', '.join(VERDICTS)}")
    t, _ = labelable(conn, thesis_id)
    held = labels(conn).get(thesis_id)
    if held is not None and not relabel:
        raise Refused(f"{thesis_id} is already labelled ({held.label_id}); --relabel stores a new label that "
                      "replaces it")
    if held is None and relabel:
        raise Refused(f"{thesis_id} has no label to replace: drop --relabel")
    record = LabelRecord(
        label_id=new_id("lb"), dataset_id=DATASET_ID, item_id=thesis_id, item_version=digest(t),
        label=VERDICTS[verdict], source="human", recorded_at=now or datetime.now(UTC), critique=note, rubric=RUBRIC,
        who="operator", blind=True, relabel_of=held.label_id if held else None,
    )
    journal.add(conn, record)
    return record


# ---------- agree ----------

@dataclass(frozen=True)
class Pairing:
    """Latest labels against latest judge verdicts: the 0/1 pairs (human, judge) and what was left out."""

    pairs: tuple[tuple[int, int], ...]  # 1 = met (label) / pass (judge)
    decided: int  # theses whose latest label is met or not met
    unknown_labels: int  # latest label `unknown`: pairs with nothing (judge_agreement's rule)
    abstains: int  # decided labels whose judge verdict is `fail` with `unknown:`: left out (ADR-003)
    not_judged: int  # decided labels with no stored judge verdict
    unlabelled_verdicts: int  # judged theses without a label


def pairing(conn: sqlite3.Connection) -> Pairing:
    """Pair each thesis's latest label with its latest judge verdict; met / pass is 1."""
    held, judged = labels(conn), journal.judge_verdicts(conn)
    pairs: list[tuple[int, int]] = []
    unknown = abstains = not_judged = 0
    for thesis_id, label in held.items():
        verdict = judged.get(thesis_id)
        if label.label == "unknown":
            unknown += 1
        elif verdict is None:
            not_judged += 1
        elif journal.abstained(verdict):
            abstains += 1
        else:
            pairs.append((int(label.label == "met"), int(verdict["verdict"] == "pass")))
    return Pairing(tuple(pairs), len(held) - unknown, unknown, abstains, not_judged,
                   sum(thesis_id not in held for thesis_id in judged))


def render_agree(p: Pairing) -> list[str]:
    """n, kappa with its interval, raw agreement, ADR-003's wide-interval note and the PROPOSED thresholds; with
    fewer than 2 pairs, which side it is waiting for."""
    n = len(p.pairs)
    counts = (f"  labels: {p.decided} met/not met, {p.unknown_labels} unknown (left out); of the {p.decided}: "
              f"{n} paired, {p.abstains} judge unknown: (left out), {p.not_judged} not judged; "
              f"{p.unlabelled_verdicts} judged without a label")
    if n < 2:
        waiting = "awaiting labels" if p.decided < 2 else "awaiting judge verdicts"
        return [f"agree: {waiting} (n = {n} pairs; kappa needs at least 2)", counts]
    a = agreement(p.pairs)
    same = sum(human == judge for human, judge in p.pairs)
    descriptive = f" (descriptive: n < {PROPOSED_N} proposed labels)" if n < PROPOSED_N else ""
    if a.kappa is None:
        kappa = f"  kappa undefined: {a.kappa_undefined}"
    else:
        kappa = (f"  kappa {a.kappa.kappa:.2f}, 95% CI [{a.kappa.ci.lower:.2f}, {a.kappa.ci.upper:.2f}] "
                 f"(gigai-core cohen_kappa, large-sample){descriptive}")
    rates = "  judge pass rate on your met: " + (f"{a.tpr:.1%}" if a.tpr is not None else "n/a") + \
            "; judge fail rate on your not met: " + (f"{a.tnr:.1%}" if a.tnr is not None else "n/a")
    return [f"agree: n = {n} pairs", f"  raw agreement {same}/{n} = {same / n:.1%}", kappa, rates, counts,
            f"  note: {WIDE_NOTE}",
            f"  thresholds PROPOSED (ADR-003, operator decision Q1 pending; not applied): kappa >= {MIN_KAPPA} "
            f"(gigai-core MIN_KAPPA) on n = {PROPOSED_N} labels; gigai-core's own gate needs n >= {MIN_UNITS}",
            "  p1_judge stays validated = False: only an ADR that records the measured kappa changes it"]


# ---------- claims (TRAINING-SPIKE §7.2 row 5, §7.4) ----------

TAGS = get_args(ClaimTag)
CLAIM_ADD = ("`tr label --claims add <claim_id> --tag fact|inference|opinion [--supported|--unsupported] "
             "--labeller NAME`")


def claim_labels(conn: sqlite3.Connection) -> dict[str, ClaimLabel]:
    """Every claim label, keyed by claim id."""
    rows = conn.execute("SELECT body FROM claim_label ORDER BY rowid")
    return {record.claim_id: record for record in (ClaimLabel.model_validate_json(body) for (body,) in rows)}


def claims_to_label(conn: sqlite3.Connection) -> list[tuple[Claim, str, str]]:
    """Teacher claims with no label yet, oldest first, with their analysis's ticker and session."""
    rows = conn.execute("SELECT c.body, a.ticker, a.session FROM claim c JOIN analysis a USING (analysis_id) "
                        "WHERE a.arm = 'teacher' "
                        "AND NOT EXISTS (SELECT 1 FROM claim_label l WHERE l.claim_id = c.claim_id) ORDER BY c.rowid")
    return [(Claim.model_validate_json(body), ticker, session) for body, ticker, session in rows]


def teacher_claim(conn: sqlite3.Connection, claim_id: str) -> tuple[Claim, Analysis]:
    """The claim and its analysis, or Refused: an unknown id, or a claim of a main-arm analysis (its tags are Claude
    or GPT output and cannot train the tagger, TRAINING-SPIKE §7.1)."""
    try:
        c = journal.get(conn, Claim, claim_id)
    except KeyError:
        raise Refused(f"no claim {claim_id}") from None
    a = journal.get(conn, Analysis, c.analysis_id)
    if a.arm != "teacher":
        raise Refused(f"{claim_id} is from a {a.arm} analysis: claim labels are for teacher claims "
                      "(TRAINING-SPIKE §7.4)")
    return c, a


def render_claims_list(conn: sqlite3.Connection) -> list[str]:
    """One line per teacher claim to label, then n unlabelled and n labelled; no tag of any kind."""
    todo, done = claims_to_label(conn), len(claim_labels(conn))
    if not todo:
        return [f"nothing to label: no teacher claim without a claim label (0 unlabelled, {done} labelled)"]
    lines = [f"{ticker:<6} {session} {c.claim_id}" for c, ticker, session in todo]
    return lines + [f"{len(todo)} unlabelled, {done} labelled: `tr label --claims show <claim_id>`, then {CLAIM_ADD}"]


def source_rows(conn: sqlite3.Connection, source_ids: tuple[str, ...]) -> list[str]:
    """The cited SourceRefs as stored: id, kind, uri, feed and when they were read."""
    lines = []
    for source_id in source_ids:
        try:
            s = journal.get(conn, SourceRef, source_id)
        except KeyError:
            lines.append(f"  {source_id} | missing from the journal")
            continue
        lines.append(f"  {s.source_id} | {s.kind} | {s.uri} | feed {s.feed or '-'} | {s.retrieved_at.isoformat()}")
    return lines or ["  none cited"]


def show_claim(conn: sqlite3.Connection, claim_id: str) -> list[str]:
    """The claim as a labeller judges it: its text with the value filled in and the cited source rows. Blind: no
    model tag, derived_from or steps, no claims_valid verdict, no earlier label; nothing is recorded."""
    c, a = teacher_claim(conn, claim_id)
    text = c.text.replace("{value}", plain(c.value)) if c.value is not None else c.text
    value = [f"value: {plain(c.value)}" + (f" {c.unit}" if c.unit else "")] if c.value is not None else []
    return [f"{c.claim_id} {a.ticker} {a.session} (analysis {a.analysis_id})", f"text: {text}", *value,
            "cited sources (source_id | kind | uri | feed | retrieved_at)", *source_rows(conn, c.source_ids), "",
            f"blind: label it with {CLAIM_ADD.replace('<claim_id>', c.claim_id)}"]


def add_claim_label(conn: sqlite3.Connection, claim_id: str, tag: str, labeller: str, *, supported: bool | None = None,
                    now: datetime | None = None) -> ClaimLabel:
    """Store one blind ClaimLabel. Refused: an unknown tag, a blank labeller, a non-teacher claim and a second label
    on a claim (ClaimLabel has no relabel field, so the first label stands)."""
    if tag not in TAGS:
        raise Refused(f"tag {tag!r}: a claim is one of {', '.join(TAGS)}")
    if not labeller.strip():
        raise Refused("--labeller is blank: name the person who labelled the claim")
    teacher_claim(conn, claim_id)
    held = claim_labels(conn).get(claim_id)
    if held is not None:
        raise Refused(f"{claim_id} is already labelled ({held.claim_label_id}); a claim takes one label")
    record = ClaimLabel(claim_label_id=new_id("clb"), claim_id=claim_id, tag=tag, supported=supported,
                        labeller=labeller.strip(), blind=True, labelled_at=now or datetime.now(UTC))
    journal.add(conn, record)
    return record
