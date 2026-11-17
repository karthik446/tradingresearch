"""News: pagination, the kept fields, an idempotent store, the look-ahead guard and SourceRefs (G1).

The fixtures are two real Alpaca pages (AAPL, 2026-11-10) with headlines, summaries and authors replaced by
placeholders of the same length and urls cut to the host, so no article text is committed.
"""

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from tradingresearch import alpaca, news
from tradingresearch.commands import news as news_cmd
from tradingresearch.records import SourceRef

FIXTURES = Path(__file__).parent / "fixtures" / "news"
PAGES = [json.loads((FIXTURES / f"page{n}.json").read_text()) for n in (1, 2)]
SESSION = date(2026, 11, 10)  # closes 21:00Z
LATER = datetime(2026, 11, 16, tzinfo=UTC)
RETRIEVED = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
AFTER_CLOSE = 119002269  # created 2026-11-10T21:31:17Z


def recorded_http(seen: list[httpx.Request]) -> httpx.Client:
    """Serves the recorded pages: the first without a page_token, the second with page 1's token."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        token = request.url.params.get("page_token")
        return httpx.Response(200, json=PAGES[1] if token == PAGES[0]["next_page_token"] else PAGES[0])
    return httpx.Client(transport=httpx.MockTransport(handler))


def articles() -> list[dict]:
    return PAGES[0]["news"] + PAGES[1]["news"]


def test_news_follows_next_page_token_until_null():
    seen: list[httpx.Request] = []
    with recorded_http(seen) as http:
        got = alpaca.news(http, ["AAPL"], "2026-11-10T00:00:00Z", "2026-11-14T00:00:00Z", limit=3)
    assert [a["id"] for a in got] == [a["id"] for a in articles()]
    assert len(seen) == 2 and seen[1].url.params["page_token"] == PAGES[0]["next_page_token"]
    assert str(seen[0].url).startswith(alpaca.NEWS_URL)
    assert seen[0].url.params["include_content"] == "false" and seen[0].url.params["limit"] == "3"


def test_news_stops_at_the_cap():
    seen: list[httpx.Request] = []
    with recorded_http(seen) as http:
        got = alpaca.news(http, ["AAPL"], "2026-11-10T00:00:00Z", "2026-11-14T00:00:00Z", limit=3, max_articles=3)
    assert len(got) == 3 and len(seen) == 1


def test_normalise_keeps_the_listed_fields_in_utc():
    raw = PAGES[1]["news"][1]
    row = news.normalise(raw, RETRIEVED)
    assert row.article_id == AFTER_CLOSE and row.created_at == datetime(2026, 11, 10, 21, 31, 17, tzinfo=UTC)
    assert (row.headline, row.url, row.source, row.symbols) == (raw["headline"], raw["url"], "fiscal.ai", ("AAPL",))
    assert row.content_sha256.startswith("sha256:")
    assert news.normalise(raw, LATER).content_sha256 == row.content_sha256  # retrieval time is not content


def test_the_store_is_idempotent_and_split_by_new_york_day(tmp_path):
    rows = [news.normalise(a, RETRIEVED) for a in articles()]
    assert news.store(tmp_path, "AAPL", rows) == 6
    assert news.store(tmp_path, "AAPL", rows) == 0
    files = sorted(p.name for p in (tmp_path / "news" / "AAPL").iterdir())
    assert files == ["2026-11-09.jsonl", "2026-11-10.jsonl"]  # 01:01Z on the 10th is the 9th in New York
    assert len(news.load(news.path_for(tmp_path, "AAPL", SESSION))) == 5


def test_no_summary_or_body_text_is_stored(tmp_path):
    news.store(tmp_path, "AAPL", [news.normalise(a, RETRIEVED) for a in articles()])
    text = "".join(p.read_text() for p in (tmp_path / "news" / "AAPL").iterdir())
    assert "placeholder summary" not in text
    assert all(set(json.loads(line)) == set(news.Headline.model_fields) for line in text.splitlines())


def test_headlines_after_the_close_are_never_returned(tmp_path):
    news.store(tmp_path, "AAPL", [news.normalise(a, RETRIEVED) for a in articles()])
    rows = news.headlines_for(tmp_path, "AAPL", SESSION, now=LATER)
    assert [r.article_id for r in rows] == [118120577, 118217756, 118243856, 118734073]
    assert AFTER_CLOSE not in {r.article_id for r in rows}
    assert all(r.created_at <= datetime(2026, 11, 10, 21, 0, tzinfo=UTC) for r in rows)
    midday = news.headlines_for(tmp_path, "AAPL", SESSION, now=datetime(2026, 11, 10, 15, 0, tzinfo=UTC))
    assert [r.article_id for r in midday] == [118120577, 118217756, 118243856]


def test_source_ref_is_a_valid_news_source():
    row = news.normalise(PAGES[0]["news"][0], RETRIEVED)
    ref = news.source_ref(row)
    assert (ref.kind, ref.feed, ref.uri, ref.content_sha256) == ("news", None, row.url, row.content_sha256)
    assert ref.source_id == "src_" + row.content_sha256.removeprefix("sha256:")[:16]
    assert SourceRef.model_validate_json(ref.model_dump_json()) == ref


def test_a_day_counts_as_fetched_only_as_far_as_the_fetch_reached(tmp_path):
    midday = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
    assert news.missing_days(tmp_path, "AAPL", SESSION, now=LATER) == [date(2026, 11, 9), SESSION]
    with recorded_http([]) as http:
        news.fetch(http, tmp_path, "AAPL", date(2026, 11, 9), SESSION, now=midday)
        assert news.missing_days(tmp_path, "AAPL", SESSION, now=midday) == []
        assert news.missing_days(tmp_path, "AAPL", SESSION, now=LATER) == [SESSION]  # fetched only until 15:00Z
        assert news.fetch(http, tmp_path, "AAPL", SESSION, SESSION, now=LATER) == 0  # same recorded articles
    assert news.missing_days(tmp_path, "AAPL", SESSION, now=LATER) == []


def test_tr_news_prints_the_untrusted_banner_and_rows(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(news_cmd, "alpaca_client", lambda cfg: recorded_http([]))
    args = argparse.Namespace(ticker="AAPL", session="2026-11-10", days=1)
    news_cmd.cmd_news(args, argparse.Namespace(data_dir=tmp_path))
    out = capsys.readouterr().out.splitlines()
    assert "UNTRUSTED INPUT" in out[0] and out[1] == "time | source | headline | url"
    assert out[2] == "2026-11-10 01:01Z | fiscal.ai | " + PAGES[0]["news"][0]["headline"] + " | https://www.tradingview.com/"
    assert len(out) == 6
