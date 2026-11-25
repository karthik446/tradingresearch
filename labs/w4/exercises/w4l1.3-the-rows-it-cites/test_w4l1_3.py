"""w4l1.3 the rows it cites: each row a tool returns is {source_id, name, unit, value} (plus the regime's label), its
value written as the fixed arm's SOURCES table writes it, and `names` picks rows by name or says which names exist.

The fixture's values are already rounded to the table's digits, so a row that shows its raw value would pass on them.
These checks run on the same FAKEA context with every value times 1.0000123 (tools/fakea.py `context(extra=True)`):
close is 101.40124722 there, revenue_CY2026Q3 1950023985.0000002, and the table (analyze.render) shows 101.401 and
1950023985. The tools mode and the fixed mode are compared on the same numbers only when a row shows what the table
shows.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fakea  # noqa: E402

from tradingresearch import tools  # noqa: E402

THREE = ("get_indicators", "get_levels", "get_fundamentals")
CTX = fakea.context(extra=True)
TABLE = fakea.table(CTX)  # source_id -> (name, value or label as the table shows it, unit)
BY_ID = {row.source_id: row for row in CTX.rows}


def answer(name: str, arguments: str) -> dict:
    try:
        got = fakea.result_of(tools.run_tool(CTX, name, arguments))
    except Exception as exc:  # noqa: BLE001 - a raise is a failure this check reports
        got = f"raised {exc!r}"
    assert isinstance(got, dict), f"run_tool({name!r}, {arguments!r}) {got}"
    return got


def rows_of(name: str, arguments: str = "{}") -> list[dict]:
    got = answer(name, arguments)
    assert isinstance(got.get("rows"), list), f"run_tool({name!r}, {arguments!r}) returned {json.dumps(got)[:200]}"
    return got["rows"]


def test_each_row_carries_what_a_claim_cites():
    for name in THREE:
        for got in rows_of(name):
            row = BY_ID.get(got.get("source_id"))
            want = {"source_id", "name", "unit", "value"} | ({"label"} if row and row.label is not None else set())
            assert set(got) == want, (
                f"{name} returns the row {json.dumps(got)[:160]}; a row is {{source_id, name, unit, value}}, plus "
                f"label when the row has one. Lacking {sorted(want - set(got))}, extra {sorted(set(got) - want)}: a "
                f"claim cites a row by its source_id, and validate_claims rejects a claim whose source_id is unknown")
            assert row is not None, f"{name} returns {json.dumps(got)[:160]}, whose source_id is no row of the context"
            assert (got["name"], got["unit"]) == (row.name, row.unit), (
                f"{name} returns {json.dumps(got)[:160]} for {row.source_id}, which is {row.name} in {row.unit}")


def test_each_value_is_the_number_the_sources_table_shows():
    for name in THREE:
        for got in rows_of(name):
            row, (_, shown, _) = BY_ID[got["source_id"]], TABLE[got["source_id"]]
            if row.label is not None:
                assert got["value"] is None and got.get("label") == shown, (
                    f"{name} returns {json.dumps(got)} for {row.name}; it has no value, and the table shows its "
                    f"label, {shown}")
                continue
            value = got["value"]
            assert isinstance(value, (int, float)) and not isinstance(value, bool), (
                f"{name} returns {row.name}'s value as {value!r}, a {type(value).__name__}: a value is a JSON number")
            assert value == float(shown), (
                f"{name} returns {row.name} as {value!r}; the fixed SOURCES table shows {shown} for the same row (its "
                f"value is {row.value!r} in this context). A claim that copies {value!r} cites a number the fixed arm "
                f"never showed, so the two arms are not answering from the same numbers")


def test_names_picks_those_rows_and_an_unknown_name_is_an_error_listing_the_names():
    picked = [got["name"] for got in rows_of("get_indicators", '{"names": ["close", "rsi_14"]}')]
    assert sorted(picked) == ["close", "rsi_14"], (
        f'get_indicators with {{"names": ["close", "rsi_14"]}} returns {len(picked)} rows ({", ".join(picked[:6])}'
        f'{", ..." if len(picked) > 6 else ""}): the model asked for two rows, and every other one is context it did '
        f"not ask for")
    every = [got["name"] for got in rows_of("get_indicators")]
    for names, why in ((["rsi"], "no row is named rsi (the row is rsi_14)"),
                       (["close", "rsi"], "close exists but rsi does not; answering with close alone hides that"),
                       (["level_hvn_1"], "level_hvn_1 is get_levels's row, not get_indicators's")):
        got = answer("get_indicators", json.dumps({"names": names}))
        assert isinstance(got.get("error"), str), (
            f"get_indicators with {json.dumps({'names': names})} returns {json.dumps(got)[:160]}: {why}, so the "
            f"answer is an error the model can correct")
        missing = [n for n in every if n not in got["error"]]
        assert not missing, (
            f"the error for {json.dumps({'names': names})} is {got['error'][:160]!r}; it does not list "
            f"{', '.join(missing[:5])}: the model can only ask again with a real name if the error lists them")
