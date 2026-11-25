"""w4l1.1 closed schemas: each tool's parameters list exactly the arguments its handler reads, typed and described,
and allow nothing else.

The project depends on no JSON-schema validator, so the schemas are read with a small one (tools/fakea.py `refusal`):
it reads type, properties, additionalProperties, required, items, minItems, maxItems, uniqueItems, enum and const, and
stops on any other keyword that is not an annotation. Each schema is checked by what it accepts and refuses, so any
schema that draws the same line passes.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

from tradingresearch import tools  # noqa: E402

THREE = ("get_indicators", "get_levels", "get_fundamentals")  # the stub's names; the checks call the tools by them
# What the recorded model sent to the capture's own tool, get_sources: '{"groups": [...]}'.
RECORDED = json.loads(fakea.load("turn1.reply")["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
SERVED = {  # calls each handler answers: every one must pass the schema
    "get_indicators": [{}, {"names": ["close"]}, {"names": ["close", "rsi_14", "regime_spy"]}],
    "get_levels": [{}],
    "get_fundamentals": [{}, {"metrics": list(tools.METRICS)}, *({"metrics": [m]} for m in tools.METRICS)],
}
NOT_SERVED = {  # calls a handler cannot serve: every one must be refused, with why
    "get_indicators": [({"names": []}, "an empty list asks for no row"), ({"names": "close"}, "a string, not a list"),
                       ({"names": [101.4]}, "a number where a row name goes"),
                       ({"metrics": ["revenue"]}, "get_fundamentals's argument, which this handler never reads"),
                       (RECORDED, "the recorded model's arguments to the capture's tool")],
    "get_levels": [({"names": ["level_hvn_1"]}, "the handler reads no argument, so a name filter is ignored"),
                   (RECORDED, "the recorded model's arguments to the capture's tool")],
    "get_fundamentals": [({"metrics": ["ebitda"]}, "ebitda is not one of METRICS"),
                         ({"metrics": []}, "an empty list asks for no metric"),
                         ({"metrics": "revenue"}, "a string, not a list"),
                         ({"names": ["close"]}, "get_indicators's argument, which this handler never reads")],
}


def schema(name: str) -> dict:
    spec = next((s for s in tools.TOOLS if s.name == name), None)
    assert spec is not None, f"TOOLS has no tool named {name!r}: the stub's three tools are {', '.join(THREE)}"
    return spec.parameters


def test_each_name_is_unique_valid_and_served():
    names = [spec.name for spec in tools.TOOLS]
    for name in names:
        assert fakea.NAME.fullmatch(name), f"{name!r} is not a valid tool name for the chat API: 1-64 of A-Z a-z 0-9 _ -"
        assert names.count(name) == 1, (
            f"two tools in TOOLS are named {name!r}: the model calls a tool by its name, so one of the two can never be "
            f"called, and HANDLERS serves only one of them")
        assert name in tools.HANDLERS, f"{name!r} has no handler in HANDLERS: every call to it can only fail"
    assert sorted(names) == sorted(THREE), f"TOOLS offers {names}; the checks need {', '.join(THREE)}"


def test_every_schema_is_closed_and_every_argument_described():
    for name in THREE:
        p = schema(name)
        assert p.get("type") == "object", f"{name}'s schema has type {p.get('type')!r}: arguments are a JSON object"
        assert p.get("additionalProperties") is False, (
            f"{name}'s schema is open: it does not set additionalProperties to false, so any argument passes. The "
            f"recorded model sent {json.dumps(RECORDED)} to its tool; {name} would take the same, its handler would "
            f"ignore it and answer as if asked for nothing")
        props = p.get("properties")
        assert isinstance(props, dict), (
            f"{name}'s schema has no properties object: list the arguments its handler reads (an empty object when it "
            f"reads none), so the model, and run_tool in the next exercise, can see what is allowed")
        for key, sub in props.items():
            text = sub.get("description") if isinstance(sub, dict) else None
            assert isinstance(text, str) and text.strip(), (
                f"{name}'s argument {key!r} has no description: the model sees only its name and type, and has to "
                f"guess what goes in it and what leaving it out means")
        unknown = [k for k in p.get("required", []) if k not in props]
        assert not unknown, f"{name}'s schema requires {unknown}, which it does not list"


def test_each_schema_accepts_every_call_its_handler_serves():
    for name, calls in SERVED.items():
        for args in calls:
            why = fakea.refusal(schema(name), args)
            assert why is None, (
                f"{name}'s schema refuses {json.dumps(args)} ({why}), which its handler serves: a model that follows "
                f"the schema can never ask for it")


def test_each_schema_refuses_what_its_handler_cannot_serve():
    for name, calls in NOT_SERVED.items():
        for args, reason in calls:
            assert fakea.refusal(schema(name), args) is not None, (
                f"{name}'s schema accepts {json.dumps(args)}: {reason}. The schema is all the model knows about the "
                f"tool, so what it accepts is what the model may send")
