"""w1l4.2 experiment config: two arms on the same 20 ticker-days, the rule written down before the run.

`experiment.load` is the runner's own pre-flight: it checks every prompt file and grader before any spend.
"""

import re
import tomllib
from pathlib import Path

import tradingresearch
from tradingresearch.evals import GRADERS
from tradingresearch.experiment import load

REPO = Path(tradingresearch.__file__).resolve().parents[2]
PATH = REPO / "experiments" / "prompt-v2.toml"
GRADER_ID = "|".join(sorted(map(re.escape, GRADERS), key=len, reverse=True))


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
