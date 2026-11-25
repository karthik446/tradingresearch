"""The tradingresearch records (SPIKE §1.1). Every record is a gigai-core CoreModel: frozen, strict, closed, finite."""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from gigai_core import CoreModel
from gigai_core.records import Prereg
from pydantic import AwareDatetime, model_validator

Feed = Literal["sip", "iex"]
Horizon = Literal["day", "short", "swing"]
Direction = Literal["long", "short"]
ClaimTag = Literal["fact", "inference", "opinion"]
TermsClass = Literal["trainable", "restricted", "unknown"]
Regime = Literal["bull-normal", "bull-high", "mixed-normal", "mixed-high", "bear-normal", "bear-high"]
SetupType = Literal["breakout_20d", "pullback_to_level", "range_fade", "gap_continuation", "event_drift"]
State = Literal["PROPOSED", "OPEN", "CANCELLED", "EXPIRED", "CLOSED", "GRADED"]
EventReason = Literal[
    "written", "entry_fill", "gap_fill", "stop", "target", "time_exit", "invalidated", "window_missed",
    "pre_entry_stop", "corporate_action", "data_missing", "graded",
]

# Thesis rule 3: hold_sessions per horizon (sessions after the entry session).
HOLD_RANGE: dict[str, tuple[int, int]] = {"day": (0, 0), "short": (2, 5), "swing": (5, 20)}
# TODO(w5l4.1) the TrainingSplit embargo floor: SWING_ENTRY_SESSIONS, MIN_EMBARGO from it and the longest hold in
#   HOLD_RANGE, and EMBARGO_WHY, the reason a refusal states.
MAX_CONTEXT_TOKENS = 14_000
RULES_VERSION = "rules-1"  # the reconcile rules (SPIKE §6) a thesis or event is settled by; reconcile picks rules by it


def clean_route(route: str) -> bool:
    """True only for one known provider: the teacher terms filter and the training set need who served every turn."""
    prefix, _, rest = route.partition(":")
    host = rest.split("/")[0].lower()
    return prefix == "openrouter" and host not in ("", "unknown") and not host.startswith("mixed(")


def _trainable_route(terms_class: str, route: str) -> None:
    """A trainable record (the teacher arm) is refused when its route lost provenance (unknown or mixed)."""
    if terms_class == "trainable" and not clean_route(route):
        raise ValueError(f"a trainable record needs one known provider route, got {route!r}")


class SourceRef(CoreModel):
    source_id: str
    kind: Literal["edgar_fact", "edgar_filing", "bars_daily", "bars_1m", "news", "computed"]
    uri: str
    retrieved_at: AwareDatetime
    content_sha256: str
    feed: Feed | None
    licence_note: str

    @model_validator(mode="after")
    def _feed_for_bars(self) -> Self:
        if self.kind.startswith("bars_") and self.feed is None:
            raise ValueError(f"{self.kind} source needs a feed (sip or iex)")
        return self


class Claim(CoreModel):
    claim_id: str
    analysis_id: str
    text: str
    tag: ClaimTag
    value: float | None
    unit: str | None
    source_ids: tuple[str, ...]
    derived_from: tuple[str, ...]
    steps: str | None

    @model_validator(mode="after")
    def _tag_rules(self) -> Self:
        if self.tag == "fact" and (not self.source_ids or self.derived_from):
            raise ValueError("a fact cites at least one source and derives from no claim")
        if self.tag == "inference" and (not self.derived_from or not self.steps):
            raise ValueError("an inference names the claims it derives from and the steps")
        return self


class Level(CoreModel):
    price: float
    kind: Literal["hvn", "pivot_high", "pivot_low", "high_20", "low_20"]
    strength: float
    distance_atr: float


class Congestion(CoreModel):
    low: float
    high: float
    sessions: int
    range_atr: float

    @model_validator(mode="after")
    def _is_congestion(self) -> Self:
        if self.sessions < 5 or self.range_atr > 1.5:
            raise ValueError("congestion needs sessions >= 5 and range_atr <= 1.5")
        return self


class IndicatorSnapshot(CoreModel):
    ticker: str
    session: date
    values: dict[str, float]
    levels: tuple[Level, ...]
    congestion: Congestion | None
    regime: Regime
    bars_source_id: str
    code_version: str


class Analysis(CoreModel):
    analysis_id: str
    ticker: str
    session: date
    created_at: AwareDatetime
    run_id: str
    snapshot: IndicatorSnapshot
    claims: tuple[Claim, ...]
    input_hash: str
    prompt_version: str
    model: str
    arm: Literal["main", "teacher"] = "main"
    sample_trace_id: str
    provider_route: str
    terms_class: TermsClass
    context_tokens: int

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if self.arm == "teacher" and self.terms_class != "trainable":
            raise ValueError("a teacher analysis must be terms_class 'trainable'")
        _trainable_route(self.terms_class, self.provider_route)
        if self.context_tokens > MAX_CONTEXT_TOKENS:
            raise ValueError(f"context_tokens {self.context_tokens} > {MAX_CONTEXT_TOKENS}")
        if any(claim.analysis_id != self.analysis_id for claim in self.claims):
            raise ValueError("every claim must carry this analysis_id")
        return self


class EntryRule(CoreModel):
    kind: Literal["market_open", "stop", "limit"]
    price: float | None
    window_start: AwareDatetime
    window_end: AwareDatetime

    @model_validator(mode="after")
    def _price(self) -> Self:
        if (self.price is None) != (self.kind == "market_open"):
            raise ValueError("price is None exactly when kind is market_open")
        return self


class Thesis(CoreModel):
    """Rules 1 (when the entry has a price), 3 and 5 (main arms) are checked here.

    Rules that need the Analysis (market_open reference price, evidence tags, ATR stop floor, teacher fill bound,
    arm match) are checked by `thesis.check_thesis` before a record is built.
    """

    thesis_id: str
    analysis_id: str
    ticker: str
    horizon: Horizon
    direction: Direction
    setup_type: SetupType
    prediction: str
    reason: str
    entry: EntryRule
    stop: float
    target: float
    hold_sessions: int
    invalidation_price: float
    invalidation_text: str
    evidence: tuple[str, ...]
    regime: str
    arm: Literal["champion", "challenger", "teacher"]
    sample_trace_id: str
    provider_route: str
    terms_class: TermsClass
    rules_version: str
    created_at: AwareDatetime
    input_hash: str

    @model_validator(mode="after")
    def _rules(self) -> Self:
        _trainable_route(self.terms_class, self.provider_route)
        if self.entry.price is not None:
            low, high = (self.stop, self.target) if self.direction == "long" else (self.target, self.stop)
            if not low < self.entry.price < high:
                raise ValueError(f"rule 1: {self.direction} needs stop/entry/target in order")
        lo, hi = HOLD_RANGE[self.horizon]
        if not lo <= self.hold_sessions <= hi:
            raise ValueError(f"rule 3: {self.horizon} hold_sessions must be {lo}-{hi}")
        if not self.evidence:
            raise ValueError("rule 2: evidence is empty")
        if self.arm != "teacher" and self.entry.window_start <= self.created_at:
            raise ValueError("rule 5: entry window must start after created_at")
        return self


class NoTrade(CoreModel):
    analysis_id: str
    horizon: Horizon
    reason: str
    created_at: AwareDatetime


class Event(CoreModel):
    event_id: str
    subject_id: str
    state: State
    at: AwareDatetime
    recorded_at: AwareDatetime
    price: float | None
    reason: EventReason
    bars_source_id: str | None
    rules_version: str


class OutcomeGrade(CoreModel):
    subject_id: str
    entry_price: float
    exit_price: float
    r_gross: float
    cost_bps: float
    cost_r: float
    r_net: float
    mfe_r: float
    mae_r: float
    exit_reason: str
    sessions_held: int


class Grade(CoreModel):
    grade_id: str
    thesis_id: str
    outcome: OutcomeGrade
    outcome_score_id: str
    process_score_id: str | None
    code_checks: dict[str, bool]
    shadow_id: str


class Shadow(CoreModel):
    shadow_id: str
    thesis_id: str
    direction: Direction
    entry_price: float
    entry_at: AwareDatetime
    stop: float
    target: float
    hold_sessions: int
    rule_version: str


class RuleChange(CoreModel):
    change_id: str
    description: str
    diff_ref: str
    prereg: Prereg
    decided: Literal["pending", "adopted", "rejected", "insufficient"]


class TeacherOutcome(CoreModel):
    teacher_outcome_id: str
    thesis_id: str
    final_state: Literal["CLOSED", "CANCELLED", "EXPIRED"]
    outcome: OutcomeGrade | None
    code_checks: dict[str, bool]
    outcome_score_id: str | None
    rules_version: str
    settled_at: AwareDatetime

    @model_validator(mode="after")
    def _outcome_only_when_closed(self) -> Self:
        if (self.outcome is not None) != (self.final_state == "CLOSED"):
            raise ValueError("outcome is set exactly when final_state is CLOSED")
        return self


class TrainingSplit(CoreModel):
    split_id: str
    cutoff_session: date
    embargo_sessions: int
    prereg: Prereg
    registered_at: AwareDatetime

    @model_validator(mode="after")
    def _rules(self) -> Self:
        # TODO(w5l4.1) refuse an embargo under MIN_EMBARGO with a ValueError that states the floor and EMBARGO_WHY.
        if self.registered_at.date() >= self.cutoff_session:
            raise ValueError("a split is registered before its cutoff session")
        return self


class ClaimLabel(CoreModel):
    claim_label_id: str
    claim_id: str
    tag: ClaimTag
    supported: bool | None
    labeller: str
    blind: bool
    labelled_at: AwareDatetime
