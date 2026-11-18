"""Cost per call, run, arm, day, step, model and tag: pure sums over `trace.Call` rows (REPO-PLAN §7 G7, SPIKE §1.3,
G15-SPIKE §3), joined with the cost ledger `analyze.save` appends to (COST-SPIKE §2.2): the ledger names a run's
step and tag, and a ledger row whose run file is gone still counts in the totals."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import date
from pathlib import Path

from gigai_core import CoreModel
from gigai_core.records import RunRecord
from pydantic import AwareDatetime

from .sessions import NY
from .trace import Call, calls, header

UNTAGGED = "(untagged)"  # the `--by tag` row of runs with no `cost_tag`


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


class LedgerRow(CoreModel):
    """One row of the cost ledger as `analyze.ledger_row` writes it (COST-1): the run's totals and labels, no
    per-call detail."""

    run_id: str
    data_dir: Path
    created_at: AwareDatetime
    step: str
    purpose: str | None
    cost_tag: str | None
    experiment: str | None
    arm: str | None
    session: str | None
    models: list[str]
    calls: int
    tokens_in: int
    tokens_out: int
    reasoning_tokens: int | None
    cached_tokens: int | None
    spent_usd: float
    calls_without_cost: int


def read_ledger(path: Path) -> list[LedgerRow]:
    """Every row of the ledger in file order; none when there is no ledger yet."""
    if not path.is_file():
        return []
    return [LedgerRow.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def day(call: Call | LedgerRow) -> date:
    """The New York date of the call (a ledger row: of the run), so an evening run counts on the session day it
    belongs to."""
    at = call.started_at if isinstance(call, Call) else call.created_at
    return at.astimezone(NY).date()


def tag_key(row: LedgerRow | None) -> str:
    return row.cost_tag if row and row.cost_tag else UNTAGGED


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


def by_step(rows: Iterable[Call], ledger: Mapping[str, LedgerRow] = {}) -> list[Usage]:
    """The ledger's step where the run has a row (`TR_COST_TAG` named it), else `trace.step`'s `analyze`, `thesis`,
    `judge` or `other`."""
    return grouped(rows, lambda call: ledger[call.run_id].step if call.run_id in ledger else call.step)


def by_tag(rows: Iterable[Call], ledger: Mapping[str, LedgerRow] = {}) -> list[Usage]:
    """The ledger's `cost_tag` of the run; runs with no tag, or no ledger row, group under `(untagged)`."""
    return grouped(rows, lambda call: tag_key(ledger.get(call.run_id)))


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


# ---------- the ledger joined with the run files (COST-SPIKE §2.2, §2.4 `--all-dirs`) ----------


def run_dirs(roots: Iterable[Path]) -> Iterator[Path]:
    """Every `runs` directory at or below each root, in path order; dot-directories (`.git`, `.venv`) are not
    entered."""
    for root in roots:
        for parent, dirs, _ in os.walk(root):
            dirs[:] = sorted(name for name in dirs if not name.startswith("."))
            if Path(parent).name == "runs":
                yield Path(parent)


def all_runs(roots: Iterable[Path], ledger: Iterable[LedgerRow],
             ) -> tuple[list[tuple[RunRecord, Path]], list[LedgerRow]]:
    """The run files under every `runs` directory below `roots`, plus the file each ledger row points at
    (`<data_dir>/runs/<run_id>.jsonl`, wherever that is), one per run_id (the first found wins), oldest first; and
    the ledger-only rows: those whose run file is not found anywhere, which still count toward the totals."""
    found: dict[str, tuple[RunRecord, Path]] = {}
    rows = list(ledger)
    paths = [path for runs in run_dirs(roots) for path in sorted(runs.glob("run_*.jsonl"))]
    paths += [path for row in rows if (path := row.data_dir / "runs" / f"{row.run_id}.jsonl").is_file()]
    for path in paths:
        record = header(path)
        found.setdefault(record.run_id, (record, path))
    orphans = [row for row in rows if row.run_id not in found]
    return sorted(found.values(), key=lambda pair: pair[0].created_at), orphans


def from_ledger(key: str, rows: list[LedgerRow]) -> Usage:
    """One row for ledger-only runs: their totals, with no items, cache writes or latencies (the run files held
    those)."""
    cost = round(sum(row.spent_usd for row in rows), 6)
    without = sum(row.calls_without_cost for row in rows)
    return Usage(
        key=key, calls=sum(row.calls for row in rows), items=0,
        tokens_in=sum(row.tokens_in for row in rows), cache_write=None,
        cache_read=reported(row.cached_tokens for row in rows),
        tokens_out=sum(row.tokens_out for row in rows), reasoning=reported(row.reasoning_tokens for row in rows),
        cost_usd=cost, usd_per_item=0.0, mean_latency_ms=0.0, p50_ms=0, p95_ms=0,
        prices_missing=without > 0, calls_without_cost=without,
    )


def fold(rows: list[Usage], orphans: Iterable[LedgerRow], key: Callable[[LedgerRow], str]) -> list[Usage]:
    """`rows` with the ledger-only runs added by `key`: calls, tokens, cost and the no-cost count join the row of
    their key (a new row for a key no run file had); items, $ per item and latencies stay the run files', since a
    ledger row has no per-call detail."""
    extra: dict[str, list[LedgerRow]] = {}
    for row in orphans:
        extra.setdefault(key(row), []).append(row)
    joined = []
    for row in rows:
        more = from_ledger(row.key, extra.pop(row.key, []))
        joined.append(row.model_copy(update={
            "calls": row.calls + more.calls, "tokens_in": row.tokens_in + more.tokens_in,
            "tokens_out": row.tokens_out + more.tokens_out,
            "cache_read": reported([row.cache_read, more.cache_read]),
            "reasoning": reported([row.reasoning, more.reasoning]),
            "cost_usd": round(row.cost_usd + more.cost_usd, 6),
            "prices_missing": row.prices_missing or more.prices_missing,
            "calls_without_cost": row.calls_without_cost + more.calls_without_cost,
        }) if more.calls else row)
    return joined + [from_ledger(name, group) for name, group in extra.items()]
