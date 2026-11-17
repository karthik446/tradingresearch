"""`tr dataset` (TRAINING-SPIKE §7.4): the row filter, the private and public forms, the price check and hydrate.
Invented FAKEA data only: bars made by formula and one headline, served at the HTTP transport; the teacher replies go
through the real OpenRouter adapter replaying the recorded envelope with invented claims. No model call."""

import hashlib
import json
import math
import re
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from gigai_core import Dataset
from gigai_core.dataset import items_sha256
from test_teacher import PRICE, REPLY, TEACHER, replaying

from factories import thesis
from tradingresearch import analyze as an, dataset as ds, journal, news, sessions, split as sp
from tradingresearch.cli import main
from tradingresearch.records import SourceRef

TICKER = "FAKEA"
S1, S2, S3 = date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)  # train/val; S3 is the val session
BAD_REPLY, BAD_THESIS = date(2026, 9, 17), date(2026, 9, 18)
EMBARGOED, CUTOFF = date(2026, 11, 2), date(2026, 11, 16)
REGISTERED = datetime(2026, 9, 1, 12, tzinfo=UTC)
ROUTE = "openrouter:deepinfra/fp8/flex"
EDGAR = SourceRef(source_id="src_ed6a7f00000000a1", kind="edgar_fact",
                  uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json#Revenues/CY2025/"
                      "accn=0000000001-26-000042",
                  retrieved_at=REGISTERED, content_sha256="sha256:" + "e" * 64, feed=None,
                  licence_note="SEC EDGAR, public")
EDGAR_ROW = an.Row(EDGAR.source_id, "revenue_ttm", 1234567890.0, "USD")
ARTICLE = {"id": 9001, "headline": "FakeCo slides to 101.5 after widget recall", "url": "https://example.com/fakea",
           "source": "benzinga", "symbols": [TICKER], "created_at": "2026-09-15T14:30:00Z"}


# ---------- invented market data at the transport ----------

def close_on(symbol: str, day: date) -> float:
    i = day.toordinal()
    return round((100.0 if symbol == TICKER else 400.0) + 8 * math.sin(i / 9) + (i % 40) * 0.07, 2)


def daily(symbol: str, day: date) -> dict:
    i, c = day.toordinal(), close_on(symbol, day)
    o = round(c - 0.4 * math.cos(i), 2)
    stamp = datetime.combine(day, datetime.min.time(), sessions.NY).astimezone(UTC)
    return {"t": stamp.isoformat().replace("+00:00", "Z"), "o": o, "h": round(max(o, c) + 1.13, 2),
            "l": round(min(o, c) - 0.97, 2), "c": c, "v": 1_000_000 + i * 7919 % 300_000, "n": 900, "vw": c}


def minutes(symbol: str, opens: datetime) -> list[dict]:
    base = close_on(symbol, opens.astimezone(sessions.NY).date()) - 1.0
    rows = []
    for k in range(390):
        c = round(base + (k % 60) * 0.03, 2)
        rows.append({"t": (opens + timedelta(minutes=k)).isoformat().replace("+00:00", "Z"), "o": c,
                     "h": round(c + 0.05, 2), "l": round(c - 0.05, 2), "c": c, "v": 1000 + k, "n": 5, "vw": c})
    return rows


def alpaca(request: httpx.Request) -> httpx.Response:
    url = request.url
    if url.path == "/v1beta1/news":
        return httpx.Response(200, json={"news": [ARTICLE], "next_page_token": None})
    assert url.path == "/v2/stocks/bars", url
    p = url.params
    if p["timeframe"] == "1Min":
        opens = datetime.fromisoformat(p["start"])
        return httpx.Response(200, json={"bars": {p["symbols"]: minutes(p["symbols"], opens)},
                                         "next_page_token": None})
    start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
    days = [d for d in sessions.recent(400, end) if d >= start]
    return httpx.Response(200, json={"bars": {s: [daily(s, d) for d in days] for s in p["symbols"].split(",")},
                                     "next_page_token": None})


def source(cache) -> ds.AlpacaSource:
    return ds.AlpacaSource(httpx.Client(transport=httpx.MockTransport(alpaca)), cache)


# ---------- a journal of teacher analyses ----------

def context(src: ds.AlpacaSource, day: date) -> an.Context:
    bars, snapshot = src.snapshot(TICKER, day, "sip")
    s_sources, s_rows = an.snapshot_rows(snapshot)
    return an.Context(TICKER, day, snapshot, [bars, *s_sources, EDGAR], s_rows + [EDGAR_ROW])


def claims(ctx: an.Context, steps: str, headline: str | None = None, digits: bool = False) -> dict:
    """An invented teacher reply citing the context's rows: prices copied as the table shows them."""
    sid, values = {r.name: r.source_id for r in ctx.rows}, ctx.values()
    out = [
        {"id": "c1", "tag": "fact", "text": "The close was {value}.", "value": ds.shown(values[sid["close"]]),
         "unit": "USD", "source_ids": [sid["close"]], "derived_from": [], "steps": None},
        {"id": "c2", "tag": "fact", "text": "The twenty-session mean was {value}.",
         "value": ds.shown(values[sid["sma_20"]]), "unit": "USD", "source_ids": [sid["sma_20"]], "derived_from": [],
         "steps": None},
        {"id": "c3", "tag": "fact", "text": "RSI read {value}.", "value": round(values[sid["rsi_14"]], 2),
         "unit": "index", "source_ids": [sid["rsi_14"]], "derived_from": [], "steps": None},
        {"id": "c4", "tag": "inference", "text": "The close sits on the mean's side of strength.", "value": None,
         "unit": None, "source_ids": [], "derived_from": ["c1", "c2"], "steps": steps},
        {"id": "c5", "tag": "fact", "text": "Trailing revenue was {value}.", "value": 1234567890, "unit": "USD",
         "source_ids": [EDGAR.source_id], "derived_from": [], "steps": None},
    ]
    if headline:
        out.append({"id": "c6", "tag": "opinion", "text": "The recall headline weighs on sentiment.", "value": None,
                    "unit": None, "source_ids": [headline], "derived_from": [], "steps": None})
    if digits:
        out[0]["text"] = "The close was 101 dollars."  # number_in_text: claims_valid fails
    return {"claims": out}


def analyze(conn, data_dir, ctx: an.Context, reply: dict, *, arm="teacher", terms="trainable", version="analyze-1"):
    envelope = {**REPLY, "choices": [{**REPLY["choices"][0],
                                      "message": {**REPLY["choices"][0]["message"], "content": json.dumps(reply)}}]}
    return an.analyze(conn, ctx, replaying(envelope, []), model=TEACHER.model, max_usd=0.10,
                      prices={TEACHER.model: PRICE}, data_dir=data_dir, prompt_version=version, arm=arm,
                      terms_class=terms).analysis


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A data dir with a registered split and one analysis per filter case; returns a builder for variants."""
    monkeypatch.setattr(an, "context_tokens", lambda system, prompt: 1894)

    def build(steps: str = "the close holds above the mean", everything: bool = True) -> dict:
        conn = journal.connect(tmp_path / "journal.db")
        sp.register(conn, CUTOFF, 22, sp.gate_prereg(REGISTERED), REGISTERED)
        src = source(tmp_path / "pub")
        headline = news.normalise(ARTICLE, REGISTERED)
        news.store(tmp_path, TICKER, [headline])
        c1, c2, c3 = (context(src, d) for d in (S1, S2, S3))
        ids = {"S1": analyze(conn, tmp_path, c1, claims(c1, steps)).analysis_id,
               "S2": analyze(conn, tmp_path, c2, claims(c2, steps, news.source_ref(headline).source_id),
                             version="analyze-3").analysis_id,
               "S3": analyze(conn, tmp_path, c3, claims(c3, "steady")).analysis_id}
        if everything:
            ids["rerun"] = analyze(conn, tmp_path, c1, claims(c1, steps)).analysis_id
            ids["main_arm"] = analyze(conn, tmp_path, c1, claims(c1, steps), arm="main").analysis_id
            # a teacher row is trainable by construction (records.Analysis), so non-trainable is a main-arm row
            ids["not_trainable"] = analyze(conn, tmp_path, c1, claims(c1, steps), arm="main", terms=None).analysis_id
            for name, day in (("test_split", CUTOFF), ("embargoed", EMBARGOED)):
                ctx = context(src, day)
                ids[name] = analyze(conn, tmp_path, ctx, claims(ctx, steps)).analysis_id
            ctx = context(src, BAD_REPLY)
            ids["claims_invalid"] = analyze(conn, tmp_path, ctx, claims(ctx, steps, digits=True)).analysis_id
            ctx = context(src, BAD_THESIS)
            ids["checks_failed"] = analyze(conn, tmp_path, ctx, claims(ctx, steps)).analysis_id
            journal.add(conn, thesis(ids["checks_failed"], ticker=TICKER, arm="teacher", terms_class="trainable",
                                     provider_route=ROUTE, evidence=("cl_missing",)))  # P2 fails
        return {"conn": conn, "dir": tmp_path, "ids": ids}

    return build


def lines_sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------- the row filter ----------

@pytest.mark.parametrize("reason", ["rerun", "main_arm", "not_trainable", "test_split", "embargoed", "claims_invalid",
                                    "checks_failed"])
def test_the_row_filter_keeps_out_each_case_and_counts_its_reason(world, reason):
    w = world()
    selection = ds.select_rows(w["conn"], sp.governing(w["conn"]), w["dir"])
    kept = {r.analysis.analysis_id for r in selection.rows}
    assert kept == {w["ids"][k] for k in ("S1", "S2", "S3")}
    assert w["ids"][reason] not in kept and selection.excluded[reason] == 1
    assert sum(selection.excluded.values()) == 7 and selection.read == 10


def test_publish_without_a_registered_split_is_refused(tmp_path):
    conn = journal.connect(tmp_path / "journal.db")
    with pytest.raises(sp.Refused, match="no training split registered yet"):
        ds.publish(conn, tmp_path, tmp_path / "out", "teacher-sft", "private")
    assert not (tmp_path / "out").exists()


# ---------- the two forms ----------

def test_the_private_form_is_verbatim_and_each_file_hashes_to_items_sha256(world):
    w = world(everything=False)
    out = w["dir"] / "private"
    release = ds.publish(w["conn"], w["dir"], out, "teacher-sft", "private")
    assert {f: len(i) for f, i in release.files.items()} == {"teacher-sft.train.jsonl": 2, "teacher-sft.val.jsonl": 1}
    sums = dict(reversed(line.split("  ")) for line in (out / "SHA256SUMS").read_text().splitlines())
    sheet = (out / "DATASHEET.md").read_text()
    for fname in release.files:
        digest = lines_sha(out / fname)
        loaded = Dataset.from_jsonl(out / fname, expect_sha256=digest)  # raises DatasetDigestMismatch otherwise
        assert items_sha256(loaded.items) == digest == sums[fname] and f"sha256 `{digest}`" in sheet
    [val] = Dataset.from_jsonl(out / "teacher-sft.val.jsonl").items
    assert (val.id, val.cluster_id, val.licence) == (f"{TICKER}:{S3}:teacher", S3.isoformat(), ds.LICENCE)
    s2 = next(i for i in Dataset.from_jsonl(out / "teacher-sft.train.jsonl").items if i.cluster_id == S2.isoformat())
    sid = news.source_ref(news.normalise(ARTICLE, REGISTERED)).source_id
    assert ARTICLE["headline"] in s2.prompt  # verbatim
    assert s2.source_ids[f"news:{sid}"] == 9001 and s2.source_ids[f"news_url:{sid}"] == ARTICLE["url"]
    assert s2.source_ids[f"edgar:{EDGAR.source_id}"] == "0000000001-26-000042" and s2.source_ids["feed"] == "sip"
    assert (out / "LICENSE").read_text().startswith("Community Data License Agreement - Permissive - Version 2.0")


def test_the_public_form_holds_no_alpaca_price_and_no_headline_text(world):
    w = world(everything=False)
    out = w["dir"] / "public"
    ds.publish(w["conn"], w["dir"], out, "teacher-sft", "public")
    files = [out / "teacher-sft.train.jsonl", out / "teacher-sft.val.jsonl"]
    assert ARTICLE["headline"] not in "".join(f.read_text() for f in files)
    for f in files:
        for item in Dataset.from_jsonl(f).items:
            snapshot = journal.get(w["conn"], an.Analysis, item.source_ids["analysis_id"]).snapshot
            prices = ds.price_rows(snapshot)
            texts = [item.prompt, item.system or "", json.dumps(item.expected)]
            numbers = {n for t in texts for n in re.findall(r"\d+(?:\.\d+)?", t)}
            assert not numbers & {an.plain(p) for p in prices.values()}, item.id
            assert all(f"{{{{px:{sid}}}}}" in item.prompt for sid in prices)
            assert item.expected["claims"][0]["value"] == f"{{{{px:{item.expected['claims'][0]['source_ids'][0]}}}}}"
            assert "1234567890" in item.prompt  # EDGAR rows ship verbatim
    s2 = next(i for i in Dataset.from_jsonl(files[0]).items if i.cluster_id == S2.isoformat())
    assert "{{news:src_" in s2.prompt


@pytest.mark.parametrize(("text", "hit"), [("12.50", True), ("$1,234.5", True), ("1e3", True), ("$.5", True),
                                          ("5%", False), ("101.37%", True), ("101", True), ("7", False),
                                          ("sma_200", False), ("2026-09-14", False), ("{{px:src_0123456789abcdef}}",
                                                                                     False)])
def test_the_price_check_rejects_price_shaped_numbers_and_keeps_scale_free_ones(text, hit):
    assert bool(ds.free_text_hits(f"it held {text} into the close.", [101.37])) is hit


def test_a_public_publish_with_a_price_left_in_free_text_is_refused_and_writes_nothing(world):
    w = world(steps="the close held 12.50 above the mean", everything=False)
    with pytest.raises(ds.Refused, match=rf"price check failed(.|\n)*{TICKER}:{S1}:teacher: 12.50"):
        ds.publish(w["conn"], w["dir"], w["dir"] / "public", "teacher-sft", "public")
    assert not (w["dir"] / "public").exists()
    ds.publish(w["conn"], w["dir"], w["dir"] / "private", "teacher-sft", "private")  # the private form may hold it


def test_publish_never_writes_into_a_non_empty_directory(world):
    w = world(everything=False)
    (w["dir"] / "out").mkdir()
    (w["dir"] / "out" / "keep.txt").write_text("x")
    with pytest.raises(ds.Refused, match="not empty"):
        ds.publish(w["conn"], w["dir"], w["dir"] / "out", "teacher-sft", "private")


def test_the_cli_publishes_under_the_data_dir_and_prints_the_counts(world, monkeypatch, capsys):
    w = world()
    monkeypatch.setenv("TR_DATA_DIR", str(w["dir"]))
    main(["dataset", "publish", "--form", "public"])
    out = capsys.readouterr().out
    assert f"wrote public release to {w['dir'] / 'release' / 'teacher-sft'}" in out
    assert "teacher-sft.train.jsonl 2, teacher-sft.val.jsonl 1 items" in out and "3 of 10 analyses kept" in out
    assert "checks_failed 1" in out and (w["dir"] / "release" / "teacher-sft" / "DATASHEET.md").exists()


# ---------- hydrate ----------

def test_hydrating_the_public_form_reproduces_the_private_bytes(world):
    w = world(everything=False)
    ds.publish(w["conn"], w["dir"], w["dir"] / "public", "teacher-sft", "public")
    ds.publish(w["conn"], w["dir"], w["dir"] / "private", "teacher-sft", "private")
    written = ds.hydrate(w["dir"] / "public", w["dir"] / "hydrated", source(w["dir"] / "reader"))
    assert written == {"teacher-sft.train.jsonl": 2, "teacher-sft.val.jsonl": 1}
    for fname in written:
        assert (w["dir"] / "hydrated" / fname).read_bytes() == (w["dir"] / "private" / fname).read_bytes()


def test_a_tampered_public_file_fails_hydrate_naming_the_item_and_writes_nothing(world):
    w = world(everything=False)
    pub = w["dir"] / "public"
    ds.publish(w["conn"], w["dir"], pub, "teacher-sft", "public")
    path = pub / "teacher-sft.train.jsonl"
    first, second = path.read_text().splitlines()
    path.write_text(first + "\n" + second.replace("Trailing revenue", "Trailing sales") + "\n")
    with pytest.raises(ds.Refused, match=rf"first differing item: {TICKER}:{S2}:teacher"):
        ds.hydrate(pub, w["dir"] / "hydrated", source(w["dir"] / "reader"))
    assert not (w["dir"] / "hydrated").exists()
