"""Observe w1l3.3: a four-claim chain where only recursion grounds the last inference, then the recorded run.

uv run python labs/w1/exercises/w1l3.3-recurse/observe.py   (from the repo root)

The recorded run stays at 19 flagged: none of its 20 replies has an inference that needs a grandparent's citation.
The chain below is made up so the change is visible.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

from tradingresearch.evals import InferencesGrounded

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[2] / "data")
CHAIN = [
    {"id": "c1", "tag": "fact", "text": "high_20 is {value}.", "source_ids": ["s1"], "derived_from": [], "steps": None},
    {"id": "c2", "tag": "inference", "text": "Price is just under its recent high.", "source_ids": [],
     "derived_from": ["c1"], "steps": "the close is below the value in c1"},
    {"id": "c3", "tag": "inference", "text": "The move has not reversed.", "source_ids": [],
     "derived_from": ["c2"], "steps": "c2 says price is under the high"},
    {"id": "c4", "tag": "inference", "text": "No breakout above high_20 yet.", "source_ids": [],
     "derived_from": ["c3"], "steps": "c3 says the move holds below the high"},
]

grader = InferencesGrounded()
score = grader.grade(SimpleNamespace(parse_status="ok", output_parsed={"claims": CHAIN}), {"names": {"s1": "high_20"}})
print("chain c1 fact (cites high_20) <- c2 inference <- c3 inference <- c4 inference naming high_20")
print(f"  score {score.value:g}  {score.explanation or 'grounded: c4 inherits what c1 cites, through c3 and c2'}")

rows = [json.loads(line) for line in (DATA / "observe.jsonl").open()]
flagged = sum(grader.grade(SimpleNamespace(parse_status=r["parse_status"], output_parsed=r["output_parsed"]),
                           {"values": r["values"], "names": r["names"]}).value == 0 for r in rows)
print(f"recorded observe run: flagged {flagged} of {len(rows)}")
