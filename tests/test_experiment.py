"""The `mode` and `drop` arm knobs (REPO-PLAN §2.4 week 4, §2.5 week 5), checked at config load.
tests/test_week4.py runs a tools arm, tests/test_masking.py two drop arms."""

import re
from pathlib import Path

import pytest

from tradingresearch import experiment

CONFIG = """name = "modes"
model = "openai/gpt-4.1-nano"
max_usd_per_arm = 0.01
tickers = ["AAPL"]
sessions = ["2026-11-13"]
graders = ["parsed"]

[[arms]]
name = "baseline"
prompt = "analyze-1"
"""


def config(tmp_path: Path, mode: str | None) -> Path:
    path = tmp_path / "modes.toml"
    path.write_text(CONFIG + (f'mode = "{mode}"\n' if mode else ""))
    return path


def test_mode_defaults_to_fixed_and_accepts_tools(tmp_path):
    assert experiment.load(config(tmp_path, None)).arms[0].mode == "fixed"
    assert experiment.load(config(tmp_path, "tools")).arms[0].mode == "tools"


def test_an_unknown_mode_is_refused_at_load(tmp_path):
    path = config(tmp_path, "agentic")
    with pytest.raises(SystemExit, match=r"arm baseline: mode must be one of fixed, tools, not 'agentic'"):
        experiment.load(path)


def with_drop(tmp_path: Path, line: str) -> Path:
    path = tmp_path / "drop.toml"
    path.write_text(CONFIG + line + "\n")
    return path


def test_drop_defaults_to_empty_and_takes_section_names(tmp_path):
    assert experiment.load(config(tmp_path, None)).arms[0].drop == ()
    assert experiment.load(with_drop(tmp_path, "drop = []")).arms[0].drop == ()
    assert experiment.load(with_drop(tmp_path, 'drop = ["edgar", "levels"]')).arms[0].drop == ("edgar", "levels")


@pytest.mark.parametrize(("line", "why"), [
    ('drop = ["news"]', "unknown section(s) news; sections: indicators, levels, edgar, headlines"),
    ('drop = ["headlines"]', "prompt analyze-1 renders no headlines; dropping them needs a prompt that shows them"),
    ('drop = "edgar"', "must be a list of section names"),
    ("drop = [1]", "must be a list of section names"),
    ('drop = ["edgar", "edgar"]', "names a section twice"),
    ('drop = ["indicators", "levels", "edgar"]', "names every section"),
    ('mode = "tools"\ndrop = ["edgar"]', "a tools arm has none"),
])
def test_a_bad_drop_is_refused_at_load(tmp_path, line, why):
    with pytest.raises(SystemExit, match=r"arm baseline: drop.*" + re.escape(why)):
        experiment.load(with_drop(tmp_path, line))
