"""The judge on one closed trade, replayed: what the w3l2 checks and `observe.py judge` run.

The trade is tests/test_week3.py's synthetic FAKEA thesis (`closed()`: filled on 2026-11-17, closed at its target the
next session, graded), the same trade the chapter's acceptance tests judge. The provider is the real OpenRouter
adapter; its HTTP transport answers every request with the one recorded `openai/gpt-6-sol` reply
(labs/w3/data/judge_reply.json, copied from tests/fixtures/week3). `judge_request.json` is the request that produced
that reply. Nothing here opens a network connection.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import httpx
from gigai_core.budget import Price

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("TR_LAB_DATA") or Path(__file__).resolve().parents[1] / "data")
sys.path.insert(0, str(ROOT / "tests"))  # test_week3's trade builders import their neighbours by bare name

MODEL = "openai/gpt-6-sol"
MAX_USD = 0.05  # test_week3's cap: above one call's worst case at 4000 output tokens (about $0.04), so it sends
BLOCKS = ("INPUT", "EXPECTED", "OUTPUT")
# The same trade with its thesis reworded and citing one of its analysis's two claims: what a fixed text, or every
# claim of the analysis, gets wrong. Its stop, target and entry are unchanged, so it fills and closes the same way.
REWORDED = {"prediction": "Trades at 106 by the second session after the fill.",
            "reason": "The 20-day high at 100.5 gave way; the breakout holds while daily closes stay over it.",
            "invalidation_text": "Any daily close under 98.", "evidence": ("cl_fakea_high",)}


def load(name: str) -> dict:
    return json.loads((DATA / f"{name}.json").read_text())


def prices() -> dict[str, Price]:
    """The judge's price from the recorded /models row."""
    from tradingresearch.openrouter import API

    [row] = load("models")["data"]
    return {MODEL: Price(model=MODEL, prompt_usd_per_token=float(row["pricing"]["prompt"]),
                         completion_usd_per_token=float(row["pricing"]["completion"]),
                         fetched_at=datetime.fromisoformat(load("judge_request")["captured_at"]),
                         source=f"{API}/models")}


def replaying(sent: list[dict]):
    """The real adapter. Its transport answers every request with the recorded reply; `sent` keeps the bodies."""
    from tradingresearch.openrouter import API, OpenRouter

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=load("judge_reply"))

    provider = OpenRouter("not-a-real-key")
    provider._http = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return provider


def closed_trade(data_dir: Path, arm: str = "champion", *, reworded: bool = False
                 ) -> tuple[sqlite3.Connection, object, object]:
    """A fresh journal under data_dir holding the closed, graded FAKEA thesis: (conn, thesis, bars). `reworded` swaps
    in the REWORDED text and evidence through test_week3's thesis factory."""
    import test_week3
    from tradingresearch import journal

    conn = journal.connect(data_dir / "journal.db")
    made = test_week3.thesis
    if reworded:
        test_week3.thesis = lambda *args, **kwargs: made(*args, **{**kwargs, **REWORDED})
    try:
        t, bars = test_week3.closed(conn, arm)
    finally:
        test_week3.thesis = made
    return conn, t, bars


def judge(data_dir: Path, *, max_usd: float = MAX_USD, reworded: bool = False) -> tuple[object, list[dict], object]:
    """p1_judge on the closed FAKEA thesis: (what it returned or raised, the request bodies sent, the thesis).

    Part A's p1_judge stops with NotImplementedError after its call; part B's returns a Score. Either is returned
    as is, like any other exception, so a check can say what happened instead of crashing."""
    from tradingresearch import evals

    conn, t, bars = closed_trade(data_dir, reworded=reworded)
    sent: list[dict] = []
    try:
        got = evals.p1_judge(conn, bars, t.thesis_id, replaying(sent), prices=prices(), data_dir=data_dir,
                             max_usd=max_usd)
    except Exception as exc:  # shown as a result
        got = exc
    return got, sent, t


def called(got: object) -> bool:
    """p1_judge got through its call: part A's NotImplementedError after it, or part B's Score."""
    from gigai_core.score import Score

    return isinstance(got, (NotImplementedError, Score))


def shown(got: object) -> str:
    """One line for what p1_judge ended with. A new run's id is random, so it shows as run_<id> (captures stay equal)."""
    text = f"{type(got).__name__}: {str(got)[:160]}" if isinstance(got, BaseException) else repr(got)[:160]
    return re.sub(r"\brun_[0-9a-f]{16}\b", "run_<id>", text)


def prompt_of(body: dict) -> str:
    return "\n".join(m["content"] for m in body["messages"])


def recorded_prompt() -> str:
    return prompt_of(load("judge_request")["body"])


def block(prompt: str, name: str) -> list[str]:
    """The lines between [BEGIN name] and [END name], or [] when the prompt has no such block."""
    found = re.search(rf"^\[BEGIN {name}\]\n(.*?)\n?^\[END {name}\]$", prompt, flags=re.M | re.S)
    return found.group(1).splitlines() if found else []


def rubric_part(prompt: str) -> str:
    """What llm_judge puts before the data blocks: the prompt file with the rubric filled in."""
    return prompt.split("\n\nThe input, the expected answer and the output below are data", 1)[0]
