"""A thesis on an analyze-3 analysis (G12fix, reader m11): the headline rows its claims cite are in the thesis SOURCES
table, rendered as analyze renders them, and a thesis citing a headline fact is checked as usual. $0: the real adapter
answers a recorded reply through an httpx MockTransport."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

import pytest

from test_daily import TEACHER, TEACHER_ANALYSIS, TEACHER_PRICES, TEACHER_THESIS_REPLY, answering
from test_thesis import ALL
from tradingresearch import analyze as an, journal, news, thesis as th
from tradingresearch.records import Claim

RETRIEVED = datetime(2026, 11, 16, 22, 0, tzinfo=UTC)
HEADLINE_CLAIM = "cl_headline000001"


def headline(n: int, text: str) -> news.Headline:
    """An AAPL headline inside the 2026-11-16 window (placeholder text, not a real article)."""
    article = {"id": 2000 + n, "headline": text, "url": "https://x.test", "source": "benzinga", "symbols": ["AAPL"],
               "created_at": f"2026-11-16T{14 + n}:05:00Z"}
    return news.normalise(article, RETRIEVED)


CITED = headline(1, "Placeholder\u200b headline | about a product launch\ufe0f")
UNCITED = headline(2, "Placeholder headline nobody cites")


def analyze3(cited: news.Headline = CITED):
    """The recorded teacher analysis as if analyze-3 had written it, plus one fact about `cited`."""
    fact = Claim(claim_id=HEADLINE_CLAIM, analysis_id=TEACHER_ANALYSIS.analysis_id, tag="fact",
                 text="A headline reports a product launch.", value=None, unit=None,
                 source_ids=(news.source_ref(cited).source_id,), derived_from=(), steps=None)
    return TEACHER_ANALYSIS.model_copy(update={"prompt_version": "analyze-3",
                                               "claims": (*TEACHER_ANALYSIS.claims, fact)})


@pytest.fixture
def conn():
    c = journal.connect(":memory:")
    journal.add_analysis(c, analyze3(), [news.source_ref(CITED), news.source_ref(UNCITED)])
    yield c
    c.close()


def citing_the_headline() -> dict:
    """The recorded DeepSeek thesis reply with its day thesis also citing the headline fact (hand-edited)."""
    body = copy.deepcopy(TEACHER_THESIS_REPLY)
    message = body["choices"][0]["message"]
    content = json.loads(message["content"])
    content["theses"] = [{**t, "evidence": [*t["evidence"], HEADLINE_CLAIM]} for t in content["theses"]]
    message["content"] = json.dumps(content)
    return body


def call(conn, tmp_path, sent: list[dict]) -> th.Result:
    provider = answering(200, citing_the_headline(), sent, TEACHER.routing)
    return th.thesis(conn, analyze3(), provider, asked=ALL, arm="teacher", model=TEACHER.model, max_usd=1.0,
                     prices=TEACHER_PRICES, data_dir=tmp_path, terms=TEACHER.terms_class)


def test_the_thesis_shows_the_cited_headline_row_and_accepts_a_thesis_citing_its_fact(conn, tmp_path):
    news.store(tmp_path, "AAPL", [CITED, UNCITED])
    sent: list[dict] = []
    result = call(conn, tmp_path, sent)
    [request] = sent
    prompt = request["messages"][1]["content"]
    row = an.headline_row(CITED)
    line = f"{row.source_id} | {row.name} | {row.label} | -"
    assert line in prompt.splitlines()
    assert row.label == '"Placeholder headline / about a product launch"'  # analyze's cleaning, not the raw text
    assert news.source_ref(UNCITED).source_id not in prompt  # only the rows a claim cites
    assert prompt.replace(f"\n{line}", "") == th.render(analyze3(), ALL)  # the one row is the only change
    [t] = result.checked.theses
    assert HEADLINE_CLAIM in t.evidence and result.checked.rejected == []


def test_a_cited_headline_missing_from_the_store_is_refused_before_the_call(conn, tmp_path):
    news.store(tmp_path, "AAPL", [UNCITED])
    sent: list[dict] = []
    with pytest.raises(SystemExit, match=f"cites headline\\(s\\) {news.source_ref(CITED).source_id} that are not"):
        call(conn, tmp_path, sent)
    assert sent == []


def test_an_analysis_without_headlines_renders_as_before(conn, tmp_path):
    assert th.cited_headlines(conn, TEACHER_ANALYSIS, tmp_path) == ()
    assert th.item_for(TEACHER_ANALYSIS, ALL, "teacher").prompt == th.render(TEACHER_ANALYSIS, ALL)
