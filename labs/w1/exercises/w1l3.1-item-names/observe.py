"""Observe w1l3.1: the keys of one dataset item's `expected`, and the dataset hash a run would record.

uv run python labs/w1/exercises/w1l3.1-item-names/observe.py   (from the repo root)
"""

import json
from datetime import date
from pathlib import Path

from gigai_core import Dataset

from tradingresearch.analyze import Context, Row, item_for

DATA = Path(__file__).resolve().parents[2] / "data"
row = next(r for r in map(json.loads, (DATA / "observe.jsonl").open()) if r["item"] == "AMZN:2026-11-13")
rows = [Row(source_id=sid, name=name, value=row["values"][sid], unit=None,
            label="label" if row["values"][sid] is None else None) for sid, name in row["names"].items()]
item = item_for(Context("AMZN", date(2026, 11, 13), None, [], rows))
print("expected keys:", sorted(item.expected))
print("names:", len(item.expected.get("names", {})), "of", len(rows), "table rows")
print("dataset sha256:", Dataset.of("observe", [item]).ref.sha256[:16])
