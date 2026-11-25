"""w5l2.2 graders and cluster: the ablation is read by seven code graders, each once (parsed, claims_valid,
all_claims_valid and the four <section>_grounded), and writes `cluster = "ticker"` out, though it is the default.

The $0 replay runs the arms through the real OpenRouter adapter whose transport answers every request with the
recorded reply (tools/fakea.py `ablation`, at most 100 requests). That reply cites one headline, seven indicator rows
(one fails, `empty_placeholder`) and no level or EDGAR row, and has 11 claims; in the no-headlines arm its headline
claim fails `dropped_source`.
"""

import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

from tradingresearch import evals, experiment  # noqa: E402

GRADERS = ["all_claims_valid", "claims_valid", "edgar_grounded", "headlines_grounded", "indicators_grounded",
           "levels_grounded", "parsed"]


def config():
    try:
        return experiment.load(fakea.CONFIG)
    except SystemExit as exc:
        raise AssertionError(f"experiment.load refused {fakea.CONFIG}: {exc}") from None


def test_seven_code_graders_each_once():
    got = list(config().graders)
    missing = len(set(GRADERS) - set(got))
    unexpected = sorted(g for g in set(got) if g not in GRADERS or got.count(g) > 1)
    assert sorted(got) == GRADERS, (
        f"graders = {got}; expected seven, each once, in any order: the guard metric that the stub already lists, the "
        f"primary metric, the whole-analysis metric, and the four registered <section>_grounded graders "
        f"({missing} of the seven missing; not among them or listed twice: {unexpected})")
    kinds = {name: evals.GRADERS[name].kind for name in got}
    assert set(kinds.values()) == {"code"}, f"the graders' kinds are {kinds}; a drop arm is graded by code only"


def test_the_cluster_is_written_out():
    raw = tomllib.loads(fakea.CONFIG.read_text())
    assert raw.get("cluster") == "ticker", (
        f"the file sets cluster = {raw.get('cluster', '(nothing)')!r}; write the cluster key out at the top of the "
        f"file, set to the unit the paired intervals resample: the arms share their ticker-days, and the days of one "
        f"ticker are not independent draws")


def test_the_replay_grades_the_recorded_reply_per_arm(tmp_path):
    cfg = config()
    n = len(cfg.tickers)
    results = fakea.ablation(cfg, tmp_path, [])
    means = {r.arm.name: experiment.means(r.run) for r in results}
    want = {"parsed": (1.0, n), "claims_valid": (pytest.approx(10 / 11), n), "indicators_grounded":
            (pytest.approx(6 / 7), n), "headlines_grounded": (1.0, n)}
    for arm, drop_want in [("full", {}), ("no-edgar", {}),
                           ("no-headlines", {"claims_valid": (pytest.approx(9 / 11), n), "headlines_grounded": (0.0, n)})]:
        expected = want | drop_want
        got = {g: means[arm].get(g) for g in [*expected, "levels_grounded", "edgar_grounded"]}
        assert got == expected | {"levels_grounded": None, "edgar_grounded": None}, (
            f"arm {arm}: (mean, n) per grader {got}; expected {expected}, and no score for levels or edgar, which no "
            f"claim cites")
