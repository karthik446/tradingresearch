"""The gigai-core runs lab w5l3 compares ($0, no network): the author's three context-ablation runs, rebuilt from
data/ablation.runs.json, and hand-built runs whose scores a check chooses.

    stored()          {arm: Run} for full, no-headlines and no-edgar, as the author's run of 2026-11-17 scored them
    run(arm, scores)  one arm over TICKERS on one session: every item asked and parsed; `scores` is grader -> item ->
                      value, an item a grader has no value for is ungraded

A rebuilt run keeps what `compare` reads: the dataset, the items and their clusters, one parsed sample per item, and
every score with its grader, version and value, in the order the run wrote them. The replies and the requests are not
in the data file. TR_LAB_DATA overrides labs/w5/data.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from gigai_core import Run
from gigai_core.dataset import DatasetItem, DatasetRef
from gigai_core.providers import ProviderIdentity
from gigai_core.records import RunRecord
from gigai_core.sample import Sample
from gigai_core.score import ScoreRecord

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[1] / "data")
ARMS = ("full", "no-headlines", "no-edgar")
T0 = datetime(2026, 11, 13, 22, 0, tzinfo=UTC)
TICKERS = ("AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "UNH", "HD", "KO", "CAT")  # compare needs 10 clusters
IDS = tuple(f"{t}:2026-11-13" for t in TICKERS)
HAND = DatasetRef(id="ablation", version="1", sha256="0" * 64)


def build(run_id: str, tag: str, model: str, at: datetime, dataset: DatasetRef, items: list[tuple[str, str]],
          scores: list[tuple[str, str, str, float]]) -> Run:
    """A run of `items` ((id, cluster) pairs), one parsed sample each, with `scores` (grader, version, item, value)."""
    from tradingresearch import analyze as an  # the repo's own call settings, as `exp run` records them

    found = {item_id: DatasetItem(id=item_id, cluster_id=cluster, expected={}, prompt=f"SOURCES {item_id}")
             for item_id, cluster in items}
    samples = {item_id: Sample(trace_id=f"trace_{run_id[4:]}_{i:02d}", run_id=run_id, item_id=item_id,
                               item_version="1", cluster_id=item.cluster_id, repeat_index=0, input=(),
                               output_text="{}", output_parsed={}, parse_status="ok", outcome="succeeded",
                               error=None, recorded_at=at)
               for i, (item_id, item) in enumerate(found.items())}
    records = [ScoreRecord(score_id=f"score_{run_id[4:]}_{i:03d}", trace_id=samples[item_id].trace_id,
                           grader_id=grader, grader_version=version, kind="code", value=value, recorded_at=at)
               for i, (grader, version, item_id, value) in enumerate(scores)]
    record = RunRecord(run_id=run_id, dataset=dataset, settings=an.call_settings(model),
                       provider=ProviderIdentity(provider="openrouter", endpoint="lab", adapter="lab"),
                       created_at=at, tag=tag)
    return Run(record=record, items=found, samples=tuple(samples.values()), scores=tuple(records))


def stored() -> dict[str, Run]:
    """The author's three runs, by arm."""
    data = json.loads((DATA / "ablation.runs.json").read_text())
    dataset = DatasetRef(**data["dataset"])
    items = [tuple(pair) for pair in data["items"]]
    return {r["arm"]: build(r["run_id"], r["tag"], r["model"], datetime.fromisoformat(r["created_at"]), dataset,
                            items, [tuple(row) for row in r["scores"]])
            for r in data["runs"]}


def run(arm: str, scores: dict[str, dict[str, float]]) -> Run:
    """A hand-built arm over TICKERS: grader -> item -> value, graders scored in the order given."""
    rows = [(grader, "1", item, values[item]) for item in IDS for grader, values in scores.items() if item in values]
    return build(f"run_hand{arm.replace('-', '')[:12]:0<12}", f"ablation:{arm}:analyze-3", "openai/gpt-4.1-nano", T0,
                 HAND, [(item, item.split(":")[0]) for item in IDS], rows)
