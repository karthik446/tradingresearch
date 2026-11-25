"""w4l2.3 the cap and the trace: the loop ends at max_turns model calls with a failed sample, a failed call fails the
sample with its error, a spending cap's refusal reaches the caller, and every span is in the trace as it ends.

The replies are the recording or edits of it (tools/fakea.py `answer`): `turn1` asks for a tool every time it is sent,
so only the cap ends a loop of them; `three_calls` asks for three tools at once; `turn2` is the final JSON; `busy` is an
HTTP 503 the adapter retries inside one call; `failed` an HTTP 400 it does not retry. The replay itself answers HTTP 400
from request 13 on (fakea.STOP_AFTER = 12), so a loop with no cap still ends. `fakea.Capped` refuses every call after
the first the way gigai-core's CallBudget does: BudgetExceeded.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402
from gigai_core.budget import BudgetExceeded  # noqa: E402
from gigai_core.trace import ListTrace, ModelSpan, ToolSpan, TrialSpan  # noqa: E402

from tradingresearch import analyze as an  # noqa: E402
from tradingresearch import openrouter, tools  # noqa: E402


def replayed(replies: tuple[str, ...], max_turns: int | None = None, cycle: bool = False, trace=None):
    sent: list[dict] = []
    try:
        sample = fakea.run(fakea.replaying(sent, replies, cycle=cycle), max_turns=max_turns, trace=trace)
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"analyze_with_tools raised {exc!r} with the replies {replies}: a sample that cannot "
                             f"finish is a failed sample, returned") from None
    return sent, sample


def ended(sample) -> str:
    return f"{sample.outcome}, error {sample.error.code if sample.error else None}"


def test_a_model_that_never_stops_gets_max_turns_calls_and_a_failed_sample():
    for max_turns in (3, None, 1, 6, 12):
        cap = an.MAX_TOOL_TURNS if max_turns is None else max_turns
        sent, sample = replayed(("turn1",), max_turns)
        assert len(sent) == cap, (
            f"with max_turns={cap} the loop made {len(sent)} calls: every reply asks for a tool, so the cap is all that "
            f"ends it ({fakea.STOP_AFTER + 1} calls is where the replay itself gives up)")
        assert (sample.outcome, sample.error and sample.error.code) == ("failed", "max_tool_turns"), (
            f"after {cap} calls that all asked for a tool the sample ends {ended(sample)}: it is a failed sample whose "
            f"error code is max_tool_turns, so the run counts it and the trace says why")
        assert sample.output_parsed is None, f"the failed sample holds a parsed output: {sample.output_parsed!r}"


def test_a_final_reply_on_the_last_allowed_call_succeeds():
    sent, sample = replayed(("turn1", "turn1", "turn2"), max_turns=3)
    assert (len(sent), ended(sample)) == (3, "succeeded, error None"), (
        f"two replies ask for a tool, then the third and last allowed call is the final JSON; the loop made "
        f"{len(sent)} calls and the sample ends {ended(sample)}: the cap fails a sample only when no reply ended the "
        f"loop, and this one did, on its last allowed call")
    assert sample.parse_status == "ok", f"the final JSON on call 3 parses as {sample.parse_status}"


def test_the_cap_counts_model_calls_not_tool_calls():
    sent, sample = replayed(("three_calls",), max_turns=3)
    assert (len(sent), ended(sample)) == (3, "failed, error max_tool_turns"), (
        f"every reply asks for three tools at once; with max_turns=3 the loop made {len(sent)} calls and the sample "
        f"ends {ended(sample)}: max_turns counts model calls, so 3 calls are allowed whatever number of tool calls "
        f"they ask for")


def test_every_call_offers_the_tools():
    sent, _ = replayed(("turn1",), max_turns=3)
    offered = [len(body.get("tools") or []) for body in sent]
    assert all(body.get("tools") == [openrouter.tool(s) for s in tools.TOOLS] for body in sent), (
        f"the {len(sent)} requests offer {offered} tools: every call offers TOOLS, the last allowed one too. The model "
        f"may need one more row on any call, and a request that drops the tools leaves it no way to ask")


def test_a_failed_call_ends_the_loop_and_fails_the_sample_with_its_error():
    for replies, calls in ((("failed",), 1), (("turn1", "failed"), 2)):
        trace = ListTrace()
        sent, sample = replayed(replies, trace=trace)
        assert len(sent) == calls, f"the replies {replies} got {len(sent)} calls; the HTTP 400 is the last one"
        assert (sample.outcome, sample.error and sample.error.code) == ("failed", "http_400"), (
            f"with the replies {replies} the sample ends {ended(sample)}; call {calls} failed with HTTP 400, which "
            f"the adapter does not retry: the sample fails with that call's error")
        errors = [s.error and s.error.code for s in sample.model_spans]
        assert len(errors) == calls and errors[-1] == "http_400", f"the sample's model spans have errors {errors}"
        trial = [s for s in trace.spans if isinstance(s, TrialSpan)]
        assert trial and trial[-1].error == sample.error, (
            f"with the replies {replies} the trace's trial span has error "
            f"{trial[-1].error.code if trial and trial[-1].error else None}; the sample's is http_400: the trace is "
            f"where a reader of the run sees why an item failed, so the trial span carries the sample's error")
        traced = [s.error and s.error.code for s in trace.spans if isinstance(s, ModelSpan)]
        assert traced == errors, (
            f"with the replies {replies} the trace's model spans have errors {traced}; the sample's have {errors}: a "
            f"failed call's span goes to the trace too, as soon as the call ends, so a reader of the run sees the "
            f"HTTP 400 there")


def test_retries_stay_inside_one_model_call():
    sent, sample = replayed(("busy", "turn1"), max_turns=3, cycle=True)
    assert (len(sent), len(sample.model_spans)) == (6, 3), (
        f"{len(sent)} posts and {len(sample.model_spans)} model spans: each call is an HTTP 503 the adapter retries "
        f"once, then a reply asking for a tool, so 3 calls make 6 posts, each call one span")
    assert ended(sample) == "failed, error max_tool_turns", f"the sample ends {ended(sample)}"


def test_a_spending_cap_refusal_reaches_the_caller_and_the_trace_keeps_what_ran():
    sent: list[dict] = []
    trace = ListTrace()
    with pytest.raises(BudgetExceeded):
        got = fakea.run(fakea.Capped(fakea.replaying(sent, ("three_calls",)), allowed=1), trace=trace)
        pytest.fail(f"the cap refused the second call and analyze_with_tools returned a sample ({ended(got)}): a "
                    f"refusal is not a failed call of this item, it stops the whole run, so it reaches the caller")
    kinds = [type(s).__name__ for s in trace.spans]
    assert kinds == ["ModelSpan", "ToolSpan", "ToolSpan", "ToolSpan"], (
        f"after the refusal the trace holds {kinds}: the first call and its three tool calls ran and cost money before "
        f"the run stopped; a span goes to the trace when it ends, so they are there")


def test_every_span_reaches_the_trace_in_order_with_the_trial_span_last():
    trace = ListTrace()
    sent, sample = replayed(("three_calls", "turn2"), trace=trace)
    kinds = [type(s).__name__ for s in trace.spans]
    assert kinds == ["ModelSpan", "ToolSpan", "ToolSpan", "ToolSpan", "ModelSpan", "TrialSpan"], (
        f"the trace got {kinds}: a span goes to the trace when it ends, so a model call comes before the tool calls "
        f"it asked for, and the trial span, which ends last, is last")
    trial = trace.spans[-1]
    assert isinstance(trial, TrialSpan) and sample.spans == (trial, *trace.spans[:-1]), (
        "the sample's spans are not the trial span followed by the trace's other spans in the same order")
    assert {s.parent_id for s in trace.spans if isinstance(s, (ModelSpan, ToolSpan))} == {trial.span_id}, (
        "a model or tool span's parent is not the trial span")
