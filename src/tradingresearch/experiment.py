"""Experiments as config: the same ticker-days, one run per arm, the registry's graders, a paired comparison.

A config is a TOML file (see experiments/). Every arm asks the same gigai-core Dataset, so `compare` pairs the
answers item by item; an arm differs from the baseline only in what the config names (prompt version, model, an
OpenRouter `provider` routing table such as a teacher's DeepInfra pin, SPIKE §9.4, and `mode`: `fixed` context or
`tools`, REPO-PLAN §2.4). `cluster` names the unit the intervals resample: `ticker` (week 1, the default) or `session`
(the live stream), REPO-PLAN D5.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from gigai_core import CallBudget, Dataset, DatasetItem, Run, compare
from gigai_core import run as run_eval
from gigai_core.stats.intervals import MIN_CLUSTERS

from . import analyze as an
from .evals import graders as registry
from .openrouter import Routing

REQUIRED = ("name", "model", "max_usd_per_arm", "tickers", "sessions", "graders", "arms")
CLUSTERS = ("ticker", "session")
MODES = ("fixed", "tools")  # context handed over up front, or asked for with tool calls (week 4)


@dataclass(frozen=True)
class Arm:
    name: str
    prompt: str
    model: str
    provider: Routing | None = None  # recorded in every call's ProviderIdentity, so the run shows how it was routed
    mode: str = "fixed"


@dataclass(frozen=True)
class Config:
    name: str
    tickers: tuple[str, ...]
    sessions: tuple[date, ...]
    graders: tuple[str, ...]
    arms: tuple[Arm, ...]
    max_usd_per_arm: float
    cluster: str = "ticker"


def load(path: Path) -> Config:
    raw = tomllib.loads(path.read_text())
    missing = [key for key in REQUIRED if key not in raw]
    if missing:
        raise SystemExit(f"{path}: missing {missing}")
    arms = tuple(Arm(a["name"], a["prompt"], a.get("model", raw["model"]), routing(path, a), mode(path, a))
                 for a in raw["arms"])
    for arm in arms:
        an.system_prompt(arm.prompt)  # fail before any spend if a prompt file is missing
    registry(raw["graders"])  # and if a grader is not registered
    config = Config(raw["name"], tuple(raw["tickers"]), tuple(date.fromisoformat(s) for s in raw["sessions"]),
                    tuple(raw["graders"]), arms, float(raw["max_usd_per_arm"]), raw.get("cluster", "ticker"))
    check_clusters(path, config)
    return config


def check_clusters(path: Path, config: Config) -> None:
    """Refuse, before any spend, a cluster key `compare` cannot use: unknown, or (with an arm to compare) fewer than
    MIN_CLUSTERS units. A one-arm config compares nothing, so its count is not checked."""
    if config.cluster not in CLUSTERS:
        raise SystemExit(f"{path}: cluster must be one of {', '.join(CLUSTERS)}, not {config.cluster!r}")
    units = config.tickers if config.cluster == "ticker" else config.sessions
    count = len(set(units))
    if len(config.arms) > 1 and count < MIN_CLUSTERS:
        raise SystemExit(f"{path}: cluster = {config.cluster!r} gives {count} clusters; compare needs at least "
                         f"{MIN_CLUSTERS}")


def routing(path: Path, arm: dict) -> Routing | None:
    """An arm's `provider` table, refused before any spend if a key, type or quantization is wrong."""
    if "provider" not in arm:
        return None
    try:
        return Routing.from_config(arm["provider"])
    except ValueError as exc:
        raise SystemExit(f"{path}: arm {arm.get('name')}: {exc}") from None


def mode(path: Path, arm: dict) -> str:
    """An arm's `mode`, refused before any spend unless it is one of MODES."""
    value = arm.get("mode", "fixed")
    if value not in MODES:
        raise SystemExit(f"{path}: arm {arm.get('name')}: mode must be one of {', '.join(MODES)}, not {value!r}")
    return value


@dataclass
class ArmResult:
    arm: Arm
    run: Run
    path: Path
    analyses: int


def run_arms(conn, config: Config, contexts: list[an.Context], provider, prices: dict, data_dir: Path
             ) -> list[ArmResult]:
    """One run per arm on one Dataset. Each parsed sample is also stored as an Analysis, so `tr check` reads it."""
    if any(arm.mode == "tools" for arm in config.arms):  # before the first arm, so no call is made
        raise NotImplementedError("mode=tools: week 4 learner work")
    dataset = Dataset.of(config.name, items(config, contexts))
    by_item = {f"{ctx.ticker}:{ctx.session}": ctx for ctx in contexts}
    results = []
    for arm in config.arms:
        routed = provider.routed(arm.provider) if arm.provider else provider
        run = run_eval(dataset, routed, registry(list(config.graders)), settings=an.call_settings(arm.model),
                       budget=CallBudget(max_usd=config.max_usd_per_arm, prices=prices),
                       system=an.system_prompt(arm.prompt), trace_dir=data_dir / "traces",
                       tag=f"{config.name}:{arm.name}:{arm.prompt}")
        path = an.save(run, data_dir)
        stored = 0
        for sample in run.samples:
            if sample.parse_status == "ok":
                ctx = by_item[sample.item_id]
                an.store(conn, ctx, sample, run.record.run_id, model=arm.model, prompt_version=arm.prompt,
                         route=routed.route_for(run.items[sample.item_id].prompt))
                stored += 1
        results.append(ArmResult(arm, run, path, stored))
    return results


def items(config: Config, contexts: list[an.Context]) -> list[DatasetItem]:
    """The dataset items: `ticker` keeps `analyze.item_for` byte for byte; `session` clusters on the session date."""
    found = [an.item_for(ctx) for ctx in contexts]
    if config.cluster == "session":
        return [item.model_copy(update={"cluster_id": ctx.session.isoformat()}) for item, ctx in zip(found, contexts)]
    return found


def means(run: Run) -> dict[str, tuple[float, int]]:
    """Mean score and graded count per grader."""
    found: dict[str, list[float]] = {}
    for score in run.scores:
        found.setdefault(score.grader_id, []).append(score.value)
    return {grader: (sum(values) / len(values), len(values)) for grader, values in sorted(found.items())}
