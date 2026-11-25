"""w5l3.2 why and how many. Each entry in `Compared.skipped` reads `<grader>: <why> (n=A vs B)`, in the order the
graders were asked: why is `not scored in both arms` when either run has no score for the grader, else `no item scored
in both arms`; A and B count the items run a and run b scored with it. The no_shared_metric refusal names them all:
`cannot compare: no grader is scored on a common item in both runs (<entries joined by "; ">)`, or `(no grader named)`
when no grader was asked.

The runs: the author's three context-ablation runs (tools/runs.py rebuilds them from data/ablation.runs.json) and
hand-built runs over ten tickers whose scores each test chooses.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import runs  # noqa: E402
from gigai_core.comparison import ComparisonRefused  # noqa: E402

from tradingresearch import experiment  # noqa: E402
from tradingresearch.commands import exp  # noqa: E402

SEVEN = ("parsed", "claims_valid", "all_claims_valid", "indicators_grounded", "levels_grounded", "edgar_grounded",
         "headlines_grounded")  # the order experiments/context-ablation.toml names them
STORED = runs.stored()
IDS = runs.IDS
ALL = dict.fromkeys(IDS, 1.0)
NOT = "not scored in both arms"
NONE = "no item scored in both arms"


def counts(a: str, b: str, grader: str) -> str:
    """How many items each arm scored with the grader, and which: the counterexample a FAIL message shows."""
    items = [sorted(STORED[arm].values(grader)) for arm in (a, b)]
    return f"{grader} scored on {len(items[0])} items in {a} {items[0]}, {len(items[1])} in {b} {items[1]}"


def skipped(a, b, graders, what: str) -> tuple:
    try:
        return experiment.compare(a, b, graders).skipped
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"compare({what}, {list(graders)}) raised {exc!r}") from None


REAL = {
    ("full", "no-edgar"): (f"levels_grounded: {NONE} (n=1 vs 3)", f"edgar_grounded: {NOT} (n=6 vs 0)"),
    ("no-edgar", "full"): (f"levels_grounded: {NONE} (n=3 vs 1)", f"edgar_grounded: {NOT} (n=0 vs 6)"),
    ("no-headlines", "no-edgar"): (f"edgar_grounded: {NOT} (n=11 vs 0)", f"headlines_grounded: {NOT} (n=0 vs 16)"),
    ("full", "no-headlines"): (f"headlines_grounded: {NOT} (n=16 vs 0)",),
}


@pytest.mark.parametrize("arms", REAL, ids=lambda arms: " -> ".join(arms))
def test_each_skipped_grader_says_why_and_how_many_items_each_run_scored(arms):
    a, b = arms
    got = skipped(STORED[a], STORED[b], SEVEN, f"{a} -> {b}")
    want = REAL[arms]
    names = [w.split(":")[0] for w in want]
    assert got == want, (
        f"compare({a} -> {b}, the config's seven graders) skipped {got!r}; expected {want!r}, in the order asked "
        f"({'; '.join(counts(a, b, g) for g in names)})")


def test_the_reason_depends_on_whether_a_run_has_no_score_or_no_common_item():
    a = runs.run("a", {"parsed": ALL, "disjoint": {IDS[0]: 1.0, IDS[1]: 0.0}, "a_only": ALL,
                       "late": {IDS[9]: 1.0}})
    b = runs.run("b", {"parsed": ALL, "disjoint": {IDS[7]: 1.0, IDS[8]: 1.0, IDS[9]: 1.0}, "b_only": {IDS[4]: 0.0},
                       "late": {IDS[8]: 1.0}})
    asked = ("b_only", "parsed", "disjoint", "never_scored", "late", "a_only")
    want = (f"b_only: {NOT} (n=0 vs 1)", f"disjoint: {NONE} (n=2 vs 3)", f"never_scored: {NOT} (n=0 vs 0)",
            f"late: {NONE} (n=1 vs 1)", f"a_only: {NOT} (n=10 vs 0)")
    got = skipped(a, b, asked, "hand a -> hand b")
    assert got == want, (
        f"compare(hand a -> hand b, {list(asked)}) skipped {got!r}; expected {want!r}: b_only is scored on 1 item in b "
        f"only, disjoint on items 0-1 in a and 7-9 in b, never_scored in neither, late on item 9 in a and 8 in b, "
        f"a_only on all 10 in a only")


REFUSED = {
    "full -> no-edgar, edgar then levels": (
        "full", "no-edgar", ("edgar_grounded", "levels_grounded"),
        f"(edgar_grounded: {NOT} (n=6 vs 0); levels_grounded: {NONE} (n=1 vs 3))"),
    "no-headlines -> full, headlines and an unknown grader": (
        "no-headlines", "full", ("headlines_grounded", "levels"),
        f"(headlines_grounded: {NOT} (n=0 vs 16); levels: {NOT} (n=0 vs 0))"),
    "full -> no-headlines, no grader named": ("full", "no-headlines", (), "(no grader named)"),
}


@pytest.mark.parametrize("which", REFUSED)
def test_the_refusal_names_every_skipped_grader(which):
    a, b, asked, names = REFUSED[which]
    want = f"cannot compare: no grader is scored on a common item in both runs {names}"
    try:
        got = experiment.compare(STORED[a], STORED[b], asked)
    except ComparisonRefused as exc:
        refused = exc
    except Exception as exc:  # noqa: BLE001 - reported here
        raise AssertionError(f"compare({which}) raised {exc!r}; expected ComparisonRefused") from None
    else:
        raise AssertionError(f"compare({which}) returned a comparison of {[m.metric for m in got.comparison.metrics]};"
                             f" expected the refusal {want!r}")
    assert (refused.code, str(refused)) == ("no_shared_metric", want), (
        f"compare({which}) refused {refused.code}: {str(refused)!r}; expected no_shared_metric: {want!r}")


@pytest.mark.parametrize("b", ["no-headlines", "no-edgar"])
def test_tr_exp_compare_prints_the_chapters_skipped_lines(b, capsys):
    a = "full"
    want = {"no-headlines": [f"    skipped headlines_grounded: {NOT} (n=16 vs 0)"],
            "no-edgar": [f"    skipped edgar_grounded: {NOT} (n=6 vs 0)",
                         f"    skipped levels_grounded: {NONE} (n=1 vs 3)"]}[b]
    exp.show(STORED[a].record.run_id, STORED[b].record.run_id, STORED[a], STORED[b], exp.scored(STORED[a], STORED[b]))
    got = [line for line in capsys.readouterr().out.splitlines() if line.startswith("    skipped")]
    assert got == want, (
        f"tr exp compare {a} -> {b} printed the skipped lines {got}; the chapter's block (section 5) prints {want}, "
        f"graders in the order the runs first scored them")
