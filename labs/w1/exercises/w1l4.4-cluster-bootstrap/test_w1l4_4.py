"""w1l4.4 cluster bootstrap: an interval for the mean diff that respects days of one stock not being independent."""

import os
import random
from pathlib import Path

import pytest

from tradingresearch.paired import cluster_bootstrap, load, paired_diff

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
A, B = load(DATA / "prompt-v2-baseline.jsonl"), load(DATA / "prompt-v2-variant.jsonl")
CLUSTERS = {item: row["cluster"] for item, row in A.items()}


def test_seeded():
    diffs = paired_diff(A, B, "inferences_grounded")
    random.seed(1)
    first = cluster_bootstrap(diffs, CLUSTERS, n=50, seed=7)
    random.seed(2)
    second = cluster_bootstrap(diffs, CLUSTERS, n=50, seed=7)
    assert first == second, (
        f"seed=7 gave {first} and then {second}: your interval follows the module-level random, not `seed`. "
        "The draws must depend on `seed` alone, whatever else in the process used random before, so a result can be "
        "rerun."
    )


def test_interval_matches_compare():
    lo, hi = cluster_bootstrap(paired_diff(A, B, "all_claims_valid"), CLUSTERS)
    narrow = " Yours is narrower: did you resample the 20 items? Their two days per ticker move together." if (
        0 < hi - lo < 0.48) else ""
    assert lo == pytest.approx(0.45, abs=0.02) and hi == pytest.approx(0.95, abs=0.02), (
        f"cluster_bootstrap returned ({lo:+.3f}, {hi:+.3f}); gigai-core's compare printed [+0.450, +0.950] for "
        f"all_claims_valid.{narrow} Resample the 10 tickers with replacement, mean all diffs of the drawn tickers, "
        "repeat n times, read the 2.5th and 97.5th percentiles."
    )


def test_ten_tickers_of_five_identical_days_are_ten_draws_not_fifty():
    diffs = {f"T{c}:{day}": 1.0 if c < 5 else 0.0 for c in range(10) for day in range(5)}
    lo, hi = cluster_bootstrap(diffs, {item: item.split(":")[0] for item in diffs})
    assert hi - lo >= 0.5, (
        f"10 tickers, each with 5 identical diffs (5 tickers all +1, 5 all 0): interval ({lo:+.2f}, {hi:+.2f}) is "
        f"{hi - lo:.2f} wide. Resampling whole tickers gives about [+0.20, +0.80] (10 independent draws); resampling "
        "the 50 items gives about [+0.36, +0.64], as if the copies of one day were new evidence. Draw tickers, not items."
    )


def test_level_sets_the_width():
    diffs = {f"T{i}": float(i < 5) for i in range(10)}
    clusters = {item: item for item in diffs}
    wide, narrow = cluster_bootstrap(diffs, clusters), cluster_bootstrap(diffs, clusters, level=0.5)
    assert narrow == pytest.approx((0.4, 0.6), abs=0.05) and wide == pytest.approx((0.2, 0.8), abs=0.05), (
        f"10 one-item tickers, 5 at +1 and 5 at 0: level=0.95 gave ({wide[0]:+.2f}, {wide[1]:+.2f}) and level=0.5 "
        f"gave ({narrow[0]:+.2f}, {narrow[1]:+.2f}). A 50% interval holds the middle half of the resampled means, about "
        "[+0.40, +0.60] here against [+0.20, +0.80] at 95%: the bounds must follow `level`."
    )


def test_unequal_tickers_weigh_by_their_days():
    diffs = {**{f"A:{day}": 1.0 for day in range(9)}, **{f"T{c}:0": 0.0 for c in range(9)}}
    lo, hi = cluster_bootstrap(diffs, {item: item.split(":")[0] for item in diffs})
    assert lo <= 0.5 <= hi and hi == pytest.approx(0.79, abs=0.06), (
        f"ticker A has 9 days at +1 and nine other tickers have 1 day at 0 each, so the mean diff is +0.50 (9 of 18). "
        f"Your interval is ({lo:+.2f}, {hi:+.2f}); about [+0.00, +0.79] is expected. If you averaged each drawn ticker "
        "first, A's 9 days count as one: a draw is a ticker, but the mean is over all the days the drawn tickers bring."
    )


def test_too_few_clusters():
    by_session = {item: item.split(":")[1] for item in CLUSTERS}
    with pytest.raises(ValueError):
        cluster_bootstrap(paired_diff(A, B, "all_claims_valid"), by_session)
