"""Saved runs and their model calls, read back for cost (SPIKE §1.3: `RunRecord.prices` is empty, so cost is
`ModelCall.cost_usd`). Calls come from the run file: its samples carry the same spans as `data/traces/`."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from gigai_core import CoreModel, open_run
from gigai_core.records import RunRecord
from gigai_core.run import RunHeaderLine
from gigai_core.values import Outcome
from pydantic import AwareDatetime


class Call(CoreModel):
    """One model call of a saved run as its span recorded it; None where the trace holds no value."""

    run_id: str
    item_id: str
    started_at: AwareDatetime
    model: str
    provider_route: str  # the model OpenRouter says served the call; the upstream host is not in the trace
    arm: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    status: Outcome
    error: str | None  # the CallError code of a failed call


def arm(record: RunRecord) -> str | None:
    """`<experiment>:<arm>` from an `exp run` tag (`<experiment>:<arm>:<prompt>`); None for other runs."""
    parts = (record.tag or "").split(":")
    return f"{parts[0]}:{parts[1]}" if len(parts) == 3 else None


def kind(record: RunRecord) -> str:
    """`exp` for an experiment arm, else the dataset id (`analyze` for `tr analyze`)."""
    return "exp" if arm(record) else record.dataset.id


def header(run_path: Path) -> RunRecord:
    """The run record from the first line only, so listing runs does not parse every sample."""
    with run_path.open("rb") as file:
        return RunHeaderLine.model_validate_json(file.readline()).record


def iter_runs(data_dir: Path) -> Iterator[tuple[RunRecord, Path]]:
    """Every saved run under `data_dir/runs`, oldest first."""
    found = [(header(path), path) for path in (data_dir / "runs").glob("run_*.jsonl")]
    yield from sorted(found, key=lambda pair: pair[0].created_at)


def calls(run_path: Path) -> Iterator[Call]:
    """Every model call of one run (subject and judge calls) in recorded order."""
    run = open_run(run_path)
    run_arm = arm(run.record)
    for sample in run.samples:
        for span in sample.model_spans:
            call = span.call
            yield Call(
                run_id=run.record.run_id, item_id=sample.item_id, started_at=span.started_at,
                model=call.settings.model, provider_route=call.resolved_model, arm=run_arm,
                prompt_tokens=call.usage.input_tokens, completion_tokens=call.usage.output_tokens,
                cost_usd=call.cost_usd, latency_ms=call.latency_ms,
                status="failed" if span.error else "succeeded", error=span.error.code if span.error else None,
            )
