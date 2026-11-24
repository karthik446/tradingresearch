"""w1l4.2 experiment config: replay in src/tradingresearch/replay.py, then experiments/prompt-v2.toml.

The first tests call replay on small configs written here and on the recorded prompt-v2 replies (labs/w1/data). The
rest check your config: two arms on the same 20 ticker-days, the rule written down before the run.
`experiment.load` is the runner's own pre-flight: it checks every prompt file and grader before any spend.
"""

import json
import os
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from gigai_core.graders.protocol import CannotGrade

import tradingresearch
from tradingresearch.evals import GRADERS
from tradingresearch.experiment import load
from tradingresearch.replay import replay

REPO = Path(tradingresearch.__file__).resolve().parents[2]
PATH = REPO / "experiments" / "prompt-v2.toml"
GRADER_ID = "|".join(sorted(map(re.escape, GRADERS), key=len, reverse=True))
DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
RECORDED = {"analyze-1": DATA / "prompt-v2-baseline.jsonl", "analyze-2": DATA / "prompt-v2-variant.jsonl"}
TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "UNH", "HD", "KO", "CAT"]


def a_config(tmp_path: Path, arms: list[tuple[str, str]], graders: list[str], tickers: list[str] = TICKERS) -> Path:
    lines = ['name = "test"', 'model = "anthropic/claude-sonnet-5.5"', "max_usd_per_arm = 1.00",
             f"tickers = {json.dumps(tickers)}", 'sessions = ["2026-11-12", "2026-11-13"]', f"graders = {json.dumps(graders)}"]
    for name, prompt in arms:
        lines += ["", "[[arms]]", f'name = "{name}"', f'prompt = "{prompt}"']
    path = tmp_path / "test.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def regraded(path: Path, grader_id: str, tickers: list[str] = TICKERS) -> float:
    """This test's own mean of one grader over the recorded replies of some tickers."""
    grader, values = GRADERS[grader_id](), []
    for row in map(json.loads, path.open()):
        if row["cluster"] in tickers:
            sample = SimpleNamespace(parse_status=row["parse_status"], output_parsed=row["output_parsed"])
            try:
                values.append(grader.grade(sample, {"values": row["values"], "names": row["names"]}).value)
            except CannotGrade:
                pass
    return sum(values) / len(values)


def same(got, want: dict[str, dict[str, float]]) -> bool:
    return isinstance(got, dict) and got.keys() == want.keys() and all(got[arm] == pytest.approx(want[arm]) for arm in want)


def test_replay_grades_each_arm(tmp_path):
    got = replay(a_config(tmp_path, [("baseline", "analyze-1")], ["parsed", "all_claims_valid"]), RECORDED)
    want = {"baseline": {"parsed": 1.0, "all_claims_valid": regraded(RECORDED["analyze-1"], "all_claims_valid")}}
    assert same(got, want), (
        f"replay returned {got!r} for a config with one arm (baseline, prompt analyze-1) and graders parsed and "
        f"all_claims_valid; grading the 20 recorded analyze-1 replies gives {want!r}"
    )


def test_replay_grades_the_replies_itself(tmp_path):
    zeroed = tmp_path / "zeroed.jsonl"
    with zeroed.open("w") as fh:
        for row in map(json.loads, RECORDED["analyze-1"].open()):
            fh.write(json.dumps(row | {"scores": {name: 0.0 for name in row["scores"]}}) + "\n")
    got = replay(a_config(tmp_path, [("baseline", "analyze-1")], ["all_claims_valid"]), {"analyze-1": zeroed})
    want = regraded(zeroed, "all_claims_valid")
    assert got.get("baseline", {}).get("all_claims_valid") == pytest.approx(want), (
        f"replay returned {got!r} for the analyze-1 replies with every stored score set to 0, but grading those "
        f"replies gives all_claims_valid={want:.3f}. A stored score is what the author's grader said then; the config's "
        "graders are what your run would say."
    )


def test_an_arm_finds_its_replies_by_prompt(tmp_path):
    got = replay(a_config(tmp_path, [("treatment", "analyze-2")], ["all_claims_valid"]), RECORDED)
    want = {"treatment": {"all_claims_valid": regraded(RECORDED["analyze-2"], "all_claims_valid")}}
    assert same(got, want), (
        f"replay returned {got!r} for one arm named 'treatment' with prompt analyze-2; expected {want!r}. The "
        "recordings are filed by the prompt that made them, and an arm may have any name."
    )


def test_only_the_configs_items_count(tmp_path):
    got = replay(a_config(tmp_path, [("baseline", "analyze-1")], ["all_claims_valid"], ["JPM", "MSFT"]), RECORDED)
    want = regraded(RECORDED["analyze-1"], "all_claims_valid", ["JPM", "MSFT"])
    assert got.get("baseline", {}).get("all_claims_valid") == pytest.approx(want), (
        f"replay returned {got!r} for a config with tickers JPM and MSFT only; their 4 analyze-1 replies give "
        f"all_claims_valid={want:.3f}, all 20 give {regraded(RECORDED['analyze-1'], 'all_claims_valid'):.3f}. "
        "A run asks only the config's ticker-days."
    )


def config():
    assert PATH.exists(), "experiments/prompt-v2.toml does not exist: start from experiments/observe.toml"
    try:
        return load(PATH)
    except SystemExit as exc:
        raise AssertionError(f"the runner's pre-flight refused the config: {exc}") from None


def test_two_arms_that_differ_only_in_the_prompt():
    arms = config().arms
    assert len(arms) == 2, (
        f"prompt-v2.toml has {len(arms)} arm(s). A comparison needs a baseline (analyze-1) and a variant (analyze-2), "
        "run fresh in the same experiment: the observe run is not a baseline (week-1.md §6, 'The baseline moved')."
    )
    assert {arm.prompt for arm in arms} == {"analyze-1", "analyze-2"}, f"arm prompts are {[a.prompt for a in arms]}"
    assert len({arm.model for arm in arms}) == 1, "the arms use different models: change one thing at a time"


def test_same_items_as_observe():
    cfg, observe = config(), tomllib.loads((REPO / "experiments" / "observe.toml").read_text())
    assert list(cfg.tickers) == observe["tickers"] and [d.isoformat() for d in cfg.sessions] == observe["sessions"], (
        "tickers or sessions differ from observe.toml. Keep the 10 tickers x 2 sessions: the taxonomy came from these "
        "items, and compare needs at least 10 clusters (tickers)."
    )


def test_the_new_grader_runs_and_the_rule_is_written():
    cfg = config()
    assert "inferences_grounded" in cfg.graders, (
        "graders lacks inferences_grounded: the variant targets inference_wider too"
    )
    head = "\n".join(line for line in PATH.read_text().splitlines() if line.startswith("#")).lower()
    rule = {role: re.search(rf"{role}[^;.\n]*?\b({GRADER_ID})\b", head) for role in ("primary", "guard")}
    assert rule["primary"] and rule["guard"] and rule["primary"].group(1) == "all_claims_valid", (
        "the comment at the top must pre-register the rule: the primary metric (all_claims_valid) and a guard metric, "
        "each named by its grader id, written before the run so the result cannot pick the rule"
    )
    for role, found in rule.items():
        assert found.group(1) in cfg.graders, (
            f"your comment names {found.group(1)} as the {role} metric, but graders is {list(cfg.graders)}: the run "
            "would not record the number the rule reads, so the decision could not be made from it"
        )
    assert cfg.max_usd_per_arm <= 1.0, f"max_usd_per_arm is {cfg.max_usd_per_arm}: the author's cap is $1.00 per arm"
