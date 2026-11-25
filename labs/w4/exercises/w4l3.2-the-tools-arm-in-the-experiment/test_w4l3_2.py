"""w4l3.2 the tools arm in the experiment: run_arms runs a mode = tools arm through run_tools, refuses a model grader
beside it before any call, stores each parsed item, and stores the route of the exchange's first user turn.

Two items, FAKEA and FAKEB (fakea.other: the same context under another ticker). The replies are the recording or
edits of it (tools/fakea.py `answer`): `turn1` asks for a tool, `turn2` is the final JSON. A config with two arms
lists ten tickers, because a two-arm config needs ten clusters; the items are still FAKEA and FAKEB. Storing an
analysis counts its context tokens with a tokenizer that is not on disk, so the checks pin that count, as the repo's
tests do. The replay answers HTTP 400 from request 13 on.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402
from gigai_core.graders.protocol import CannotGrade  # noqa: E402

from tradingresearch import analyze as an  # noqa: E402
from tradingresearch import evals  # noqa: E402
from tradingresearch import experiment as ex  # noqa: E402
from tradingresearch import journal  # noqa: E402

SESSION = date(2026, 11, 13)
TEN = ("FAKEA", "FAKEB", "FAKEC", "FAKED", "FAKEE", "FAKEF", "FAKEG", "FAKEH", "FAKEI", "FAKEJ")


@pytest.fixture(autouse=True)
def pinned_tokens(monkeypatch):
    monkeypatch.setattr(an, "context_tokens", lambda system, prompt: 1600)


def served_by(*hosts: str):
    """`edit` for fakea.replaying: request i is answered as served by hosts[i]."""
    def edit(n: int, body: dict) -> dict:
        body["provider"] = hosts[n % len(hosts)]
        return body
    return edit


def run_arms(tmp_path, modes, replies, graders=("parsed",), cycle=False, edit=None, tickers=("FAKEA", "FAKEB")):
    """run_arms on FAKEA and FAKEB: (results or the SystemExit raised, request bodies sent, stored analyses)."""
    sent: list[dict] = []
    provider = fakea.replaying(sent, replies, cycle=cycle, edit=edit)
    config = fakea.experiment(tmp_path / "arms.toml", graders=graders, modes=modes, tickers=tickers)
    conn = journal.connect(tmp_path / "journal.db")
    try:
        result = ex.run_arms(conn, config, [fakea.context(), fakea.other()], provider, fakea.prices(), tmp_path)
    except SystemExit as exc:
        result = exc
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"run_arms raised {exc!r} for arms {list(modes)}: a tools arm runs through run_tools; "
                             f"only a config it refuses stops it, and that stop is a SystemExit") from None
    return result, sent, journal.analyses(conn, SESSION, "main")


def finished(result, what: str) -> list:
    assert not isinstance(result, SystemExit), f"{what}: run_arms refused the config: {result}"
    return result


def test_a_tools_arm_runs_the_loop_and_stores_each_parsed_item(tmp_path):
    result, sent, stored = run_arms(tmp_path, ("tools",), ("turn1", "turn2"), cycle=True)
    [arm] = finished(result, "one tools arm")
    assert (len(sent), arm.run.record.calls_made) == (4, 4), (
        f"{len(sent)} requests sent and the run records {arm.run.record.calls_made} calls; each item's loop asks for a "
        f"tool and then answers, so 2 calls each, 4 in all")
    assert all(body.get("tools") for body in sent), "a tools arm request went out with no tools offered"
    assert (arm.analyses, sorted(a.ticker for a in stored)) == (2, ["FAKEA", "FAKEB"]), (
        f"{arm.analyses} analyses counted and {sorted(a.ticker for a in stored)} stored; both items parsed, so both "
        f"are stored, as a fixed arm's are")
    assert arm.path.exists(), f"the run file {arm.path} was not saved"
    graded = sorted((s.grader_id, s.value) for s in arm.run.scores)
    assert graded == [("parsed", 1.0), ("parsed", 1.0)], (
        f"the tools arm's scores (grader, value): {graded}; the config's graders, parsed here, score each "
        f"succeeded sample of a tools arm as they do a fixed arm's")


def test_a_fixed_and_a_tools_arm_run_side_by_side(tmp_path):
    replies = ("turn2", "turn2", "turn1", "turn2", "turn1", "turn2")
    result, sent, stored = run_arms(tmp_path, ("fixed", "tools"), replies, tickers=TEN,
                                    edit=served_by("Anthropic", "Azure", "Google"))
    arms = finished(result, "a fixed and a tools arm")
    got = [(a.arm.mode, a.run.record.calls_made, a.analyses) for a in arms]
    assert got == [("fixed", 2, 2), ("tools", 4, 2)], (
        f"(mode, calls, stored) per arm: {got}; expected the fixed arm on core run, one call per item, then the tools "
        f"arm through the loop, two calls per item, each storing both items")
    offered = [bool(body.get("tools")) for body in sent]
    assert offered == [False, False, True, True, True, True], (
        f"tools offered per request: {offered}; the fixed arm sends the context and no tools, the tools arm offers "
        f"them on every call")
    fixed = {a.ticker: a.provider_route for a in stored if a.run_id == arms[0].run.record.run_id}
    assert fixed == {"FAKEA": "openrouter:Anthropic", "FAKEB": "openrouter:Azure"}, (
        f"the fixed arm's stored routes {fixed}; its calls for FAKEA and FAKEB were served by Anthropic and Azure. A "
        f"fixed arm's exchange begins with the item's prompt, so that is the turn to ask the route of")


def test_each_item_is_stored_with_the_route_of_its_own_exchange(tmp_path):
    result, sent, stored = run_arms(tmp_path, ("tools",), ("turn2",), edit=served_by("Azure", "Google"))
    finished(result, "one tools arm, each item answered at once")
    routes = {a.ticker: a.provider_route for a in stored}
    assert routes == {"FAKEA": "openrouter:Azure", "FAKEB": "openrouter:Google"}, (
        f"stored routes {routes}; each item answered on its first call, FAKEA's served by Azure and FAKEB's by "
        f"Google. The adapter logs a route under the exchange's user turn, and in tools mode that turn is the "
        f"item's tools prompt, not the item's dataset prompt (asking for that one gives openrouter:unknown)")


class LabJudge:
    """A grader of kind model that is not p1_judge."""

    id, version, kind = "lab_judge", "1", "model"

    def grade(self, sample, expected):
        raise CannotGrade("a lab judge grades nothing")


@pytest.mark.parametrize("modes,judge", [(("tools",), "p1_judge"), (("fixed", "tools"), "p1_judge"),
                                         (("tools",), "lab_judge")],
                         ids=["tools-arm", "tools-arm-second", "another-model-grader"])
def test_a_model_grader_beside_a_tools_arm_is_refused_before_any_call(tmp_path, monkeypatch, modes, judge):
    monkeypatch.setitem(evals.GRADERS, "lab_judge", LabJudge)
    result, sent, stored = run_arms(tmp_path, modes, ("turn2",), graders=("parsed", judge), tickers=TEN)
    assert isinstance(result, SystemExit) and sent == [], (
        f"arms {list(modes)} graded by parsed and {judge} (kind model): run_arms "
        f"{'refused' if isinstance(result, SystemExit) else 'ran'} after {len(sent)} requests. A model grader cannot "
        f"read a tool loop, so the config is refused (SystemExit) before the first arm, with no request sent")
    assert stored == [], f"a refused config stored {len(stored)} analyses"


def test_a_model_grader_on_a_fixed_only_config_still_runs(tmp_path):
    result, sent, stored = run_arms(tmp_path, ("fixed",), ("turn2",), graders=("parsed", "p1_judge"))
    [arm] = finished(result, "one fixed arm graded by parsed and p1_judge")
    assert (len(sent), arm.analyses) == (2, 2), (
        f"{len(sent)} requests and {arm.analyses} analyses; the refusal is for a tools arm only: a fixed arm with a "
        f"model grader runs as before")


def test_a_tools_arm_that_never_stops_makes_at_most_the_cap_per_item(tmp_path):
    result, sent, stored = run_arms(tmp_path, ("tools",), ("turn1",))
    [arm] = finished(result, "every reply asks for a tool")
    per_item = [sum(1 for body in sent if any(m.get("content") == an.tools_prompt(ctx) for m in body["messages"]))
                for ctx in (fakea.context(), fakea.other())]
    assert per_item == [an.MAX_TOOL_TURNS] * 2, (
        f"every reply asks for a tool; FAKEA got {per_item[0]} calls and FAKEB {per_item[1]}: each item's loop stops "
        f"at MAX_TOOL_TURNS = {an.MAX_TOOL_TURNS} ({fakea.STOP_AFTER + 1} is where the replay itself gives up)")
    assert (arm.analyses, stored) == (0, []), f"{arm.analyses} analyses from samples that never answered"
