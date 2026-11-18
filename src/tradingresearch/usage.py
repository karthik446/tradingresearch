"""Cost per call, run, arm, day, step and model: pure sums over `trace.Call` rows (REPO-PLAN §7 G7, SPIKE §1.3,
G15-SPIKE §3)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

from gigai_core import CoreModel

from .sessions import NY
from .trace import Call, calls


class Usage(CoreModel):
    """Totals for one group of calls. `prices_missing`: a call has no cost (`calls_without_cost` counts them), so
    `cost_usd` is a lower bound. `items` counts distinct item ids (an arm's analyze and thesis calls of one ticker-day
    are one item). `cache_write`, `cache_read` and `reasoning` are None when no call reported them. `p50_ms` /
    `p95_ms` are nearest-rank percentiles over items of the summed latency of each item's calls in the group."""

    key: str
    calls: int
    items: int
    tokens_in: int
    cache_write: int | None
    cache_read: int | None
    tokens_out: int
    reasoning: int | None
    cost_usd: float
    usd_per_item: float
    mean_latency_ms: float
    p50_ms: int
    p95_ms: int
    prices_missing: bool
    calls_without_cost: int


def day(call: Call) -> date:
    """The New York date of the call, so an evening run counts on the session day it belongs to."""
    return call.started_at.astimezone(NY).date()


def reported(values: Iterable[int | None]) -> int | None:
    """The sum of the values a provider reported; None when none did."""
    found = [value for value in values if value is not None]
    return sum(found) if found else None


def nearest_rank(values: list[int], percent: int) -> int:
    """The smallest value with at least `percent`% of `values` at or below it; 0 for no values."""
    ordered = sorted(values)
    return ordered[max((percent * len(ordered) + 99) // 100, 1) - 1] if ordered else 0


def summarize(key: str, group: list[Call]) -> Usage:
    """One row for `group`; a missing token count adds 0, a missing cost adds 0, sets `prices_missing` and counts in
    `calls_without_cost`."""
    per_item: dict[str, int] = {}
    for call in group:
        per_item[call.item_id] = per_item.get(call.item_id, 0) + call.latency_ms
    cost = sum(call.cost_usd or 0.0 for call in group)
    latencies = list(per_item.values())
    return Usage(
        key=key, calls=len(group), items=len(per_item),
        tokens_in=sum(call.prompt_tokens or 0 for call in group),
        cache_write=reported(call.cache_write_tokens for call in group),
        cache_read=reported(call.cache_read_tokens for call in group),
        tokens_out=sum(call.completion_tokens or 0 for call in group),
        reasoning=reported(call.reasoning_tokens for call in group),
        cost_usd=round(cost, 6), usd_per_item=round(cost / len(per_item), 6) if per_item else 0.0,
        mean_latency_ms=sum(call.latency_ms for call in group) / len(group) if group else 0.0,
        p50_ms=nearest_rank(latencies, 50), p95_ms=nearest_rank(latencies, 95),
        prices_missing=any(call.cost_usd is None for call in group),
        calls_without_cost=sum(call.cost_usd is None for call in group),
    )


def grouped(rows: Iterable[Call], key: Callable[[Call], str]) -> list[Usage]:
    """One row per key, in the order each key first appears."""
    found: dict[str, list[Call]] = {}
    for call in rows:
        found.setdefault(key(call), []).append(call)
    return [summarize(name, group) for name, group in found.items()]


def by_call(rows: Iterable[Call]) -> list[Usage]:
    return [summarize(f"{call.run_id} {call.item_id}", [call]) for call in rows]


def by_run(rows: Iterable[Call]) -> list[Usage]:
    return grouped(rows, lambda call: call.run_id)


def by_arm(rows: Iterable[Call]) -> list[Usage]:
    """Experiment arms as `<experiment>:<arm>`; calls outside an experiment group under `-`."""
    return grouped(rows, lambda call: call.arm or "-")


def by_day(rows: Iterable[Call]) -> list[Usage]:
    return sorted(grouped(rows, lambda call: day(call).isoformat()), key=lambda row: row.key)


def by_step(rows: Iterable[Call]) -> list[Usage]:
    """`analyze`, `thesis`, `judge` or `other` (`trace.step`)."""
    return grouped(rows, lambda call: call.step)


def by_model(rows: Iterable[Call]) -> list[Usage]:
    """The requested model (the span's `settings.model`), not the model that served the call."""
    return grouped(rows, lambda call: call.model)


def total(rows: Iterable[Call]) -> Usage:
    """One row over all of `rows`, from the calls themselves (items and percentiles do not add up across view rows).
    The cost is the sum of each run's micro-dollar cost (`run_cost`), so every view's total equals the `--by run`
    total to the last digit."""
    group = list(rows)
    per_run: dict[str, float] = {}
    for call in group:
        per_run[call.run_id] = per_run.get(call.run_id, 0.0) + (call.cost_usd or 0.0)
    found = summarize("total", group)
    cost = round(sum(round(run, 6) for run in per_run.values()), 6)
    per_item = round(cost / found.items, 6) if found.items else 0.0
    return found.model_copy(update={"cost_usd": cost, "usd_per_item": per_item})


def run_cost(run_path: Path) -> Usage:
    """A saved run's cost summed from its calls: the one place the base asks what a run cost."""
    return summarize(run_path.stem, list(calls(run_path)))
