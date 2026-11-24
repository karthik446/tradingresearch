"""w1l1.1 unknown_source: a claim may cite only source ids that are in its SOURCES table.

Claims are the author's, from the recorded observe run (run_c40caab0968e44a3).
"""

import json
import os
from pathlib import Path

from tradingresearch.analyze import validate_claims

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")


def recorded(item: str) -> dict:
    for line in (DATA / "observe.jsonl").open():
        row = json.loads(line)
        if row["item"] == item:
            return row
    raise LookupError(item)


def reasons(row: dict) -> dict[str, tuple[str, str]]:
    try:
        _, rejected = validate_claims(row["output_parsed"], row["values"], "an_lab")
    except KeyError as exc:
        raise AssertionError(
            f"validate_claims crashed with KeyError {exc} on {row['item']}: a claim cites a source id that is not in "
            "the table and check_one looked it up in `values`. Reject it as unknown_source before any lookup."
        ) from None
    return {r.claim: (r.reason, r.detail) for r in rejected}


def test_unh_2026_11_12_c7_cites_a_source_that_is_not_in_the_table():
    got = reasons(recorded("UNH:2026-11-12"))
    assert "c7" in got, "UNH 2026-11-12 c7 cites src_aa2421e8c7298ffd, which is not in its SOURCES table, but it was kept"
    assert got["c7"] == ("unknown_source", "src_aa2421e8c7298ffd"), (
        f"c7 should be rejected as ('unknown_source', 'src_aa2421e8c7298ffd'): the reason, then the unknown ids "
        f"joined by ', '. Got {got['c7']}"
    )


def test_ids_from_the_table_are_not_unknown():
    row = recorded("KO:2026-11-13")
    got = reasons(row)
    wrong = [cid for cid, (reason, _) in got.items() if reason == "unknown_source"]
    assert not wrong, (
        f"KO 2026-11-13 {wrong} cite only ids from their table, yet were rejected as unknown_source: "
        "a known id is a key of `values`"
    )


def test_any_id_missing_from_the_table_is_unknown():
    claim = {"id": "c1", "tag": "fact", "text": "The close is {value}.", "value": 1.0, "unit": "usd",
             "source_ids": ["src_known", "src_zz_new", "src_aa_new"], "derived_from": [], "steps": None}
    got = reasons({"item": "a made-up reply", "output_parsed": {"claims": [claim]}, "values": {"src_known": 1.0}})
    assert got.get("c1") == ("unknown_source", "src_zz_new, src_aa_new"), (
        "a made-up claim cites src_known (in its table) and src_zz_new, src_aa_new (not in it). Expected "
        f"('unknown_source', 'src_zz_new, src_aa_new'), got {got.get('c1')}. The check must hold for any id missing "
        "from the table, not only the one in the recording, and list the missing ids in the order the claim cites them."
    )


def test_opinions_and_inferences_cite_known_ids_too():
    claims = [
        {"id": "c1", "tag": "fact", "text": "The close is {value}.", "value": 1.0, "unit": "usd",
         "source_ids": ["src_known"], "derived_from": [], "steps": None},
        {"id": "c2", "tag": "opinion", "text": "The trend looks strong.", "value": None, "unit": None,
         "source_ids": ["src_zz_new"], "derived_from": [], "steps": None},
        {"id": "c3", "tag": "inference", "text": "Price is above the close.", "value": None, "unit": None,
         "source_ids": ["src_aa_new"], "derived_from": ["c1"], "steps": "c1 gives the close"},
    ]
    got = reasons({"item": "a made-up reply", "output_parsed": {"claims": claims}, "values": {"src_known": 1.0}})
    for cid, tag, src in (("c2", "opinion", "src_zz_new"), ("c3", "inference", "src_aa_new")):
        assert got.get(cid) == ("unknown_source", src), (
            f"a made-up {tag} {cid} cites {src}, which is not in its table. Expected ('unknown_source', '{src}'), got "
            f"{got.get(cid)}. An id outside the table is unknown whatever the claim's tag: an opinion or an inference "
            "that cites a made-up source is as unsupported as a fact that does."
        )


def made_up(tag: str, value: float | None, *sources: str) -> dict:
    return {"id": "c1", "tag": tag, "text": "The trend looks calm.", "value": value, "unit": None,
            "source_ids": list(sources), "derived_from": [], "steps": None}


def test_an_id_whose_value_is_null_is_known():
    values = {"src_known": 1.0, "src_regime": None}
    got = reasons({"item": "a made-up reply", "output_parsed": {"claims": [made_up("fact", None, "src_regime")]},
                   "values": values})
    assert got.get("c1") is None, (
        f"a made-up fact c1 cites src_regime, which is in its table with value null (a label row, such as the regime), "
        f"and was rejected as {got.get('c1')}. The id is a key of the table, so it is known: unknown means the id is "
        "missing from the table, not that its value is null."
    )


def test_ids_match_exactly_case_included():
    got = reasons({"item": "a made-up reply", "output_parsed": {"claims": [made_up("fact", None, "SRC_KNOWN")]},
                   "values": {"src_known": 1.0}})
    assert got.get("c1") == ("unknown_source", "SRC_KNOWN"), (
        f"a made-up fact c1 cites SRC_KNOWN; its table has src_known. Expected ('unknown_source', 'SRC_KNOWN'), got "
        f"{got.get('c1')}. A source id is matched exactly, case included: SRC_KNOWN is no id in the table, and a "
        "model that miscopies an id has not cited the source."
    )


def test_a_made_up_id_is_reported_before_the_opinion_rule():
    got = reasons({"item": "a made-up reply", "output_parsed": {"claims": [made_up("opinion", 3.0, "src_zz_new")]},
                   "values": {"src_known": 1.0}})
    assert got.get("c1") == ("unknown_source", "src_zz_new"), (
        f"a made-up opinion c1 has value 3.0 and cites src_zz_new, which is not in its table. Expected "
        f"('unknown_source', 'src_zz_new'), got {got.get('c1')}. Both rules are broken; check_one reports the first "
        "one in its order, and the unknown_source check sits before the number_in_opinion check."
    )
