"""`tr check` on a drop arm's analysis (G12fix, reader m4): the verdicts the store wrote, the hidden rows named; and
on a retrieval arm's analysis (G13fix): the chunks of its `retrieval` row citable, another item's chunk not. $0."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_masking import pinned_tokens, run_pair, ten  # noqa: F401  (pinned_tokens: fixture)
from test_retrieval_analyze import cited_arm
from test_week4 import prices

from tradingresearch import experiment, journal
from tradingresearch.commands.check import cmd_check
from tradingresearch.records import Analysis
from tradingresearch.retrieval import store


def checked(tmp_path, analysis_id: str, capsys) -> str:
    cmd_check(SimpleNamespace(analysis_id=analysis_id),
              SimpleNamespace(db_path=tmp_path / "journal.db", data_dir=tmp_path))
    return capsys.readouterr().out


def test_check_agrees_with_the_store_on_both_arms_of_a_drop_pair(tmp_path, capsys, pinned_tokens):  # noqa: F811
    _, conn, results = run_pair(tmp_path, [])
    assert store.rows(conn) == [], "no retrieval row: the check reads the SOURCES table only, as before G13fix"
    for result, rejected in zip(results, (0, 1), strict=True):
        ids = conn.execute("SELECT analysis_id FROM analysis WHERE json_extract(body, '$.run_id') = ?",
                           (result.run.record.run_id,)).fetchall()
        assert len(ids) == 10
        for (analysis_id,) in ids:
            out = checked(tmp_path, analysis_id, capsys)
            kept = len(journal.get(conn, Analysis, analysis_id).claims)
            assert out.endswith(f"kept {kept}, rejected {rejected}\n")
            if rejected:  # c12 cites eps_diluted_CY2026Q3, an EDGAR row the drop arm never saw
                assert "\nc12 [fact] REJECTED dropped_source" in out
                assert "rows not shown to the model (edgar)" in out.splitlines()[1]
                eps = next(line for line in out.splitlines() if "eps_diluted_CY2026Q3" in line)
                assert eps.endswith("(not shown to the model)")
            else:
                assert "\nc12 [fact] ok" in out and "not shown" not in out


@pytest.mark.usefixtures("pinned_tokens")
def test_check_keeps_a_retrieval_arms_passage_citation_and_rejects_a_chunk_not_in_its_row(tmp_path, capsys):
    """Every item gets one reply whose c13 cites FAKEA's top passage: kept on FAKEA (its row holds the chunk), and
    rejected on the other nine (their rows are empty), so `tr check` agrees with the store on all ten."""
    config, top, replied, provider = cited_arm(tmp_path)
    conn = journal.connect(tmp_path / "journal.db")
    experiment.run_arms(conn, config, ten(), provider, prices(), tmp_path)

    rows = store.rows(conn)
    assert len(rows) == 10
    for row in rows:
        out = checked(tmp_path, row["analysis_id"], capsys)
        kept = len(journal.get(conn, Analysis, row["analysis_id"]).claims)
        assert out.endswith(f"kept {kept}, rejected {replied - kept}\n")
        if row["ticker"] == "FAKEA":
            assert "\nc13 [fact] ok\n" in out and f"\n    src:  {top.chunk_id} passage\n" in out
            assert kept == replied
        else:
            assert row["chunks"] == [] and f"\nc13 [fact] REJECTED unknown_source: {top.chunk_id}\n" in out
            assert f"\n    src:  {top.chunk_id} NOT IN TABLE = -\n" in out
