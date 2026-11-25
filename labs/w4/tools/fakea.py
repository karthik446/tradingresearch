"""The tool loop on the FAKEA context, replayed: what the w4l1-w4l2 checks and `observe.py` run.

The context is tests/test_week4.py's hand-built FAKEA ticker-day (labs/w4/data/fakea.context.json, copied from
tests/fixtures/week4): 38 rows, 39 sources, session 2026-11-13. The provider is the real OpenRouter adapter; its HTTP
transport answers with the two recorded replies of one tools-mode exchange (turn1.reply.json asks for a tool,
turn2.reply.json is the final JSON), or with edited copies of them (`answer`). The requests that produced them are
turn1.request.json and turn2.request.json. Nothing here opens a network connection.

The recorded exchange was captured with the capture's own tool, `get_sources`, not with the three tools of
tradingresearch.tools. `capture_tool` puts that tool back for one block, so what your loop sends can be compared with
what was sent; everywhere else your own TOOLS and run_tool answer.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from unittest import mock

import httpx

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[1] / "data")

MODEL = "anthropic/claude-sonnet-5.5"  # the recorded exchange's model
PROMPT = "analyze-1"
STOP_AFTER = 12  # the replay answers HTTP 400 from the 13th request on, so a loop with no cap still ends
EXTRA = 1.0000123  # `context(extra=True)`: every value times this, so it carries digits past what the table shows


def load(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text())


def context(extra: bool = False):
    """The FAKEA context the recorded exchange was asked about. With `extra`, the same rows with each value times
    EXTRA (1.0000123): the unrounded numbers a computed indicator carries, e.g. close 101.4 becomes 101.40124722."""
    from tradingresearch import analyze as an
    from tradingresearch.records import IndicatorSnapshot, SourceRef

    raw = load("fakea.context")
    rows = [an.Row(**r) for r in raw["rows"]]
    if extra:
        rows = [an.Row(**{**r, "value": None if r["value"] is None else r["value"] * EXTRA}) for r in raw["rows"]]
    return an.Context(raw["ticker"], date.fromisoformat(raw["session"]),
                      IndicatorSnapshot.model_validate_json(json.dumps(raw["snapshot"])),
                      [SourceRef.model_validate_json(json.dumps(s)) for s in raw["sources"]], rows)


def table(ctx) -> dict[str, tuple[str, str, str]]:
    """The fixed arm's SOURCES table (analyze.render) for `ctx`: source_id -> (name, shown value or label, unit)."""
    from tradingresearch import analyze as an

    lines = an.render(ctx).split("\n")
    start = lines.index("SOURCES (source_id | name | value | unit)") + 1
    out = {}
    for line in lines[start:]:
        if not line:
            break
        source_id, name, shown, unit = line.split(" | ")
        out[source_id] = (name, shown, unit)
    return out


# ---------- the replies ----------

# Edited copies of turn1.reply, never sent to a model: "three_calls" asks for all three of the shipped tools in one
# reply, "one_more" asks for one more row (a second round), "busy" is an HTTP 503 (the adapter retries it) and
# "failed" an HTTP 400 for a rejected request (no reply, no retry).
THREE_CALLS = (("toolu_lab_1", "get_indicators", '{"names": ["close", "rsi_14"]}'),
               ("toolu_lab_2", "get_levels", "{}"),
               ("toolu_lab_3", "get_fundamentals", '{"metrics": ["revenue"]}'))
ONE_MORE = (("toolu_lab_4", "get_indicators", '{"names": ["sma_50"]}'),)


def answer(kind: str) -> httpx.Response:
    if kind == "failed":
        return httpx.Response(400, json={"error": {"code": 400, "message": "Provider returned error"}})
    if kind == "busy":
        return httpx.Response(503, json={"error": {"code": 503, "message": "Provider overloaded"}})
    if kind == "stopped":
        return httpx.Response(400, json={"error": {"code": 400, "message": f"the lab's replay stops answering after "
                                                                           f"{STOP_AFTER} requests"}})
    if kind == "turn2":
        return httpx.Response(200, json=load("turn2.reply"))
    reply = load("turn1.reply")
    if kind != "turn1":
        calls = {"three_calls": THREE_CALLS, "one_more": ONE_MORE}[kind]
        [template] = reply["choices"][0]["message"]["tool_calls"]
        reply["choices"][0]["message"]["tool_calls"] = [
            {**copy.deepcopy(template), "index": i, "id": id_, "function": {"name": name, "arguments": arguments}}
            for i, (id_, name, arguments) in enumerate(calls)]
    return httpx.Response(200, json=reply)


def replaying(sent: list[dict], replies: tuple[str, ...] = ("turn1", "turn2"), cycle: bool = False):
    """The real adapter, with a retry policy that does not sleep. Request i gets `answer(replies[i])`: the last one
    again once they run out, or from the start again with `cycle`. From request STOP_AFTER + 1 on it gets an HTTP 400.
    `sent` keeps every request body the adapter posted, retries included."""
    from tradingresearch.openrouter import API, OpenRouter
    from tradingresearch.retry import Policy

    def handler(request: httpx.Request) -> httpx.Response:
        n = len(sent)
        sent.append(json.loads(request.content))
        if n >= STOP_AFTER:
            return answer("stopped")
        return answer(replies[n % len(replies)] if cycle else replies[min(n, len(replies) - 1)])

    provider = OpenRouter("not-a-real-key", policy=Policy(sleep=lambda seconds: None))
    provider._http = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return provider


class Capped:
    """A provider whose calls past the first `allowed` are refused before they are sent, the way a spending cap
    (gigai-core CallBudget) refuses a call it cannot afford: BudgetExceeded, which is not a ProviderError."""

    def __init__(self, provider, allowed: int = 1):
        self.provider, self.allowed, self.calls = provider, allowed, 0

    @property
    def identity(self):
        return self.provider.identity

    def invoke(self, request):
        from gigai_core.budget import BudgetExceeded

        if self.calls >= self.allowed:
            raise BudgetExceeded(f"call {self.calls + 1} would pass the run's cap")
        self.calls += 1
        return self.provider.invoke(request)


def run(provider, max_turns: int | None = None, trace=None, ctx=None):
    """analyze_with_tools on the FAKEA context (or `ctx`) with the recorded model and prompt."""
    from tradingresearch import analyze as an

    kwargs = {} if max_turns is None else {"max_turns": max_turns}
    return an.analyze_with_tools(ctx or context(), provider, model=MODEL, prompt_version=PROMPT, trace=trace, **kwargs)


def recorded_tool_turn() -> dict:
    """The `tool` message of turn2.request: what the capture's get_sources answered."""
    [turn] = [m for m in load("turn2.request")["messages"] if m["role"] == "tool"]
    return turn


@contextlib.contextmanager
def capture_tool() -> Iterator[None]:
    """For one block, tradingresearch.tools offers only the capture's own tool, get_sources (its spec is the one in
    turn1.request.json), and run_tool answers the recorded call with the recorded rows (turn2.request.json). So the
    requests your loop sends can be compared with the recorded ones. The capture's tool answered in plain SOURCES
    lines; a ToolSpan keeps a tool's result as JSON, so here the same lines come back as {"sources": "<the lines>"},
    and the tool turn is the one part of the second request that differs from the recording."""
    from gigai_core.providers import ToolSpec
    from tradingresearch import tools

    [offered] = load("turn1.request")["tools"]
    spec = ToolSpec(**offered["function"])
    content = json.dumps({"sources": recorded_tool_turn()["content"]})

    def run_tool(ctx, name: str, arguments: str) -> str:
        return content if name == spec.name else json.dumps({"error": f"unknown tool {name!r}"})

    with mock.patch.object(tools, "TOOLS", (spec,)), mock.patch.object(tools, "run_tool", run_tool):
        yield


# ---------- reading tool results and schemas ----------

def result_of(text: object) -> dict | str:
    """run_tool's text as a dict, or a sentence saying why it is not one."""
    if not isinstance(text, str):
        return f"returned {type(text).__name__} {text!r:.80}, not JSON text"
    try:
        parsed = json.loads(text)
    except ValueError:
        return f"returned {text!r:.80}, which is not JSON"
    return parsed if isinstance(parsed, dict) else f"returned {text!r:.80}, which is not a JSON object"


NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
ANNOTATIONS = {"description", "title", "examples", "default", "$comment"}
READ = {"type", "properties", "additionalProperties", "required", "items", "minItems", "maxItems", "uniqueItems",
        "enum", "const", "minLength", "maxLength", "pattern", "allOf", "anyOf", "oneOf", "not"}
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def unread(schema: object) -> list[str]:
    """The keywords anywhere in `schema` that `refusal` does not read (annotations aside): it judges a value by the
    rest, so a line drawn only with these is not seen."""
    if not isinstance(schema, dict):
        return []
    found = set(schema) - READ - ANNOTATIONS
    subs = [*schema.get("properties", {}).values(), schema.get("items"), schema.get("additionalProperties"),
            schema.get("not"), *schema.get("allOf", []), *schema.get("anyOf", []), *schema.get("oneOf", [])]
    for sub in subs:
        found.update(unread(sub))
    return sorted(found)


def refusal(schema: dict, value: object, where: str = "arguments") -> str | None:
    """Why a JSON-schema validator would refuse `value`, or None when it accepts it. It reads the keywords in READ (the
    ones tool schemas use) and skips any other, judging the value by what it can read; `unread` lists the skipped."""
    for sub in schema.get("allOf", []):
        why = refusal(sub, value, where)
        if why:
            return why
    if "anyOf" in schema and all(refusal(sub, value, where) for sub in schema["anyOf"]):
        return f"{where} is {json.dumps(value)}, which matches none of anyOf"
    if "oneOf" in schema and sum(refusal(sub, value, where) is None for sub in schema["oneOf"]) != 1:
        return f"{where} is {json.dumps(value)}, which does not match exactly one of oneOf"
    if "not" in schema and refusal(schema["not"], value, where) is None:
        return f"{where} is {json.dumps(value)}, which matches the schema under not"
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is(value, t) for t in allowed):
            return f"{where} is {json.dumps(value)}, not of type {schema['type']}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{where} is {json.dumps(value)}, not one of {schema['enum']}"
    if "const" in schema and value != schema["const"]:
        return f"{where} is {json.dumps(value)}, not {json.dumps(schema['const'])}"
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return f"{where} is {json.dumps(value)}, shorter than minLength {schema['minLength']}"
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return f"{where} is {json.dumps(value)}, longer than maxLength {schema['maxLength']}"
        if "pattern" in schema and not re.search(schema["pattern"], value):
            return f"{where} is {json.dumps(value)}, which does not match the pattern {schema['pattern']!r}"
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                return f"{where} has no {key!r}, which is required"
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                why = refusal(props[key], item, f"{where}.{key}")
                if why:
                    return why
            elif schema.get("additionalProperties", True) is False:
                return f"{where} has {key!r}, which is not a listed property"
            elif isinstance(schema.get("additionalProperties"), dict):
                why = refusal(schema["additionalProperties"], item, f"{where}.{key}")
                if why:
                    return why
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            return f"{where} has {len(value)} item(s), fewer than minItems {schema['minItems']}"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{where} has {len(value)} items, more than maxItems {schema['maxItems']}"
        if schema.get("uniqueItems") and len({json.dumps(v) for v in value}) < len(value):
            return f"{where} repeats an item"
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                why = refusal(schema["items"], item, f"{where}[{i}]")
                if why:
                    return why
    return None


def _is(value: object, kind: str) -> bool:
    if kind in ("number", "integer"):
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        return ok and (kind == "number" or float(value).is_integer())
    return isinstance(value, TYPES.get(kind, ()))
