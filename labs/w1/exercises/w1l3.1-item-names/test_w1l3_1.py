"""w1l3.1 names in each item: the grader needs every source id's table name, so the dataset item must carry it.

Rows are the author's AMZN:2026-11-13 SOURCES table, from the recorded observe run (run_c40caab0968e44a3).
"""

import json
import os
from datetime import date
from pathlib import Path

from gigai_core import Dataset

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
    assert expected["names"] == row["names"], (
        f"expected['names'] has {len(expected['names'])} entries, the table has {len(row['names'])} rows: map every "
        "row's source_id to its name, nothing else"
    )


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
        "after this change must not be compared as if they used the same dataset (week-1.md §5)."
    )
