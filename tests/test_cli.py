"""The command table keeps `tr` help byte-identical, and `@grader` registers graders by id (REPO-PLAN §2.2–§2.3)."""

import argparse
from pathlib import Path

import pytest

from tradingresearch.cli import build_parser, main
from tradingresearch.commands import COMMANDS
from tradingresearch.evals import GRADERS, Parsed, grader, graders

HELP = Path(__file__).parent / "fixtures" / "help"
CASES = [("tr", [])] + [(name, [name]) for name in ("sessions", "bars", "facts", "snapshot", "news", "screen",
                                                    "analyze", "thesis", "open", "reconcile", "daily", "check", "exp",
                                                    "usage")]
CASES.append(("exp_run", ["exp", "run"]))


@pytest.mark.parametrize(("golden", "argv"), CASES, ids=[golden for golden, _ in CASES])
def test_help_matches_the_golden_text_captured_before_the_split(golden, argv, monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", "80")  # the golden files were captured at this width
    monkeypatch.setenv("NO_COLOR", "1")
    with pytest.raises(SystemExit) as exit_:
        main([*argv, "--help"])
    assert exit_.value.code == 0
    assert capsys.readouterr().out == (HELP / f"{golden}.txt").read_text()


def test_each_command_module_registers_its_own_command_names():
    seen: set[str] = set()
    for module in COMMANDS:
        sub = argparse.ArgumentParser().add_subparsers()
        module.register(sub)
        names = set(sub.choices)
        assert names, module.__name__
        assert not names & seen, f"{module.__name__} re-registers {names & seen}"
        seen |= names
    top = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    assert seen == set(top.choices)


@pytest.fixture
def registry():
    saved = dict(GRADERS)
    yield GRADERS
    GRADERS.clear()
    GRADERS.update(saved)


def test_a_duplicate_grader_id_raises_and_keeps_the_first(registry):
    class Shadow:
        id = "parsed"

    with pytest.raises(ValueError, match="'parsed' is already registered by Parsed"):
        grader(Shadow)
    assert registry["parsed"] is Parsed


def test_a_decorated_grader_is_registered_and_nameable_from_config(registry):
    @grader
    class Toy:
        id = "toy_test_grader"

    assert registry["toy_test_grader"] is Toy
    assert isinstance(graders(["toy_test_grader"])[0], Toy)


def test_the_registry_starts_with_the_week1_graders():
    assert list(GRADERS)[:4] == ["parsed", "claims_valid", "all_claims_valid", "inferences_grounded"]
