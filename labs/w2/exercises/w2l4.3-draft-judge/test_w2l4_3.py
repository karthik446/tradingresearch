"""w2l4.3 the draft P1 judge: registered as a model grader, marked unvalidated, and refusing to score.

labs/w2/conftest.py installs the offline guard (labs/w2/tools/offline.py) before this file imports evals: socket
connect, connect_ex, sendto, sendmsg, create_connection and getaddrinfo, subprocess.Popen, os.system and the os
exec/spawn/fork functions, httpx's send, and gigai-core's ModelJudge.grade each record the attempt and raise. The
check reads that record after grade returns, so a judge that tries one of them fails even if it catches the error,
and the check costs $0 with or without a key. It guards those entry points only; it is not a sandbox, and like the
rest of the labs it is an honor system.

The samples are an empty reply (parsed, and not parsed), the author's recorded AAPL reply
(tests/fixtures/thesis/AAPL_2026-11-16.reply.json: one swing thesis and two no-trade horizons), that reply with a
second thesis, and a reply with no-trade entries only.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from gigai_core.graders.protocol import CannotGrade

from tradingresearch import evals

JUDGE = "p1_judge"
FIXTURES = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "thesis"
REPLY = json.loads((FIXTURES / "AAPL_2026-11-16.reply.json").read_text())
SAMPLES = {
    "an empty reply": ("ok", {"theses": [], "no_trade": []}),
    "an empty reply that did not parse": ("invalid_json", {"theses": [], "no_trade": []}),
    "the recorded AAPL reply (one swing thesis)": ("ok", REPLY),
    "the recorded reply plus a short-horizon copy of its thesis": (
        "ok", {**REPLY, "theses": [*REPLY["theses"], {**REPLY["theses"][0], "horizon": "short", "hold_sessions": 3}]}),
    "a reply with no-trade entries only": ("ok", {"theses": [], "no_trade": REPLY["no_trade"]}),
}


def judge_class() -> type:
    assert JUDGE in evals.GRADERS, (
        f"No grader is registered under {JUDGE!r}. The experiment configs name p1_judge beside the P2-P4 graders, "
        f"and evals.graders() finds it in evals.GRADERS, which holds {', '.join(evals.GRADERS)}"
    )
    return evals.GRADERS[JUDGE]


def test_the_judge_is_registered_as_an_unvalidated_model_grader():
    cls = judge_class()
    assert cls.id == JUDGE, f"evals.GRADERS[{JUDGE!r}] is {cls.__name__}, whose id is {cls.id!r}"
    assert cls.kind == "model", (
        f"{cls.__name__}.kind is {cls.kind!r}. P1 asks whether the mechanism in a thesis's reason happened, which "
        f"no rule in code decides: a model judges it, and kind 'model' is how a report tells its score from P2-P4's"
    )
    version = getattr(cls, "version", None)
    assert isinstance(version, str) and version, (
        f"{cls.__name__}.version is {version!r} ({type(version).__name__}). Every grader in the registry carries its "
        f"version as a non-empty string (LevelsCoherent has {evals.GRADERS['p4_levels_coherent'].version!r})"
    )
    validated = getattr(cls, "validated", None)
    assert validated is False, (
        f"{cls.__name__}.validated is {validated!r}. A judge is validated only once its scores agree with outcomes, "
        f"and there is no closed trade until week 3: until then validated is False, so no report counts its scores"
    )


@pytest.mark.parametrize("name", SAMPLES)
def test_the_draft_refuses_to_score_without_calling_a_model(name, offline_hits):
    cls = judge_class()
    parse_status, parsed = SAMPLES[name]
    sample = SimpleNamespace(parse_status=parse_status, output_parsed=parsed, trace_id="t")
    try:
        got = cls().grade(sample, {})
    except Exception as exc:  # judged below, outside the handler, so the message is the first line pytest shows
        got = exc
    called = f"{cls.__name__}().grade({name}, {{}})"
    tried = list(dict.fromkeys(offline_hits))
    offline_hits.clear()
    if tried:
        pytest.fail(
            f"{called} tried a network or model call ({', '.join(tried)}), whatever it did with the error. An "
            f"unvalidated judge costs money and returns scores nobody may count yet, so until week 3 it has no reason "
            f"to reach a model at all"
        )
    if isinstance(got, CannotGrade):
        reason = str(got).lower()
        assert "draft" in reason or "validat" in reason, (
            f"{called} raised CannotGrade({got!s}). The judge refuses every sample for one reason, whatever the "
            f"sample holds: it is a draft, not validated. Say so (the word 'draft', or 'validated'), so a report "
            f"shows why P1 has no rate"
        )
        return
    if isinstance(got, Exception):
        pytest.fail(
            f"{called} raised {type(got).__name__}: {got}. The runner leaves a sample out of the rate only on "
            f"CannotGrade; any other exception stops the eval run"
        )
    pytest.fail(
        f"{called} returned {got!r}. A draft judge has no score to give for any reply, empty or full: a score here "
        f"would be counted in P1's rate, and the runner leaves a run out of the rate only when its grader refuses it"
    )
