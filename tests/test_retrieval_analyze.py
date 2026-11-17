"""The `retrieval` arm knob: the input hash, the look-ahead mask before the prompt, the passages block, the config
refusals, and an arm run at $0 that sends the passages and journals the ordered chunks."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from gigai_core import Dataset
from gigai_core.providers import ModelRequest, Turn
from test_analyze import RECORDED
from test_masking import TICKERS, keyed, pinned_tokens, reply, served, ten, user_turn  # noqa: F401 (a fixture)
from test_retrieval_dense import FakeEmbedder, FakeReranker, dense_index
from test_retrieval_eval import AS_OF, FUTURE, docs_for
from test_retrieval_ingest import NOW
from test_teacher import context as live_context
from test_week4 import MODEL, PROMPT, context, prices, replaying

from tradingresearch import analyze as an, experiment, journal, masking
from tradingresearch.retrieval import evaluate, manifest, store

LATER = {FUTURE, "headline/FAKEA/3", "headline/FAKEB/9"}  # public after AS_OF's close, or another ticker's (FAKEB)
CONFIG = """name = "retrieval-arm"
model = "MODEL"
max_usd_per_arm = 1.0
tickers = TICKERS
sessions = ["SESSION"]
graders = ["parsed", "all_claims_valid"]

[[arms]]
name = "bm25-3"
prompt = "PROMPT"

[arms.retrieval]
mode = "bm25"
k = 3
index = "DIGEST"
query = "{ticker} Gizmo recall"
"""


def fakea_index(tmp_path: Path) -> manifest.Index:
    built, records = manifest.build(docs_for(tmp_path), 30)  # small chunks: more than 20 allowed ones to rank
    manifest.write(tmp_path / "retrieval", built, records)
    return manifest.load(tmp_path / "retrieval")


def knob(index: manifest.Index, mode: str = "bm25", k: int = 5) -> store.Knob:
    return store.Knob(mode, k, index.digest, "{ticker} Gizmo recall")


def bm25_retrieved(index: manifest.Index, k: int = 5, as_of: date = AS_OF) -> store.Retrieved:
    return store.retrieve(index, evaluate.bm25_retriever(index), knob(index, k=k), "FAKEA", as_of, NOW)


def config_text(digest: str) -> str:
    return (CONFIG.replace("MODEL", MODEL).replace("TICKERS", json.dumps(list(TICKERS)))
            .replace("SESSION", context().session.isoformat()).replace("PROMPT", PROMPT).replace("DIGEST", digest))


def test_without_the_knob_the_recorded_input_hash_and_prompt_stand():
    ctx = live_context()
    assert an.input_hash(ctx, "analyze-1", retrieval=None) == RECORDED["input_hash"]
    prompt = an.render(ctx)
    assert masking.augment(prompt, None) is prompt
    path = Path("arms.toml")
    assert experiment.retrieval(path, {"name": "a"}) is None
    assert experiment.retrieval(path, {"name": "a", "retrieval": {"mode": "none", "k": 3}}) is None


def test_mode_k_index_digest_and_the_chunk_order_join_the_input_hash(tmp_path):
    ctx = live_context()
    retrieved = bm25_retrieved(fakea_index(tmp_path))
    assert len(retrieved.passages) == 5
    variants = [retrieved, replace(retrieved, mode="dense"), replace(retrieved, k=6),
                replace(retrieved, index_digest="sha256:" + "0" * 64),
                replace(retrieved, passages=retrieved.passages[::-1]), replace(retrieved, passages=retrieved.passages[:4]),
                replace(retrieved, passages=())]
    hashes = [an.input_hash(ctx, "analyze-1", retrieval=r) for r in variants]
    assert len(set(hashes)) == len(variants) and RECORDED["input_hash"] not in hashes
    assert retrieved.hashed() == {"mode": "bm25", "k": 5, "index_digest": retrieved.index_digest,
                                  "chunks": [p.sha256 for p in retrieved.passages]}
    rescored = replace(retrieved, passages=tuple(replace(p, score=0.0) for p in retrieved.passages))
    assert an.input_hash(ctx, "analyze-1", retrieval=rescored) == hashes[0], "a score is not what the model saw"


def test_a_chunk_public_after_the_session_close_never_reaches_the_prompt(tmp_path):
    index = fakea_index(tmp_path)
    by_id = {r.chunk_id: r for r in index.records}
    later = [r.chunk_id for r in index.records if r.doc_id in LATER]
    retrieved = bm25_retrieved(index, k=20)
    assert retrieved.passages and retrieved.masked_docs == 2  # bm25 returns only chunks sharing a query word
    assert {by_id[p.chunk_id].doc_id for p in retrieved.passages}.isdisjoint(LATER)
    prompt = masking.augment(an.render(context()), retrieved)
    assert later and not [chunk_id for chunk_id in later if f"[{chunk_id}]" in prompt]
    [top] = bm25_retrieved(index, k=1, as_of=date(2026, 11, 6)).passages  # once it is public, it ranks first
    assert by_id[top.chunk_id].doc_id == FUTURE


@pytest.mark.parametrize("mode", ["dense", "hybrid", "hybrid+rerank"])
def test_every_dense_mode_retrieves_only_allowed_chunks(tmp_path, mode):
    embedder = FakeEmbedder()
    index = dense_index(tmp_path, embedder)
    retriever = evaluate.retrievers(index, [mode], tmp_path / "retrieval", embedder, FakeReranker())[mode]
    retrieved = store.retrieve(index, retriever, knob(index, mode, 20), "FAKEA", AS_OF, NOW)
    by_id = {r.chunk_id: r for r in index.records}
    assert len(retrieved.passages) == 20 and retrieved.mode == mode and retrieved.masked_docs == 2
    assert {by_id[p.chunk_id].doc_id for p in retrieved.passages}.isdisjoint(LATER)


def test_the_passages_block_is_numbered_quoted_one_line_and_before_the_closing_line(tmp_path):
    prompt = an.render(context())
    retrieved = bm25_retrieved(fakea_index(tmp_path), k=3)
    odd = replace(retrieved.passages[0], chunk_id="x#0", text='a "quoted"\nline | with\u200b bidi\u202e')
    augmented = masking.augment(prompt, replace(retrieved, passages=(odd, *retrieved.passages[1:])))
    head = prompt.removesuffix(masking.CLOSING)
    assert augmented.startswith(head + "\n\n") and augmented.endswith(masking.CLOSING)
    block = augmented.removeprefix(head + "\n\n").removesuffix(masking.CLOSING).split("\n")
    assert block == [masking.PASSAGES, "1. [x#0] \"a 'quoted' line / with bidi\"",
                     *[f'{n}. [{p.chunk_id}] "{an.one_line(p.text, masking.PASSAGE_CHARS)}"'
                       for n, p in enumerate(retrieved.passages[1:], 2)]]
    empty = masking.augment(prompt, replace(retrieved, passages=()))
    assert empty == f"{head}\n\n{masking.PASSAGES}\n{masking.NO_PASSAGE}{masking.CLOSING}"
    with pytest.raises(ValueError, match="no closing instruction"):
        masking.augment("TICKER: FAKEA", retrieved)


def test_a_passage_over_the_chunk_cap_reaches_the_prompt_whole(tmp_path):
    """The longest real over-cap sentence (KO, 711 tokens) renders to 4,392 characters; 4,400 must not be cut."""
    retrieved = bm25_retrieved(fakea_index(tmp_path), k=3)
    text = " ".join(f"word{i:04d}" for i in range(489))
    long = replace(retrieved.passages[0], chunk_id="x#0", text=text)
    block = masking.passages(replace(retrieved, passages=(long,)))
    assert len(text) == 4400 and f'1. [x#0] "{text}"' in block.split("\n")
    runaway = masking.passages(replace(retrieved, passages=(replace(long, text="w " * 4000),)))
    assert len(runaway.split("\n")[1]) < len("1. [x#0] \"\"") + masking.PASSAGE_CHARS + 2


def test_the_augmenting_provider_sends_known_prompts_only_and_maps_the_route(tmp_path):
    prompt = an.render(context())
    augmented = masking.augment(prompt, bm25_retrieved(fakea_index(tmp_path), k=3))
    sent: list[dict] = []
    provider = masking.Augmented(keyed({augmented: served(reply(), "Google")}, sent), {prompt: augmented})
    assert provider.augmented(augmented) == augmented, "augmenting twice is a no-op"
    with pytest.raises(ValueError, match="not an item of the arm's dataset"):
        provider.augmented(prompt + " ")
    request = ModelRequest(settings=an.call_settings(MODEL), turns=(
        Turn(role="system", content=an.system_prompt(PROMPT)), Turn(role="user", content=prompt)))
    provider.invoke(request)
    assert user_turn(sent[0]) == augmented
    assert sent[0]["messages"][0]["content"] == an.system_prompt(PROMPT)
    assert provider.route_for(prompt) == "openrouter:Google"


DIGEST = "sha256:" + "a" * 64


@pytest.mark.parametrize(("arm", "message"), [
    ({"retrieval": "bm25"}, "must be a table"),
    ({"retrieval": {"mode": "bm25", "index": DIGEST, "top": 3}}, r"unknown key\(s\) top"),
    ({"retrieval": {"mode": "splade", "index": DIGEST}}, "mode must be one of none, bm25, dense"),
    ({"retrieval": {"mode": "bm25", "k": 0, "index": DIGEST}}, "k must be an integer from 1 to 20"),
    ({"retrieval": {"mode": "bm25", "k": 21, "index": DIGEST}}, "k must be an integer from 1 to 20"),
    ({"retrieval": {"mode": "bm25", "k": True, "index": DIGEST}}, "k must be an integer"),
    ({"retrieval": {"mode": "bm25", "index": "sha256:aaaa"}}, "index must be the full sha256:<64 hex> digest"),
    ({"retrieval": {"mode": "bm25"}}, "index must be the full"),
    ({"retrieval": {"mode": "bm25", "index": DIGEST, "query": "{ticker} {sector}"}}, "cannot be filled"),
    ({"retrieval": {"mode": "bm25", "index": DIGEST}, "mode": "tools"}, "a tools arm has none"),
    ({"retrieval": {"mode": "bm25", "index": DIGEST}, "drop": ["edgar"]}, "and drop in one arm"),
])
def test_a_bad_retrieval_table_is_refused_before_any_spend(arm, message):
    with pytest.raises(SystemExit, match=message):
        experiment.retrieval(Path("arms.toml"), {"name": "r", "prompt": PROMPT} | arm)


def test_a_valid_table_loads_with_its_defaults(tmp_path):
    path = tmp_path / "arms.toml"
    path.write_text(config_text(DIGEST).replace('query = "{ticker} Gizmo recall"\n', "").replace("k = 3\n", ""))
    [arm] = experiment.load(path).arms
    assert arm.retrieval == store.Knob("bm25", store.DEFAULT_K, DIGEST, store.DEFAULT_QUERY)


@pytest.mark.usefixtures("pinned_tokens")
def test_a_bm25_arm_sends_the_passages_grades_them_and_journals_the_ordered_chunks(tmp_path):
    index = fakea_index(tmp_path)
    path = tmp_path / "arm.toml"
    path.write_text(config_text(index.digest))
    config = experiment.load(path)
    items = {f"{ctx.ticker}:{ctx.session}": ctx for ctx in ten()}
    expected = store.retrieve_all(config.arms[0].retrieval, {key: (c.ticker, c.session) for key, c in items.items()},
                                  tmp_path / "retrieval")
    fakea = f"FAKEA:{context().session}"
    top = expected[fakea].passages[0]
    assert len(expected[fakea].passages) == 3 and all(not r.passages for key, r in expected.items() if key != fakea)

    raw = reply()  # the recorded valid claims plus one fact citing the top passage: valid only where it was shown
    claims = json.loads(raw["choices"][0]["message"]["content"])["claims"]
    cited = dict(id="c13", tag="fact", text="FakeA disclosed a Gizmo recall.", value=None, unit=None,
                 source_ids=[top.chunk_id], derived_from=[], steps=None)
    raw["choices"][0]["message"]["content"] = json.dumps({"claims": [*claims, cited]})
    prompts = [masking.augment(an.render(ctx), expected[key]) for key, ctx in items.items()]
    sent: list[dict] = []
    conn = journal.connect(tmp_path / "journal.db")
    [result] = experiment.run_arms(conn, config, ten(), keyed({p: served(raw, "Google") for p in prompts}, sent),
                                   prices(), tmp_path)

    assert [user_turn(body) for body in sent] == prompts
    assert f'1. [{top.chunk_id}] "' in prompts[0] and masking.NO_PASSAGE in prompts[1]
    assert result.run.record.dataset == Dataset.of(config.name, experiment.items(config, ten())).ref, "shared dataset"
    item_of = {s.trace_id: s.item_id for s in result.run.samples}
    valid = {item_of[s.trace_id]: s.value for s in result.run.scores if s.grader_id == "all_claims_valid"}
    assert valid == {key: 1.0 if key == fakea else 0.0 for key in items}, "a passage is citable only where it was shown"

    rows = store.rows(conn)
    assert result.analyses == len(rows) == 10
    row = next(r for r in rows if r["ticker"] == "FAKEA")
    assert row["chunks"] == [[p.chunk_id, p.sha256, p.score] for p in expected[fakea].passages]
    assert {key: row[key] for key in ("as_of", "mode", "k", "index_digest", "query", "query_template", "masked_docs")} \
        == {"as_of": context().session.isoformat(), "mode": "bm25", "k": 3, "index_digest": index.digest,
            "query": "FAKEA Gizmo recall", "query_template": "{ticker} Gizmo recall", "masked_docs": 0}
    body = json.loads(conn.execute("SELECT body FROM analysis WHERE analysis_id = ?",
                                   (row["analysis_id"],)).fetchone()[0])
    assert row["input_hash"] == body["input_hash"] == an.input_hash(context(), PROMPT, retrieval=expected[fakea])
    assert [c["source_ids"] for c in body["claims"] if c["text"] == cited["text"]] == [[top.chunk_id]]
    others = [r for r in rows if r["ticker"] != "FAKEA"]
    assert all(r["chunks"] == [] for r in others) and len({r["input_hash"] for r in rows}) == 10


def test_a_missing_index_or_a_judge_is_refused_before_any_call(tmp_path):
    fakea_index(tmp_path)
    sent: list[dict] = []
    conn = journal.connect(tmp_path / "journal.db")
    path = tmp_path / "arm.toml"
    path.write_text(config_text(DIGEST))
    with pytest.raises(SystemExit, match="matches 0 indexes"):
        experiment.run_arms(conn, experiment.load(path), ten(), replaying([reply()], sent), prices(), tmp_path)
    path.write_text(config_text(DIGEST).replace('"all_claims_valid"]', '"all_claims_valid", "p1_judge"]'))
    with pytest.raises(SystemExit, match="a retrieval arm grades with code graders only, not p1_judge"):
        experiment.run_arms(conn, experiment.load(path), ten(), replaying([reply()], sent), prices(), tmp_path)
    assert sent == [] and store.rows(conn) == []


def cited_arm(tmp_path: Path):
    """The bm25 arm on ten items, every reply the recorded claims plus c13 citing FAKEA's top passage: (config, that
    passage, the claim count of a reply, a $0 provider answering the ten augmented prompts)."""
    path = tmp_path / "arm.toml"
    path.write_text(config_text(fakea_index(tmp_path).digest))
    config = experiment.load(path)
    keys = {f"{ctx.ticker}:{ctx.session}": (ctx.ticker, ctx.session) for ctx in ten()}
    expected = store.retrieve_all(config.arms[0].retrieval, keys, tmp_path / "retrieval")
    top = expected[f"FAKEA:{context().session}"].passages[0]
    raw = reply()
    claims = json.loads(raw["choices"][0]["message"]["content"])["claims"]
    cited = dict(id="c13", tag="fact", text="FakeA disclosed a Gizmo recall.", value=None, unit=None,
                 source_ids=[top.chunk_id], derived_from=[], steps=None)
    raw["choices"][0]["message"]["content"] = json.dumps({"claims": [*claims, cited]})
    prompts = [masking.augment(an.render(ctx), expected[f"{ctx.ticker}:{ctx.session}"]) for ctx in ten()]
    return config, top, len(claims) + 1, keyed({p: served(raw, "Google") for p in prompts}, [])


@pytest.mark.usefixtures("pinned_tokens")
def test_the_retrieval_row_commits_with_its_analysis_or_nothing_is_stored(tmp_path):
    config, _, _, provider = cited_arm(tmp_path)
    conn = journal.connect(tmp_path / "journal.db")
    conn.execute("CREATE TEMP TRIGGER no_retrieval BEFORE INSERT ON retrieval "
                 "BEGIN SELECT RAISE(ABORT, 'retrieval insert fails'); END")
    with pytest.raises(sqlite3.IntegrityError, match="retrieval insert fails"):
        experiment.run_arms(conn, config, ten(), provider, prices(), tmp_path)
    tables = ("analysis", "claim", "source_ref", "retrieval")
    assert [conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables] == [0, 0, 0, 0]
    assert not conn.in_transaction
