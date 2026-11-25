"""w4l2.2 answer every tool call: the reply that asks for tools goes back as the assistant turn, each call gets a tool
turn with its id and its result, in order, and the loop calls again until a reply asks for no tool.

The recorded exchange (inside tools/fakea.py `capture_tool`) asks for one tool, get_sources; its second request is
labs/w4/data/turn2.request.json. The other replies are edits of the recorded first one (tools/fakea.py `answer`):
`three_calls` asks get_indicators, get_levels and get_fundamentals at once (ids toolu_lab_1 to toolu_lab_3),
`one_more` asks get_indicators again (toolu_lab_4). Every reply ends with the recorded final JSON, turn2.reply.json.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402
from gigai_core.trace import ListTrace, ToolSpan  # noqa: E402

from tradingresearch import tools  # noqa: E402

CTX = fakea.context()
RECORDED = fakea.load("turn2.request")
FINAL = json.loads(fakea.load("turn2.reply")["choices"][0]["message"]["content"])


def replayed(replies: tuple[str, ...], capture: bool = False, trace=None) -> tuple[list[dict], object]:
    sent: list[dict] = []
    try:
        if capture:
            with fakea.capture_tool():
                answered = [tools.run_tool(CTX, c["function"]["name"], c["function"]["arguments"])
                            for c in RECORDED["messages"][2]["tool_calls"]]
                return sent, (fakea.run(fakea.replaying(sent, replies), trace=trace), answered)
        return sent, fakea.run(fakea.replaying(sent, replies), trace=trace)
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"analyze_with_tools raised {exc!r} with the replies {replies}") from None


def test_the_second_request_is_the_recorded_one_but_for_the_user_and_tool_turns():
    sent, (_, answered) = replayed(("turn1", "turn2"), capture=True)
    assert len(sent) >= 2, (
        f"{len(sent)} request was sent: the recorded first reply asks for get_sources (id "
        f"{RECORDED['messages'][2]['tool_calls'][0]['id']}), so the loop answers it and calls again; the recorded "
        f"run made 2 calls")
    first, second = sent[:2]
    assert second["messages"][:2] == first["messages"], "the second request does not start with the first one's turns"
    assert second["messages"][2:3] == RECORDED["messages"][2:3], (
        f"the turn after the user turn is {json.dumps(second['messages'][2:3])[:200]}; the recording sent the reply "
        f"back as it came, {json.dumps(RECORDED['messages'][2])[:200]}: a tool turn answers a call the model can see")
    tool_turn = {**RECORDED["messages"][3], "content": answered[0]}
    assert second["messages"][3:] == [tool_turn], (
        f"after the assistant turn the second request has {json.dumps(second['messages'][3:])[:200]}; the recording "
        f"has one tool turn, with the call's id and what run_tool answered")
    assert {k: v for k, v in second.items() if k != "messages"} == {k: v for k, v in RECORDED.items() if k != "messages"}


def test_each_call_gets_its_own_tool_turn_and_span_in_order():
    trace = ListTrace()
    sent, sample = replayed(("three_calls", "turn2"), trace=trace)
    assert len(sent) >= 2, f"{len(sent)} request was sent: the first reply asks for three tools, so the loop calls again"
    calls = [m for m in sent[1]["messages"][2:] if m["role"] == "assistant"]
    assert [c["id"] for m in calls for c in m.get("tool_calls") or []] == [i for i, _, _ in fakea.THREE_CALLS], (
        f"the second request sends back {json.dumps(calls)[:200]}: the assistant turn carries the three calls")
    got = [(m["role"], m.get("tool_call_id"), m["content"]) for m in sent[1]["messages"][3:]]
    want = [("tool", i, tools.run_tool(CTX, name, args)) for i, name, args in fakea.THREE_CALLS]
    assert got == want, (
        f"the reply asked for {[(i, n) for i, n, _ in fakea.THREE_CALLS]}; the turns after it are "
        f"{[(r, i, c[:40]) for r, i, c in got]}: one tool turn per call, in the order asked, each with the call's id "
        f"and its run_tool result, or the model cannot tell which answer is whose")
    spans = [s.call.id for s in trace.spans if isinstance(s, ToolSpan)]
    assert spans == [i for i, _, _ in fakea.THREE_CALLS], f"the trace has tool spans for {spans}"


def test_the_loop_calls_again_until_a_reply_asks_for_no_tool():
    sent, sample = replayed(("three_calls", "one_more", "turn2"))
    assert len(sent) == 3, (
        f"{len(sent)} requests were sent: the first reply asks for three tools, the second for one more, the third "
        f"is the final JSON; one call each")
    assert len(sent[2]["messages"]) == 8, f"the third request has {len(sent[2]['messages'])} turns: 2 + (1 + 3) + (1 + 1)"
    assert (sample.outcome, sample.parse_status, sample.output_parsed) == ("succeeded", "ok", FINAL), (
        f"the sample ends {sample.outcome}, {sample.parse_status}: the last reply is the recorded final JSON")
