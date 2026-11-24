"""w1l4.3 paired differences and McNemar, on the author's recorded experiment (run_c5fb0100989a4e0d vs run_537a07e6ec264989)."""

import os
from pathlib import Path

import pytest

from tradingresearch.paired import discordant, load, mcnemar_p, paired_diff

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
A, B = load(DATA / "prompt-v2-baseline.jsonl"), load(DATA / "prompt-v2-variant.jsonl")


def test_paired_diff_per_item():
    diffs = paired_diff(A, B, "all_claims_valid")
    assert len(diffs) == 20, (
        f"paired_diff returned {len(diffs)} items; both arms answered the same 20 ticker-days, so there are 20 pairs"
    )
    mean = sum(diffs.values()) / len(diffs)
    assert mean == pytest.approx(0.70), f"mean diff {mean:+.3f}; the recorded means are 0.150 -> 0.850, so +0.700"


def test_different_items_cannot_be_paired():
    try:
        paired_diff(A, {k: v for k, v in B.items() if k != "KO:2026-11-13"}, "all_claims_valid")
    except ValueError:
        return
    except KeyError as err:
        pytest.fail(f"arms with different items must raise ValueError before any lookup; got KeyError {err}")
    pytest.fail("paired_diff paired two arms with different items (b has no KO:2026-11-13); it must raise ValueError")


def test_discordant_pairs():
    got = discordant(paired_diff(A, B, "all_claims_valid")), discordant(paired_diff(A, B, "inferences_grounded"))
    assert got == ((14, 0), (14, 1)), (
        f"discordant gave {got}; on the recording all_claims_valid has 14 items only the variant passed and 0 only the "
        "baseline passed, inferences_grounded 14 and 1. The 6 or 5 ties are ignored."
    )


def test_mcnemar_exact():
    got = mcnemar_p(14, 0), mcnemar_p(14, 1), mcnemar_p(0, 0)
    assert got[0] == pytest.approx(0.000122, rel=0.01) and got[1] == pytest.approx(0.000977, rel=0.01), (
        f"mcnemar_p(14, 0) = {got[0]:.3g}, (14, 1) = {got[1]:.3g}; compare printed 0.000122 and 0.000977. Two-sided: "
        "double the binomial tail P(X <= min(up, down)) with n = up + down, p = 0.5."
    )
    assert got[2] == 1.0, "with no discordant pairs there is no evidence either way: p = 1"


def test_a_p_value_never_exceeds_1():
    assert mcnemar_p(1, 1) == 1.0, (
        f"mcnemar_p(1, 1) = {mcnemar_p(1, 1):g}. One pair each way is no evidence either way, and a probability is "
        "at most 1: doubling a tail that already holds more than half the mass overshoots."
    )
    over = [(up, down) for up in range(8) for down in range(8) if mcnemar_p(up, down) > 1.0]
    assert not over, f"mcnemar_p is above 1 for (up, down) = {over[:4]}: a probability is at most 1"
