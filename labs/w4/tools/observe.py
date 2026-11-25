"""Observe for the week-4 labs: what your tools answer and what your tool loop sends, keeps and ends with ($0, no network).

    python labs/w4/tools/observe.py tools   # w4l1: TOOLS and run_tool on the FAKEA context
    python labs/w4/tools/observe.py loop    # w4l2: analyze_with_tools on the recorded exchange and edits of it

`tools` prints one row per tool in TOOLS (its arguments, whether the schema is closed, how many arguments carry a
description, and whether it refuses the recorded call to the capture's get_sources), then run_tool's answer to six
calls, then how many of get_indicators' rows carry the number the fixed arm's SOURCES table shows, on the context
with extra digits (tools/fakea.py `context(extra=True)`).

`loop` runs analyze_with_tools through the real OpenRouter adapter whose transport answers with the recorded replies:
first the recorded exchange (inside fakea.capture_tool, so the requests compare with turn1.request.json and
turn2.request.json), then four edits of it: three calls in one reply, a model that never stops asking (max_turns 3),
an HTTP 400, and an HTTP 503 before every reply. The replies cannot react to what you send; the requests, spans and
the sample you end with are what your code decides.

TR_LAB_DATA overrides labs/w4/data. Exits 0 in every mode: it shows what your code does, the exercise's check decides.
The offline guard (tools/offline.py) is installed before your code is imported; a guarded call it tried is named in a
`note:` line at the end.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline  # noqa: E402

offline.install()  # before fakea and your code are imported
import fakea  # noqa: E402

RECORDED_CALL = fakea.load("turn1.reply")["choices"][0]["message"]["tool_calls"][0]["function"]


def module(name: str) -> object | str:
    try:
        return importlib.import_module(f"tradingresearch.{name}")
    except Exception as exc:  # a learner's half-written file: show it, keep going
        return f"{type(exc).__name__}: {exc}"


def cut(text: str, width: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def answered(tools, ctx, name: str, arguments: str) -> str:
    try:
        result = fakea.result_of(tools.run_tool(ctx, name, arguments))
    except Exception as exc:  # noqa: BLE001 - shown
        return f"raised {type(exc).__name__}: {exc}"
    if isinstance(result, str):
        return result
    if "error" in result:
        return f"error: {result['error']}"
    rows = result.get("rows")
    if not isinstance(rows, list):
        return f"no rows list: {json.dumps(result)}"
    return f"{len(rows)} rows, first {json.dumps(rows[0]) if rows else None}"


def tools_mode() -> None:
    tools = module("tools")
    if isinstance(tools, str):
        print(f"tradingresearch.tools does not import: {tools}")
        return
    print("TOOLS")
    for spec in tools.TOOLS:
        schema = spec.parameters if isinstance(spec.parameters, dict) else {}
        props = schema.get("properties") or {}
        described = sum(1 for p in props.values() if isinstance(p, dict) and p.get("description"))
        refused = fakea.refusal(schema, json.loads(RECORDED_CALL["arguments"])) is not None
        print(f"  {spec.name:<17} arguments {sorted(props)}  closed {schema.get('additionalProperties') is False}  "
              f"described {described}/{len(props)}  refuses {RECORDED_CALL['arguments']}: {refused}")
    ctx = fakea.context()
    print("\nrun_tool on the FAKEA context")
    for name, arguments in (("get_indicators", '{"names": ["close", "rsi_14"]}'), (RECORDED_CALL["name"],
                            RECORDED_CALL["arguments"]), ("get_indicators", "{not json"),
                            ("get_indicators", '{"names": ["rsi"]}'), ("get_levels", "{}"),
                            ("get_fundamentals", '{"metrics": ["ebitda"]}')):
        print(f"  {name} {arguments}\n      {cut(answered(tools, ctx, name, arguments), 150)}")
    extra = fakea.context(extra=True)
    shown = fakea.table(extra)
    try:
        rows = json.loads(tools.run_tool(extra, "get_indicators", "{}"))["rows"]
        same = [r for r in rows if r.get("source_id") in shown and shown[r["source_id"]][1] in
                (str(r.get("value")).removesuffix(".0"), r.get("label"))]
        print(f"\nget_indicators on the context with extra digits: {len(same)} of {len(rows)} rows carry the value the "
              f"SOURCES table shows")
        for r in [r for r in rows if r not in same][:3]:
            table = shown[r["source_id"]][1] if r.get("source_id") in shown else "? (no source_id to look up)"
            print(f"  differs: {cut(json.dumps(r), 90)}  table shows {table}")
    except Exception as exc:  # noqa: BLE001 - shown
        print(f"\nget_indicators on the context with extra digits: raised {type(exc).__name__}: {exc}")


def loop_run(label: str, replies: tuple[str, ...], capture: bool = False, cycle: bool = False,
             max_turns: int | None = None) -> list[dict]:
    from gigai_core.trace import ListTrace

    sent: list[dict] = []
    trace = ListTrace()
    print(f"\n{label}")
    try:
        if capture:
            with fakea.capture_tool():
                sample = fakea.run(fakea.replaying(sent, replies, cycle), max_turns, trace)
        else:
            sample = fakea.run(fakea.replaying(sent, replies, cycle), max_turns, trace)
    except Exception as exc:  # noqa: BLE001 - shown
        print(f"  {len(sent)} requests, then raised {type(exc).__name__}: {cut(exc, 120)}")
        return sent
    tool_turns = [m.get("tool_call_id") for m in (sent[-1]["messages"] if sent else []) if m["role"] == "tool"]
    parsed = sample.output_parsed
    claims = len(parsed.get("claims", [])) if isinstance(parsed, dict) else None
    print(f"  requests {len(sent)}  tool turns in the last {len(tool_turns)} {tool_turns[:3]}")
    print(f"  sample {sample.outcome}, parse {sample.parse_status}, error "
          f"{sample.error.code if sample.error else None}, claims {claims}")
    print(f"  trace {[type(s).__name__ for s in trace.spans]}")
    print(f"  sample spans: model {len(sample.model_spans)}, tool {len(sample.tool_spans)}")
    return sent


def loop_mode() -> None:
    an, tools = module("analyze"), module("tools")
    if isinstance(an, str) or isinstance(tools, str):
        print(f"does not import: {an if isinstance(an, str) else tools}")
        return
    ctx = fakea.context()
    try:
        user = an.tools_prompt(ctx)
        rows = [r.source_id for r in ctx.rows if r.source_id in user]
        print(f"tools_prompt: {len(user)} chars, {len(rows)} of {len(ctx.rows)} source rows, render's is "
              f"{len(an.render(ctx))} chars")
    except Exception as exc:  # noqa: BLE001 - shown
        print(f"tools_prompt raised {type(exc).__name__}: {exc}")
    sent = loop_run("the recorded exchange (the capture's tool, get_sources)", ("turn1", "turn2"), capture=True)
    for i, name in enumerate(("turn1.request", "turn2.request")[: len(sent)]):
        recorded = fakea.load(name)
        keys = sorted(k for k in sent[i].keys() | recorded.keys() if sent[i].get(k) != recorded.get(k))
        turns = [j for j, (a, b) in enumerate(zip(sent[i]["messages"], recorded["messages"])) if a != b]
        print(f"  request {i + 1} vs {name}: keys that differ {keys}, turns that differ {turns} of "
              f"{len(recorded['messages'])} (the user turn is 1, the tool turn 3)")
    sent = loop_run("your three tools, three calls in one reply", ("three_calls", "turn2"))
    print(f"  tools offered {[t['function']['name'] for t in sent[0].get('tools') or []] if sent else []}")
    loop_run(f"a model that never stops asking, max_turns 3 (the replay stops at {fakea.STOP_AFTER})", ("turn1",),
             max_turns=3)
    loop_run("an HTTP 400 on the second call", ("turn1", "failed"))
    loop_run("an HTTP 503 before every reply, max_turns 3", ("busy", "turn1"), cycle=True, max_turns=3)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    modes = {"tools": tools_mode, "loop": loop_mode}
    if mode not in modes:
        print(f"usage: python labs/w4/tools/observe.py {'|'.join(modes)}")
        return 2
    modes[mode]()
    if offline.HITS:
        print(f"note: your code tried {', '.join(dict.fromkeys(offline.HITS))}: blocked, the week-4 labs open no "
              f"connection and start no process")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
