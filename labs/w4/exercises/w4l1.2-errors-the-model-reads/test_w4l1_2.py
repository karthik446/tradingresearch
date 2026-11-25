"""w4l1.2 errors the model reads: every mistake in a call comes back from run_tool as {"error": ...}, never raised.

run_tool gets the raw argument text the model sent. The calls here are the recorded model's own call (to the capture's
tool, get_sources, which is not one of yours) and calls a model can plausibly send: text that is not JSON, JSON that is
not an object, an argument the schema does not list, a value that is not a non-empty list of strings, a metric that
does not exist. Each one, for every tool, must be an object with one key, "error", holding a non-empty sentence.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

from tradingresearch import tools  # noqa: E402

[RECORDED] = fakea.load("turn1.reply")["choices"][0]["message"]["tool_calls"]  # get_sources {"groups": [...]}
THREE = ("get_indicators", "get_levels", "get_fundamentals")
NOT_AN_OBJECT = [("{names: [close]}", "text that is not JSON"), ("[]", "a JSON array"), ('"close"', "a JSON string"),
                 ("null", "JSON null"), ("7", "a JSON number")]
BAD_VALUE = [('"close"', "a string, not a list"), ("[]", "an empty list"), ("[14]", "a list of numbers"),
             ('{"close": 1}', "an object, not a list")]
CASES = [(name, text, why) for name in THREE for text, why in NOT_AN_OBJECT]
CASES += [(name, RECORDED["function"]["arguments"], "the recorded model's argument 'groups', which no schema lists")
          for name in THREE]
CASES += [("get_levels", '{"names": ["level_hvn_1"]}', "an argument get_levels's schema does not list")]
CASES += [(name, f'{{"{key}": {value}}}', f"{key} as {why}")
          for name, key in (("get_indicators", "names"), ("get_fundamentals", "metrics")) for value, why in BAD_VALUE]
CASES += [("get_fundamentals", '{"metrics": ["ebitda"]}', "a metric there is not (the ToolError fundamentals raises)")]


def call(name: str, arguments: str) -> dict | str:
    """run_tool on the FAKEA context: the parsed result, or a sentence saying what went wrong instead."""
    try:
        text = tools.run_tool(fakea.context(), name, arguments)
    except Exception as exc:  # noqa: BLE001 - a raise is the failure this check reports
        return (f"run_tool({name!r}, {arguments!r}) raised {exc!r}. The model never reads an exception: the loop's "
                f"turn ends in a crash instead of an answer it can correct")
    got = fakea.result_of(text)
    return got if isinstance(got, dict) else f"run_tool({name!r}, {arguments!r}) {got}"


def error_of(name: str, arguments: str, why: str) -> str:
    got = call(name, arguments)
    assert isinstance(got, dict), got
    assert "rows" not in got, (
        f"run_tool({name!r}, {arguments!r}) answered with {len(got['rows'])} rows: {why} is a mistake, and rows hide it "
        f"from the model, which then cites an answer to a question it did not ask")
    assert set(got) == {"error"} and isinstance(got["error"], str) and got["error"].strip(), (
        f"run_tool({name!r}, {arguments!r}) returned {json.dumps(got)[:200]}: an error is an object with one key, "
        f"\"error\", holding a non-empty sentence")
    return got["error"]


def test_an_unknown_tool_is_an_error_that_names_every_tool():
    name, arguments = RECORDED["function"]["name"], RECORDED["function"]["arguments"]
    error = error_of(name, arguments, f"{name!r}, the capture's own tool, which TOOLS does not offer,")
    missing = [spec.name for spec in tools.TOOLS if spec.name not in error]
    assert not missing, (
        f"the error for the recorded call to {name!r} is {error!r}; it does not name {', '.join(missing)}. The model "
        f"called a tool it was never offered; it can only call a real one next if the error lists them all")


def test_every_bad_call_is_an_error_for_every_tool():
    for name, arguments, why in CASES:
        error_of(name, arguments, why)


def test_no_arguments_returns_every_row_of_the_tool():
    for name in THREE:
        for arguments in ("", "{}"):
            got = call(name, arguments)
            assert isinstance(got, dict), got
            assert isinstance(got.get("rows"), list) and got["rows"], (
                f"run_tool({name!r}, {arguments!r}) returned {json.dumps(got)[:200]}: a call with no arguments asks "
                f"for every row of the tool (some providers send an empty text for it)")
