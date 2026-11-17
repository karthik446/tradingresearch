"""`tr retrieval build|query|eval` end to end on FAKEA (offline), and the help goldens."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_retrieval_eval import EX991, FUTURE
from test_retrieval_ingest import NOW, fake_archives, write_headlines

from tradingresearch.cli import main
from tradingresearch.commands import retrieval as command

HELP = Path(__file__).parent / "fixtures" / "help"
SCHEMA = Path(__file__).parents[1] / "evals" / "retrieval_query.schema.md"
FUTURE_HEADLINE = datetime(2026, 11, 6, 12, tzinfo=UTC)  # after the 2026-11-05 close


@pytest.mark.parametrize(("golden", "argv"), [
    ("retrieval", ["retrieval"]), ("retrieval_build", ["retrieval", "build"]),
    ("retrieval_query", ["retrieval", "query"]), ("retrieval_eval", ["retrieval", "eval"]),
])
def test_help_matches_the_golden_text(golden, argv, monkeypatch, capsys):
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("NO_COLOR", "1")
    with pytest.raises(SystemExit) as exit_:
        main([*argv, "--help"])
    assert exit_.value.code == 0
    assert capsys.readouterr().out == (HELP / f"{golden}.txt").read_text()


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("TR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(command, "utc_now", lambda: NOW)
    monkeypatch.setattr(command, "archives_client", lambda cfg: fake_archives(cfg.data_dir / "edgar")[0])
    write_headlines(tmp_path, "FAKEA", [(3, "FakeA recalls Gizmo line", FUTURE_HEADLINE)])
    return tmp_path


def test_build_query_eval(data_dir, capsys, tmp_path):
    main(["retrieval", "build", "--ticker", "FAKEA", "--quarters", "1"])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("index sha256:")
    assert out[1].startswith("docs 5 (10-Q 1, 8-K 2, EX-99.1 1, headline 1), chunks ")
    assert out[2].startswith("SEC requests 8, ")
    [folder] = (data_dir / "retrieval").iterdir()
    assert out[0] == f"index sha256:{folder.name}"

    main(["retrieval", "build", "--ticker", "FAKEA", "--quarters", "1"])  # cached: no request, same index
    again = capsys.readouterr().out.splitlines()
    assert again[0] == out[0] and again[2].startswith("SEC requests 0, ")

    main(["retrieval", "query", "Gizmo recall", "--ticker", "FAKEA", "--as-of", "2026-11-05", "-k", "3"])
    lines = capsys.readouterr().out.splitlines()
    assert "| 2 hits | 2 future docs masked" in lines[0] and "UNTRUSTED INPUT" in lines[0]
    assert lines[1] == "rank | score | chunk | text" and len(lines) == 4  # only 2 visible chunks say Gizmo/recall
    assert not any(FUTURE in line or "headline/3" in line for line in lines)

    queries = tmp_path / "queries.jsonl"
    queries.write_text("".join(line + "\n" for line in SCHEMA.read_text().splitlines() if line.startswith('{"id"')))
    main(["retrieval", "eval", "--queries", str(queries), "--index", folder.name[:10]])
    table = capsys.readouterr().out.splitlines()
    assert table[0] == f"index sha256:{folder.name} | 2 queries | 4 future docs masked in total"
    assert table[2].startswith("bm25 | all | 2 | ") and table[2].count("(") == 4
    assert [line.split(" | ")[1] for line in table[2:]] == ["all", "lookup", "numeric"]


def test_query_rejects_a_non_session_and_eval_rejects_a_bad_label(data_dir, tmp_path):
    main(["retrieval", "build", "--ticker", "FAKEA", "--quarters", "1"])
    with pytest.raises(SystemExit, match="not an NYSE session"):
        main(["retrieval", "query", "x", "--ticker", "FAKEA", "--as-of", "2026-11-07"])
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"id": "q", "ticker": "FAKEA", "as_of": "2026-11-05", "kind": "numeric", "text": "x",
                               "gold": [{"doc": EX991, "quote": "not in the filing"}]}) + "\n")
    with pytest.raises(SystemExit, match="is in no chunk"):
        main(["retrieval", "eval", "--queries", str(bad)])


def test_empty_queries_file_prints_zero_and_needs_no_index(data_dir, capsys, tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    main(["retrieval", "eval", "--queries", str(empty)])
    assert capsys.readouterr().out == "0 queries\n"


def test_shipped_queries_file_is_empty():
    assert (Path(__file__).parents[1] / "evals" / "retrieval_query.jsonl").read_text() == ""
