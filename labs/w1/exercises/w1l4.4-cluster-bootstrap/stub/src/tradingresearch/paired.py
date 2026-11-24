"""Paired comparison of two arms on the same items, by hand: what gigai-core's `compare` does for a binary metric.

uv run python -m tradingresearch.paired BASELINE.jsonl VARIANT.jsonl
Each line of a file is one item: {"item": ..., "cluster": ..., "scores": {metric: value}}.
"""

from __future__ import annotations

import json
import random
import sys
from math import comb
from pathlib import Path

MIN_CLUSTERS = 10  # gigai-core's compare refuses below this; a ticker is a cluster
PRIMARY, GUARD = "all_claims_valid", "parsed"  # pre-registered in experiments/prompt-v2.toml (ADR-002)


def load(path: Path) -> dict[str, dict]:
    """Rows by item id."""
    return {row["item"]: row for row in map(json.loads, Path(path).open())}


def paired_diff(a: dict[str, dict], b: dict[str, dict], metric: str) -> dict[str, float]:
    """Per item, b's score minus a's. Both arms must have the same items, or the pairs mean nothing."""
    if a.keys() != b.keys():
        raise ValueError(f"arms differ in items: {sorted(a.keys() ^ b.keys())}")
    return {item: b[item]["scores"][metric] - a[item]["scores"][metric] for item in sorted(a)}


def discordant(diffs: dict[str, float]) -> tuple[int, int]:
    """(up, down) for a 0/1 metric: items only the variant passed, items only the baseline passed."""
    values = list(diffs.values())
    return values.count(1), values.count(-1)


def mcnemar_p(up: int, down: int) -> float:
    """Exact two-sided McNemar test: is `up` out of `up + down` discordant pairs far from half?"""
    n = up + down
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, k) for k in range(min(up, down) + 1)) / 2**n)


def cluster_bootstrap(diffs: dict[str, float], clusters: dict[str, str], *, n: int = 10_000, seed: int = 0,
                      level: float = 0.95) -> tuple[float, float]:
    """Interval for the mean diff: resample whole clusters (tickers) with replacement, n times."""
    # TODO(w1l4.4) group diffs by cluster; ValueError below MIN_CLUSTERS. random.Random(seed); each round draws as
    #   many clusters as there are, with replacement, and takes the mean of all their diffs. Return the percentiles.
    return 0.0, 0.0


def decide(primary_ci: tuple[float, float], guard_diff: float) -> str:
    """The rule written before the run: ship only if the primary interval is above 0 and the guard did not drop."""
    # TODO(w1l4.5) return "ship" or "keep baseline".
    return "undecided"


def main() -> None:
    a, b = load(Path(sys.argv[1])), load(Path(sys.argv[2]))
    clusters = {item: row["cluster"] for item, row in a.items()}
    print(f"compare baseline -> variant: {len(a)} items, {len(set(clusters.values()))} clusters")
    found = {}
    for metric in sorted(next(iter(a.values()))["scores"]):
        diffs = paired_diff(a, b, metric)
        mean = sum(diffs.values()) / len(diffs) if diffs else 0.0
        binary = all(row["scores"][metric] in (0, 1) for row in (*a.values(), *b.values()))
        up, down = discordant(diffs) if binary else (0, 0)
        test = f"up {up} down {down}  mcnemar p={mcnemar_p(up, down):.3g}" if binary else "(not 0/1: no McNemar)"
        lo, hi = cluster_bootstrap(diffs, clusters) if diffs else (0.0, 0.0)
        found[metric] = (mean, (lo, hi))
        print(f"  {metric:<20} diff {mean:+.3f}  CI [{lo:+.3f}, {hi:+.3f}]  {test}")
    print(f"decision (primary {PRIMARY}, guard {GUARD}): {decide(found[PRIMARY][1], found[GUARD][0])}")


if __name__ == "__main__":
    main()
