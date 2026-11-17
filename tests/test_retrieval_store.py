"""The `retrieval` journal table: one append-only row per retrieval-arm analysis with its ordered chunks, and a
journal written before the table gains it and nothing else."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import date

import pytest
from test_analyze import RECORDED

from tradingresearch import journal
from tradingresearch.records import Analysis
from tradingresearch.retrieval import store

RETRIEVED = store.Retrieved(
    ticker="AAPL", as_of=date(2026, 11, 16), mode="hybrid+rerank", k=3, index_digest="sha256:" + "b" * 64,
    query="AAPL quarterly results", query_template="{ticker} quarterly results",
    passages=(store.Passage("acc-2/ex99.htm#4", "c" * 64, 2.5, "Revenue rose."),
              store.Passage("headline/7#0", "d" * 64, 1.25, "Apple ships."),
              store.Passage("acc-1/10q.htm#0", "e" * 64, -0.5, "Risk factors.")),
    masked_docs=2)
PRIOR_TABLES = [t for t in journal.IMMUTABLE if t != "retrieval"]
ANALYSIS = Analysis.model_validate_json(json.dumps(RECORDED))


def prior_journal(path) -> None:
    """A journal as the code before G13b wrote it: the schema text up to the retrieval table (appended last, so the
    prefix is the older schema), its triggers, one analysis and one daily row."""
    conn = sqlite3.connect(path)
    conn.executescript(journal.SCHEMA[:journal.SCHEMA.index("-- G13b")]
                       + "".join(journal.append_only_triggers(t) for t in PRIOR_TABLES))
    journal.add(conn, ANALYSIS)
    journal.add_daily_run(conn, {"daily_id": "dr_1", "session": "2026-11-16", "step": "analyze", "ticker": "AAPL",
                                 "status": "ok", "reason": "", "ids": [RECORDED["analysis_id"]], "cost_usd": 0.01})
    conn.close()


def contents(conn: sqlite3.Connection) -> tuple[set, dict]:
    master = set(conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
    tables = [name for kind, name, _, _ in master if kind == "table"]
    return master, {name: conn.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall() for name in tables}


def test_a_row_keeps_the_ordered_chunks_and_links_its_analysis(tmp_path):
    conn = journal.connect(tmp_path / "journal.db")
    journal.add(conn, ANALYSIS)
    store.add(conn, RETRIEVED, RECORDED["analysis_id"], RECORDED["input_hash"])
    assert store.rows(conn) == store.rows(conn, RECORDED["analysis_id"]) == [{
        "analysis_id": RECORDED["analysis_id"], "input_hash": RECORDED["input_hash"], "ticker": "AAPL",
        "as_of": "2026-11-16", "mode": "hybrid+rerank", "k": 3, "index_digest": "sha256:" + "b" * 64,
        "query": "AAPL quarterly results", "query_template": "{ticker} quarterly results",
        "chunks": [["acc-2/ex99.htm#4", "c" * 64, 2.5], ["headline/7#0", "d" * 64, 1.25],
                   ["acc-1/10q.htm#0", "e" * 64, -0.5]],
        "masked_docs": 2}]
    assert store.rows(conn, "an_other") == []


def test_the_table_is_append_only_and_needs_a_stored_analysis(tmp_path):
    conn = journal.connect(tmp_path / "journal.db")
    journal.add(conn, ANALYSIS)
    store.add(conn, RETRIEVED, RECORDED["analysis_id"], RECORDED["input_hash"])
    for statement in ("UPDATE retrieval SET k = 5", "DELETE FROM retrieval"):
        with pytest.raises(sqlite3.DatabaseError, match="retrieval is append-only"):
            conn.execute(statement)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.add(conn, RETRIEVED, "an_missing", RECORDED["input_hash"])
    assert len(store.rows(conn)) == 1


def test_an_older_journal_gains_only_the_retrieval_table(tmp_path):
    prior_journal(tmp_path / "prior.db")
    shutil.copy(tmp_path / "prior.db", tmp_path / "copy.db")
    before = sqlite3.connect(tmp_path / "prior.db")
    old_master, old_rows = contents(before)
    assert "retrieval" not in old_rows and old_rows["analysis"] and old_rows["daily_run"]

    conn = journal.connect(tmp_path / "copy.db")
    new_master, new_rows = contents(conn)
    assert {(kind, name) for kind, name, _, _ in new_master - old_master} == {
        ("table", "retrieval"), ("trigger", "retrieval_no_update"), ("trigger", "retrieval_no_delete")}
    assert old_master <= new_master, "every older table, index and trigger is as it was"
    assert {name: rows for name, rows in new_rows.items() if name != "retrieval"} == old_rows
    assert new_rows["retrieval"] == []
    conn.close()
    assert contents(journal.connect(tmp_path / "copy.db")) == (new_master, new_rows), "reopening changes nothing"
