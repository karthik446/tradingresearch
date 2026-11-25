"""Small valid records for tests. Each test changes only the field it is about."""

from datetime import UTC, date, datetime, timedelta

from tradingresearch.hashing import new_id
from tradingresearch.records import Analysis, Claim, EntryRule, Event, IndicatorSnapshot, SourceRef, Thesis

T0 = datetime(2026, 11, 13, 22, 0, tzinfo=UTC)  # after the 2026-11-13 close


def source(**overrides) -> SourceRef:
    fields = dict(
        source_id="src_0123456789abcdef", kind="computed", uri="tradingresearch:indicators.py#rsi_14",
        retrieved_at=T0, content_sha256="sha256:" + "0" * 64, feed=None, licence_note="computed from Alpaca SIP bars",
    )
    return SourceRef(**(fields | overrides))


def snapshot(**overrides) -> IndicatorSnapshot:
    fields = dict(
        ticker="AAPL", session=date(2026, 11, 13), values={"close": 230.0, "atr_14": 4.0}, levels=(),
        congestion=None, regime="bull-normal", bars_source_id="src_bars", code_version="0.1.0",
    )
    return IndicatorSnapshot(**(fields | overrides))


def claim(analysis_id: str, **overrides) -> Claim:
    fields = dict(
        claim_id=new_id("cl"), analysis_id=analysis_id, text="Close was {value} USD.", tag="fact", value=230.0,
        unit="USD", source_ids=("src_0123456789abcdef",), derived_from=(), steps=None,
    )
    return Claim(**(fields | overrides))


def analysis(**overrides) -> Analysis:
    analysis_id = overrides.pop("analysis_id", new_id("an"))
    fields = dict(
        analysis_id=analysis_id, ticker="AAPL", session=date(2026, 11, 13), created_at=T0, run_id="run_0",
        snapshot=snapshot(), claims=(claim(analysis_id),), input_hash="sha256:" + "1" * 64, prompt_version="analyze-1",
        model="anthropic/claude-sonnet-5.5", sample_trace_id="tr_0", provider_route="openrouter:Anthropic",
        terms_class="restricted", context_tokens=3000,
    )
    return Analysis(**(fields | overrides))


def thesis(analysis_id: str, **overrides) -> Thesis:
    start = T0 + timedelta(hours=16, minutes=30)  # next session's open
    fields = dict(
        thesis_id=new_id("th"), analysis_id=analysis_id, ticker="AAPL", horizon="short", direction="long",
        setup_type="breakout_20d", prediction="Closes above 240 within 5 sessions.", reason="20-day high break.",
        entry=EntryRule(kind="stop", price=232.0, window_start=start, window_end=start + timedelta(hours=6, minutes=30)),
        stop=226.0, target=244.0, hold_sessions=5, invalidation_price=226.0, invalidation_text="Back inside the range.",
        evidence=("cl_0",), regime="bull-normal", arm="champion", sample_trace_id="tr_0",
        provider_route="openrouter:Anthropic",
        terms_class="restricted", rules_version="1", created_at=T0, input_hash="sha256:" + "2" * 64,
    )
    return Thesis(**(fields | overrides))


def event(subject_id: str, state: str, reason: str = "written") -> Event:
    return Event(
        event_id=new_id("ev"), subject_id=subject_id, state=state, at=T0, recorded_at=T0, price=None, reason=reason,
        bars_source_id=None, rules_version="1",
    )
