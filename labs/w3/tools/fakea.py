"""The judge on closed FAKEA trades, replayed: what the w3l2-w3l4 checks and `observe.py` run.

The trade is tests/test_week3.py's synthetic FAKEA thesis (`closed()`: filled on 2026-11-17, closed at its target the
next session, graded), the same trade the chapter's acceptance tests judge. The provider is the real OpenRouter
adapter; its HTTP transport answers every request with the one recorded `openai/gpt-6-sol` reply
(labs/w3/data/judge_reply.json, copied from tests/fixtures/week3), or with an edited copy of it (`answer`). The
request that produced the recorded reply is `judge_request.json`. Nothing here opens a network connection.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
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


# The reply variants part B's checks replay. "recorded" is the real reply; the others are edits of it, never sent to a
# model: "no_verdict" keeps its two sentences of reasoning and drops the verdict line, "unknown" and "fail" end with
# the rubric's unknown or fail instead of pass (same usage, so the same cost), "failed" is an HTTP 400 for a rejected
# request and "credits" an HTTP 402 for an account out of credits (no reply either way).
UNKNOWN_LINE = ('{"verdict":"unknown","explanation":"The summary gives two closes after the fill but no level the '
                'reason names fails, so whether the break held cannot be told."}')
FAIL_LINE = '{"verdict":"fail","explanation":"The level the reason names broke the day after the fill."}'


def answer(kind: str = "recorded") -> httpx.Response:
    if kind == "failed":
        return httpx.Response(400, json={"error": {"code": 400, "message": "Provider returned error"}})
    if kind == "credits":
        return httpx.Response(402, json={"error": {"code": 402, "message": "Insufficient credits"}})
    reply = load("judge_reply")
    message = reply["choices"][0]["message"]
    reasoning = message["content"].rstrip().rpartition("\n\n")[0]
    message["content"] = {"recorded": message["content"], "no_verdict": reasoning,
                          "unknown": f"{reasoning}\n\n{UNKNOWN_LINE}", "fail": f"{reasoning}\n\n{FAIL_LINE}"}[kind]
    return httpx.Response(200, json=reply)


def replaying(sent: list[dict], replies: tuple[str, ...] = ("recorded",)):
    """The real adapter. Request i gets `answer(replies[i])` (the last one again once they run out); `sent` keeps the
    bodies."""
    from tradingresearch.openrouter import API, OpenRouter

    def handler(request: httpx.Request) -> httpx.Response:
        kind = replies[min(len(sent), len(replies) - 1)]
        sent.append(json.loads(request.content))
        return answer(kind)

    provider = OpenRouter("not-a-real-key")
    provider._http = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return provider


def offline(monkeypatch, replies: tuple[str, ...] = ("recorded",)) -> list[dict]:
    """test_week3.offline with these replies: every httpx client answers here, Alpaca's daily FAKEA bars, the recorded
    /models row, and chat request i gets `answer(replies[i])` (the last one again once they run out). Anything else is
    an error. Returns the chat request bodies sent."""
    import test_week3 as w

    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url
        if (url.host, url.path) == ("data.alpaca.markets", "/v2/stocks/bars"):
            return httpx.Response(200, json=w.alpaca_daily(url.params))
        if (url.host, url.path) == ("openrouter.ai", "/api/v1/models"):
            return httpx.Response(200, json=load("models"))
        if (url.host, url.path) == ("openrouter.ai", "/api/v1/chat/completions"):
            kind = replies[min(len(sent), len(replies) - 1)]
            sent.append(json.loads(request.content))
            return answer(kind)
        raise AssertionError(f"unexpected request {request.method} {url}")

    transport, client = httpx.MockTransport(handler), httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: client(*a, **(k | {"transport": transport})))
    monkeypatch.setattr(httpx, "get", lambda url, **k: client(transport=transport).get(url, **k))
    return sent


SESSION = "2026-11-19"  # test_grade's D3: the session journal_of grades on, so `tr grade` output does not move by date


def cli(monkeypatch, data_dir: Path, argvs: list[list[str]], replies: tuple[str, ...] = ("recorded",)
        ) -> list[tuple[str, int]]:
    """`tr <argv>` for each argv in turn on data_dir's journal, with fake keys and `offline`: (what it printed, how
    many judge requests it sent). An exception from `tr` propagates."""
    import contextlib
    import io

    from tradingresearch.cli import main

    keys = data_dir / "keys.env"
    keys.write_text("OPENROUTER_API_KEY=not-a-real-key\nAPCA_API_KEY_ID=not-a-real-id\n"
                    "APCA_API_SECRET_KEY=not-a-real-secret\n")
    monkeypatch.setenv("TR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("TR_ENV_FILE", str(keys))
    sent = offline(monkeypatch, replies)
    out = []
    for argv in argvs:
        before, printed = len(sent), io.StringIO()
        with contextlib.redirect_stdout(printed):
            main(argv)
        out.append((printed.getvalue(), len(sent) - before))
    return out


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


def trade(conn: sqlite3.Connection, arm: str = "champion", n: int = 0, *, swing: bool = False):
    """test_week3.written: the PROPOSED FAKEA thesis. For n > 0 its analysis and claim ids end in `_n`, so one journal
    can hold several (claim ids are unique per journal); such a thesis's prompt names its own claim ids, so its
    request is not the recorded one, and the replayed reply answers it all the same. `swing` makes it a swing thesis
    (hold 5 sessions): the journal keeps one live thesis per ticker, horizon and arm. It still closes at its target."""
    import test_week3 as w

    if n == 0:
        return w.written(conn, arm)
    made = {name: getattr(w, name) for name in ("claim", "analysis", "thesis")}
    horizon = {"horizon": "swing", "hold_sessions": 5} if swing else {}
    w.claim = lambda aid, **kw: made["claim"](f"{aid}_{n}", **{**kw, "claim_id": f"{kw['claim_id']}_{n}"})
    w.analysis = lambda **kw: made["analysis"](**{**kw, "analysis_id": f"{kw['analysis_id']}_{n}"})
    w.thesis = lambda aid, **kw: made["thesis"](f"{aid}_{n}", **{**kw, **horizon, "evidence": tuple(
        f"{c}_{n}" for c in kw["evidence"])})
    try:
        return w.written(conn, arm)
    finally:
        for name, fn in made.items():
            setattr(w, name, fn)


def journal_of(data_dir: Path, arms: tuple[str, ...], *, settled: bool = True, graded: bool = True,
               graded_in: tuple[int, ...] | None = None) -> tuple[sqlite3.Connection, list, object]:
    """A fresh journal holding one FAKEA thesis per entry of `arms`, written in that order (an arm's second thesis is
    a swing one), then settled through the fill day and the exit day and graded, as test_week3.closed does for one:
    (conn, theses, bars). A teacher thesis closes but gets no Grade; `graded=False` stops after settling (CLOSED, no
    Grade yet). `graded_in` grades the theses one by one in that order of their indexes (so grade rows land in an
    order other than the one the theses were written in)."""
    import test_week3 as w
    from tradingresearch import journal

    conn = journal.connect(data_dir / "journal.db")
    theses = [trade(conn, arm, n, swing=arm in arms[:n]) for n, arm in enumerate(arms)]
    bars = w.Bars()
    if settled:
        for day in (w.D1, w.D2, w.D3):
            w.settle(conn, bars, day)
    if settled and graded and graded_in is not None:
        states = {t.thesis_id: state for t, state in journal.ungraded_theses(conn)}
        for i in graded_in:
            if theses[i].thesis_id in states:
                w.grade.grade_one(conn, bars, theses[i], states[theses[i].thesis_id], w.D3, w.NOW, False)
    elif settled and graded:
        w.grade.run(conn, bars, w.D3, now=w.NOW)
    return conn, theses, bars


@dataclass
class Judging:
    got: object  # what p1_judge returned, or the exception it raised
    sent: list[dict]  # the request bodies the transport received
    thesis: object
    conn: sqlite3.Connection  # the journal p1_judge wrote through, still open (uncommitted rows show here)
    data_dir: Path
    raised: bool = False  # got was raised, not returned (a returned exception is a value no caller sees as an error)


def judging(data_dir: Path, *, arm: str = "champion", replies: tuple[str, ...] = ("recorded",),
            max_usd: float = MAX_USD, reworded: bool = False, broken: str | None = None) -> Judging:
    """p1_judge on one FAKEA thesis: the closed, graded one (arm "champion", "challenger"), the closed teacher thesis
    (no Grade), or "never_entered" (PROPOSED, never filled). Whatever it returns or raises is kept, so a check can say
    what happened instead of crashing. `broken` names a journal function that raises sqlite3.OperationalError while
    p1_judge runs (after the trade is built, which writes through the journal too)."""
    import test_week3 as w
    from tradingresearch import evals, journal

    if arm == "never_entered":
        conn = journal.connect(data_dir / "journal.db")
        t, bars = w.written(conn), w.Bars()
    else:
        conn, t, bars = closed_trade(data_dir, arm, reworded=reworded)
    sent: list[dict] = []
    kept = getattr(journal, broken) if broken else None

    def fails(*args, **kwargs):
        raise sqlite3.OperationalError(f"disk I/O error (injected into journal.{broken})")

    if broken:
        setattr(journal, broken, fails)
    try:
        got, raised = evals.p1_judge(conn, bars, t.thesis_id, replaying(sent, replies), prices=prices(),
                                     data_dir=data_dir, max_usd=max_usd), False
    except Exception as exc:  # shown as a result
        got, raised = exc, True
    finally:
        if broken:
            setattr(journal, broken, kept)
    return Judging(got, sent, t, conn, data_dir, raised)


def judge(data_dir: Path, *, max_usd: float = MAX_USD, reworded: bool = False) -> tuple[object, list[dict], object]:
    """`judging` on the closed FAKEA thesis with the recorded reply: (what it returned or raised, the bodies, the
    thesis). Part A's p1_judge stops with NotImplementedError after its call; part B's returns a Score."""
    j = judging(data_dir, max_usd=max_usd, reworded=reworded)
    return j.got, j.sent, j.thesis


def judge_prompt_sha256() -> str:
    """The sha256 of the P1 judge's prompt, as gigai-core's llm_judge digests it (its frame and the rubric p1_judge
    builds), so a check can compare what a Score and its ScoreRecord say."""
    from gigai_core import CallSettings
    from gigai_core.graders.judge import llm_judge
    from tradingresearch import evals

    rubric = (evals.RUBRICS / "p1_judge_prompt.txt").read_text().replace(
        "{rubric}", (evals.RUBRICS / "p1_thesis_quality.md").read_text())
    return llm_judge(None, rubric=rubric, settings=CallSettings(model=evals.JUDGE_MODEL)).prompt_sha256


def stored(conn: sqlite3.Connection, thesis_id: str) -> tuple[dict | None, list]:
    """What the judge left in the journal for one thesis: its latest judge_verdict row (or None) and its p1_judge
    ScoreRecords (the outcome grade's own record is left out)."""
    from tradingresearch import journal

    return (journal.judge_verdict(conn, thesis_id),
            [r for r in journal.scores_for(conn, thesis_id) if r.grader_id == "p1_judge"])


def run_files(data_dir: Path) -> list[Path]:
    return sorted((data_dir / "runs").glob("run_*.jsonl"))


def spent(path: Path) -> float:
    """What a run file says its calls cost (its header's spent_usd): what `tr usage` reports."""
    from tradingresearch import trace

    return trace.header(path).spent_usd


def model_spans(data_dir: Path) -> list[tuple[str, str]]:
    """(trace_id, span_id) of every model span the run files under data_dir/runs hold: what a judge ScoreRecord must
    point at."""
    found = []
    for path in run_files(data_dir):
        for line in path.read_text().splitlines():
            sample = json.loads(line).get("sample")
            for span in (sample or {}).get("spans", []):
                if span.get("kind") == "model_call":
                    found.append((sample["trace_id"], span["span_id"]))
    return found


def called(got: object) -> bool:
    """p1_judge got through its call: the NotImplementedError a part A or w3l3.1 stub raises after it, or a Score."""
    from gigai_core.score import Score

    return isinstance(got, (NotImplementedError, Score))


def masked(text: str) -> str:
    """Random ids (run, thesis, score, trace, span) as run_<id>, th_<id>, ...; a run file's temporary path as
    <data_dir>/runs/run_<id>.jsonl. They change every run, and the captured FAIL and PASS texts must not."""
    text = re.sub(r"\b(run|th|sc|trace|span)_[0-9a-f]{16}\b", r"\1_<id>", text)
    return re.sub(r"\S*/runs/run_<id>\.jsonl", "<data_dir>/runs/run_<id>.jsonl", text)


def shown(got: object) -> str:
    """One line for what p1_judge ended with, `masked`, cut to 160 chars."""
    return masked(f"{type(got).__name__}: {got}" if isinstance(got, BaseException) else repr(got))[:160]


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
