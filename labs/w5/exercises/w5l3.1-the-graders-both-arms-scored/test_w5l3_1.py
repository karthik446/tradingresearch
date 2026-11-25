"""w5l3.1 the graders both arms scored. `experiment.compare(a, b, graders)` compares run b against run a on each grader
both runs scored on at least one common item, in the order asked, and returns `Compared`: `comparison`, core's
comparison of those graders, and `skipped`, a tuple with one entry per grader left out, starting `<grader>:`. A grader
one run never scored, or that the two runs scored on different items only, is left out. With none left, it refuses
with ComparisonRefused, code `no_shared_metric`.

The runs: the author's three context-ablation runs (tools/runs.py rebuilds them from data/ablation.runs.json) and
hand-built runs over ten tickers whose scores each test chooses.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import runs  # noqa: E402
from gigai_core import compare as core_compare  # noqa: E402
from gigai_core.comparison import ComparisonRefused  # noqa: E402

from tradingresearch import experiment  # noqa: E402

SEVEN = ("parsed", "claims_valid", "all_claims_valid", "indicators_grounded", "levels_grounded", "edgar_grounded",
         "headlines_grounded")  # the order experiments/context-ablation.toml names them
SECTIONS = ("levels_grounded", "edgar_grounded", "headlines_grounded")
STORED = runs.stored()
IDS = runs.IDS
ALL = dict.fromkeys(IDS, 1.0)


def compared(a, b, graders, what: str):
    try:
        return experiment.compare(a, b, graders)
    except ComparisonRefused as exc:
        raise AssertionError(f"compare({what}, {list(graders)}) refused {exc.code}: {exc.reason}; a grader one run "
                             f"did not score is skipped, and the rest compared") from None
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"compare({what}, {list(graders)}) raised {exc!r}") from None


def metrics(got) -> list[str]:
    return [m.metric for m in got.comparison.metrics]


def scored(arm: str, grader: str) -> list[str]:
    return sorted(STORED[arm].values(grader))


def where(arms: tuple[str, str]) -> str:
    """Where each section grader has scores in the two arms: the counterexample a FAIL message shows."""
    return "; ".join(f"{g} items {scored(arms[0], g) or 'none'} vs {scored(arms[1], g) or 'none'}" for g in SECTIONS)


KEPT = {
    ("full", "no-headlines"): SEVEN[:6],
    ("full", "no-edgar"): ("parsed", "claims_valid", "all_claims_valid", "indicators_grounded", "headlines_grounded"),
    ("no-headlines", "no-edgar"): SEVEN[:5],
}


@pytest.mark.parametrize("arms", [*KEPT, *[(b, a) for a, b in KEPT]], ids=lambda arms: " -> ".join(arms))
def test_the_authors_arms_compare_the_shared_graders_and_skip_the_rest(arms):
    a, b = arms
    kept = KEPT.get(arms) or KEPT[(b, a)]
    got = compared(STORED[a], STORED[b], SEVEN, f"{a} -> {b}")
    assert metrics(got) == list(kept), (
        f"compare({a} -> {b}, the config's seven graders) compared {metrics(got)}; expected {list(kept)}, in the "
        f"order asked ({where(arms)})")
    left = [g for g in SEVEN if g not in kept]
    assert isinstance(got.skipped, tuple) and sorted(s.split(":")[0] for s in got.skipped) == sorted(left), (
        f"compare({a} -> {b}) skipped {got.skipped!r}; expected a tuple with one entry per grader left out, each "
        f"starting '<grader>:', for {left}")
    assert all(s.startswith(f"{g}:") for s, g in zip(sorted(got.skipped), sorted(left))), got.skipped
    assert (got.comparison.items, got.comparison.clusters) == (20, 10), (
        f"compare({a} -> {b}) paired {got.comparison.items} items in {got.comparison.clusters} clusters; the runs "
        f"asked the same 20 ticker-days of 10 tickers")


def hand() -> tuple:
    """Two hand-built arms and the order graders are asked in, each a boundary of the rule."""
    a = runs.run("a", {"parsed": ALL, "first_shared": {IDS[0]: 1.0}, "last_shared": {IDS[2]: 1.0, IDS[9]: 0.0},
                       "disjoint": {IDS[0]: 1.0, IDS[1]: 1.0}, "zeros": dict.fromkeys(IDS, 0.0),
                       "a_only": ALL})
    b = runs.run("b", {"parsed": ALL, "first_shared": {IDS[0]: 0.0, IDS[5]: 1.0}, "last_shared": {IDS[9]: 1.0},
                       "disjoint": {IDS[8]: 1.0, IDS[9]: 1.0}, "zeros": dict.fromkeys(IDS, 0.0),
                       "b_only": ALL})
    asked = ("last_shared", "disjoint", "b_only", "zeros", "never_scored", "parsed", "a_only", "first_shared")
    return a, b, asked


HAND_KEPT = ["last_shared", "zeros", "parsed", "first_shared"]


def test_one_common_item_is_enough_and_the_kept_graders_stay_in_the_order_asked():
    a, b, asked = hand()
    got = compared(a, b, asked, "hand a -> hand b")
    assert metrics(got) == HAND_KEPT, (
        f"compare(hand a -> hand b, {list(asked)}) compared {metrics(got)}; expected {HAND_KEPT}: first_shared and "
        f"last_shared share one item (the first, the last), zeros is scored 0.0 everywhere in both, parsed everywhere; "
        f"disjoint is scored on items 0-1 in a and 8-9 in b, a_only and b_only in one run, never_scored in none")
    left = ["disjoint", "b_only", "never_scored", "a_only"]
    assert sorted(s.split(":")[0] for s in got.skipped) == sorted(left), (
        f"compare(hand a -> hand b) skipped {got.skipped!r}; expected one entry starting '<grader>:' for each of "
        f"{left}")
    back = compared(b, a, asked, "hand b -> hand a")
    assert metrics(back) == HAND_KEPT, (
        f"compare(hand b -> hand a, {list(asked)}) compared {metrics(back)}; the rule is the same both ways round: "
        f"expected {HAND_KEPT}")


@pytest.mark.parametrize("which", ["full -> no-edgar", "no-edgar -> full", "hand a -> hand b", "hand b -> hand a"])
def test_the_comparison_is_core_compare_of_b_against_a_on_the_kept_graders(which):
    if which.startswith("hand"):
        a, b, asked = hand()
        a, b, kept = (a, b, HAND_KEPT) if which.endswith("b") else (b, a, HAND_KEPT)
    else:
        first, _, second = which.split(" ")
        a, b, asked, kept = STORED[first], STORED[second], SEVEN, KEPT[("full", "no-edgar")]
    got = compared(a, b, asked, which)
    assert isinstance(got, experiment.Compared), f"compare({which}) returned {type(got).__name__}; expected Compared"
    want = core_compare(a, b, list(kept))
    assert got.comparison == want, (
        f"compare({which}).comparison has means {[(m.metric, m.mean_a, m.mean_b) for m in got.comparison.metrics]}; "
        f"expected core compare(a, b, {list(kept)}), b against a: {[(m.metric, m.mean_a, m.mean_b) for m in want.metrics]}")


REFUSED = {
    "full -> no-edgar, the two dropped sections": (STORED["full"], STORED["no-edgar"],
                                                   ("levels_grounded", "edgar_grounded")),
    "no-edgar -> full, the two dropped sections": (STORED["no-edgar"], STORED["full"],
                                                   ("edgar_grounded", "levels_grounded")),
    "hand a -> hand b, disjoint only (parsed is shared, not asked)": (*hand()[:2], ("disjoint",)),
    "hand a -> hand b, a grader no run scored": (*hand()[:2], ("never_scored",)),
    "full -> no-headlines, no grader named": (STORED["full"], STORED["no-headlines"], ()),
}


@pytest.mark.parametrize("which", REFUSED)
def test_with_no_grader_left_it_refuses_no_shared_metric(which):
    a, b, asked = REFUSED[which]
    try:
        got = experiment.compare(a, b, asked)
    except ComparisonRefused as exc:
        refused = exc
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"compare({which}) raised {exc!r}; expected ComparisonRefused, code no_shared_metric") \
            from None
    else:
        raise AssertionError(f"compare({which}) returned a comparison of {metrics(got)}; with no grader scored on a "
                             f"common item in both runs it refuses: ComparisonRefused, code no_shared_metric")
    assert refused.code == "no_shared_metric", (
        f"compare({which}) refused {refused.code}: {refused.reason}; with no grader scored on a common item in both "
        f"runs the code is no_shared_metric")
