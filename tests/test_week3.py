"""Week 3 acceptance: the real P1 judge, `tr grade --judge`, the trace policy, the SLO review and measured costs.

What you write (REPO-PLAN week 3; ADR-003 picks the judge):
- In `tradingresearch/evals.py`:
  - `p1_verdict(reply) -> (verdict, reason)` reads the judge's reply as the rubric's "Verdict format" says: the
    last JSON object in the reply wins; `pass` and `fail` keep their explanation; a verdict of `unknown` becomes
    `fail` with `unknown: ` put before its explanation; a reply with no verdict raises `CannotGrade`.
  - `p1_judge(conn, bars, thesis_id, provider, *, prices, data_dir, max_usd) -> Score` grades one closed thesis.
    The prompt is `evals/rubrics/p1_judge_prompt.txt` with `evals/rubrics/p1_thesis_quality.md` filled in, the
    thesis's cited claims, grade.py's post-trade summary (`label.summary`) and the thesis text. It makes ONE call
    through `provider`, with gigai-core `llm_judge` and the ADR-003 model `openai/gpt-6-sol`. It stores the
    verdict with `journal.add_judge_verdict(..., score_id=...)` and the matching ScoreRecord (grader `p1_judge`,
    kind `model`, `judge_model` set) in the `score` table. The call goes into a run file under `data_dir/runs`,
    which is what `tr usage` reads. Teacher theses and theses that never entered raise `CannotGrade` before any
    call. `GRADERS["p1_judge"].validated` stays False.
- `tr grade --judge` (commands/grade.py): off by default. With the flag, it judges every graded champion or
  challenger thesis that has no verdict yet and prints the cost in dollars, to 4 or more decimals.
- `docs/adr/ADR-004-trace-policy.md`, `docs/slo-review.md`, `docs/measured-costs.md`. These tests check only their
  structure (headings, key phrases, numbers, the exit code). They never check your prose.

The judge tests run the real OpenRouter adapter. Its HTTP transport answers every request with one recorded
`openai/gpt-6-sol` reply, `fixtures/week3/judge_reply.json`. That reply came from a real call on this file's
synthetic FAKEA trade; `judge_request.json` is the request that produced it. The tests check the request your code
builds and what it stores. They never make a network call. Imports of what you write happen inside each test, so
before you write it, each test fails on its own and the rest of the suite still runs.
"""

import importlib
import json
import re
from datetime import UTC, datetime, time
from pathlib import Path

import httpx
import pytest
from gigai_core.budget import Price
from gigai_core.graders.protocol import CannotGrade
from gigai_core.score import Score

from factories import analysis, claim, event, snapshot, thesis
from test_grade import D0, D1, D2, D3, DAILY, NOW, Bars, ny, settle
from tradingresearch import grade, journal, label, trace
from tradingresearch.analyze import snapshot_rows
from tradingresearch.cli import main
from tradingresearch.openrouter import API, OpenRouter
from tradingresearch.records import RULES_VERSION, Congestion, EntryRule, Thesis
from tradingresearch.sessions import NY

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "week3"
RUBRIC = ROOT / "evals" / "rubrics" / "p1_thesis_quality.md"
PROMPT = ROOT / "evals" / "rubrics" / "p1_judge_prompt.txt"
RUBRIC_SECTIONS = ("Question", "Inputs", "Met", "Not met", "Unknown", "Hindsight", "Verdict format")
MODEL = "openai/gpt-6-sol"  # ADR-003's judge
MAX_TOKENS = 4000  # the bound on the judge's reply; ADR-003 estimates about 500 output tokens per trade
MAX_USD = 0.05
RAW_BAR_VALUES = ("100.2", "101.6", "106.5", "107.5", "107.2")  # opens, highs and a post-exit close of DAILY
RUN_ID = r"\brun_[0-9a-f]{16}\b"


def evals():
    return importlib.import_module("tradingresearch.evals")


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def recorded_verdict() -> tuple[str, str]:
    """The verdict and explanation on the recorded reply's last line, read without the code under test."""
    content = load("judge_reply")["choices"][0]["message"]["content"]
    last = json.loads(content.strip().splitlines()[-1])
    return last["verdict"], last["explanation"]


def prices() -> dict[str, Price]:
    """The judge's price from the recorded /models row."""
    [row] = load("models")["data"]
    return {MODEL: Price(model=MODEL, prompt_usd_per_token=float(row["pricing"]["prompt"]),
                         completion_usd_per_token=float(row["pricing"]["completion"]),
                         fetched_at=datetime.fromisoformat(load("judge_request")["captured_at"]),
                         source=f"{API}/models")}


def written(conn, arm: str = "champion") -> Thesis:
    """A PROPOSED long FAKEA thesis: stop entry 101 on D1, stop 98, target 106; it cites high_20 and the
    congestion top, both 100.5."""
    values = {"close": 100.0, "atr_14": 2.0, "sma_20": 99.0, "high_20": 100.5}
    snap = snapshot(ticker="FAKEA", session=D0, values=values,
                    congestion=Congestion(low=98.5, high=100.5, sessions=7, range_atr=1.0))
    rows = {row.name: row for row in snapshot_rows(snap)[1]}
    aid = f"an_fakea_{arm}"
    high = claim(aid, claim_id="cl_fakea_high", text="The 20-day high was {value} USD.", value=100.5,
                 source_ids=(rows["high_20"].source_id,))
    top = claim(aid, claim_id="cl_fakea_top", text="The 7-session congestion topped at {value} USD.", value=100.5,
                source_ids=(rows["congestion_high"].source_id,))
    a = analysis(analysis_id=aid, ticker="FAKEA", session=D0, snapshot=snap, claims=(high, top),
                 terms_class="trainable" if arm == "teacher" else "restricted")
    journal.add_analysis(conn, a, sources=[])
    t = thesis(aid, ticker="FAKEA", arm=arm, rules_version=RULES_VERSION, setup_type="breakout_20d",
               prediction="Reaches 106 within 2 sessions.",
               reason="The break above the 7-session congestion top and 20-day high at 100.5 holds: every close "
                      "after the fill stays above 100.5.",
               invalidation_text="A close back below 98.", stop=98.0, target=106.0, invalidation_price=98.0,
               hold_sessions=2, evidence=("cl_fakea_high", "cl_fakea_top"), terms_class=a.terms_class,
               entry=EntryRule(kind="stop", price=101.0, window_start=ny(D1, "09:30"), window_end=ny(D1, "16:00")))
    journal.add(conn, t, event(t.thesis_id, "PROPOSED").model_copy(update={"rules_version": RULES_VERSION}))
    return t


def closed(conn, arm: str = "champion") -> tuple[Thesis, Bars]:
    """The FAKEA thesis filled on D1, closed at its target on D2, then graded (no Grade for the teacher arm)."""
    t, bars = written(conn, arm), Bars()
    for day in (D1, D2, D3):
        settle(conn, bars, day)
    grade.run(conn, bars, D3, now=NOW)
    return t, bars


def replaying(sent: list[dict]) -> OpenRouter:
    """The real adapter. Its transport answers every request with the recorded reply; `sent` keeps the bodies."""
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=load("judge_reply"))

    provider = OpenRouter("not-a-real-key")
    provider._http = httpx.Client(base_url=API, transport=httpx.MockTransport(handler))
    return provider


def judge_once(tmp_path: Path) -> tuple:
    """Judge the closed FAKEA thesis once through the recorded transport: (conn, thesis, bars, sent, score)."""
    conn = journal.connect(tmp_path / "journal.db")
    t, bars = closed(conn)
    sent: list[dict] = []
    score = evals().p1_judge(conn, bars, t.thesis_id, replaying(sent), prices=prices(), data_dir=tmp_path,
                             max_usd=MAX_USD)
    return conn, t, bars, sent, score


def prompt_of(body: dict) -> str:
    return "\n".join(m["content"] for m in body["messages"])


def doc(relative: str) -> str:
    path = ROOT / relative
    assert path.is_file(), f"{relative} is missing: it is a week-3 file you write"
    return path.read_text()


# ---------- the verdict parser (hand-built reply strings, not model output) ----------

PARSE_CASES = [
    pytest.param('Short covering is not in the summary.\n{"verdict": "fail", "explanation": "unknown: short covering '
                 'is not measured"}', "fail", "unknown: short covering is not measured", id="fail_unknown_kept"),
    pytest.param('Sector rotation is not measured.\n{"verdict": "unknown", "explanation": "the summary does not '
                 'measure sector rotation"}', "fail", "unknown: the summary does not measure sector rotation",
                 id="unknown_becomes_fail"),
    pytest.param('The format is {"verdict": "pass", "explanation": "one sentence"}.\nCloses fell to 99.\n'
                 '{"verdict": "fail", "explanation": "closes fell back below the level"}', "fail",
                 "closes fell back below the level", id="last_json_wins"),
    pytest.param('Closes held above 100.5 on 2 of 2 sessions.\n{"verdict": "pass", "explanation": "the level held on '
                 'every close"}', "pass", "the level held on every close", id="pass"),
]


@pytest.mark.parametrize(("reply", "verdict", "reason"), PARSE_CASES)
def test_the_verdict_parser(reply, verdict, reason):
    """Rubric "Verdict format": the last JSON object decides; an unknown is `fail` with `unknown:` (ADR-003)."""
    assert evals().p1_verdict(reply) == (verdict, reason)
    assert journal.abstained({"verdict": verdict, "reason": reason}) == reason.startswith("unknown:")


@pytest.mark.parametrize("reply", ["I cannot decide this one.", '{"answer": "pass"}'], ids=["no_json", "no_verdict"])
def test_a_reply_without_a_verdict_cannot_be_graded(reply):
    """No verdict is not an abstain: the reply cannot be graded and nothing is stored."""
    with pytest.raises(CannotGrade):
        evals().p1_verdict(reply)


# ---------- the judge on a closed thesis (the recorded reply) ----------

def test_the_judge_sends_one_request_with_the_adr_003_model_the_rubric_and_the_summary(tmp_path):
    """One call per trade: ADR-003's model, a bounded reply, the rubric, the summary, the claims and the thesis."""
    conn, t, bars, sent, _ = judge_once(tmp_path)
    assert len(sent) == 1
    [body] = sent
    assert body["model"] == MODEL
    assert isinstance(body.get("max_tokens"), int) and 0 < body["max_tokens"] <= MAX_TOKENS
    prompt = prompt_of(body)
    assert PROMPT.read_text().splitlines()[0] in prompt and "{rubric}" not in prompt
    for section in RUBRIC_SECTIONS:
        assert f"## {section}" in prompt
    summary = label.summary(conn, bars, t, label.labelable(conn, t.thesis_id)[1])
    for line in summary.splitlines():
        assert line in prompt
    for text in (t.prediction, t.reason, t.invalidation_text, "cl_fakea_high", "cl_fakea_top"):
        assert text in prompt


def test_the_judge_prompt_holds_no_raw_bar_rows(tmp_path):
    """The judge sees the code-written summary only: no bar columns, no opens or highs, nothing after the exit."""
    _, _, _, sent, _ = judge_once(tmp_path)
    prompt = prompt_of(sent[0])
    assert not [value for value in RAW_BAR_VALUES if value in prompt]
    assert not re.search(r"['\"](o|h|l|vw)['\"]\s*:", prompt)
    assert not re.search(r"\bo\s+h\s+l\s+c\b", prompt)


def test_the_judge_returns_a_score_and_stores_its_verdict_and_score(tmp_path):
    """The recorded verdict becomes a Score, a judge_verdict row and the ScoreRecord that row points at."""
    conn, t, _, _, score = judge_once(tmp_path)
    verdict, explanation = recorded_verdict()
    assert isinstance(score, Score) and score.value == (1.0 if verdict == "pass" else 0.0)
    stored = journal.judge_verdict(conn, t.thesis_id)
    assert stored is not None and (stored["verdict"], stored["reason"]) == (verdict, explanation)
    [record] = [s for s in journal.scores_for(conn, t.thesis_id) if s.grader_id == "p1_judge"]
    assert (record.kind, record.value, record.judge_model) == ("model", score.value, MODEL)
    assert stored["score_id"] == record.score_id
    assert evals().GRADERS["p1_judge"].validated is False  # only an ADR with a measured kappa changes it


def test_the_judge_call_and_its_cost_land_in_a_run_file(tmp_path):
    """Usage is recorded where `tr usage` reads it: one gpt-6-sol call at the provider-reported cost."""
    judge_once(tmp_path)
    calls = [c for _, path in trace.iter_runs(tmp_path) for c in trace.calls(path) if c.model == MODEL]
    assert len(calls) == 1
    assert calls[0].cost_usd == pytest.approx(load("judge_reply")["usage"]["cost"])


@pytest.mark.parametrize("arm", ["teacher", "never_entered"])
def test_teacher_and_never_entered_theses_are_never_judged(arm, tmp_path):
    """No P1 for the teacher arm or for a thesis that never filled: CannotGrade, no request, nothing stored."""
    conn = journal.connect(tmp_path / "journal.db")
    t, bars = closed(conn, arm="teacher") if arm == "teacher" else (written(conn), Bars())
    sent: list[dict] = []
    with pytest.raises(CannotGrade):
        evals().p1_judge(conn, bars, t.thesis_id, replaying(sent), prices=prices(), data_dir=tmp_path,
                         max_usd=MAX_USD)
    assert sent == [] and journal.judge_verdict(conn, t.thesis_id) is None


# ---------- tr grade --judge ----------

def alpaca_daily(params) -> dict:
    """Alpaca's /v2/stocks/bars page of synthetic DAILY bars; a daily bar's `t` is midnight New York in UTC."""
    start, end = (datetime.fromisoformat(params[k]).date() for k in ("start", "end"))
    bars = [{"t": datetime.combine(d, time(0), NY).astimezone(UTC).isoformat().replace("+00:00", "Z"),
             "o": o, "h": h, "l": low, "c": c, "v": 1000, "n": 10, "vw": c}
            for d, (o, h, low, c) in DAILY.items() if start <= d <= end]
    return {"bars": {params["symbols"]: bars}, "next_page_token": None}


def offline(monkeypatch) -> list[dict]:
    """Every httpx client answers from here: Alpaca daily bars, the recorded /models row and the recorded judge
    reply. Anything else is an error. Returns the chat request bodies sent."""
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url
        if (url.host, url.path) == ("data.alpaca.markets", "/v2/stocks/bars"):
            return httpx.Response(200, json=alpaca_daily(url.params))
        if (url.host, url.path) == ("openrouter.ai", "/api/v1/models"):
            return httpx.Response(200, json=load("models"))
        if (url.host, url.path) == ("openrouter.ai", "/api/v1/chat/completions"):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json=load("judge_reply"))
        raise AssertionError(f"unexpected request {request.method} {url}")

    transport, client = httpx.MockTransport(handler), httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: client(*a, **(k | {"transport": transport})))
    monkeypatch.setattr(httpx, "get", lambda url, **k: client(transport=transport).get(url, **k))
    return sent


def test_tr_grade_judge_is_off_by_default_then_judges_once_and_prints_the_cost(tmp_path, monkeypatch, capsys):
    """Plain `tr grade` makes no model call; `--judge` judges the unjudged closed thesis once and prints the cost."""
    keys = tmp_path / "keys.env"
    keys.write_text("OPENROUTER_API_KEY=not-a-real-key\nAPCA_API_KEY_ID=not-a-real-id\n"
                    "APCA_API_SECRET_KEY=not-a-real-secret\n")
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TR_ENV_FILE", str(keys))
    with pytest.raises(SystemExit):
        main(["grade", "--help"])
    assert "--judge" in capsys.readouterr().out, "tr grade has no --judge flag yet"
    conn = journal.connect(tmp_path / "journal.db")
    t, _ = closed(conn)
    conn.close()
    sent = offline(monkeypatch)
    main(["grade"])
    assert sent == []
    capsys.readouterr()
    main(["grade", "--judge"])
    out = capsys.readouterr().out
    assert len(sent) == 1 and sent[0]["model"] == MODEL
    cost = load("judge_reply")["usage"]["cost"]
    assert any(abs(float(amount) - cost) <= 5e-5 for amount in re.findall(r"\$(\d+\.\d+)", out)), out
    conn = journal.connect(tmp_path / "journal.db")
    assert journal.judge_verdict(conn, t.thesis_id)["verdict"] == recorded_verdict()[0]
    conn.close()
    main(["grade", "--judge"])
    assert len(sent) == 1  # already judged: no second call


# ---------- the week-3 documents (structure only) ----------

def test_adr_004_names_what_never_enters_a_trace():
    """ADR-004: keys, account data and fetched content stay out of traces, a redaction rule, the consequences."""
    text = doc("docs/adr/ADR-004-trace-policy.md")
    assert text.startswith("# ADR-004")
    for label_ in ("**Status:**", "**Decision.**", "**Consequences.**"):  # the labels ADR-001..003 use
        assert label_ in text
    lower = text.lower()
    for phrase in ("key", "account", "redact"):
        assert phrase in lower, phrase
    assert re.search(r"git-?ignored|\.?gitignore", lower)


def test_the_slo_review_has_four_slos_and_the_injected_breach():
    """The four SLOs with targets, measured values or `awaiting sessions`, and the pasted breach with exit code 1."""
    text = doc("docs/slo-review.md")
    lower = text.lower()
    for phrase in ("17:30", "missed", "fresh", "--inject-delay-minutes", "target"):
        assert phrase in lower, phrase
    measured = re.search(r"\b(ok|BREACH)\s+(missed|fresh)\b", text)
    awaiting = "awaiting sessions" in lower and re.search(r"\btr slo\b|slo_check", text)
    assert measured or awaiting
    assert re.search(r"\bBREACH\s+finished\b.*\(\+\d+(\.\d+)? min injected\)", text)  # slo_check's breach line
    assert re.search(r"\bslo \d{4}-\d{2}-\d{2}: \d/3 met\b", text)
    assert re.search(r"\b(exit(?: code| status)?|rc)\W{0,3}1\b", lower)


@pytest.mark.parametrize("step", ["analyze", "thesis", "judge", "daily"])
def test_measured_costs_has_a_row_per_step_with_its_run_id(step):
    """A table row per step (analyze, thesis, judge per trade, a full daily) with a dollar cost and its run id."""
    text = doc("docs/measured-costs.md")
    rows = [line for line in text.splitlines() if line.lstrip().startswith("|") and step in line.lower()]
    run_id = r"\b(run|dy)_[0-9a-f]{16}\b" if step == "daily" else RUN_ID
    assert [row for row in rows if re.search(r"\$\d+(\.\d+)?", row) and re.search(run_id, row)], rows
