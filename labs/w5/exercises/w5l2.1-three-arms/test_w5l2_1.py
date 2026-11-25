"""w5l2.1 three arms: experiments/context-ablation.toml loads with three fixed analyze-3 arms on one model, named full,
no-headlines and no-edgar, that differ only in the sections they drop: nothing, the headlines, the EDGAR rows.

experiment.load (the shipped loader) reads the file. The $0 replay runs the arms through the real OpenRouter adapter
whose transport answers every request with the recorded reply (tools/fakea.py `ablation`, at most 100 requests), on
the config's tickers, each holding the FAKEA rows and headlines. It grades with `parsed` alone, whatever the file
lists: the graders, the cluster and the pre-registration are w5l2.2 and w5l2.3.
"""

import re
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

from tradingresearch import analyze as an, experiment, masking  # noqa: E402

ARMS = {"full": (), "no-headlines": ("headlines",), "no-edgar": ("edgar",)}


def config():
    try:
        return experiment.load(fakea.CONFIG)
    except SystemExit as exc:
        raise AssertionError(f"experiment.load refused {fakea.CONFIG}: {exc}") from None


def test_three_arms_named_by_what_they_drop():
    arms = config().arms
    got = [(arm.name, list(arm.drop)) for arm in arms]
    assert len(arms) == 3 and {arm.name: arm.drop for arm in arms} == ARMS, (
        f"the arms (name, drop) are {got}; expected exactly three, each named for what it drops: a full arm with an "
        f"empty drop, and one no-<section> arm per section the ablation leaves out (the headlines; the EDGAR rows), "
        f"dropping that section alone under its masking.SECTIONS name")


def test_the_arms_differ_only_in_what_they_drop():
    arms = config().arms
    shown = [(arm.name, arm.prompt, arm.model, arm.provider, arm.mode) for arm in arms]
    assert {arm.prompt for arm in arms} == {"analyze-3"} and {arm.mode for arm in arms} == {"fixed"}, (
        f"the arms (name, prompt, model, provider, mode) are {shown}; every arm runs prompt analyze-3 in fixed mode")
    assert len({(arm.model, repr(arm.provider)) for arm in arms}) == 1, (
        f"the arms (name, prompt, model, provider, mode) are {shown}; every arm runs the same model, routed the same "
        f"way, so the drop is the only difference")


def test_the_replay_sends_each_arm_the_recorded_request_masked(tmp_path):
    cfg, sent = config(), []
    results = fakea.ablation(replace(cfg, graders=("parsed",)), tmp_path, sent)
    n = len(cfg.tickers)
    assert len(results) == 3 and len(sent) == 3 * n, (
        f"the replay ran {len(results)} arms and sent {len(sent)} requests; expected 3 arms of {n} tickers")
    assert len({r.run.record.dataset for r in results}) == 1, "the three arms must run over one dataset"
    recorded = fakea.user_turn(fakea.load("analyze3.request"))
    for i, result in enumerate(results):
        want = masking.mask(recorded, result.arm.drop)
        for body in sent[i * n:(i + 1) * n]:
            turn = fakea.user_turn(body)
            ticker = re.match(r"TICKER: (\S+)", turn).group(1)
            assert turn == want.replace("TICKER: FAKEA", f"TICKER: {ticker}", 1), (
                f"arm {result.arm.name} (drop {list(result.arm.drop)}) sent a user turn that is not the recorded one "
                f"masked by its drop")
            assert body["messages"][0]["content"] == an.system_prompt("analyze-3"), (
                f"arm {result.arm.name} sent a system prompt that is not analyze-3's")


def test_every_arm_runs_the_model_at_the_top_of_the_file():
    top = tomllib.loads(fakea.CONFIG.read_text()).get("model")
    models = {arm.name: arm.model for arm in config().arms}
    assert top and set(models.values()) == {top}, (
        f"the file's top-level model is {top!r} and the arms run {models}; expected every arm to run the model the top "
        f"of the file names: an arm with a model of its own is a model comparison, not a context ablation")
