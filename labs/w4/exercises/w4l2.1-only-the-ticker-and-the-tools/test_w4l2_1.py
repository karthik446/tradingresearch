"""w4l2.1 only the ticker and the tools: the tools-mode user turn holds no source row, and the request offers TOOLS.

analyze_with_tools runs on the FAKEA context through the real OpenRouter adapter, whose transport answers with the
recorded replies (labs/w4/data/turn1.reply.json, turn2.reply.json). Inside tools/fakea.py `capture_tool`, TOOLS is the
one tool the recording was made with, so the first request can be compared with the recorded one
(turn1.request.json); outside it, your own three tools are offered.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

from tradingresearch import analyze as an  # noqa: E402
from tradingresearch import openrouter, tools  # noqa: E402

CTX = fakea.context()
RECORDED = fakea.load("turn1.request")


def first_request(capture: bool) -> dict:
    sent: list[dict] = []
    try:
        if capture:
            with fakea.capture_tool():
                fakea.run(fakea.replaying(sent))
        else:
            fakea.run(fakea.replaying(sent))
    except Exception as exc:  # noqa: BLE001 - reported below
        raise AssertionError(f"analyze_with_tools raised {exc!r} on the recorded exchange") from None
    assert sent, "analyze_with_tools sent no request"
    return sent[0]


def test_the_user_turn_is_the_ticker_the_session_and_where_the_rows_are():
    user, rendered = an.tools_prompt(CTX), an.render(CTX).splitlines()
    rows = [line for line in user.splitlines() if any(r.source_id in line for r in CTX.rows)]
    values = [s for _, s, _ in fakea.table(CTX).values() if len(s) >= 4 and re.search(rf"(?<![\w.]){re.escape(s)}(?![\w.])", user)]
    assert not rows and not values, (
        f"tools_prompt's turn holds {len(rows)} of the {len(CTX.rows)} source rows and {len(values)} of their values "
        f"(first: {(rows or values)[0]!r}). In tools mode every number the model cites came through a tool call, "
        f"which the trace records; a row in the prompt is a number no tool call accounts for")
    lines = user.splitlines()
    assert lines[:2] == rendered[:2], f"the turn starts {lines[:2]}; the fixed turn (render) starts {rendered[:2]}"
    assert lines[-1:] == rendered[-1:], f"the turn ends {lines[-1:]}; the fixed turn ends {rendered[-1:]}"
    assert "SOURCES" in user and "tool" in user, (
        "the turn does not say where the rows are: the fixed turn has a SOURCES table here, so this one says the table "
        "is not included and the tools return the rows")


def test_the_first_request_is_the_recorded_one_but_for_the_user_turn():
    sent = first_request(capture=True)
    assert sent["messages"][1:] == [{"role": "user", "content": an.tools_prompt(CTX)}], (
        f"the first request's turns after the system prompt are {str(sent['messages'][1:])[:200]}: one user turn, "
        f"the one tools_prompt writes")
    differ = sorted(k for k in sent.keys() | RECORDED.keys() if k != "messages" and sent.get(k) != RECORDED.get(k))
    assert not differ, (
        f"the first request differs from the recorded one in {', '.join(differ)}; the recording offered "
        f"{[t['function']['name'] for t in RECORDED['tools']]} with tool_choice {RECORDED['tool_choice']!r}, and "
        f"you sent {[t['function']['name'] for t in sent.get('tools') or []]}: a model offered no tool answers from "
        f"the turn alone, with nothing to cite")
    assert sent["messages"][0] == RECORDED["messages"][0], "the system prompt is not the recorded analyze-1 one"


def test_the_request_offers_your_three_tools():
    sent = first_request(capture=False)
    assert sent.get("tools") == [openrouter.tool(spec) for spec in tools.TOOLS], (
        f"the request offers {[t['function']['name'] for t in sent.get('tools') or []]}; TOOLS holds "
        f"{[s.name for s in tools.TOOLS]}, each sent with its description and schema")
