"""Experiments as config: the same ticker-days, one run per arm, the registry's graders, a paired comparison.

A config is a TOML file (see experiments/). Every arm asks the same gigai-core Dataset, so `compare` pairs the
answers item by item; an arm differs from the baseline only in what the config names (prompt version, model).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from gigai_core import CallBudget, Dataset, Run, compare
from gigai_core import run as run_eval

from . import analyze as an
from .evals import graders as registry

REQUIRED = ("name", "model", "max_usd_per_arm", "tickers", "sessions", "graders", "arms")


@dataclass(frozen=True)
class Arm:
    name: str
    prompt: str
    model: str


@dataclass(frozen=True)
class Config:
    name: str
    tickers: tuple[str, ...]
    sessions: tuple[date, ...]
    graders: tuple[str, ...]
    arms: tuple[Arm, ...]
    max_usd_per_arm: float


def load(path: Path) -> Config:
    raw = tomllib.loads(path.read_text())
    missing = [key for key in REQUIRED if key not in raw]
    if missing:
        raise SystemExit(f"{path}: missing {missing}")
    arms = tuple(Arm(a["name"], a["prompt"], a.get("model", raw["model"])) for a in raw["arms"])
    for arm in arms:
        an.system_prompt(arm.prompt)  # fail before any spend if a prompt file is missing
    registry(raw["graders"])  # and if a grader is not registered
    return Config(raw["name"], tuple(raw["tickers"]), tuple(date.fromisoformat(s) for s in raw["sessions"]),
                  tuple(raw["graders"]), arms, float(raw["max_usd_per_arm"]))


@dataclass
class ArmResult:
    arm: Arm
    run: Run
    path: Path
    analyses: int


def run_arms(conn, config: Config, contexts: list[an.Context], provider, prices: dict, data_dir: Path
             ) -> list[ArmResult]:
    """One run per arm on one Dataset. Each parsed sample is also stored as an Analysis, so `tr check` reads it."""
    dataset = Dataset.of(config.name, [an.item_for(ctx) for ctx in contexts])
    by_item = {f"{ctx.ticker}:{ctx.session}": ctx for ctx in contexts}
    results = []
    for arm in config.arms:
        run = run_eval(dataset, provider, registry(list(config.graders)), settings=an.call_settings(arm.model),
                       budget=CallBudget(max_usd=config.max_usd_per_arm, prices=prices),
                       system=an.system_prompt(arm.prompt), trace_dir=data_dir / "traces",
                       tag=f"{config.name}:{arm.name}:{arm.prompt}")
        path = an.save(run, data_dir)
        stored = 0
        for sample in run.samples:
            if sample.parse_status == "ok":
                ctx = by_item[sample.item_id]
                an.store(conn, ctx, sample, run.record.run_id, model=arm.model, prompt_version=arm.prompt,
                         route=provider.route_for(run.items[sample.item_id].prompt))
                stored += 1
        results.append(ArmResult(arm, run, path, stored))
    return results


def means(run: Run) -> dict[str, tuple[float, int]]:
    """Mean score and graded count per grader."""
    found: dict[str, list[float]] = {}
    for score in run.scores:
        found.setdefault(score.grader_id, []).append(score.value)
    return {grader: (sum(values) / len(values), len(values)) for grader, values in sorted(found.items())}
