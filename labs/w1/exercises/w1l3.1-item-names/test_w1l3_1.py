"""w1l3.1 names in each item: the grader needs every source id's table name, so the dataset item must carry it.

Rows are the author's AMZN:2026-11-13 SOURCES table, from the recorded observe run (run_c40caab0968e44a3).
"""

import json
import os
from datetime import date
from pathlib import Path

from gigai_core import Dataset
import pytest

from tradingresearch.analyze import Context, Row, item_for

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")


def amzn() -> tuple[Context, dict]:
    row = next(r for r in map(json.loads, (DATA / "observe.jsonl").open()) if r["item"] == "AMZN:2026-11-13")
    # A row with no number is a label row (the regime); the recording keeps its value, not its label text.
    rows = [Row(source_id=sid, name=name, value=row["values"][sid], unit=None,
                label="label" if row["values"][sid] is None else None) for sid, name in row["names"].items()]
    return Context("AMZN", date(2026, 11, 13), None, [], rows), row


def test_item_carries_source_names():
    ctx, row = amzn()
    expected = item_for(ctx).expected
    assert "names" in expected, (
        f"item_for(AMZN:2026-11-13).expected has keys {sorted(expected)}. inferences_grounded must turn a cited source "
        "id into a name such as sma_200, so next to values the item needs a 'names' entry: every source id of the "
        "table, mapped to that row's name."
    )
    names, want = expected["names"], row["names"]
    assert isinstance(names, dict), f"expected['names'] is a {type(names).__name__}; make it a dict: source id to table name"
    if names != want:
        wrong = [sid for sid in want if names.get(sid) != want[sid]]
        extra = sorted(set(names) - set(want))
        detail = (f"maps {wrong[0]} to {names.get(wrong[0])!r}; it should map to that row's table name, "
                  f"{want[wrong[0]]!r} ({len(wrong)} of {len(want)} rows wrong)" if wrong else
                  f"has {len(extra)} keys that are not source ids of the table, e.g. {extra[0]!r}")
        pytest.fail(f"expected['names'] {detail}: map every row's source_id to its name, nothing else")


def test_values_are_unchanged():
    ctx, row = amzn()
    expected = item_for(ctx).expected
    assert expected.get("values") == row["values"], (
        "expected['values'] changed: claims_valid still reads it. Add names next to values; do not replace them."
    )


def test_the_dataset_hash_moves():
    ctx, _ = amzn()
    item = item_for(ctx)
    old = Dataset.of("observe", [item.model_copy(update={"expected": {"values": ctx.values()}})]).ref.sha256
    new = Dataset.of("observe", [item]).ref.sha256
    assert new != old, (
        "the dataset sha256 did not change, so expected did not change. A run records this hash: runs made before and "
        "after this change must not be compared as if they used the same dataset (the chapter's First evals section)."
    )


def test_names_come_from_the_context_given():
    rows = [Row(source_id="src_zz01", name="close", value=12.5, unit="usd"),
            Row(source_id="src_zz02", name="regime", value=None, unit=None, label="bull"),
            Row(source_id="src_zz03", name="revenue_CY2025Q2", value=1.0, unit="usd")]
    got = item_for(Context("ZZZ", date(2030, 1, 2), None, [], rows)).expected.get("names")
    want = {"src_zz01": "close", "src_zz02": "regime", "src_zz03": "revenue_CY2025Q2"}
    assert got == want, (
        f"item_for on a made-up ZZZ:2030-01-02 table of 3 rows (close, the regime label row, revenue_CY2025Q2) gave "
        f"names={got}; expected {want}. names comes from the rows of the context given, whatever its ticker or day."
    )
    got = item_for(Context("ZZZ", date(2030, 1, 2), None, [], [])).expected.get("names")
    assert got == {}, f"a context with no rows gave names={got}; a table with no rows has no names: {{}}"
