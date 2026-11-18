"""Week 4 acceptance: tools over the context, the tool loop, the tool-call grader, the tools-vs-fixed experiment,
ADR-005 and the first RuleChange pre-registration.

Specs: REPO-PLAN "Week 4" and §2.4, PLAN-60 "Week 4". The learner modules are imported inside each test, so before
you write them every test here fails on its own and the rest of the suite still runs.

The contract, in the names these tests use:
- `tools.TOOLS`: the core `ToolSpec`s over what an analysis already holds (Context rows: indicators, levels,
  congestion, regime; EDGAR fact rows). Names are unique and valid for the chat API, every argument is described, and
  each schema is closed (`additionalProperties: false`).
- `tools.run_tool(context, name, arguments)`: offline and deterministic. `arguments` is the raw JSON text the model
  sent. It returns a string. An error (unknown tool, malformed or unknown arguments) is returned as a JSON object
  with a non-empty `"error"` string and is never raised; the unknown-tool error names every tool.
- `analyze.analyze_with_tools(context, provider, *, model, prompt_version, max_turns=MAX_TOOL_TURNS)`: the system
  turn is `system_prompt(prompt_version)`, and the user turn names the ticker and session but carries no source rows
  (the data comes through the tools). It calls with `TOOLS`, runs every tool call with `run_tool`, and sends each
  result back as a `tool` turn. It stops at the first reply without tool calls. It returns a gigai-core `Sample`
  with one `ModelSpan` per call and one `ToolSpan` per executed tool call. After `max_turns` calls without a final
  reply it returns a failed `Sample` (`outcome="failed"`, `error` set) and does not raise.
- `evals.GRADERS["tool_calls_ok"]`: a code grader over `sample.tool_spans` with an int class attribute `max_calls`.
  Its value is 1.0, or 0.0 with an explanation starting `tool_error` (a span's `error` is set or its result is an
  `{"error": ...}` object), `repeated_call` (the same name and arguments twice), or `too_many_calls` (more than
  `max_calls`).
- `experiment.run_arms` runs a `mode="tools"` arm through the loop; a never-ending loop stops at `MAX_TOOL_TURNS`
  calls per item.
- `experiments/tools-vs-fixed.toml`: two arms with the same prompt, model and provider, modes `fixed` and `tools`.
- `docs/adr/ADR-005-tools-vs-fixed-context.md`: the decision, a fixed-vs-tools table whose cells are numbers (with
  the run id they came from) or `awaiting sessions` / `awaiting experiment`, and the consequences.
- `experiments/rule-change-1.toml`: the first RuleChange as TOML, top-level `change_id`, `description`, `diff_ref`,
  `decided = "pending"` and a `[prereg]` table, read with `RuleChange.model_validate(tomllib.loads(text))`. Commit it
  BEFORE the first session it covers, then store it with `rules.register(conn, change)`. Its `diff_ref` is a new
  `rules.CHALLENGER_RULES` entry, not an `example-*` one.

The model replies are one recorded real exchange (claude-sonnet-5.5 through the repo's `OpenRouter`,
2026-11-17 UTC, $0.022888, on the made-up FAKEA context in tests/fixtures/week4/), replayed at the HTTP transport.
The capture used its own tool `get_sources`. Your tool names may differ, so the tests check what `run_tool`
returns for the recorded call and never require fixed names.
"""

from __future__ import annotations

import importlib
import json
import re
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from gigai_core.budget import Price
from gigai_core.providers import ToolCall, ToolSpec
from gigai_core.sample import Sample
from gigai_core.score import Score
from gigai_core.trace import CallError, ToolSpan

from tradingresearch import analyze as an, evals, experiment, journal, rules
from tradingresearch.providers.openrouter import API, OpenRouter
from tradingresearch.records import IndicatorSnapshot, RuleChange, SourceRef

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "week4"
MODEL = an.DEFAULT_MODEL  # the recorded model
PROMPT = "analyze-1"  # the recorded system prompt
TURNS = 6  # a cap the recorded two-turn exchange stays under
ADR = "docs/adr/ADR-005-tools-vs-fixed-context.md"
CONFIG = ROOT / "experiments" / "tools-vs-fixed.toml"
RULE_CHANGE = ROOT / "experiments" / "rule-change-1.toml"
AWAITING = ("awaiting sessions", "awaiting experiment")
METRICS = ("all_claims_valid", "token", "cost", "latency", "tool call")
NUMBER = re.compile(r"\$?-?\d[\d,]*(\.\d+)?\s*(%|ms|s)?", re.IGNORECASE)
RUN_ID = r"\brun_[0-9a-f]{16}\b"
T0 = datetime(2026, 11, 17, tzinfo=UTC)
LIVE_CONTEXT_TOKENS = 1600  # pinned: the student tokenizer downloads from the HF hub


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def tools():
    return importlib.import_module("tradingresearch.tools")


def context() -> an.Context:
    """The hand-built FAKEA context the recorded call was asked about."""
    raw = load("fakea.context")
    return an.Context(raw["ticker"], date.fromisoformat(raw["session"]),
                      IndicatorSnapshot.model_validate_json(json.dumps(raw["snapshot"])),
                      [SourceRef.model_validate_json(json.dumps(s)) for s in raw["sources"]],
                      [an.Row(**r) for r in raw["rows"]])


def recorded_calls() -> list[ToolCall]:
    """The tool calls of the recorded turn-1 reply."""
    message = load("turn1.reply")["choices"][0]["message"]
    return [ToolCall(id=c["id"], name=c["function"]["name"], arguments=c["function"]["arguments"])
            for c in message["tool_calls"]]


def final_text() -> str:
    return load("turn2.reply")["choices"][0]["message"]["content"]


def prices() -> dict[str, Price]:
    """The model's price from the /models row recorded with the exchange."""
    [row] = load("models")["data"]
    return {MODEL: Price(model=MODEL, prompt_usd_per_token=float(row["pricing"]["prompt"]),
                         completion_usd_per_token=float(row["pricing"]["completion"]), fetched_at=T0,
                         source=f"{API}/models")}


def replaying(replies: list[dict], sent: list[dict]) -> OpenRouter:
    """The real adapter; its transport answers the n-th request with replies[n] (the last one once they run out)."""
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=replies[min(len(sent), len(replies)) - 1])

    provider = OpenRouter("not-a-real-key")
    provider._http = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return provider


def recorded(sent: list[dict]) -> OpenRouter:
    return replaying([load("turn1.reply"), load("turn2.reply")], sent)


def looping(sent: list[dict]) -> OpenRouter:
    """Asks for the recorded tool call on every turn: a loop only the turn cap can stop."""
    return replaying([load("turn1.reply")], sent)


def with_tools(provider: OpenRouter, max_turns: int = TURNS) -> Sample:
    return an.analyze_with_tools(context(), provider, model=MODEL, prompt_version=PROMPT, max_turns=max_turns)


def error_of(result: object) -> str:
    """The message of a structured tool error; fails when `result` is not one."""
    assert isinstance(result, str), f"run_tool returned {type(result).__name__}, not str"
    parsed = json.loads(result)
    assert isinstance(parsed, dict) and isinstance(parsed.get("error"), str) and parsed["error"], result
    return parsed["error"]


@pytest.fixture
def pinned_tokens(monkeypatch):
    monkeypatch.setattr(an, "context_tokens", lambda system, prompt: LIVE_CONTEXT_TOKENS)


# ---------- the tools ----------

def test_the_tools_are_core_tool_specs_with_unique_valid_names():
    """Names, descriptions and schemas are part of the prompt: core `ToolSpec`s, API-valid unique names."""
    specs = list(tools().TOOLS)
    assert specs and all(isinstance(s, ToolSpec) for s in specs)
    names = [s.name for s in specs]
    assert len(names) == len(set(names)), names
    for spec in specs:
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", spec.name), spec.name
        assert spec.description.strip(), spec.name


def test_every_tool_argument_is_described_and_every_schema_is_closed():
    """An object schema per tool, a description on each argument, `additionalProperties: false`."""
    for spec in tools().TOOLS:
        schema = json.loads(json.dumps(spec.model_dump(mode="json")["parameters"]))
        assert schema.get("type") == "object" and schema.get("additionalProperties") is False, spec.name
        properties = schema.get("properties", {})
        assert set(schema.get("required", [])) <= set(properties), spec.name
        for name, prop in properties.items():
            assert isinstance(prop.get("description"), str) and prop["description"].strip(), f"{spec.name}.{name}"


def test_an_unknown_tool_is_an_error_that_names_every_tool():
    """An unknown name comes back as `{"error": ...}` listing the real tools; nothing is raised."""
    t = tools()
    message = error_of(t.run_tool(context(), "no_such_tool", "{}"))
    missing = [s.name for s in t.TOOLS if s.name not in message]
    assert not missing, f"the error does not name {missing}: {message}"


@pytest.mark.parametrize("arguments", ["{not json", "[]", '{"no_such_argument": 1}'],
                         ids=["malformed_json", "not_an_object", "unknown_argument"])
def test_bad_arguments_are_an_error_for_every_tool(arguments):
    """Arguments arrive as the model's raw JSON text; malformed or unknown ones are an error, never an exception."""
    t = tools()
    for spec in t.TOOLS:
        error_of(t.run_tool(context(), spec.name, arguments))


# ---------- the tool loop (the recorded exchange) ----------

def test_the_first_request_sends_the_tools_and_no_source_rows():
    """Turn 1: the model, the shipped system prompt, the ticker and session, `TOOLS`, and no source row up front."""
    sent: list[dict] = []
    with_tools(recorded(sent))
    first = sent[0]
    assert first["model"] == MODEL
    assert first["tools"] == [{"type": "function", "function": s.model_dump(mode="json")} for s in tools().TOOLS]
    system, user = first["messages"][:2]
    assert system == {"role": "system", "content": an.system_prompt(PROMPT)}
    assert user["role"] == "user" and "FAKEA" in user["content"] and "2026-11-13" in user["content"]
    shown = "\n".join(str(m.get("content") or "") for m in first["messages"])
    assert not [r.source_id for r in context().rows if r.source_id in shown], "the source rows were sent up front"


def test_the_second_request_answers_each_tool_call_with_its_run_tool_result():
    """Turn 2: turn 1's messages, the assistant's tool calls, then one `tool` turn per call with its id and result."""
    sent: list[dict] = []
    with_tools(recorded(sent))
    first, second = sent[:2]
    calls = recorded_calls()
    n = len(first["messages"])
    assert second["messages"][:n] == first["messages"]
    assistant, *answers = second["messages"][n:]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"] == [{"id": c.id, "type": "function",
                                        "function": {"name": c.name, "arguments": c.arguments}} for c in calls]
    assert [(m["role"], m.get("tool_call_id")) for m in answers] == [("tool", c.id) for c in calls]
    t = tools()
    assert [m["content"] for m in answers] == [t.run_tool(context(), c.name, c.arguments) for c in calls]
    assert second["tools"] == first["tools"]


def test_the_loop_stops_at_the_final_json_and_returns_a_parsed_sample():
    """The first reply without tool calls ends the loop: two calls, a succeeded sample holding the recorded claims."""
    sent: list[dict] = []
    sample = with_tools(recorded(sent))
    assert len(sent) == 2
    assert isinstance(sample, Sample)
    assert (sample.outcome, sample.parse_status, sample.error) == ("succeeded", "ok", None)
    assert sample.output_parsed == json.loads(final_text())
    kept, _ = an.validate_claims(sample.output_parsed, context().values(), "an_week4")
    assert kept, "no claim of the recorded reply survives validate_claims"


def test_every_model_call_and_tool_call_is_in_the_trace():
    """One ModelSpan per call and one ToolSpan per executed tool call, in order."""
    sample = with_tools(recorded([]))
    calls = recorded_calls()
    assert len(sample.model_spans) == 2
    assert list(sample.model_spans[0].tool_calls) == calls
    assert sample.model_spans[1].text == final_text()
    assert [span.call for span in sample.tool_spans] == calls


def test_the_turn_cap_returns_a_failed_sample_without_raising():
    """A model that never stops calling tools gets `max_turns` calls, then a failed sample, not an exception."""
    sent: list[dict] = []
    sample = with_tools(looping(sent), max_turns=3)
    assert len(sent) == 3
    assert sample.outcome == "failed" and sample.error is not None
    assert len(sample.model_spans) == 3


# ---------- the tools arm in an experiment ----------

TOOLS_ARM = f"""name = "week4-tools"
model = "{MODEL}"
max_usd_per_arm = 1.0
tickers = ["FAKEA"]
sessions = ["2026-11-13"]
graders = ["parsed"]

[[arms]]
name = "tools"
prompt = "{PROMPT}"
mode = "tools"
"""


def tools_arm(tmp_path: Path) -> experiment.Config:
    path = tmp_path / "week4-tools.toml"
    path.write_text(TOOLS_ARM)
    return experiment.load(path)


def test_a_tools_arm_runs_through_run_arms(tmp_path, pinned_tokens):
    """`mode="tools"` no longer stops: the arm's requests carry the tools, the analysis is stored, the run is saved."""
    sent: list[dict] = []
    conn = journal.connect(tmp_path / "journal.db")
    [result] = experiment.run_arms(conn, tools_arm(tmp_path), [context()], recorded(sent), prices(), tmp_path)
    assert len(sent) == 2 and all("tools" in body for body in sent)
    assert result.arm.mode == "tools" and result.analyses == 1 and result.path.exists()


def test_a_tools_arm_that_never_stops_makes_no_more_than_the_cap(tmp_path, pinned_tokens):
    """The loop guard holds inside an experiment: at most MAX_TOOL_TURNS calls for the one item, nothing stored."""
    sent: list[dict] = []
    conn = journal.connect(tmp_path / "journal.db")
    [result] = experiment.run_arms(conn, tools_arm(tmp_path), [context()], looping(sent), prices(), tmp_path)
    assert 0 < len(sent) <= an.MAX_TOOL_TURNS
    assert result.analyses == 0


# ---------- the tool-call grader (hand-built samples) ----------

def sample_of(calls: list[tuple[str, str, str, bool]]) -> Sample:
    """A succeeded sample whose ToolSpans are (name, arguments, result, raised) in order."""
    spans = tuple(
        ToolSpan(span_id=f"span_{i}", turn=0, started_at=T0, completed_at=T0, parent_id="span_trial",
                 call=ToolCall(id=f"call_{i}", name=name, arguments=arguments), result=result,
                 error=CallError(code="tool_exception", message="boom", retryable=False) if raised else None)
        for i, (name, arguments, result, raised) in enumerate(calls))
    return Sample(trace_id="trace_week4", run_id="run_week4", item_id="FAKEA:2026-11-13", item_version="1",
                  cluster_id="FAKEA", repeat_index=0, input=(), output_text='{"claims": []}',
                  output_parsed={"claims": []}, parse_status="ok", outcome="succeeded", error=None, spans=spans,
                  recorded_at=T0)


def tool_calls_ok():
    return evals.GRADERS["tool_calls_ok"]


def test_tool_calls_ok_is_a_registered_code_grader_with_a_call_cap():
    cls = tool_calls_ok()
    assert cls.kind == "code" and cls.id == "tool_calls_ok" and cls.version
    assert isinstance(cls.max_calls, int) and cls.max_calls > 0


GRADER_CASES = [
    pytest.param([("lookup", '{"name": "close"}', "101.4", False), ("lookup", '{"name": "rsi_14"}', "61.3", False)],
                 None, id="clean"),
    pytest.param([("lookup", '{"name": "close"}', '{"error": "unknown tool \'lookup\'"}', False)], "tool_error",
                 id="error_result"),
    pytest.param([("lookup", '{"name": "close"}', None, True)], "tool_error", id="raised"),
    pytest.param([("lookup", '{"name": "close"}', "101.4", False), ("lookup", '{"name": "close"}', "101.4", False)],
                 "repeated_call", id="repeated"),
]


@pytest.mark.parametrize(("calls", "reason"), GRADER_CASES)
def test_tool_calls_ok(calls, reason):
    """1.0 for distinct successful calls; 0.0 with the reason prefix for an errored or a repeated call."""
    score = tool_calls_ok()().grade(sample_of(calls), None)
    assert isinstance(score, Score)
    if reason is None:
        assert score.value == 1.0
    else:
        assert score.value == 0.0 and (score.explanation or "").startswith(reason), score.explanation


def test_tool_calls_ok_fails_one_call_over_the_cap():
    """`max_calls` distinct successful calls pass; one more is `too_many_calls`."""
    cls = tool_calls_ok()
    at_cap = [("lookup", json.dumps({"n": i}), "1", False) for i in range(cls.max_calls)]
    assert cls().grade(sample_of(at_cap), None).value == 1.0
    over = cls().grade(sample_of([*at_cap, ("lookup", json.dumps({"n": cls.max_calls}), "1", False)]), None)
    assert over.value == 0.0 and (over.explanation or "").startswith("too_many_calls"), over.explanation


# ---------- the tools-vs-fixed experiment config ----------

def test_the_tools_vs_fixed_experiment_has_two_arms_that_differ_only_in_mode():
    """Same prompt, model and provider; modes fixed and tools; all_claims_valid among the graders."""
    config = experiment.load(CONFIG)
    assert len(config.arms) == 2
    fixed, with_tools_ = sorted(config.arms, key=lambda arm: arm.mode)
    assert (fixed.mode, with_tools_.mode) == ("fixed", "tools")
    assert (fixed.prompt, fixed.model, fixed.provider) == (with_tools_.prompt, with_tools_.model, with_tools_.provider)
    assert "all_claims_valid" in config.graders


# ---------- ADR-005 (structure only) ----------

def first_table(text: str) -> list[list[str]]:
    """The cells of the first markdown table, the separator row dropped."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("|")), None)
    assert start is not None, "ADR-005 has no table"
    block = []
    for line in lines[start:]:
        if not line.lstrip().startswith("|"):
            break
        block.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return [row for row in block if not set("".join(row)) <= set("-: ")]


def test_adr_005_records_the_decision_a_measured_table_and_the_consequences():
    """The ADR labels, the experiment it reads, and a fixed-vs-tools table of numbers (with a run id) or awaiting."""
    path = ROOT / ADR
    assert path.exists(), f"{ADR} is missing"
    text = path.read_text()
    assert text.startswith("# ADR-005")
    for label in ("**Status:**", "**Decision.**", "**Consequences.**"):  # the labels ADR-001..004 use
        assert label in text, label
    assert "tools-vs-fixed.toml" in text
    header, *body = first_table(text)
    assert any("fixed" in c.lower() for c in header) and any("tools" in c.lower() for c in header), header
    for metric in METRICS:
        assert [row for row in body if metric in row[0].lower()], f"no table row for {metric}"
    cells = [cell for row in body for cell in row[1:]]
    for cell in cells:
        assert NUMBER.fullmatch(cell) or cell.lower() in AWAITING, f"not a number or {AWAITING}: {cell!r}"
    if any(NUMBER.fullmatch(cell) for cell in cells):
        assert re.search(RUN_ID, text), "a measured number needs the run id it came from"


# ---------- the first RuleChange pre-registration ----------

def rule_change() -> RuleChange:
    assert RULE_CHANGE.exists(), f"{RULE_CHANGE.relative_to(ROOT)} is missing"
    return RuleChange.model_validate(tomllib.loads(RULE_CHANGE.read_text()))


def test_the_first_rule_change_is_preregistered_by_the_book():
    """§8.2: the horizon's net-R delta as primary metric, the fixed guard, margin, N and pass rule; still pending."""
    change = rule_change()
    horizon = journal.prereg_horizon(change.prereg)
    assert change.prereg.primary_metric == f"{journal.RULE_METRIC}:{horizon}"
    assert change.decided == "pending"
    assert change.prereg.registered_at.tzinfo is not None


def test_the_first_rule_change_names_a_real_challenger_and_registers(tmp_path):
    """The diff_ref resolves to a new registry entry (not an example) and `rules.register` stores it."""
    change = rule_change()
    assert not change.diff_ref.startswith("example-"), change.diff_ref
    assert change.diff_ref in rules.CHALLENGER_RULES
    rules.resolve(change.diff_ref)
    conn = journal.connect(tmp_path / "journal.db")
    rules.register(conn, change)
    assert [c.change_id for c in journal.rule_changes(conn, "pending")] == [change.change_id]
