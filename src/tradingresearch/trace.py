"""Saved runs and their model calls, read back for cost (SPIKE §1.3: `RunRecord.prices` is empty, so cost is
`ModelCall.cost_usd`). Calls come from the run file: its samples carry the same spans as `data/traces/`. Each call
carries its pipeline step and its prompt-cache tokens for `tr usage --by step|model` (G15-SPIKE §3)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Literal

from gigai_core import CoreModel, open_run
from gigai_core.records import RunRecord
from gigai_core.run import RunHeaderLine
from gigai_core.values import Outcome
from pydantic import AwareDatetime, JsonValue

Step = Literal["analyze", "thesis", "judge", "other"]


class Call(CoreModel):
    """One model call of a saved run as its span recorded it; None where the trace holds no value."""

    run_id: str
    item_id: str
    started_at: AwareDatetime
    model: str
    provider_route: str  # the model OpenRouter says served the call; the upstream host is not in the trace
    arm: str | None
    prompt_tokens: int | None  # prompt tokens including cache writes and reads, as the adapter recorded them
    cache_write_tokens: int | None
    cache_read_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    status: Outcome
    error: str | None  # the CallError code of a failed call
    step: Step


def arm(record: RunRecord) -> str | None:
    """`<experiment>:<arm>` from an `exp run` tag (`<experiment>:<arm>:<prompt>`); None for other runs."""
    parts = (record.tag or "").split(":")
    return f"{parts[0]}:{parts[1]}" if len(parts) == 3 else None


def kind(record: RunRecord) -> str:
    """`exp` for an experiment arm, else the dataset id (`analyze` for `tr analyze`)."""
    return "exp" if arm(record) else record.dataset.id


def step(record: RunRecord) -> Step:
    """The pipeline step of a run's calls (COST-SPIKE §2.1): `analyze` / `thesis` from the tag's prompt part
    (`analyze-N`, `thesis-N`, also the last part of an `exp run` tag) or the dataset id, `judge` for a
    `tr grade --judge` run, else `other`."""
    from .evals import P1Judge  # evals imports label, which imports grade, which imports this module
    prompt = (record.tag or "").split(":")[-1]
    if prompt.startswith("analyze-") or record.dataset.id == "analyze":
        return "analyze"
    if prompt.startswith("thesis-") or record.dataset.id == "thesis":
        return "thesis"
    return "judge" if record.tag == P1Judge.id else "other"


def count(value: JsonValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def cache_tokens(raw: Mapping[str, JsonValue]) -> tuple[int | None, int | None]:
    """(write, read) prompt-cache tokens from the provider's own usage payload: Anthropic's
    `cache_creation_input_tokens` / `cache_read_input_tokens`, OpenRouter's `prompt_tokens_details.cached_tokens` (a
    read; OpenRouter reports no write). None where the reply did not say."""
    details = raw.get("prompt_tokens_details")
    if isinstance(details, dict):
        return None, count(details.get("cached_tokens"))
    return count(raw.get("cache_creation_input_tokens")), count(raw.get("cache_read_input_tokens"))


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
    run_arm, run_step = arm(run.record), step(run.record)
    for sample in run.samples:
        for span in sample.model_spans:
            call = span.call
            cache_write, cache_read = cache_tokens(call.usage.raw)
            yield Call(
                run_id=run.record.run_id, item_id=sample.item_id, started_at=span.started_at,
                model=call.settings.model, provider_route=call.resolved_model, arm=run_arm,
                prompt_tokens=call.usage.input_tokens, cache_write_tokens=cache_write, cache_read_tokens=cache_read,
                completion_tokens=call.usage.output_tokens, cost_usd=call.cost_usd, latency_ms=call.latency_ms,
                status="failed" if span.error else "succeeded", error=span.error.code if span.error else None,
                step=run_step,
            )
