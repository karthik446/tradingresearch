"""Cost per call, run, arm and day: pure sums over `trace.Call` rows (REPO-PLAN §7 G7, SPIKE §1.3)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

from gigai_core import CoreModel

from .sessions import NY
from .trace import Call, calls


class Usage(CoreModel):
    """Totals for one group of calls. `prices_missing`: a call has no cost, so `cost_usd` is a lower bound."""

    key: str
    calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    mean_latency_ms: float
    prices_missing: bool


def day(call: Call) -> date:
    """The New York date of the call, so an evening run counts on the session day it belongs to."""
    return call.started_at.astimezone(NY).date()


def summarize(key: str, group: list[Call]) -> Usage:
    """One row for `group`; a missing token count adds 0, a missing cost adds 0 and sets `prices_missing`."""
    return Usage(
        key=key, calls=len(group),
        tokens_in=sum(call.prompt_tokens or 0 for call in group),
        tokens_out=sum(call.completion_tokens or 0 for call in group),
        cost_usd=round(sum(call.cost_usd or 0.0 for call in group), 6),
        mean_latency_ms=sum(call.latency_ms for call in group) / len(group) if group else 0.0,
        prices_missing=any(call.cost_usd is None for call in group),
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


def total(rows: list[Usage]) -> Usage:
    """The sum of `rows`; the mean latency is weighted by each row's call count."""
    count = sum(row.calls for row in rows)
    return Usage(
        key="total", calls=count,
        tokens_in=sum(row.tokens_in for row in rows), tokens_out=sum(row.tokens_out for row in rows),
        cost_usd=round(sum(row.cost_usd for row in rows), 6),
        mean_latency_ms=sum(row.mean_latency_ms * row.calls for row in rows) / count if count else 0.0,
        prices_missing=any(row.prices_missing for row in rows),
    )


def run_cost(run_path: Path) -> Usage:
    """A saved run's cost summed from its calls: the one place the base asks what a run cost."""
    return summarize(run_path.stem, list(calls(run_path)))
