"""w4l3.1 the tools arm is a Run: run_tools plans the budget on every item's first request before any call, reserves
every call, grades only succeeded samples (CannotGrade leaves no score), and counts spend and calls from model calls.

The items are FAKEA and copies of it under other tickers (fakea.other), so each has its own tools prompt. The replies
are the recording or edits of it (tools/fakea.py `answer`): `turn1` asks for get_sources (not one of TOOLS, so the loop
answers with an error and calls again), `one_more` asks for get_indicators, `turn2` is the final JSON, `failed` an
HTTP 400. `fakea.costless` drops a reply's usage.cost, so the budget keeps each call's estimate instead of its cost.
The price is the recorded /models row (data/models.json). The replay answers HTTP 400 from request 13 on.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402
from gigai_core import Dataset  # noqa: E402
from gigai_core.budget import BudgetExceeded  # noqa: E402
from gigai_core.graders.protocol import CannotGrade, Score  # noqa: E402

from tradingresearch import analyze as an  # noqa: E402
from tradingresearch import experiment as ex  # noqa: E402

PLAN_2 = 0.081384  # the first requests of FAKEA and FAKEB, as CallBudget estimates them
PLAN_3 = 0.122076  # FAKEA, FAKEB and FAKEC


def contexts(n: int) -> list:
    """FAKEA, FAKEB (its values carry extra digits, so its expected values differ from FAKEA's) and FAKEC."""
    return [fakea.context(), fakea.other(fakea.context(extra=True)), fakea.other(ticker="FAKEC")][:n]


def run_tools(tmp_path, replies, n=2, max_usd=1.0, graders=(), edit=None, cycle=False):
    """run_tools over the first n contexts: (run or the exception it raised, request bodies sent, trace lines)."""
    sent: list[dict] = []
    provider = fakea.replaying(sent, replies, cycle=cycle, edit=edit)
    ctxs = contexts(n)
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = fakea.experiment(tmp_path / "arm.toml", max_usd=max_usd)
    dataset = Dataset.of(config.name, ex.items(config, ctxs))
    by_item = {f"{ctx.ticker}:{ctx.session}": ctx for ctx in ctxs}
    try:
        result = ex.run_tools(config, config.arms[0], dataset, by_item, provider, list(graders), fakea.prices(),
                              tmp_path)
    except BudgetExceeded as exc:
        result = exc
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"run_tools raised {exc!r} with the replies {replies}: a failed call or a model that "
                             f"cannot finish is a failed sample in the run, not an exception") from None
    files = sorted((tmp_path / "traces").glob("*.jsonl"))
    lines = [json.loads(line) for f in files for line in f.read_text().splitlines()]
    return result, sent, lines


def done(result, what: str):
    assert not isinstance(result, BudgetExceeded), f"{what}: run_tools stopped with {result}"
    return result


def first_user(body: dict) -> str:
    return next(m["content"] for m in body["messages"] if m["role"] == "user")


class Recording:
    """A code grader that notes which items it was shown, with the expected value it got, and passes them."""

    id, version, kind = "recording", "1", "code"

    def __init__(self):
        self.seen: list[str] = []
        self.expected: dict[str, object] = {}

    def grade(self, sample, expected) -> Score:
        self.seen.append(sample.item_id)
        self.expected[sample.item_id] = expected
        return Score(value=1.0, explanation=None)


class Refusing:
    id, version, kind = "refusing", "1", "code"

    def grade(self, sample, expected) -> Score:
        raise CannotGrade("this grader grades nothing")


def test_each_item_runs_the_loop_on_its_own_tools_prompt(tmp_path):
    run, sent, _ = run_tools(tmp_path, ("turn1", "turn2"), cycle=True)
    run = done(run, "two items, $1 cap")
    want = [an.tools_prompt(ctx) for ctx in contexts(2) for _ in range(2)]
    got = [first_user(body) for body in sent]
    assert got == want, (
        f"the {len(sent)} requests sent began with the user turns of items "
        f"{[next((c.ticker for c in contexts(2) if an.tools_prompt(c) == g), 'neither') for g in got]}; expected "
        f"FAKEA, FAKEA, FAKEB, FAKEB: each item's two calls ask with that item's tools prompt")
    assert all(body.get("tools") for body in sent), "a request went out with no tools offered"
    assert [s.item_id for s in run.samples] == list(run.items), (
        f"samples {[s.item_id for s in run.samples]} for items {list(run.items)}: one sample per item, in order")
    assert {s.run_id for s in run.samples} == {run.record.run_id}, (
        f"sample run ids {sorted({s.run_id for s in run.samples})} but the record's is {run.record.run_id}")


def test_the_budget_is_planned_on_every_first_request_before_any_call(tmp_path):
    result, sent, _ = run_tools(tmp_path / "low", ("turn1", "turn2"), max_usd=0.0813, cycle=True)
    assert isinstance(result, BudgetExceeded) and sent == [], (
        f"with max_usd_per_arm 0.0813 run_tools sent {len(sent)} requests and "
        f"{'raised ' + str(result) if isinstance(result, BudgetExceeded) else 'finished'}: the two items' first "
        f"requests, system turn and tools prompt with the tools offered, are estimated at ${PLAN_2} together, so the "
        f"run stops before its first call with BudgetExceeded and spends nothing")
    result, sent, _ = run_tools(tmp_path / "high", ("turn1", "turn2"), max_usd=0.0814, cycle=True)
    assert not isinstance(result, BudgetExceeded), (
        f"with max_usd_per_arm 0.0814 run_tools stopped after {len(sent)} requests: {result}. The first requests the "
        f"loop sends (system turn, tools prompt) are estimated at ${PLAN_2}, which fits; the requests the fixed arm "
        f"would send, with the whole context, are $0.083280")


def test_every_call_is_reserved_on_the_one_budget(tmp_path):
    result, sent, lines = run_tools(tmp_path, ("turn1", "turn2"), n=3, max_usd=0.1222, edit=fakea.costless,
                                    cycle=True)
    models = [line for line in lines if line.get("kind") == "model_call"]
    assert isinstance(result, BudgetExceeded) and len(sent) == 3, (
        f"three items planned at ${PLAN_3} under a $0.1222 cap, and the replies report no cost, so each call keeps "
        f"its estimate (about $0.0407) on the budget: the 4th call does not fit. run_tools sent {len(sent)} requests "
        f"and {'raised BudgetExceeded' if isinstance(result, BudgetExceeded) else 'finished'}; every call, the "
        f"second of each item too, is reserved on the one budget the run planned")
    assert len(models) == 3, (
        f"the run stopped after 3 calls but its trace file holds {len(models)} model spans: what ran before the "
        f"refusal stays in the trace")


def test_a_failed_item_is_never_graded_and_cannot_grade_leaves_no_score(tmp_path):
    recording = Recording()
    run, sent, _ = run_tools(tmp_path, ("failed", "turn1", "turn2", "turn1", "turn2"), n=3,
                             graders=(Refusing(), recording))
    run = done(run, "FAKEA's call fails, FAKEB and FAKEC succeed")
    outcomes = {s.item_id.split(":")[0]: s.outcome for s in run.samples}
    assert outcomes == {"FAKEA": "failed", "FAKEB": "succeeded", "FAKEC": "succeeded"}, (
        f"outcomes {outcomes}: FAKEA's only call got an HTTP 400 and the run goes on, keeping its failed sample")
    seen = [item.split(":")[0] for item in recording.seen]
    assert seen == ["FAKEB", "FAKEC"], (
        f"the graders were shown {seen}; expected FAKEB, FAKEC. A failed sample has no answer to grade, so it gets "
        f"no score, and every succeeded sample is shown to every grader, after one that raised CannotGrade too")
    traces = {s.item_id.split(":")[0]: s.trace_id for s in run.samples}
    got = sorted((sc.grader_id, next((k for k, v in traces.items() if v == sc.trace_id), "none")) for sc in run.scores)
    assert got == [("recording", "FAKEB"), ("recording", "FAKEC")], (
        f"scores (grader, item by trace id): {got}; expected one score per succeeded item from the grader that "
        f"graded, carrying that sample's trace id, and none from the grader that raised CannotGrade")
    wrong = [item.split(":")[0] for item, value in recording.expected.items() if value != run.items[item].expected]
    assert not wrong, (
        f"the graders got another item's expected value for {wrong}: FAKEB's values carry extra digits, so its "
        f"expected values differ from FAKEA's, and a sample is graded against its own item")


def test_the_record_counts_every_model_call_and_its_cost(tmp_path):
    replies = ("turn1", "one_more", "turn2", "turn1", "turn2")
    run, sent, lines = run_tools(tmp_path, replies)
    run = done(run, "FAKEA in 3 calls, FAKEB in 2")
    spent = round(sum(fakea.cost_of(r) for r in replies), 6)
    record = run.record
    assert (record.calls_made, record.spent_usd) == (5, spent), (
        f"the record says {record.calls_made} calls and ${record.spent_usd}; FAKEA took 3 model calls and FAKEB 2, "
        f"whose replies report ${spent} in all. Tool calls are not model calls and cost nothing")
    kinds = [line.get("kind") for line in lines]
    assert (kinds.count("model_call"), kinds.count("tool_call"), kinds.count("trial")) == (5, 3, 2), (
        f"the trace file holds {kinds.count('model_call')} model spans, {kinds.count('tool_call')} tool spans and "
        f"{kinds.count('trial')} trial spans; expected 5, 3 and 2: every span of both samples, in one file per run")
    assert Path(record.trace_path).read_text().count("\n") == len(lines), "the record names another trace file"
    assert record.tag == "week4-lab:tools:analyze-1", f"tag {record.tag!r}: experiment name, arm name, prompt"


def test_a_model_that_never_stops_fails_each_item_at_the_cap(tmp_path):
    recording = Recording()
    run, sent, _ = run_tools(tmp_path, ("turn1",), graders=(recording,))
    run = done(run, "every reply asks for a tool")
    per_item = [first_user(body) for body in sent]
    counts = [per_item.count(an.tools_prompt(ctx)) for ctx in contexts(2)]
    assert counts == [an.MAX_TOOL_TURNS] * 2, (
        f"every reply asks for a tool; FAKEA got {counts[0]} calls and FAKEB {counts[1]}. Each item's loop stops at "
        f"MAX_TOOL_TURNS = {an.MAX_TOOL_TURNS} calls ({fakea.STOP_AFTER + 1} is where the replay itself gives up)")
    ends = [(s.outcome, s.error and s.error.code) for s in run.samples]
    assert ends == [("failed", "max_tool_turns")] * 2, f"the samples end {ends}: both fail with max_tool_turns"
    assert recording.seen == [] and run.scores == (), f"failed samples were graded: {recording.seen}"
