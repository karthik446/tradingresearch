"""The made-up FAKEA analyze-3 context, its one recorded reply, and the $0 ablation the week-5 checks and observe run.

data/ holds copies of tests/fixtures/week5/: fakea.context.json (week 4's rows plus three invented headlines),
analyze3.request.json and analyze3.reply.json (one real exchange: claude-sonnet-5.5, prompt analyze-3, 2026-11-17
UTC, $0.016048) and models.json (the /models price row recorded with it). Of the reply's 11 claims, 7 cite indicator
rows (one fails, `empty_placeholder`), 1 cites a headline, none a level or an EDGAR row.

`replaying` is the real OpenRouter adapter whose httpx transport answers every request with that reply, up to
STOP_AFTER requests; past the cap it answers HTTP 400, so a config that sends more than an ablation should ends
instead of hanging. `ablation` runs a config's arms through it, on the config's tickers, each holding the FAKEA rows
and headlines (the headlines sit in a news store under the given folder, each window day marked fetched).
Set TR_LAB_DATA to read the data from another folder.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock

import httpx
from gigai_core.budget import Price
from gigai_core.sample import Sample

from tradingresearch import analyze as an, masking, news
from tradingresearch.openrouter import API, OpenRouter
from tradingresearch.records import IndicatorSnapshot, SourceRef
from tradingresearch.retry import Policy

DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[1] / "data")
CONFIG = Path("experiments") / "context-ablation.toml"  # relative to the repo root, where `tr lab` runs
T0 = datetime(2026, 11, 17, tzinfo=UTC)
CONTEXT_TOKENS = 1600  # pinned: the student tokenizer downloads from the HF hub
STOP_AFTER = 100  # an ablation of three arms over ten tickers sends 30


def load(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text())


def context() -> an.Context:
    """The FAKEA context, headlines included, that the recorded call was asked about."""
    raw = load("fakea.context")
    return an.Context(raw["ticker"], date.fromisoformat(raw["session"]),
                      IndicatorSnapshot.model_validate_json(json.dumps(raw["snapshot"])),
                      [SourceRef.model_validate_json(json.dumps(s)) for s in raw["sources"]],
                      [an.Row(**r) for r in raw["rows"]],
                      tuple(news.Headline.model_validate_json(json.dumps(h)) for h in raw["headlines"]))


def expected() -> dict:
    """What a grader is handed with each FAKEA sample: {"values": source id -> value, "names": source id -> name}."""
    return an.item_for(context()).expected


def recorded() -> dict:
    """The recorded reply, parsed: {"claims": [...]}."""
    return json.loads(load("analyze3.reply")["choices"][0]["message"]["content"])


def rows(section: str) -> list[an.Row]:
    """The FAKEA table rows masking.section_of puts in `section`, in table order."""
    return [r for r in context().table() if masking.section_of(r.name) == section]


def row(name: str) -> an.Row:
    return next(r for r in context().table() if r.name == name)


def fact(cid: str, *names: str, value: float | None = None, text: str | None = None) -> dict:
    """A fact citing the named FAKEA rows; `value` defaults to the first row's (a valid fact), or pass a wrong one."""
    cited = [row(name) for name in names]
    value = cited[0].value if value is None else value
    text = text or ("The row reads {value}." if value is not None else "A headline says so.")
    return dict(id=cid, tag="fact", text=text, value=value, unit=cited[0].unit,
                source_ids=[r.source_id for r in cited], derived_from=[], steps=None)


def describe(claims) -> str:
    """Each claim as `id: the rows it cites`, for a failure message; a parsed reply's claims list, or the reply."""
    if isinstance(claims, dict) and isinstance(claims.get("claims"), list):
        claims = claims["claims"]
    if not isinstance(claims, list) or not all(isinstance(c, dict) for c in claims):
        return repr(claims)
    names = expected()["names"]
    out = []
    for c in claims:
        sources = c.get("source_ids")
        cited = [names.get(s, s) for s in sources] if isinstance(sources, list) else sources
        out.append(f"{c.get('id')}: {cited}")
    return "; ".join(out)


def sample_of(parsed, parse_status: str = "ok") -> Sample:
    """A succeeded sample holding `parsed` as the reply."""
    return Sample(trace_id="trace_lab", run_id="run_lab", item_id="FAKEA:2026-11-13", item_version="1",
                  cluster_id="FAKEA", repeat_index=0, input=(), output_text=json.dumps(parsed),
                  output_parsed=parsed, parse_status=parse_status, outcome="succeeded", error=None, spans=(),
                  recorded_at=T0)


def prices(models) -> dict[str, Price]:
    """The /models price row recorded with the exchange, for each model named."""
    [row] = load("models")["data"]
    return {model: Price(model=model, prompt_usd_per_token=float(row["pricing"]["prompt"]),
                         completion_usd_per_token=float(row["pricing"]["completion"]), fetched_at=T0,
                         source=f"{API}/models") for model in models}


def replaying(sent: list[dict]) -> OpenRouter:
    """The real adapter; its transport answers each request with the recorded reply, HTTP 400 past STOP_AFTER."""
    reply = load("analyze3.reply")

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        if len(sent) > STOP_AFTER:
            return httpx.Response(400, json={"error": {"message": f"the lab replay stops after {STOP_AFTER} requests"}})
        return httpx.Response(200, json=reply)

    provider = OpenRouter("not-a-real-key", policy=Policy(sleep=lambda s: None))
    provider._http = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return provider


def ablation(config, folder: Path, sent: list[dict]) -> list:
    """Run the config's arms (an experiment.Config) at $0 on its tickers, one session (FAKEA's), with the context size
    pinned; returns run_arms' ArmResults. experiment (and so evals) is imported here, not when this module loads."""
    from tradingresearch import experiment, journal

    ctx = context()
    contexts = [replace(ctx, ticker=t, snapshot=ctx.snapshot.model_copy(update={"ticker": t}), headlines=())
                for t in config.tickers]
    for t in config.tickers:
        news.store(folder, t, list(ctx.headlines))
        for day in news.days_in(*news.window(ctx.session)):
            news.path_for(folder, t, day).touch()
    conn = journal.connect(folder / "journal.db")
    with mock.patch.object(an, "context_tokens", lambda system, prompt: CONTEXT_TOKENS):
        return experiment.run_arms(conn, config, contexts, replaying(sent),
                                   prices({arm.model for arm in config.arms}), folder)


def user_turn(body: dict) -> str:
    return next(m["content"] for m in body["messages"] if m["role"] == "user")
