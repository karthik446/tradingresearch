"""w1l1.4 cascade: an inference that stands on a rejected claim is rejected too (bad_derivation).

Claims are the author's, from the recorded observe run (run_c40caab0968e44a3).
"""

import json
import os
from pathlib import Path

from tradingresearch.analyze import validate_claims

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")


def rows() -> list[dict]:
    return [json.loads(line) for line in (DATA / "observe.jsonl").open()]


def aapl() -> dict:
    return next(row for row in rows() if row["item"] == "AAPL:2026-11-12")


def reasons(raw: dict, values: dict) -> dict[str, tuple[str, str]]:
    _, rejected = validate_claims(raw, values, "an_lab")
    return {r.claim: (r.reason, r.detail) for r in rejected}


def test_aapl_2026_11_12_c8_stands_on_a_rejected_claim():
    got = reasons(aapl()["output_parsed"], aapl()["values"]).get("c8")
    assert got == ("bad_derivation", "derives from a rejected or later claim: c5"), (
        f"AAPL 2026-11-12 c8 derives from c1, c2, c4 and c5, and c5 was rejected (number_in_text). Expected "
        f"('bad_derivation', 'derives from a rejected or later claim: c5'), got {got}. A claim cannot stand on a parent "
        "that was rejected or comes later; say so yourself, because the Claim constructor turns a missing parent into a "
        "KeyError, reported as not_a_claim."
    )


def test_an_id_that_is_not_in_the_reply_is_unknown():
    claims = {c["id"]: c for c in aapl()["output_parsed"]["claims"]}
    edited = {**claims["c8"], "derived_from": ["c1", "c99"]}
    got = reasons({"claims": [claims["c1"], edited]}, aapl()["values"]).get("c8")
    assert got == ("bad_derivation", "unknown claim id: c99"), (
        f"c99 is not a claim of this reply at all, so the detail is 'unknown claim id: c99' (use `ids`); got {got}"
    )


def test_one_id_that_is_not_a_claim_makes_the_detail_unknown():
    claims = {c["id"]: c for c in aapl()["output_parsed"]["claims"]}
    edited = {**claims["c8"], "derived_from": ["c5", "c99"]}
    got = reasons({"claims": [claims["c5"], edited]}, aapl()["values"]).get("c8")
    assert got == ("bad_derivation", "unknown claim id: c5, c99"), (
        f"c8 derives from c5 (a claim of this reply, rejected) and c99 (not a claim at all). 'derives from a rejected "
        f"or later claim' holds only when every missing id is a claim of this reply; one is not, so the detail is "
        f"'unknown claim id: c5, c99'; got {got}"
    )


def test_the_recorded_run_matches_the_author():
    shares, whole, cascades = [], 0, 0
    for row in rows():
        kept, rejected = validate_claims(row["output_parsed"], row["values"], "an_lab")
        shares.append(len(kept) / (len(kept) + len(rejected)))
        whole += not rejected
        cascades += sum(r.reason == "bad_derivation" for r in rejected)
    assert cascades == 14, f"the recorded run has 14 bad_derivation rejections (week-1.md §3); you have {cascades}"
    mean = round(sum(shares) / len(shares), 3)
    assert (mean, whole) == (0.748, 4), (
        f"the author's run scored claims_valid 0.748 with 4 of 20 analyses fully valid (week-1.md §2); yours "
        f"{mean}, {whole} of 20"
    )


def test_missing_ids_keep_the_derived_from_order():
    claims = {c["id"]: c for c in aapl()["output_parsed"]["claims"]}
    cases = ((["c99", "c5"], [claims["c5"]], "unknown claim id: c99, c5"),
             (["c9", "c5"], [claims["c5"], claims["c9"]], "derives from a rejected or later claim: c9, c5"))
    for parents, others, detail in cases:
        edited = {**claims["c8"], "derived_from": parents}
        got = reasons({"claims": [claims["c1"], *others[:1], edited, *others[1:]]}, aapl()["values"]).get("c8")
        assert got == ("bad_derivation", detail), (
            f"c8 with derived_from {parents} gave {got}; expected ('bad_derivation', {detail!r}). The missing ids "
            "are listed in the order derived_from has them, not sorted."
        )
