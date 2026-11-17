"""The claim validators. The full analyze round trip is exercised by real runs, never by a fake model."""

import json
from pathlib import Path

from test_teacher import context as live_context
from tradingresearch import analyze as an
from tradingresearch.analyze import validate_claims

RECORDED = json.loads(Path("tests/fixtures/teacher/AAPL_2026-11-16.deepseek-v4-pro.analysis.json").read_text())

VALUES = {"src_close": 230.0, "src_sma": 221.5, "src_regime": None}


def claim(id, tag="fact", text="Close was {value} USD.", value=230.0, unit="USD", source_ids=("src_close",),
          derived_from=(), steps=None):
    return dict(id=id, tag=tag, text=text, value=value, unit=unit, source_ids=list(source_ids),
                derived_from=list(derived_from), steps=steps)


def reasons(raw):
    kept, rejected = validate_claims({"claims": raw}, VALUES, "an_test")
    return [c.text for c in kept], {r.claim: r.reason for r in rejected}


def test_a_sourced_fact_passes_and_rounding_is_tolerated():
    kept, rejected = reasons([claim("c1"), claim("c2", value=230.4)])  # 0.17% off: prose rounding
    assert len(kept) == 2 and rejected == {}


def test_a_number_that_is_not_in_the_cited_source_is_rejected():
    _, rejected = reasons([claim("c1", value=235.0)])
    assert rejected == {"c1": "unsourced_number"}


def test_digits_in_the_text_are_rejected_but_names_and_dates_are_not():
    _, rejected = reasons([
        claim("c1", text="Close was 230 USD."),
        claim("c2", text="Above the 200-day average."),
        claim("c3", text="On 2026-11-13 close was {value}, above sma_200 and high_20."),
    ])
    assert rejected == {"c1": "number_in_text", "c2": "number_in_text"}


def test_an_unknown_source_and_a_valued_opinion_are_rejected():
    _, rejected = reasons([
        claim("c1", source_ids=("src_made_up",)),
        claim("c2", tag="opinion", text="Looks strong.", value=230.0, source_ids=()),
    ])
    assert rejected == {"c1": "unknown_source", "c2": "number_in_opinion"}


def test_only_the_value_placeholder_exists_and_it_needs_a_value():
    # both were found by open coding the first live AAPL run (week-1.md, item 5)
    _, rejected = reasons([
        claim("c1", text="The SPY regime is {value_text}.", value=None, unit=None, source_ids=("src_regime",)),
        claim("c2", text="Close was {value} USD.", value=None, unit=None),
    ])
    assert rejected == {"c1": "bad_placeholder", "c2": "empty_placeholder"}


def test_an_inference_on_a_rejected_claim_falls_with_it():
    _, rejected = reasons([
        claim("c1", value=999.0),
        claim("c2", tag="inference", text="Price is extended.", value=None, unit=None, source_ids=(),
              derived_from=("c1",), steps="Close far above the average."),
    ])
    assert rejected == {"c1": "unsourced_number", "c2": "bad_derivation"}


def test_a_mis_tagged_claim_is_rejected_by_the_record_rules():
    _, rejected = reasons([claim("c1", tag="inference", text="Price is extended.", source_ids=(), steps=None,
                                 value=None, unit=None)])
    assert rejected == {"c1": "not_a_claim"}  # an inference needs derived_from and steps


def test_a_cited_dropped_source_is_rejected_and_its_inference_falls_with_it():
    raw = [claim("c1"), claim("c2", value=221.5, source_ids=("src_sma",)),
           claim("c3", tag="inference", text="Price is extended.", value=None, unit=None, source_ids=(),
                 derived_from=("c2",), steps="Close above the average.")]
    kept, rejected = validate_claims({"claims": raw}, VALUES, "an_test", hidden=frozenset({"src_sma"}))
    assert [c.text for c in kept] == ["Close was {value} USD."]
    assert {r.claim: r.reason for r in rejected} == {"c2": "dropped_source", "c3": "bad_derivation"}
    assert validate_claims({"claims": raw}, VALUES, "an_test")[1] == []  # the full context accepts all three


def test_without_drop_the_input_hash_of_a_recorded_analysis_is_unchanged():
    ctx = live_context()
    assert an.input_hash(ctx, "analyze-1") == RECORDED["input_hash"]
    assert an.input_hash(ctx, "analyze-1", drop=()) == RECORDED["input_hash"]


def test_a_drop_list_changes_the_input_hash_whatever_its_order():
    ctx = live_context()
    one = an.input_hash(ctx, "analyze-1", drop=("edgar", "levels"))
    assert one == an.input_hash(ctx, "analyze-1", drop=("levels", "edgar"))
    assert one != RECORDED["input_hash"] != an.input_hash(ctx, "analyze-1", drop=("edgar",))
