"""The `mode` arm knob (REPO-PLAN §2.4, week 4): parsed and checked at config load, refused at run time until the
learner's tool loop exists, before any call is made."""

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


def test_a_tools_arm_stops_before_any_call(tmp_path):
    loaded = experiment.load(config(tmp_path, "tools"))
    with pytest.raises(NotImplementedError, match="mode=tools: week 4 learner work"):
        experiment.run_arms(None, loaded, [], provider=None, prices={}, data_dir=tmp_path)
