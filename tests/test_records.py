import pytest
from pydantic import ValidationError

from factories import analysis, claim, source, thesis
from tradingresearch.records import Analysis, Claim, SourceRef


def test_records_round_trip_through_json():
    a = analysis()
    assert Analysis.model_validate_json(a.model_dump_json()) == a
    s = source()
    assert SourceRef.model_validate_json(s.model_dump_json()) == s


def test_fact_without_source_is_rejected():
    with pytest.raises(ValidationError, match="a fact cites at least one source"):
        claim("an_1", source_ids=())


def test_inference_needs_derived_from_and_steps():
    with pytest.raises(ValidationError, match="an inference names"):
        claim("an_1", tag="inference", source_ids=(), derived_from=("cl_1",), steps=None)


def test_bars_source_needs_feed():
    with pytest.raises(ValidationError, match="needs a feed"):
        source(kind="bars_daily", feed=None)


def test_non_finite_number_is_rejected():
    with pytest.raises(ValidationError):
        claim("an_1", value=float("nan"))


def test_records_are_frozen_and_closed():
    c = claim("an_1")
    with pytest.raises(ValidationError):
        c.value = 1.0  # frozen
    with pytest.raises(ValidationError):
        Claim.model_validate(c.model_dump() | {"confidence": 0.9})  # extra=forbid


def test_teacher_analysis_must_be_trainable():
    with pytest.raises(ValidationError, match="trainable"):
        analysis(arm="teacher", terms_class="restricted")


def test_context_budget():
    with pytest.raises(ValidationError, match="context_tokens"):
        analysis(context_tokens=14_001)


def test_thesis_long_order_and_hold():
    with pytest.raises(ValidationError, match="rule 1"):
        thesis("an_1", stop=233.0)
    with pytest.raises(ValidationError, match="rule 3"):
        thesis("an_1", hold_sessions=1)
