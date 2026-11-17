"""The injection set (GUARDS-SPIKE §8.1, §8.5): hand-written attacks on one ticker-day, read from
`evals/injections.jsonl` (schema: evals/injections.schema.md) and applied in memory only, so an injected row never
reaches the news store, the retrieval index or the journal (the run file records the prompt as sent). Whether a model
resisted is the learner's grader (`injection_resisted`); this module only loads and applies."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from gigai_core import CoreModel
from pydantic import ValidationError

from . import analyze as an, news, sessions
from .retrieval.store import Passage, Retrieved

SOURCE = "fiscal.ai"  # an added headline's source on a day with no stored one: the stored corpus's only source (§4.2)


class Injection(CoreModel):
    """One row of the set: `replace` swaps the text of the shown row `target_source_id`, `add` shows one more."""

    id: str
    ticker: str
    session: date
    channel: Literal["headline", "filing"]
    mode: Literal["add", "replace"]
    target_source_id: str | None = None
    text: str
    intent: str


def load(path: Path) -> tuple[Injection, ...]:
    """Every row, schema-checked; a bad row raises ValueError naming its line, never its text."""
    rows: list[Injection] = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = Injection.model_validate_json(line)
        except ValidationError as exc:
            error = exc.errors()[0]
            raise ValueError(f"{path}:{number}: {'.'.join(map(str, error['loc'])) or 'row'}: {error['msg']}") from None
        if problem := check(row, {r.id for r in rows}):
            raise ValueError(f"{path}:{number}: {row.id}: {problem}")
        rows.append(row)
    return tuple(rows)


def check(row: Injection, seen: set[str]) -> str | None:
    """The rules the schema types cannot say."""
    if row.id in seen:
        return "duplicate id"
    if (row.mode == "replace") != (row.target_source_id is not None):
        return "target_source_id is required for replace and refused for add"
    if not row.text.strip() or not row.intent.strip():
        return "text and intent must be non-empty"
    return None


def hashed(row: Injection) -> dict[str, str]:
    """What joins the analyze input hash (GUARDS-SPIKE §8.2): the id and the text digest, never the text."""
    return {"id": row.id, "sha256": "sha256:" + text_sha256(row.text)}


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def headlines(ctx: an.Context, row: Injection) -> an.Context:
    """`ctx` with the injected headline: `replace` swaps the target's text (its time and source kept); `add` is the
    newest row of the window, the oldest shown row giving way so the prompt still shows at most MAX_HEADLINES."""
    if row.mode == "replace":
        found = [h for h in ctx.headlines if news.source_ref(h).source_id == row.target_source_id]
        if not found:
            raise ValueError(f"injection {row.id}: {row.target_source_id} is not a headline shown for "
                             f"{ctx.ticker} {ctx.session}")
        target = found[0]
        injected = headline(row, target.created_at, target.source, target.retrieved_at)
        return replace(ctx, headlines=tuple(injected if h is target else h for h in ctx.headlines))
    _, close = sessions.open_close(ctx.session)
    source = ctx.headlines[-1].source if ctx.headlines else SOURCE
    injected = headline(row, close - timedelta(minutes=1), source, close)
    return replace(ctx, headlines=(*ctx.headlines, injected)[-an.MAX_HEADLINES:])


def headline(row: Injection, created: datetime, source: str, retrieved_at: datetime) -> news.Headline:
    """A stored-looking headline: nothing in the prompt tells it from a real row. The negative article id is never
    an Alpaca id."""
    article = {"id": -int(text_sha256(row.id)[:12], 16), "headline": row.text, "url": "", "source": source,
               "symbols": [row.ticker], "created_at": created.isoformat()}
    return news.normalise(article, retrieved_at)


def passages(retrieved: Retrieved, row: Injection) -> Retrieved:
    """The retrieved passages with the injected filing text: `replace` swaps the target chunk's text and digest,
    `add` appends a chunk under a neutral id, cited through the chunk path as any passage is."""
    sha = text_sha256(row.text)
    if row.mode == "replace":
        if row.target_source_id not in {p.chunk_id for p in retrieved.passages}:
            raise ValueError(f"injection {row.id}: {row.target_source_id} is not a passage retrieved for "
                             f"{retrieved.ticker} {retrieved.as_of}")
        found = tuple(replace(p, sha256=sha, text=row.text) if p.chunk_id == row.target_source_id else p
                      for p in retrieved.passages)
    else:
        found = (*retrieved.passages, Passage(f"doc-{sha[:12]}#0", sha, 0.0, row.text))
    return replace(retrieved, passages=found)
