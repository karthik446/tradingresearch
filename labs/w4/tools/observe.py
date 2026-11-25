"""Observe for the week-4 labs: what your tools, tool loop, tools arm, grader, routes and rule change do ($0, no network).

    python labs/w4/tools/observe.py tools   # w4l1: TOOLS and run_tool on the FAKEA context
    python labs/w4/tools/observe.py loop    # w4l2: analyze_with_tools on the recorded exchange and edits of it
    python labs/w4/tools/observe.py arm     # w4l3.1, w4l3.2: run_tools under a cap, then a tools arm in run_arms
    python labs/w4/tools/observe.py grader  # w4l3.3: tool_calls_ok on five tool-call patterns
    python labs/w4/tools/observe.py clean   # w4l4.1: clean_route and a trainable record on nine routes
    python labs/w4/tools/observe.py route   # w4l4.2: route_for after replayed tool loops served by edited providers
    python labs/w4/tools/observe.py rule    # w4l4.3: the short-sma50-trend filter, then rule-change-1 registered

`tools` prints one row per tool in TOOLS (its arguments, whether the schema is closed, how many arguments carry a
description, and whether it refuses the recorded call to the capture's get_sources), then run_tool's answer to six
calls, then how many of get_indicators' rows carry the number the fixed arm's SOURCES table shows, on the context
with extra digits (tools/fakea.py `context(extra=True)`).

`loop` runs analyze_with_tools through the real OpenRouter adapter whose transport answers with the recorded replies:
first the recorded exchange (inside fakea.capture_tool, so the requests compare with turn1.request.json and
turn2.request.json), then four edits of it: three calls in one reply, a model that never stops asking (max_turns 3),
an HTTP 400, and an HTTP 503 before every reply. The replies cannot react to what you send; the requests, spans and
the sample you end with are what your code decides.

`arm` runs run_tools over FAKEA and FAKEB (fakea.other) under a $0.06 cap, then a $1 cap, then with FAKEA's first call
failing and a grader that scores every sample it is shown; then run_arms with one tools arm (a temp journal; the
context token count is pinned at 1600, because the tokenizer is not on disk, as the checks do) and the route stored for
each item, then a config with the model grader p1_judge beside the tools arm.

`grader` scores five recorded-style samples with tool_calls_ok: the capture's get_sources call answered with an error,
one call made twice, seven distinct calls, three clean calls, and no calls.

`clean` prints clean_route on nine routes, then whether a trainable teacher Analysis (tests/factories.py) is built
with each of them.

`route` replays the recorded loop (turn1 served by Azure, turn2 by Google) with providers edited per request and prints
route_for for the item prompt: the recording, one provider, a null provider, a new exchange for the same item whose
call fails, and two arms pinned to azure and google (each request served by its arm's pinned host).

`rule` prints the short-sma50-trend entry's answer for six short-horizon theses and two swing ones, then loads
experiments/rule-change-1.toml, registers it in a temp journal, and prints the `tr learn --status` lines and the
change pending_for 2026-11-16 and 2026-11-17.

TR_LAB_DATA overrides labs/w4/data. Exits 0 in every mode: it shows what your code does, the exercise's check decides.
The offline guard (tools/offline.py) is installed before your code is imported; a guarded call it tried is named in a
`note:` line at the end.
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import offline  # noqa: E402

offline.install()  # before fakea and your code are imported
import fakea  # noqa: E402

RECORDED_CALL = fakea.load("turn1.reply")["choices"][0]["message"]["tool_calls"][0]["function"]
ROOT = Path(__file__).resolve().parents[3]  # the repo: tests/factories.py, experiments/
SESSION = date(2026, 11, 13)  # fakea.experiment's session
SHORT_PRICES = {"stop": 238.0, "target": 220.0, "invalidation_price": 238.0}  # a valid short around close 230


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


class Seen:
    """A code grader that scores every sample it is shown 1.0 and notes whose sample it was."""

    id, version, kind = "seen", "1", "code"

    def __init__(self):
        self.items: list[str] = []

    def grade(self, sample, expected):
        from gigai_core.graders.protocol import Score

        self.items.append(sample.item_id.split(":")[0])
        return Score(value=1.0, explanation=None)


def tools_run(ex, label: str, replies: tuple[str, ...], max_usd: float = 1.0, graders=(), cycle: bool = True) -> None:
    from gigai_core import Dataset
    from gigai_core.budget import BudgetExceeded

    sent: list[dict] = []
    print(f"\n{label}")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            ctxs = [fakea.context(), fakea.other()]
            config = fakea.experiment(Path(tmp) / "arm.toml", max_usd=max_usd)
            dataset = Dataset.of(config.name, ex.items(config, ctxs))
            by_item = {f"{c.ticker}:{c.session}": c for c in ctxs}
            run = ex.run_tools(config, config.arms[0], dataset, by_item, fakea.replaying(sent, replies, cycle=cycle),
                               list(graders), fakea.prices(), Path(tmp))
        except BudgetExceeded as exc:
            print(f"  {len(sent)} requests sent, then BudgetExceeded: {cut(exc, 110)}")
            return
        except Exception as exc:  # noqa: BLE001 - shown
            print(f"  {len(sent)} requests sent, then raised {type(exc).__name__}: {cut(exc, 110)}")
            return
    print(f"  {len(sent)} requests sent; the run records {run.record.calls_made} calls and ${run.record.spent_usd}")
    print(f"  samples {[(s.item_id.split(':')[0], s.outcome) for s in run.samples]}, scores {len(run.scores)}")


def arms_run(an, ex, journal, label: str, graders: tuple[str, ...]) -> None:
    sent: list[dict] = []
    print(f"\n{label}")
    an.context_tokens = lambda system, prompt: 1600  # the tokenizer is not on disk
    with tempfile.TemporaryDirectory() as tmp:
        config = fakea.experiment(Path(tmp) / "arms.toml", graders=graders, modes=("tools",))
        conn = journal.connect(Path(tmp) / "journal.db")
        try:
            result = ex.run_arms(conn, config, [fakea.context(), fakea.other()],
                                 fakea.replaying(sent, ("turn1", "turn2"), cycle=True), fakea.prices(), Path(tmp))
        except SystemExit as exc:
            print(f"  {len(sent)} requests sent, then refused: {cut(exc, 130)}")
            return
        except Exception as exc:  # noqa: BLE001 - shown
            print(f"  {len(sent)} requests sent, then raised {type(exc).__name__}: {cut(exc, 110)}")
            return
        finally:
            stored = {a.ticker: a.provider_route for a in journal.analyses(conn, SESSION, "main")}
            conn.close()
    print(f"  {len(sent)} requests sent; calls per arm {[arm.run.record.calls_made for arm in result]}")
    print(f"  stored analyses and their routes {stored} (turn1 is served by Azure, turn2 by Google)")


def arm_mode() -> None:
    an, ex, journal = module("analyze"), module("experiment"), module("journal")
    broken = next((m for m in (an, ex, journal) if isinstance(m, str)), None)
    if broken:
        print(f"does not import: {broken}")
        return
    tools_run(ex, "run_tools, FAKEA and FAKEB, a $0.06 cap (their first requests together are planned at $0.081384)",
              ("turn1", "turn2"), max_usd=0.06)
    tools_run(ex, "run_tools, FAKEA and FAKEB, a $1 cap", ("turn1", "turn2"))
    seen = Seen()
    tools_run(ex, "run_tools, FAKEA's first call fails (HTTP 400), a grader that scores what it is shown",
              ("failed", "turn1", "turn2"), graders=(seen,), cycle=False)
    print(f"  the grader was shown {seen.items}")
    arms_run(an, ex, journal, "run_arms, one tools arm, grader parsed", ("parsed",))
    arms_run(an, ex, journal, "run_arms, one tools arm, graders parsed and the model grader p1_judge",
             ("parsed", "p1_judge"))


def grader_mode() -> None:
    from gigai_core.providers import ToolCall
    from gigai_core.sample import Sample
    from gigai_core.trace import ToolSpan

    evals = module("evals")
    if isinstance(evals, str):
        print(f"does not import: {evals}")
        return
    t0 = datetime(2026, 11, 17, tzinfo=UTC)
    rows = '{"rows": [{"name": "close", "value": 101.4}]}'

    def sample(calls) -> Sample:
        spans = tuple(ToolSpan(span_id=f"span_{i}", turn=0, started_at=t0, completed_at=t0, parent_id="span_trial",
                               call=ToolCall(id=f"call_{i}", name=name, arguments=arguments), result=result)
                      for i, (name, arguments, result) in enumerate(calls))
        return Sample(trace_id="trace_lab", run_id="run_lab", item_id="FAKEA:2026-11-13", item_version="1",
                      cluster_id="FAKEA", repeat_index=0, input=(), output_text='{"claims": []}',
                      output_parsed={"claims": []}, parse_status="ok", outcome="succeeded", error=None, spans=spans,
                      recorded_at=t0)

    cases = [
        ("the recorded get_sources call, answered with an error",
         [(RECORDED_CALL["name"], RECORDED_CALL["arguments"], {"error": "unknown tool 'get_sources'"})]),
        ("get_indicators twice, the same names spaced two ways",
         [("get_indicators", '{"names": ["close"]}', rows), ("get_indicators", '{"names":["close"]}', rows)]),
        ("seven distinct get_indicators calls", [("get_indicators", f'{{"names": ["row_{i}"]}}', rows) for i in range(7)]),
        ("three clean calls, one per tool", [("get_indicators", '{"names": ["close"]}', rows),
                                             ("get_levels", "{}", '{"levels": []}'),
                                             ("get_fundamentals", '{"metrics": ["revenue"]}', '{"rows": []}')]),
        ("no tool calls", []),
    ]
    print("tool_calls_ok on five samples (score, explanation):")
    for label, calls in cases:
        try:
            score = evals.GRADERS["tool_calls_ok"]().grade(sample(calls), None)
            print(f"  {label:56} {score.value!r:5} {cut(score.explanation, 60)}")
        except Exception as exc:  # noqa: BLE001 - shown
            print(f"  {label:56} raised {type(exc).__name__}: {cut(exc, 60)}")


def factories():
    sys.path.insert(0, str(ROOT / "tests"))
    import factories as f

    return f


def clean_mode() -> None:
    records = module("records")
    if isinstance(records, str):
        print(f"does not import: {records}")
        return
    f = factories()
    routes = ["openrouter:Azure", "openrouter:deepinfra/fp8/flex", "openrouter:google-vertex", "openrouter:unknown",
              "openrouter:Unknown", "openrouter:mixed(Azure+Google)", "openrouter:mixed(Azure)", "openrouter:", ""]
    print("route                              clean_route  a trainable teacher Analysis with it")
    for route in routes:
        try:
            clean = repr(records.clean_route(route))
        except Exception as exc:  # noqa: BLE001 - shown
            clean = type(exc).__name__
        try:
            f.analysis(arm="teacher", terms_class="trainable", provider_route=route)
            built = "built"
        except Exception as exc:  # noqa: BLE001 - shown
            errors = getattr(exc, "errors", None)
            built = "refused: " + (errors()[0]["msg"] if callable(errors) else f"{type(exc).__name__}: {exc}")
        print(f"  {route!r:34} {clean:12} {cut(built, 90)}")


def served_by(*names):
    """`edit` for fakea.replaying: request i is answered as served by names[i % len(names)] (None: a null one)."""
    def edit(n: int, body: dict) -> dict:
        body["provider"] = names[n % len(names)]
        return body
    return edit


def item_prompt(body: dict) -> str:
    return next(m["content"] for m in body["messages"] if m["role"] == "user")


def looped(provider, ctx=None) -> None:
    try:
        fakea.run(provider, ctx=ctx)
    except Exception as exc:  # noqa: BLE001 - shown
        print(f"  the loop raised {type(exc).__name__}: {cut(exc, 100)}")


def route_mode() -> None:
    openrouter = module("openrouter")
    if isinstance(openrouter, str):
        print(f"does not import: {openrouter}")
        return
    print("route_for(the item prompt) after replayed tool loops (turn1 asks for a tool, turn2 answers):")
    for label, names in (("the recording, served by Azure then Google", ("Azure", "Google")),
                         ("both turns served by Google", ("Google",)),
                         ("turn1's provider is null, turn2 served by Google", (None, "Google"))):
        sent: list[dict] = []
        provider = fakea.replaying(sent, ("turn1", "turn2"), edit=served_by(*names))
        looped(provider)
        print(f"  {label:52} {provider.route_for(item_prompt(sent[0]))}")
    sent = []
    provider = fakea.replaying(sent, ("turn1", "turn2", "failed"), edit=served_by("Azure"))
    looped(provider)
    looped(provider)
    print(f"  {'served by Azure, then a new call that fails':52} {provider.route_for(item_prompt(sent[0]))}"
          f"  (served {len(provider.served)} calls)")
    sent = []

    def pinned(n: int, body: dict) -> dict:
        body["provider"] = ((sent[n].get("provider") or {}).get("only") or ["Azure"])[0].capitalize()
        return body

    base = fakea.replaying(sent, ("turn1", "turn2"), cycle=True, edit=pinned)
    try:
        arms = {pin: base.routed(openrouter.Routing(only=(pin,))) for pin in ("azure", "google")}
    except Exception as exc:  # noqa: BLE001 - shown
        print(f"  routed raised {type(exc).__name__}: {cut(exc, 100)}")
        return
    for arm in arms.values():
        looped(arm)
    prompt = item_prompt(sent[0])
    for name, client in (*arms.items(), ("unpinned", base)):
        print(f"  {'FAKEA on the arm pinned to azure, then google: ' + name:52} {client.route_for(prompt)}"
              f"  (served {len(client.served)} calls)")


def rule_mode() -> None:
    import tomllib

    rules, journal, records = module("rules"), module("journal"), module("records")
    learn = module("commands.learn")
    broken = next((m for m in (rules, journal, records, learn) if isinstance(m, str)), None)
    if broken:
        print(f"does not import: {broken}")
        return
    f = factories()
    rule = rules.CHALLENGER_RULES.get("short-sma50-trend")
    if rule is None:
        print(f"CHALLENGER_RULES has no 'short-sma50-trend' entry ({', '.join(sorted(rules.CHALLENGER_RULES))}); "
              f"below, the function short_with_sma50_trend itself")
        refuse = rules.short_with_sma50_trend
    else:
        print(f"short-sma50-trend: {type(rule).__name__}, {rule.description!r}")
        refuse = getattr(rule, "refuse", lambda t, a: f"not a Filter: {rule!r}")
    for horizon, direction, dist in (("short", "long", -0.4), ("short", "long", 0.4), ("short", "short", 0.4),
                                     ("short", "short", -0.4), ("short", "long", None), ("short", "short", 0.0),
                                     ("swing", "long", -0.4), ("swing", "short", None)):
        values = {"close": 230.0, "atr_14": 4.0} | ({} if dist is None else {"dist_sma_50_atr": dist})
        a = f.analysis(snapshot=f.snapshot(values=values))
        t = f.thesis(a.analysis_id, horizon=horizon, direction=direction,
                     **({} if direction == "long" else SHORT_PRICES))
        try:
            why = refuse(t, a)
            answer = "kept" if why is None else f"refused: {why!r}"
        except Exception as exc:  # noqa: BLE001 - shown
            answer = f"raised {type(exc).__name__}: {exc}"
        print(f"  {horizon:5} {direction:5} dist_sma_50_atr {dist!s:5} {cut(answer, 80)}")
    change = None
    try:
        change = records.RuleChange.model_validate(tomllib.loads((ROOT / "experiments/rule-change-1.toml").read_text()))
        print(f"\nexperiments/rule-change-1.toml: {change.change_id}, diff_ref {change.diff_ref!r}, "
              f"registered_at {change.prereg.registered_at.isoformat()}")
    except Exception as exc:  # noqa: BLE001 - shown
        print(f"\nexperiments/rule-change-1.toml does not load: {cut(exc, 140)}")
    with tempfile.TemporaryDirectory() as tmp:
        conn = journal.connect(Path(tmp) / "journal.db")
        if change is not None:
            try:
                rules.register(conn, change)
                print("registered in a temp journal")
            except Exception as exc:  # noqa: BLE001 - shown
                print(f"register refused it: {cut(exc, 140)}")
        print("tr learn --status on that journal:")
        for line in learn.status_lines(conn):
            print(f"  {line}")
        found = [rules.pending_for(conn, day) for day in (date(2026, 11, 16), date(2026, 11, 17))]
        print(f"pending_for 2026-11-16, 2026-11-17: {[c and c.change_id for c in found]}")
        conn.close()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    modes = {"tools": tools_mode, "loop": loop_mode, "arm": arm_mode, "grader": grader_mode, "clean": clean_mode,
             "route": route_mode, "rule": rule_mode}
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
