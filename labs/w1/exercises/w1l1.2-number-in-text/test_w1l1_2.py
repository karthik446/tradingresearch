"""w1l1.2 number_in_text: numbers live in `value`, never in the prose.

Claims are the author's, from the recorded observe run (run_c40caab0968e44a3).
"""

import json
import os
from pathlib import Path

from tradingresearch.analyze import validate_claims

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")


def rows() -> list[dict]:
    return [json.loads(line) for line in (DATA / "observe.jsonl").open()]


def reasons(row: dict) -> dict[str, tuple[str, str]]:
    _, rejected = validate_claims(row["output_parsed"], row["values"], "an_lab")
    return {r.claim: (r.reason, r.detail) for r in rejected}


def aapl() -> dict:
    return next(row for row in rows() if row["item"] == "AAPL:2026-11-12")


def test_aapl_2026_11_12_c5_names_a_window_in_prose():
    got = reasons(aapl())
    assert "c5" in got, (
        "AAPL 2026-11-12 c5 ends '...below the 20-day high.': the 20 is a number in prose, outside {value}, but the "
        "claim was kept. Digits that ALLOWED_DIGITS matches (dates, table names such as sma_200) are allowed; a digit "
        "anywhere else in the text is a number in prose."
    )
    text = next(c["text"] for c in aapl()["output_parsed"]["claims"] if c["id"] == "c5")
    assert got["c5"] == ("number_in_text", text[:120]), (
        f"c5 should be ('number_in_text', <first 120 characters of the text>); got {got['c5']}"
    )


def test_dates_and_table_names_are_not_numbers_in_text():
    got = reasons(aapl())
    assert got.get("c1", ("",))[0] != "number_in_text", (
        "AAPL 2026-11-12 c1 'AAPL closed the 2026-11-12 session at {value} USD.' was rejected as number_in_text: a "
        "YYYY-MM-DD date is allowed. Only digits outside what ALLOWED_DIGITS matches count."
    )
    assert got.get("c2", ("",))[0] != "number_in_text", (
        "AAPL 2026-11-12 c2 'The sma_200 stood at {value} USD' was rejected as number_in_text: the 200 in sma_200 is "
        "part of a table name, which ALLOWED_DIGITS allows."
    )


def test_the_recorded_run_has_34_numbers_in_text():
    found = sum(reason == "number_in_text" for row in rows() for reason, _ in reasons(row).values())
    assert found == 34, (
        f"the recorded observe run has 34 claims with a digit outside {{value}}, dates and table names; your check "
        f"rejects {found}"
    )
