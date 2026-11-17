"""Keys stay masked, configs fail before spend, the registry and `tr check`'s table reader work."""

import pytest

from tradingresearch import experiment
from tradingresearch.cli import source_table
from tradingresearch.config import Secret, read_env_file, require
from tradingresearch.evals import GRADERS, graders


def test_a_secret_never_prints_its_value():
    key = Secret("not-a-real-key")
    assert "not-a-real-key" not in f"{key} {key!r} {[key]}"
    assert require(key, "OPENROUTER_API_KEY") == "not-a-real-key"


def test_a_missing_key_names_the_variable_only():
    with pytest.raises(SystemExit, match="OPENROUTER_API_KEY is not set"):
        require(Secret(""), "OPENROUTER_API_KEY")


def test_the_env_file_is_read_without_touching_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("TR_TEST_VAR", raising=False)
    path = tmp_path / "verify.env"
    path.write_text('# comment\nexport TR_TEST_VAR="x"\n')
    assert read_env_file(path) == {"TR_TEST_VAR": "x"}
    import os
    assert "TR_TEST_VAR" not in os.environ


def test_the_registry_refuses_an_unknown_grader():
    assert {"parsed", "claims_valid", "all_claims_valid"} <= set(GRADERS)
    with pytest.raises(SystemExit, match="unknown grader"):
        graders(["claims_valid", "vibes"])


def test_a_config_with_a_missing_prompt_fails_before_any_call(tmp_path):
    path = tmp_path / "exp.toml"
    path.write_text('name = "x"\nmodel = "m"\nmax_usd_per_arm = 0.1\ntickers = ["AAPL"]\nsessions = ["2026-11-13"]\n'
                    'graders = ["claims_valid"]\n[[arms]]\nname = "a"\nprompt = "no-such-prompt"\n')
    with pytest.raises(SystemExit, match="no prompt"):
        experiment.load(path)


def test_the_shipped_observe_config_loads():
    config = experiment.load(experiment.an.PROMPTS_DIR.parent / "experiments" / "observe.toml")
    assert len(config.tickers) * len(config.sessions) == 20 and config.arms[0].prompt == "analyze-1"


def test_source_table_reads_the_rendered_rows():
    prompt = "SOURCES\nsrc_1 | close | 230.5 | USD\nnot a row\nsrc_2 | regime_spy | bull-normal | label\n"
    assert source_table(prompt) == {"src_1": ("close", "230.5", "USD"), "src_2": ("regime_spy", "bull-normal", "label")}
