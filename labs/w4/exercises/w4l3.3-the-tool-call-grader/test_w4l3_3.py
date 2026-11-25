"""w4l3.3 the tool-call grader: tool_calls_ok is 0 with the first fault in the order the calls were made (tool_error,
repeated_call, then too_many_calls past max_calls = 2 x len(TOOLS)), else 1. No tool calls is 1.0. A result with an
"error" key is an error whatever the key holds; arguments are compared as JSON, key order and spacing ignored, the
order inside a list kept.

Two kinds of samples. Loop samples come from analyze_with_tools on FAKEA with replayed replies (tools/fakea.py): the
recorded `turn1` asks for get_sources, a tool week 4 does not offer, so its result is an error; `three_calls` asks for
each shipped tool once. Hand-built samples carry ToolSpans written here, (tool, arguments, result, raised) in order,
to reach the cases a replay does not: a raised tool, repeats, and more calls than the cap. The replay answers HTTP
400 from request 13 on.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402
from gigai_core.providers import ToolCall  # noqa: E402
from gigai_core.sample import Sample  # noqa: E402
from gigai_core.trace import CallError, ToolSpan  # noqa: E402

from tradingresearch import evals, tools  # noqa: E402

T0 = datetime(2026, 11, 17, tzinfo=UTC)
CLEAN = '{"rows": [{"name": "close", "value": 101.4}]}'
ERROR = {"error": "unknown tool 'get_sources'"}


def sample_of(calls) -> Sample:
    """A succeeded FAKEA sample whose ToolSpans are (tool, arguments, result, raised) in order."""
    spans = tuple(
        ToolSpan(span_id=f"span_{i}", turn=0, started_at=T0, completed_at=T0, parent_id="span_trial",
                 call=ToolCall(id=f"call_{i}", name=name, arguments=arguments), result=result,
                 error=CallError(code="tool_exception", message="boom", retryable=False) if raised else None)
        for i, (name, arguments, result, raised) in enumerate(calls))
    return Sample(trace_id="trace_lab", run_id="run_lab", item_id="FAKEA:2026-11-13", item_version="1",
                  cluster_id="FAKEA", repeat_index=0, input=(), output_text='{"claims": []}',
                  output_parsed={"claims": []}, parse_status="ok", outcome="succeeded", error=None, spans=spans,
                  recorded_at=T0)


def clean(*arguments: str, name: str = "get_indicators"):
    return [(name, a, CLEAN, False) for a in arguments]


def distinct(n: int):
    """n clean calls, no two alike."""
    return clean(*(f'{{"names": ["row_{i}"]}}' for i in range(n)))


def graded(sample, grader=None):
    """The grader's score, checked on every call: a Score whose value is exactly 0.0 or 1.0."""
    try:
        score = (grader or evals.GRADERS["tool_calls_ok"]()).grade(sample, None)
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"tool_calls_ok raised {exc!r} for calls [{calls_of(sample)}]; whatever the model sent, "
                             f"the grader returns a score") from None
    assert type(score.value) is float and score.value in (0.0, 1.0), (
        f"tool_calls_ok scored {score.value!r} ({type(score.value).__name__}); a score here is pass or fail, 1.0 or 0.0")
    return score


def calls_of(sample) -> str:
    return ", ".join(f"{s.call.name} {s.call.arguments}" for s in sample.tool_spans) or "none"


def fails_with(sample, reason: str, why: str):
    score = graded(sample)
    assert score.value == 0.0 and (score.explanation or "").startswith(reason), (
        f"tool_calls_ok scored {score.value} ({score.explanation!r}) for calls [{calls_of(sample)}]; expected 0.0 "
        f"with an explanation starting {reason!r}: {why}")


def passes(sample, why: str):
    score = graded(sample)
    assert score.value == 1.0, (
        f"tool_calls_ok scored {score.value} ({score.explanation!r}) for calls [{calls_of(sample)}]; expected 1.0: "
        f"{why}")


def test_the_recorded_get_sources_call_is_a_tool_error():
    sample = fakea.run(fakea.replaying([], ("turn1", "turn2")))
    [span] = sample.tool_spans
    fails_with(sample, "tool_error", f"the recorded loop asked for {span.call.name}, a tool not offered this week, "
                                     f"and its result came back as an error object: {span.result!r:.90}")


def test_clean_loops_and_a_loop_with_no_calls_score_1():
    passes(fakea.run(fakea.replaying([], ("three_calls", "turn2"))),
           "one round asking each shipped tool once, every result a row, then the answer")
    passes(fakea.run(fakea.replaying([], ("three_calls", "one_more", "turn2"))),
           "two rounds, four distinct tool calls; the model calls between them are not tool calls")
    passes(fakea.run(fakea.replaying([], ("turn2",))),
           "a loop that answered at once made no tool calls, which is clean, so compare keeps the grader for "
           "the fixed arm too")


def test_the_grader_is_registered_as_code_with_a_cap_of_twice_the_tools():
    cls = evals.GRADERS.get("tool_calls_ok")
    assert cls is not None and cls.kind == "code", (
        f"GRADERS['tool_calls_ok'] is {cls!r}, kind {getattr(cls, 'kind', None)!r}; it reads the sample's tool "
        f"calls with no model, so it is a code grader an experiment config can name")
    assert cls.max_calls == 2 * len(tools.TOOLS) == 6, (
        f"max_calls is {cls.max_calls!r}; with {len(tools.TOOLS)} tools, every tool once plus one follow-up each "
        f"is {2 * len(tools.TOOLS)}")


@pytest.mark.parametrize("result,raised", [
    (ERROR, False), ('{"error": "no row named sma_500"}', False), (CLEAN, True), (None, True)],
    ids=["error-object", "error-as-json-text", "raised-with-a-result", "raised"])
def test_an_error_object_or_a_raised_tool_is_a_tool_error(result, raised):
    fails_with(sample_of([("get_indicators", '{"names": ["close"]}', result, raised)]), "tool_error",
               "a call that raised, or whose result is an {\"error\": ...} object, stored parsed or as the JSON "
               "text sent back, is a tool error")


@pytest.mark.parametrize("value", ["", None, False, 0], ids=["empty-string", "null", "false", "zero"])
def test_an_error_key_is_a_tool_error_whatever_its_value(value):
    fails_with(sample_of([("get_indicators", '{"names": ["close"]}', {"error": value}, False)]), "tool_error",
               f"the result is an object with an \"error\" key, so it is a tool error; what the key holds, {value!r} "
               f"here, does not matter, and an empty or false value is still an error object")


@pytest.mark.parametrize("result", [
    "error: plain text is not an error object", '[{"error": "a row, not the result"}]',
    {"rows": [{"name": "error", "value": 1.0}]}, None], ids=["plain-text", "json-list", "a-row-named-error", "none"])
def test_a_result_that_is_not_an_error_object_is_clean(result):
    passes(sample_of([("get_indicators", '{"names": ["close"]}', result, False)]),
           "only a result that is itself an object with an \"error\" key is a tool error")


@pytest.mark.parametrize("first,again", [
    ('{"names": ["close"]}', '{ "names" : [ "close" ] }'),
    ('{"names": ["close"], "limit": 2}', '{"limit": 2, "names": ["close"]}')], ids=["spacing", "key-order"])
def test_the_same_arguments_written_differently_are_a_repeat(first, again):
    fails_with(sample_of(clean(first, again)), "repeated_call",
               "the same tool asked for the same thing twice; arguments are compared as JSON, not as text")


def test_different_tools_or_different_arguments_are_not_a_repeat():
    passes(sample_of([*clean("{}", name="get_levels"), *clean("{}", name="get_fundamentals"),
                      *clean('{"names": ["close"]}', '{"names": ["sma_50"]}')]),
           "a repeat is the same tool with the same arguments; {} sent to two tools, or one tool asked for two "
           "rows, is not")
    passes(sample_of(clean('{"names": ["close", "sma_50"]}', '{"names": ["sma_50", "close"]}')),
           "key order and spacing are normalised, the order of a list is not: the same names in another order is "
           "another request, not a repeat")


def test_arguments_that_are_not_json_are_graded_too():
    passes(sample_of(clean("", name="get_levels")), "a model may send empty arguments; one such call is clean")
    fails_with(sample_of(clean("", "", name="get_levels")), "repeated_call",
               "the same tool sent the same empty arguments twice")
    passes(sample_of(clean('{"names": [close]}', '{"names": [rsi_14]}')),
           "two calls whose arguments are both broken JSON but ask for different rows are not the same call")
    graded(sample_of(clean("", "{}", name="get_levels")))  # the same request, which the chapter does not call a repeat


def test_the_cap_passes_at_max_calls_and_fails_one_over():
    passes(sample_of(distinct(6)), "6 distinct clean calls is max_calls, the cap itself")
    fails_with(sample_of(distinct(7)), "too_many_calls", "7 distinct clean calls is one over max_calls = 6")


def test_the_first_fault_in_call_order_is_the_one_reported():
    a, b = '{"names": ["close"]}', '{"names": ["rsi_14"]}'
    fails_with(sample_of([*clean(a, a), ("get_levels", "{}", ERROR, False)]), "repeated_call",
               "the second call repeats the first before the third errs")
    fails_with(sample_of([("get_levels", "{}", ERROR, False), *clean(a, a)]), "tool_error",
               "the first call errs before the third repeats the second")
    fails_with(sample_of([*clean(a, b, a), *distinct(5)]), "repeated_call",
               "the third call repeats the first, four calls before the eighth goes past the cap")
    fails_with(sample_of([*distinct(6), distinct(1)[0]]), "repeated_call",
               "the seventh call repeats the first: a repeat is a fault wherever it falls, and it comes before the "
               "seventh call goes past the cap")
    fails_with(sample_of([*distinct(6), ("get_levels", "{}", CLEAN, True)]), "tool_error",
               "the seventh call raised: an erring call is a fault wherever it falls, and it comes before the seventh "
               "call goes past the cap")
    fails_with(sample_of([*clean(a, b), ("get_levels", "{}", ERROR, False)]), "tool_error",
               "two clean calls, then the third errs: one fault fails the loop, however many calls went well")
    fails_with(sample_of([("get_levels", "{}", ERROR, False), *distinct(7)]), "tool_error",
               "the first call errs; that the loop went on past the cap comes later")


def test_one_grader_grades_each_sample_on_its_own():
    grader = evals.GRADERS["tool_calls_ok"]()
    a = '{"names": ["close"]}'
    first, again = graded(sample_of(clean(a)), grader), graded(sample_of(clean(a)), grader)
    repeated, after = graded(sample_of(clean(a, a)), grader), graded(sample_of(clean(a)), grader)
    got = [s.value for s in (first, again, repeated, after)]
    assert got == [1.0, 1.0, 0.0, 1.0], (
        f"one grader on four samples, [{a}], [{a}], [{a} twice], [{a}], scored {got}; a compare grades every "
        f"sample with one instance, and a call made in one sample is not a repeat in the next")
