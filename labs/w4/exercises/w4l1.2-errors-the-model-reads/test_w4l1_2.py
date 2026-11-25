"""w4l1.2 errors the model reads: every mistake in a call comes back from run_tool as {"error": ...}, never raised.

run_tool gets the raw argument text the model sent. The calls here are the recorded model's own call (to the capture's
tool, get_sources, which is not one of yours) and calls a model can plausibly send: text that is not JSON, JSON that is
not an object, an argument the schema does not list, a value that is not a non-empty list of strings, a metric that
does not exist. Each one, for every tool, must be an object with one key, "error", holding a sentence that names the
tool and, for arguments that are not an object, says so in words, never in Python's.
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

from tradingresearch import tools  # noqa: E402

[RECORDED] = fakea.load("turn1.reply")["choices"][0]["message"]["tool_calls"]  # get_sources {"groups": [...]}
THREE = ("get_indicators", "get_levels", "get_fundamentals")
NOT_AN_OBJECT = [("{names: [close]}", "text that is not JSON"), ("[]", "a JSON array"), ('"close"', "a JSON string"),
                 ("null", "JSON null"), ("7", "a JSON number")]
BAD_VALUE = [('"close"', "a string, not a list"), ("[]", "an empty list"), ("[14]", "a list of numbers"),
             ('["close", 14]', "a list with a number after its first item"), ('{"close": 1}', "an object, not a list")]
INTERNALS = ("object has no attribute", "object is not", "not iterable", "not subscriptable", "Traceback")
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
        error = error_of(name, arguments, why)
        assert name in error, (
            f"the error for run_tool({name!r}, {arguments!r}) is {error!r}: it does not name {name}. One reply can call "
            f"several tools, and the model reads their answers side by side, so each error says which tool it is from")
        if arguments in dict(NOT_AN_OBJECT):
            leaked = [w for w in INTERNALS if w in error]
            assert "object" in error and not leaked, (
                f"the error for {dict(NOT_AN_OBJECT)[arguments]}, {arguments!r}, is {error!r}: the model reads it to fix "
                f"its next call, so it says in a sentence that the arguments must be a JSON object, never Python's "
                f"words for what broke inside the tool")


def test_no_arguments_returns_every_row_of_the_tool():
    every = Counter(row.name for row in fakea.context().rows)
    for arguments in ("", "{}"):
        names: list[str] = []
        for name in THREE:
            got = call(name, arguments)
            assert isinstance(got, dict), got
            assert isinstance(got.get("rows"), list) and got["rows"], (
                f"run_tool({name!r}, {arguments!r}) returned {json.dumps(got)[:200]}: a call with no arguments asks "
                f"for every row of the tool (some providers send an empty text for it)")
            names += [str(row.get("name")) if isinstance(row, dict) else repr(row) for row in got["rows"]]
        lost, twice = list((every - Counter(names)).elements()), list((Counter(names) - every).elements())
        assert not lost and not twice, (
            f"with the arguments {arguments!r} the three tools return {len(names)} rows between them; the FAKEA "
            f"context has {sum(every.values())}" + (f", and none of them returns {', '.join(lost[:5])}" if lost else "")
            + (f"; {', '.join(sorted(set(twice))[:5])} come back more than once" if twice else "")
            + ": each handler picks its share of the context, and a call with no arguments answers all of it, each row "
            "once. A row left out is a number the model can never cite")


def test_a_good_call_with_arguments_returns_rows():
    for name, arguments in (("get_indicators", '{"names": ["close"]}'), ("get_fundamentals", '{"metrics": ["revenue"]}')):
        got = call(name, arguments)
        assert isinstance(got, dict), got
        assert isinstance(got.get("rows"), list) and got["rows"], (
            f"run_tool({name!r}, {arguments!r}) returned {json.dumps(got)[:200]}: the schema allows that call and the "
            f"handler serves it, so it is answered with rows. A check that refuses every argument turns each good "
            f"question into an error the model cannot fix")
