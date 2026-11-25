"""Experiments as config: the same ticker-days, one run per arm, the registry's graders, a paired comparison.

A config is a TOML file (see experiments/). Every arm asks the same gigai-core Dataset, so `compare` pairs the
answers item by item; an arm differs from the baseline only in what the config names (prompt version, model, an
OpenRouter `provider` routing table such as a teacher's DeepInfra pin, week 2 section 5, and `mode`: `fixed` context or
`tools`, REPO-PLAN §2.4). `cluster` names the unit the intervals resample: `ticker` (week 1, the default) or `session`
(the live stream), REPO-PLAN D5.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from gigai_core import CallBudget, Dataset, DatasetItem, Run, compare
from gigai_core import run as run_eval
from gigai_core.budget import budgeted
from gigai_core.graders.protocol import CannotGrade, Grader
from gigai_core.providers import ModelRequest, Turn
from gigai_core.records import RunRecord
from gigai_core.sample import Sample
from gigai_core.score import ScoreRecord
from gigai_core.stats.intervals import MIN_CLUSTERS
from gigai_core.trace import JsonlTrace

from . import analyze as an
from .evals import graders as registry
from .hashing import new_id
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
    # TODO(w4l3.2) a tools arm's samples are graded by code (a model grader reads no tool calls): refuse a config
    #   that puts a non-code grader beside a tools arm, before the first arm runs, so no call is made.
    if any(arm.mode == "tools" for arm in config.arms):  # before the first arm, so no call is made
        raise NotImplementedError("mode=tools: week 4 learner work")
    dataset = Dataset.of(config.name, items(config, contexts))
    by_item = {f"{ctx.ticker}:{ctx.session}": ctx for ctx in contexts}
    results = []
    for arm in config.arms:
        routed = provider.routed(arm.provider) if arm.provider else provider
        # TODO(w4l3.2) a `mode = "tools"` arm runs through `run_tools`; a fixed arm stays on core `run`.
        run = run_eval(dataset, routed, registry(list(config.graders)), settings=an.call_settings(arm.model),
                       budget=CallBudget(max_usd=config.max_usd_per_arm, prices=prices),
                       system=an.system_prompt(arm.prompt), trace_dir=data_dir / "traces",
                       tag=f"{config.name}:{arm.name}:{arm.prompt}")
        path = an.save(run, data_dir)
        stored = 0
        for sample in run.samples:
            if sample.parse_status == "ok":
                ctx = by_item[sample.item_id]
                # TODO(w4l3.2) the route stored is the route of the exchange's first user turn; in tools mode that
                #   turn is not the item's prompt.
                an.store(conn, ctx, sample, run.record.run_id, model=arm.model, prompt_version=arm.prompt,
                         route=routed.route_for(run.items[sample.item_id].prompt))
                stored += 1
        results.append(ArmResult(arm, run, path, stored))
    return results


def run_tools(config: Config, arm: Arm, dataset: Dataset, by_item: dict[str, an.Context], provider,
              graders: list[Grader], prices: dict, data_dir: Path) -> Run:
    """A `mode = "tools"` arm as a gigai-core Run: core `run` asks once per item, so the tool loop runs here.

    Same contract as core `run`: the budget is planned on every item's first request before any call and every call
    is reserved; one trace file per run; code graders score each succeeded sample; `CannotGrade` leaves no score."""
    from .tools import TOOLS
    budget = CallBudget(max_usd=config.max_usd_per_arm, prices=prices)
    system = Turn(role="system", content=an.system_prompt(arm.prompt))
    settings = an.call_settings(arm.model)
    budget.plan([ModelRequest(settings=settings, tools=TOOLS,
                              turns=(system, Turn(role="user", content=an.tools_prompt(by_item[item.id]))))
                 for item in dataset.items])
    run_id, created_at = new_id("run"), datetime.now(UTC)
    (data_dir / "traces").mkdir(parents=True, exist_ok=True)
    trace = JsonlTrace(data_dir / "traces" / f"{run_id}.jsonl")
    subject = budgeted(provider, budget)
    samples: list[Sample] = []
    scores: list[ScoreRecord] = []
    try:
        for item in dataset.items:
            sample = an.analyze_with_tools(by_item[item.id], subject, model=arm.model, prompt_version=arm.prompt,
                                           item=item, run_id=run_id, trace=trace)
            samples.append(sample)
            if sample.outcome == "succeeded":
                scores.extend(graded(sample, item, graders))
    finally:
        trace.close()
    calls = [span.call for sample in samples for span in sample.model_spans]
    record = RunRecord(run_id=run_id, dataset=dataset.ref, settings=settings, provider=provider.identity,
                       created_at=created_at, completed_at=datetime.now(UTC), prereg=None, trace_path=trace.path,
                       spent_usd=round(sum(call.cost_usd or 0.0 for call in calls), 6), calls_made=len(calls),
                       repeats=1, tag=f"{config.name}:{arm.name}:{arm.prompt}")
    return Run(record=record, items={item.id: item for item in dataset.items}, samples=tuple(samples),
               scores=tuple(scores))


def graded(sample: Sample, item: DatasetItem, graders: list[Grader]) -> list[ScoreRecord]:
    """Each code grader's score of one sample as core `run` stores it; `CannotGrade` means no score for that grader."""
    found = []
    for grader in graders:
        try:
            score = grader.grade(sample, item.expected)
        except CannotGrade:
            continue
        found.append(ScoreRecord(score_id=new_id("score"), trace_id=sample.trace_id, grader_id=grader.id,
                                 grader_version=grader.version, kind=grader.kind, value=score.value,
                                 explanation=score.explanation, judge_model=None, judge_prompt_sha256=None,
                                 position_swapped=None, judge_span_ids=(), recorded_at=datetime.now(UTC)))
    return found


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
