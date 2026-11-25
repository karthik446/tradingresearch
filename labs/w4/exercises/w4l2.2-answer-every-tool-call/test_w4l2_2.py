"""w4l2.2 answer every tool call: the reply that asks for tools goes back as the assistant turn, each call gets a tool
turn with its id and its result, in order, and the loop calls again until a reply asks for no tool.

The recorded exchange (inside tools/fakea.py `capture_tool`) asks for one tool, get_sources; its second request is
labs/w4/data/turn2.request.json. The other replies are edits of the recorded first one (tools/fakea.py `answer`):
`three_calls` asks get_indicators, get_levels and get_fundamentals at once (ids toolu_lab_1 to toolu_lab_3),
`one_more` asks get_indicators again (toolu_lab_4). Every reply ends with the recorded final JSON, turn2.reply.json.
"""

import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402
from gigai_core.trace import ListTrace, ToolSpan  # noqa: E402

from tradingresearch import openrouter, tools  # noqa: E402

CTX = fakea.context()
RECORDED = fakea.load("turn2.request")
FINAL = json.loads(fakea.load("turn2.reply")["choices"][0]["message"]["content"])


def replayed(replies: tuple[str, ...], capture: bool = False, trace=None, ctx=None,
             edit=None) -> tuple[list[dict], object]:
    sent: list[dict] = []
    try:
        if capture:
            with fakea.capture_tool():
                answered = [tools.run_tool(CTX, c["function"]["name"], c["function"]["arguments"])
                            for c in RECORDED["messages"][2]["tool_calls"]]
                return sent, (fakea.run(fakea.replaying(sent, replies), trace=trace), answered)
        return sent, fakea.run(fakea.replaying(sent, replies, edit=edit), trace=trace, ctx=ctx)
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
    differ = sorted(k for k in second.keys() | RECORDED.keys() if k != "messages" and second.get(k) != RECORDED.get(k))
    assert not differ, (
        f"the second request differs from the recorded one in {', '.join(differ)}, not only in its turns: every call "
        f"sends the same settings and offers the same tools as the first (the recording offered "
        f"{[t['function']['name'] for t in RECORDED['tools']]} on both calls)")


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
    kept = [s.call.id for s in sample.tool_spans]
    assert kept == spans, (
        f"the sample keeps tool spans for {kept}, the trace has {spans}: the sample is what the run stores and grades, "
        f"so it keeps every tool call's span too")


def test_a_call_to_a_tool_not_offered_still_gets_its_tool_turn():
    sent, _ = replayed(("turn1", "turn2"))  # outside capture_tool: the recorded call is to get_sources, not offered
    [call] = RECORDED["messages"][2]["tool_calls"]
    got = [(m.get("tool_call_id"), m["content"]) for body in sent[1:2] for m in body["messages"] if m["role"] == "tool"]
    want = [(call["id"], tools.run_tool(CTX, call["function"]["name"], call["function"]["arguments"]))]
    assert got == want, (
        f"the recorded reply calls {call['function']['name']}, which TOOLS does not offer; the second request's tool "
        f"turns are {str(got)[:160]}: every call gets its tool turn, here run_tool's error naming the tools, or the "
        f"model's call is left unanswered and it cannot correct it")


def test_each_item_answers_from_its_own_context():
    for ctx, which in ((fakea.context(extra=True), "the same rows with extra digits"), (CTX, "the plain FAKEA rows")):
        sent, _ = replayed(("three_calls", "turn2"), ctx=ctx)
        got = [m["content"] for body in sent[1:2] for m in body["messages"] if m["role"] == "tool"]
        want = [tools.run_tool(ctx, name, args) for _, name, args in fakea.THREE_CALLS]
        assert got == want, (
            f"on a context with {which}, the tool turns are {[c[:60] for c in got]}; run_tool on that context "
            f"answers {[c[:60] for c in want]}: each call runs on the context of this item, every time, so a run over "
            f"many items never answers one with another's rows")


def test_every_call_offers_the_tools():
    sent, _ = replayed(("three_calls", "one_more", "turn2"))
    offered = [len(body.get("tools") or []) for body in sent]
    assert all(body.get("tools") == [openrouter.tool(s) for s in tools.TOOLS] for body in sent), (
        f"the {len(sent)} requests offer {offered} tools: every call offers TOOLS, not only the first. The model may "
        f"need one more row after it read the first ones, and a request without the tools leaves it no way to ask")


def test_the_loop_calls_again_until_a_reply_asks_for_no_tool():
    sent, sample = replayed(("three_calls", "one_more", "turn2"))
    assert len(sent) == 3, (
        f"{len(sent)} requests were sent: the first reply asks for three tools, the second for one more, the third "
        f"is the final JSON; one call each")
    assert len(sent[2]["messages"]) == 8, f"the third request has {len(sent[2]['messages'])} turns: 2 + (1 + 3) + (1 + 1)"
    assert (sample.outcome, sample.parse_status, sample.output_parsed) == ("succeeded", "ok", FINAL), (
        f"the sample ends {sample.outcome}, {sample.parse_status}: the last reply is the recorded final JSON")


def test_a_fourth_and_fifth_call_get_one_tool_turn_and_one_span_each():
    def fifth(n: int, body: dict) -> dict:
        if n == 0:
            calls = body["choices"][0]["message"]["tool_calls"]
            calls += [{**calls[0], "index": 3, "id": "toolu_lab_extra"},
                      {**calls[1], "index": 4, "id": "toolu_lab_extra2"}]
        return body

    sent, sample = replayed(("three_calls", "turn2"), edit=fifth)
    ids = [i for i, _, _ in fakea.THREE_CALLS] + ["toolu_lab_extra", "toolu_lab_extra2"]
    got = [m.get("tool_call_id") for body in sent[1:2] for m in body["messages"] if m["role"] == "tool"]
    kept = [s.call.id for s in sample.tool_spans]
    assert got == ids and kept == ids, (
        f"the first reply asks for five tools ({', '.join(ids)}); the second request's tool turns answer {got} and "
        f"the sample keeps spans for {kept}: one tool turn and one span per call, each once, however many calls the "
        f"reply holds")


def test_a_long_tool_result_goes_back_whole():
    close = next(r for r in CTX.rows if r.name == "close")
    extra = tuple(dataclasses.replace(close, name=f"extra_{i}", source_id=f"long_{i}") for i in range(250))
    ctx = dataclasses.replace(CTX, rows=(*CTX.rows, *extra))

    def every_row(n: int, body: dict) -> dict:
        if n == 0:
            body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{}"
        return body

    sent, _ = replayed(("one_more", "turn2"), ctx=ctx, edit=every_row)
    got = [m["content"] for body in sent[1:2] for m in body["messages"] if m["role"] == "tool"]
    want = tools.run_tool(ctx, "get_indicators", "{}")
    assert got == [want], (
        f"on a context with {len(extra)} more indicator rows, get_indicators with no arguments answers {len(want)} "
        f"characters; the tool turn holds {[len(c) for c in got]}: the model reads only what the tool turn holds, so a "
        f"result cut short hides rows it asked for")


def test_every_reply_goes_back_with_its_text():
    first, said = "Reading the indicators first.", "Need another row to check the trend."

    def with_text(n: int, body: dict) -> dict:
        if n < 2:
            body["choices"][0]["message"]["content"] = (first, said)[n]
        return body

    sent, _ = replayed(("three_calls", "one_more", "turn2"), edit=with_text)
    turns = [m.get("content") for body in sent[2:3] for m in body["messages"] if m["role"] == "assistant"]
    assert turns[-1:] == [said], (
        f"the second reply says {said!r} beside its tool call; the third request's assistant turns hold {turns}: "
        f"every reply goes back as it came, its text too, on every round, so the model reads what it said before it "
        f"asked")
    assert turns == [first, said], (
        f"the first reply says {first!r} and the second {said!r}; the third request's assistant turns hold {turns}: "
        f"an earlier reply goes back as it came on every later round too, its text included, so the model still "
        f"reads what it said first")
