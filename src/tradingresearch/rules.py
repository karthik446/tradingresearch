"""Challenger rule changes (SPIKE §8.2-8.3): a RuleChange's `diff_ref` names a code-reviewed entry of
`CHALLENGER_RULES`, either a pure post-filter on the written theses or a prompt variant in prompts/. The challenger arm
answers the champion's analysis under that rule from the first session that opens after the Prereg was registered.

`tr daily` records each challenger answer as a `daily_run` row labelled `challenger <change_id> (<analysis_id>): `;
`unanswered` reads them back so adopt.py can leave out sessions whose challenger failed or was skipped.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from . import analyze as an, journal, sessions, thesis as th
from .records import Analysis, RuleChange, Thesis

CHALLENGER = "challenger"  # a challenger row's reason starts "challenger <change_id> (<analysis_id>): "


@dataclass(frozen=True)
class Filter:
    """A pure post-filter: `refuse` names why a written challenger thesis is dropped before the store, or None."""

    description: str
    refuse: Callable[[Thesis, Analysis], str | None]


@dataclass(frozen=True)
class PromptVariant:
    """The challenger's thesis prompt, prompts/<prompt>.txt, locked by ci/gate.py like every prompt."""

    description: str
    prompt: str


Rule = Filter | PromptVariant

MIN_REL_VOLUME = 1.5


def breakout_needs_volume(t: Thesis, a: Analysis) -> str | None:
    """Example filter: a breakout_20d thesis needs rel_volume >= 1.5 at the analysed close."""
    rel = a.snapshot.values.get("rel_volume")
    if t.setup_type == "breakout_20d" and (rel is None or rel < MIN_REL_VOLUME):
        return f"breakout_20d needs rel_volume >= {MIN_REL_VOLUME:g}, got {rel}"
    return None


def short_with_sma50_trend(t: Thesis, a: Analysis) -> str | None:
    """rule-change-1: a short-horizon thesis trades with the 50-session trend (long above sma_50, short below)."""
    if t.horizon != "short":
        return None
    dist = a.snapshot.values.get("dist_sma_50_atr")
    if dist is None:
        return "short horizon needs dist_sma_50_atr to check the trend, got None"
    if (t.direction == "long" and dist < 0) or (t.direction == "short" and dist > 0):
        return f"short-horizon {t.direction} against the sma_50 trend (dist_sma_50_atr {dist:.2f})"
    return None


CHALLENGER_RULES: dict[str, Rule] = {
    "example-breakout-volume": Filter("example: drop breakout_20d theses with rel_volume < 1.5", breakout_needs_volume),
    "example-same-prompt": PromptVariant("example: the champion's own prompt, an A/A check of the pairing", "thesis-1"),
    "short-sma50-trend": Filter("drop short-horizon theses against the 50-session trend (long below sma_50, short "
                                "above)", short_with_sma50_trend),
}


def resolve(diff_ref: str) -> Rule:
    """The registry entry, or ValueError before any spend: an unknown ref, or a prompt variant with no prompt file."""
    rule = CHALLENGER_RULES.get(diff_ref)
    if rule is None:
        raise ValueError(f"unknown diff_ref {diff_ref!r}: not in rules.CHALLENGER_RULES "
                         f"({', '.join(sorted(CHALLENGER_RULES))})")
    if isinstance(rule, PromptVariant) and not (an.PROMPTS_DIR / f"{rule.prompt}.txt").is_file():
        raise ValueError(f"diff_ref {diff_ref!r} names prompt {rule.prompt!r}, but prompts/{rule.prompt}.txt does not "
                         "exist (write it and record it with ci/gate.py --record-prompts)")
    return rule


def register(conn: sqlite3.Connection, change: RuleChange) -> None:
    """Store a pre-registered change after its diff_ref resolves (journal.add_rule_change checks the Prereg)."""
    resolve(change.diff_ref)
    journal.add_rule_change(conn, change)


def pending_for(conn: sqlite3.Connection, session: date) -> RuleChange | None:
    """The pending change whose Prereg was registered before `session` opened: its challenger answers that session."""
    opens = sessions.open_close(session)[0]
    return next((c for c in journal.rule_changes(conn, "pending") if c.prereg.registered_at < opens), None)


def prompt_of(rule: Rule) -> str:
    return rule.prompt if isinstance(rule, PromptVariant) else th.DEFAULT_PROMPT


def post(rule: Rule, analysis: Analysis) -> Callable[[th.Checked], th.Checked] | None:
    """The filter applied to a checked reply before the store; a refused thesis becomes a `rule_filter` rejection."""
    if not isinstance(rule, Filter):
        return None

    def apply(checked: th.Checked) -> th.Checked:
        kept, rejected = [], list(checked.rejected)
        for t in checked.theses:
            why = rule.refuse(t, analysis)
            if why is None:
                kept.append(t)
            else:
                rejected.append(th.Rejection(t.horizon, "rule_filter", why))
        return th.Checked(kept, checked.no_trades, rejected)

    return apply


def label(change_id: str, analysis_id: str) -> str:
    return f"{CHALLENGER} {change_id} ({analysis_id}): "


def answered(conn: sqlite3.Connection, change_id: str, analysis_id: str) -> bool:
    """The challenger answered this analysis: a challenger thesis from it, or an `ok` challenger row (a call that
    returned and was checked, or no call because every horizon has a live challenger thesis)."""
    if conn.execute("SELECT 1 FROM thesis WHERE analysis_id = ? AND arm = 'challenger' LIMIT 1",
                    (analysis_id,)).fetchone():
        return True
    return conn.execute("SELECT 1 FROM daily_run WHERE step = 'thesis' AND status = 'ok' AND substr(reason, 1, ?) = ? "
                        "LIMIT 1", (len(label(change_id, analysis_id)), label(change_id, analysis_id))).fetchone() \
        is not None


def champion_ran(conn: sqlite3.Connection, session: date) -> bool:
    """`tr daily` handled the champion theses of `session` (a thesis row that is neither a teacher's nor a
    challenger's), so its journal says whether the challenger answered too."""
    rows = conn.execute("SELECT reason FROM daily_run WHERE session = ? AND step = 'thesis'", (session.isoformat(),))
    return any(not reason.startswith((f"{CHALLENGER} ", "teacher ")) for (reason,) in rows)


def unanswered(conn: sqlite3.Connection, session: date, change_id: str) -> list[str]:
    """Analyses `tr daily` gave a champion decision on `session` (the newest main analysis per ticker, as it reads
    them) with no challenger answer: the challenger failed, was stopped or was skipped. Empty when `tr daily` did not
    run the session's theses (then the thesis rows are all there is)."""
    if not champion_ran(conn, session):
        return []
    newest = {a.ticker: a for a in journal.analyses(conn, session, "main")}
    return [a.analysis_id for a in newest.values()
            if journal.has_decision(conn, a.analysis_id) and not answered(conn, change_id, a.analysis_id)]


def answerable(session: date, now: datetime) -> bool:
    """A challenger can still answer `session` until the entry windows after it open (`tr thesis` refuses then)."""
    return now < th.windows(session, "day")[0]  # every horizon's window opens at the next session's open
