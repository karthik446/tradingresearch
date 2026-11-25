"""Experiments as config: the same ticker-days, one run per arm, the registry's graders, a paired comparison.

A config is a TOML file (see experiments/). Every arm asks the same gigai-core Dataset, so `compare` pairs the
answers item by item; an arm differs from the baseline only in what the config names (prompt version, model, an
OpenRouter `provider` routing table such as a teacher's DeepInfra pin, SPIKE §9.4, `mode`: `fixed` context or
`tools`, REPO-PLAN §2.4, and `drop`: SOURCES sections masked out of a fixed arm's prompt, REPO-PLAN §2.5 / masking.py).
`cluster` names the unit the intervals resample: `ticker` (week 1, the default) or `session` (the live stream),
REPO-PLAN D5.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from gigai_core import CallBudget, Dataset, DatasetItem, Run
from gigai_core import compare as core_compare
from gigai_core import run as run_eval
from gigai_core.budget import budgeted
from gigai_core.comparison import Comparison, ComparisonRefused
from gigai_core.graders.builtin import parse_json_text
from gigai_core.graders.protocol import CannotGrade, Grader
from gigai_core.providers import ModelRequest, Turn
from gigai_core.records import RunRecord
from gigai_core.sample import Sample
from gigai_core.score import ScoreRecord
from gigai_core.stats.intervals import MIN_CLUSTERS
from gigai_core.trace import JsonlTrace, TrialSpan

from . import analyze as an, masking, news
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
    drop: tuple[str, ...] = ()  # masking.SECTIONS this arm never sees; empty = the full prompt, the default


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
    arms = tuple(Arm(a["name"], a["prompt"], a.get("model", raw["model"]), routing(path, a), mode(path, a),
                     drop(path, a)) for a in raw["arms"])
    for arm in arms:
        an.system_prompt(arm.prompt)  # fail before any spend if a prompt file is missing
    headlines(path, arms)
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


def drop(path: Path, arm: dict) -> tuple[str, ...]:
    """An arm's `drop` list, refused before any spend: not a list of known, distinct section names, `headlines` on a
    prompt that shows none, every section the prompt shows, or with `mode = "tools"` (no SOURCES table to mask)."""
    value = arm.get("drop", [])
    where = f"{path}: arm {arm.get('name')}: drop"
    shown = masking.sections_shown(arm.get("prompt", ""))
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        raise SystemExit(f"{where} must be a list of section names ({', '.join(masking.SECTIONS)})")
    if unknown := [name for name in value if name not in masking.SECTIONS]:
        raise SystemExit(f"{where}: unknown section(s) {', '.join(unknown)}; sections: {', '.join(masking.SECTIONS)}")
    if "headlines" in value and "headlines" not in shown:
        raise SystemExit(f"{where}: prompt {arm.get('prompt')} renders no headlines; dropping them needs a prompt "
                         f"that shows them ({', '.join(an.HEADLINE_PROMPTS)})")
    if len(set(value)) != len(value):
        raise SystemExit(f"{where} names a section twice: {', '.join(value)}")
    if set(value) == set(shown):
        raise SystemExit(f"{where} names every section, which leaves no SOURCES row to cite")
    if value and arm.get("mode", "fixed") == "tools":
        raise SystemExit(f"{where} masks the fixed prompt's SOURCES table; a tools arm has none")
    return tuple(value)


def headlines(path: Path, arms: tuple[Arm, ...]) -> None:
    """Fixed arms share one dataset, so they all show headlines (analyze-3) or none, and no tool serves headlines, so a
    tools arm never sits next to a headline prompt (it would differ in more than the config names); refused before
    any spend."""
    fixed = {arm.name: an.shows_headlines(arm.prompt) for arm in arms if arm.mode == "fixed"}
    if len(set(fixed.values())) > 1:
        shown = [name for name, shows in fixed.items() if shows]
        raise SystemExit(f"{path}: fixed arms {', '.join(shown)} show headlines and the others do not; they share one "
                         f"dataset, so use one kind of prompt ({', '.join(an.HEADLINE_PROMPTS)} or not)")
    tools = [arm.name for arm in arms if arm.mode == "tools"]
    if tools and any(an.shows_headlines(arm.prompt) for arm in arms):
        raise SystemExit(f"{path}: tools arm {', '.join(tools)} in a config with a headline prompt "
                         f"({', '.join(an.HEADLINE_PROMPTS)}): no tool serves headlines, so it would not see what the "
                         "headline arms see; run the headline arms in a config without tools arms")


def fetched(name: str, contexts: list[an.Context], data_dir: Path) -> None:
    """A headline arm on a news window never fetched would show no headline rows and still count as a headline arm;
    refused before the dataset and any call, naming the `tr news` commands that fetch the missing windows."""
    if missing := [ctx for ctx in contexts if news.missing_days(data_dir, ctx.ticker, ctx.session)]:
        pairs = ", ".join(f"{ctx.ticker} {ctx.session}" for ctx in missing)
        fetch = "; ".join(f"tr news {ctx.ticker} --session {ctx.session}" for ctx in missing)
        raise SystemExit(f"{name}: news not fetched for {pairs}: a headline arm would show no headline rows there. "
                         f"Fetch first: {fetch}")


@dataclass
class ArmResult:
    arm: Arm
    run: Run
    path: Path
    analyses: int


def run_arms(conn, config: Config, contexts: list[an.Context], provider, prices: dict, data_dir: Path
             ) -> list[ArmResult]:
    """One run per arm on one Dataset. Each parsed sample is also stored as an Analysis, so `tr check` reads it."""
    judges = [g.id for g in registry(list(config.graders)) if g.kind != "code"]
    if judges and any(arm.mode == "tools" or arm.drop for arm in config.arms):  # before the first arm: no call made
        raise SystemExit(f"{config.name}: a tools or drop arm grades with code graders only, not {', '.join(judges)}")
    if shown := [arm.prompt for arm in config.arms if arm.mode == "fixed" and an.shows_headlines(arm.prompt)]:
        fetched(config.name, contexts, data_dir)
        contexts = [an.with_headlines(ctx, data_dir, shown[0]) for ctx in contexts]  # read only, before the dataset
    dataset = Dataset.of(config.name, items(config, contexts))
    by_item = {f"{ctx.ticker}:{ctx.session}": ctx for ctx in contexts}
    results = []
    for arm in config.arms:
        graders = registry(list(config.graders), arm.drop)
        routed = provider.routed(arm.provider) if arm.provider else provider
        if arm.drop:
            routed = masking.Masked(routed, arm.drop)
        if arm.mode == "tools":
            run = run_tools(config, arm, dataset, by_item, routed, graders, prices, data_dir)
        elif arm.drop:
            run = run_masked(config, arm, dataset, routed, graders, prices, data_dir)
        else:
            run = run_eval(dataset, routed, graders, settings=an.call_settings(arm.model),
                           budget=CallBudget(max_usd=config.max_usd_per_arm, prices=prices),
                           system=an.system_prompt(arm.prompt), trace_dir=data_dir / "traces",
                           tag=f"{config.name}:{arm.name}:{arm.prompt}")
        path = an.save(run, data_dir)
        stored = 0
        for sample in run.samples:
            if sample.parse_status == "ok":
                ctx = by_item[sample.item_id]
                # the route of the exchange's first user turn: the item's prompt (a drop arm's Masked looks it up by
                # the masked text it sent), or in tools mode the tools prompt
                first_user = an.tools_prompt(ctx) if arm.mode == "tools" else run.items[sample.item_id].prompt
                an.store(conn, ctx, sample, run.record.run_id, model=arm.model, prompt_version=arm.prompt,
                         route=routed.route_for(first_user), drop=arm.drop)
                stored += 1
        results.append(ArmResult(arm, run, path, stored))
    return results


def run_tools(config: Config, arm: Arm, dataset: Dataset, by_item: dict[str, an.Context], provider,
              graders: list[Grader], prices: dict, data_dir: Path) -> Run:
    """A `mode = "tools"` arm as a gigai-core Run: core `run` asks once per item, so the tool loop runs here."""
    from .tools import TOOLS
    budget = CallBudget(max_usd=config.max_usd_per_arm, prices=prices)
    system = Turn(role="system", content=an.system_prompt(arm.prompt))
    budget.plan([ModelRequest(settings=an.call_settings(arm.model), tools=TOOLS,
                              turns=(system, Turn(role="user", content=an.tools_prompt(by_item[item.id]))))
                 for item in dataset.items])

    def ask(item: DatasetItem, subject, run_id: str, trace: JsonlTrace) -> Sample:
        return an.analyze_with_tools(by_item[item.id], subject, model=arm.model, prompt_version=arm.prompt,
                                     item=item, run_id=run_id, trace=trace)
    return run_items(config, arm, dataset, provider, graders, budget, data_dir, ask)


def run_masked(config: Config, arm: Arm, dataset: Dataset, provider: masking.Masked, graders: list[Grader],
               prices: dict, data_dir: Path) -> Run:
    """A fixed arm with `drop` as a gigai-core Run. Core `run` traces the request it built (the full item prompt),
    so the masked request, what the model saw, is built and traced here; the dataset, and its digest, stay full."""
    budget = CallBudget(max_usd=config.max_usd_per_arm, prices=prices)
    system = Turn(role="system", content=an.system_prompt(arm.prompt))
    sent = {item.id: provider.request(ModelRequest(
                settings=an.call_settings(arm.model), turns=(system, Turn(role="user", content=item.prompt)),
                metadata={"item_id": item.id, "repeat_index": 0}))
            for item in dataset.items}
    budget.plan(list(sent.values()))

    def ask(item: DatasetItem, subject, run_id: str, trace: JsonlTrace) -> Sample:
        return asked_once(item, sent[item.id], subject, run_id, trace)
    return run_items(config, arm, dataset, provider, graders, budget, data_dir, ask)


def run_items(config: Config, arm: Arm, dataset: Dataset, provider, graders: list[Grader], budget: CallBudget,
              data_dir: Path, ask) -> Run:
    """Core `run`'s contract for an arm asked here (the budget already planned on every item's first request):
    every call reserved, one trace file per run, code graders score each succeeded sample, `CannotGrade` leaves no
    score."""
    run_id, created_at = new_id("run"), datetime.now(UTC)
    (data_dir / "traces").mkdir(parents=True, exist_ok=True)
    trace = JsonlTrace(data_dir / "traces" / f"{run_id}.jsonl")
    subject = budgeted(provider, budget)
    samples: list[Sample] = []
    scores: list[ScoreRecord] = []
    try:
        for item in dataset.items:
            sample = ask(item, subject, run_id, trace)
            samples.append(sample)
            if sample.outcome == "succeeded":
                scores.extend(graded(sample, item, graders))
    finally:
        trace.close()
    calls = [span.call for sample in samples for span in sample.model_spans]
    record = RunRecord(run_id=run_id, dataset=dataset.ref, settings=an.call_settings(arm.model),
                       provider=provider.identity, created_at=created_at, completed_at=datetime.now(UTC), prereg=None,
                       trace_path=trace.path, spent_usd=round(sum(call.cost_usd or 0.0 for call in calls), 6),
                       calls_made=len(calls), repeats=1, tag=f"{config.name}:{arm.name}:{arm.prompt}")
    return Run(record=record, items={item.id: item for item in dataset.items}, samples=tuple(samples),
               scores=tuple(scores))


def asked_once(item: DatasetItem, request: ModelRequest, subject, run_id: str, trace: JsonlTrace) -> Sample:
    """One fixed-mode call as core `run` records it: the model span, then the trial span, `input` = what was sent."""
    trial_id, started = new_id("span"), datetime.now(UTC)
    span = an._model_span(subject, request, trial_id)
    trace.write(span)
    parsed = parse_json_text(span.text) if span.error is None else None
    outcome = "failed" if span.error is not None else "succeeded"
    completed = datetime.now(UTC)
    trial = TrialSpan(span_id=trial_id, turn=0, started_at=started, completed_at=completed, item_id=item.id,
                      repeat_index=0, outcome=outcome, error=span.error)
    trace.write(trial)
    return Sample(trace_id=new_id("trace"), run_id=run_id, item_id=item.id, item_version=item.version,
                  cluster_id=item.cluster_id, repeat_index=0, input=request.turns, output_text=span.text,
                  output_parsed=parsed.value if parsed else None,
                  parse_status=parsed.status if parsed else "not_parsed", outcome=outcome, error=span.error,
                  spans=(trial, span), recorded_at=completed)


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


@dataclass(frozen=True)
class Compared:
    comparison: Comparison
    skipped: tuple[str, ...]  # "<grader>: <why>", one per grader left out, so no grader drops silently


def compare(a: Run, b: Run, graders: Sequence[str]) -> Compared:
    """Core `compare` on the graders both runs scored on a common item. A drop arm never cites its dropped section, so
    that section's grader has no score in it (core: metric_missing), and two arms can grade one section on disjoint
    items (core: no_paired_items); either refuses the whole comparison, so such a grader is skipped and named with
    its counts. With none left, refused as core refuses."""
    # TODO(w5l3.2) each skipped entry says why and how many items each run scored, `<grader>: <why> (n=A vs B)`;
    #   the refusal names every skipped grader.
    # TODO(w5l3.1) keep the graders both runs scored on at least one common item, in the order asked; skip each other
    #   grader with an entry that starts `<grader>:`; with none kept, refuse `no_shared_metric` as core refuses.
    raise NotImplementedError
