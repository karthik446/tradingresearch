"""w2l4.3 the draft P1 judge: registered as a model grader, marked unvalidated, and refusing to score.

Every way out to a model is a tripwire here: a socket connection (connect, connect_ex, create_connection), an httpx
request, a subprocess, the judge library's ModelJudge. A draft judge that reaches any of them fails, whether or not a
key is set, so the check costs $0. A determined author can still get past them; the check is an honor system.
"""

import socket
import subprocess
from types import SimpleNamespace

import httpx
import pytest
from gigai_core.graders.protocol import CannotGrade

from tradingresearch import evals

JUDGE = "p1_judge"


class ModelCalled(Exception):
    """Raised by every tripwire: the draft judge tried to reach a model."""


@pytest.fixture
def tripwires(monkeypatch):
    def tripped(*args, **kwargs):
        raise ModelCalled("a network or model call")

    monkeypatch.setattr(socket.socket, "connect", tripped)
    monkeypatch.setattr(socket.socket, "connect_ex", tripped)
    monkeypatch.setattr(socket, "create_connection", tripped)
    monkeypatch.setattr(subprocess.Popen, "__init__", tripped)
    monkeypatch.setattr(httpx.Client, "send", tripped)
    monkeypatch.setattr(httpx.AsyncClient, "send", tripped)
    import gigai_core.graders.judge as judge  # noqa: PLC0415

    monkeypatch.setattr(judge.ModelJudge, "grade", tripped)


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


@pytest.mark.parametrize("parse_status", ("ok", "invalid_json"))
def test_the_draft_refuses_to_score_without_calling_a_model(parse_status, tripwires):
    cls = judge_class()
    sample = SimpleNamespace(parse_status=parse_status, output_parsed={"theses": [], "no_trade": []},
                             trace_id="t")
    try:
        got = cls().grade(sample, {})
    except Exception as exc:  # judged below, outside the handler, so the message is the first line pytest shows
        got = exc
    called = f"{cls.__name__}().grade(a sample with parse_status {parse_status!r}, {{}})"
    if isinstance(got, ModelCalled):
        pytest.fail(
            f"{called} tried a network or model call. An unvalidated judge costs money and returns scores nobody "
            f"may count yet: it raises CannotGrade before anything else"
        )
    if isinstance(got, CannotGrade):
        assert "draft" in str(got), (
            f"{called} raised CannotGrade({got!s}). The judge refuses every sample for one reason, before it looks "
            f"at the sample: it is a draft. Say so (the word 'draft'), so a report shows why P1 has no rate"
        )
        return
    if isinstance(got, Exception):
        pytest.fail(
            f"{called} raised {type(got).__name__}: {got}. The runner leaves a sample out of the rate only on "
            f"CannotGrade; any other exception stops the eval run"
        )
    pytest.fail(
        f"{called} returned {got!r}. A draft judge has no score to give: it raises CannotGrade, so the run is left "
        f"out of P1's rate instead of counted"
    )
