"""Filing HTML to lines, and lines to chunks (RETRIEVAL-SPIKE §1.4), on invented FAKEA documents."""

from __future__ import annotations

from pathlib import Path

import pytest

from tradingresearch.retrieval import chunk, extract
from tradingresearch.retrieval.extract import Line

FIX = Path(__file__).parent / "fixtures" / "retrieval"
DOCS = ("fakea-8k_20261029.htm", "fakea-ex991.htm", "fakea-20260930.htm", "fakea-pressrelease.htm")


def lines_of(name: str) -> list[Line]:
    return extract.lines((FIX / name).read_text())


def test_8k_rows_survive_multi_paragraph_cells_and_pretty_printing():
    lines = lines_of("fakea-8k_20261029.htm")
    rows = [line.text for line in lines if line.table is not None]
    assert rows == [
        "Three Months Ended September 30, 2026 | Change",
        "Total net revenue | $4,255 | 12%",  # label split over two <p>, "$" and "%" in their own cells
        "Restructuring charges | (45)",  # pretty-printed: newlines inside cells, ")" in its own cell
    ]
    assert {line.table for line in lines if line.table is not None} == {0}


def test_hidden_xbrl_script_and_head_are_dropped_and_br_breaks_a_line():
    text = [line.text for line in lines_of("fakea-8k_20261029.htm")]
    joined = "\n".join(text)
    assert "HIDDENXBRLTEXT" not in joined and "SCRIPTTEXT" not in joined and "fakea-8k_20261029" not in joined
    assert text[2:4] == ["FakeA Inc.", "(Exact name of registrant as specified in its charter)"]


def test_10q_row_with_br_inside_a_cell_stays_one_row():
    rows = [line.text for line in lines_of("fakea-20260930.htm") if line.table is not None]
    assert rows[:2] == ["(in millions) | September 30, 2026 | December 31, 2025", "Cash and cash equivalents | $2,980 | $2,410"]


def test_an_sgml_wrapped_exhibit_keeps_only_its_html_text():
    lines = lines_of("fakea-ex991-sgml.htm")
    assert [line.text for line in lines][:2] == ["Exhibit 99.1", "FakeA Reports Third Quarter 2026 Results"]
    joined = "\n".join(line.text for line in lines)
    assert "fakea-ex991-sgml.htm" not in joined and "EX-99.1" not in joined and "DOCUMENT" not in joined
    assert chunk.chunk_document("x", (FIX / "fakea-ex991-sgml.htm").read_text(), "html")[0].text.startswith(
        "Exhibit 99.1")


def test_glue_joins_signs_to_numbers():
    assert extract.glue(["Net", "$", "(", "12", ")", "%", "x"]) == ["Net", "$(12)%", "x"]
    assert extract.glue(["$"]) == ["$"]


def test_nested_table_is_flattened_into_its_cell():
    html = "<table><tr><td>Outer</td><td><table><tr><td>in</td><td>ner</td></tr></table></td><td>9</td></tr></table>"
    assert extract.lines(html) == [Line("Outer | in ner | 9", 0)]


def test_decode_falls_back_to_cp1252():
    assert extract.decode("caf\u00e9".encode("cp1252")) == "caf\u00e9"
    assert extract.decode("caf\u00e9".encode()) == "caf\u00e9"


@pytest.mark.parametrize(("text", "expected"), [
    ("FakeA Inc. operates in the U.S. and Canada. Revenue rose in Sep. as demand held up.",
     ["FakeA Inc. operates in the U.S. and Canada.", "Revenue rose in Sep. as demand held up."]),
    ("Sales rose, said J. Doe of FakeA Corp. They fell in the U.S. Treasury desk.",
     ["Sales rose, said J. Doe of FakeA Corp. They fell in the U.S. Treasury desk."]),
    ("Is the backlog growing? Yes. Backlog reached $5.1 billion.",
     ["Is the backlog growing?", "Yes.", "Backlog reached $5.1 billion."]),
    ('He said "it grew." Then it fell 2.5%. $3 more.', ['He said "it grew."', "Then it fell 2.5%.", "$3 more."]),
    ("Item No. 2 and e.g. Widgets stay.", ["Item No. 2 and e.g. Widgets stay."]),
])
def test_sentence_splitter(text, expected):
    assert chunk.sentences(text) == expected


def test_data_rows_and_headers():
    assert chunk.is_data_row("Net income | $701 | $633")
    assert chunk.is_data_row("Restructuring charges | (45) | (12)")
    assert chunk.is_data_row("Gross margin | 41.2% | 39.8%")
    assert not chunk.is_data_row("2026 | 2025")
    assert not chunk.is_data_row("September 30, 2026 | September 30, 2025")
    units, context = chunk.units_and_context(lines_of("fakea-ex991.htm"))
    assert context[0] == ["Condensed consolidated statements of operations (unaudited)",
                          "(in millions, except per-share amounts) | Three Months Ended",
                          "September 30, 2026 | September 30, 2025", "2026 | 2025"]
    assert "2026 | 2025" not in [unit.text for unit in units]


@pytest.mark.parametrize("max_tokens", [8, 20, 45, 60, 256, 2000])
@pytest.mark.parametrize("name", DOCS)
def test_no_unit_is_split_and_every_number_keeps_its_row_label(name, max_tokens):
    lines = lines_of(name)
    units, context = chunk.units_and_context(lines)
    chunks = chunk.chunk_lines(f"acc/{name}", lines, max_tokens)
    chunk_lines = [set(c.text.split("\n")) for c in chunks]
    for unit in units:
        if unit.table is not None:  # a row is a whole line of some chunk, label and numbers together
            assert any(unit.text in lines_ for lines_ in chunk_lines), unit.text
        else:  # a sentence sits whole inside one line of some chunk
            assert any(unit.text in line for lines_ in chunk_lines for line in lines_), unit.text
    texts = {u.text for u in units}
    for c in chunks:  # every chunk holding rows of a table starts with that table's context
        lines_ = c.text.split("\n")
        tables = {u.table for u in units if u.table is not None and u.text in lines_}
        assert len(tables) <= 1
        ctx = context[tables.pop()] if tables else []
        assert lines_[:len(ctx)] == ctx
        assert c.tokens == chunk.count_tokens(c.text)
        assert c.sha256 == chunk.sha256(c.text)
        assert c.chunk_id == f"acc/{name}#{c.ordinal}"
        if c.tokens > max_tokens:  # only a lone unit (with its context) may pass the cap
            assert len(lines_) - len(ctx) == 1 and lines_[-1] in texts, c.text
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_over_cap_row_gets_its_own_chunk_with_context():
    long_row = "Revenue detail | " + " | ".join(f"{n},000" for n in range(1, 40))
    lines = [Line("Before."), Line("Segment | 2026", 0), Line("Short | 1", 0), Line(long_row, 0), Line("Tail | 2", 0)]
    chunks = chunk.chunk_lines("d", lines, max_tokens=30)
    texts = [c.text.split("\n") for c in chunks]
    assert ["Before.", "Segment | 2026", long_row] in texts
    assert all(t[:2] == ["Before.", "Segment | 2026"] for t in texts if any("|" in line for line in t))


def test_new_table_starts_a_new_chunk_and_prose_may_follow_a_table():
    lines = [Line("First caption."), Line("A | 1", 0), Line("After table."), Line("B | 2", 1)]
    chunks = chunk.chunk_lines("d", lines, max_tokens=1000)
    assert [c.text for c in chunks] == ["First caption.", "First caption.\nA | 1\nAfter table.", "After table.\nB | 2"]


def test_headline_is_one_prose_chunk():
    [only] = chunk.chunk_document("headline/7", "FakeA  recalls\nGizmo line", "text")
    assert (only.chunk_id, only.text) == ("headline/7#0", "FakeA recalls Gizmo line")
