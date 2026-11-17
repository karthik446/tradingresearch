"""`tr check` on a drop arm's analysis (G12fix, reader m4): the verdicts the store wrote, the hidden rows named. $0."""

from __future__ import annotations

from types import SimpleNamespace

from test_masking import pinned_tokens, run_pair  # noqa: F401  (pinned_tokens is a fixture)
from tradingresearch import journal
from tradingresearch.commands.check import cmd_check
from tradingresearch.records import Analysis


def checked(tmp_path, analysis_id: str, capsys) -> str:
    cmd_check(SimpleNamespace(analysis_id=analysis_id),
              SimpleNamespace(db_path=tmp_path / "journal.db", data_dir=tmp_path))
    return capsys.readouterr().out


def test_check_agrees_with_the_store_on_both_arms_of_a_drop_pair(tmp_path, capsys, pinned_tokens):  # noqa: F811
    _, conn, results = run_pair(tmp_path, [])
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
