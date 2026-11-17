"""Filing HTML to text lines (RETRIEVAL-SPIKE §1.4 step 1), stdlib `html.parser` only.

- An EDGAR SGML wrapper (`<DOCUMENT>`, then `<TYPE>`, `<SEQUENCE>`, `<FILENAME>`, `<DESCRIPTION>` up to `<TEXT>`, and
  the closing `</TEXT></DOCUMENT>`), which some exhibit files carry, is cut before parsing: its unclosed tags would
  leave `EX-99.1 2 <file name> EX-99.1` as text.
- `script`, `style`, `head`, `title` and `ix:header` (the hidden inline-XBRL block) are dropped.
- Source newlines are spaces, so a pretty-printed table row stays one row.
- Block tags end a line, except inside a `td`/`th`, where they are a space (a cell made of several `<p>` keeps its
  row label next to its values).
- Each `<tr>` is one line, its non-empty cells joined by ` | `. Stray `$`, `(`, `)` and `%` cells are glued to their
  number: `$ | 82,904` becomes `$82,904`, `(321 | )` becomes `(321)`.
- A table inside a cell is flattened into that cell's text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

SKIP = frozenset({"script", "style", "head", "title", "ix:header"})
BLOCK = frozenset({"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"})
CELL = frozenset({"td", "th"})
OPENERS = frozenset({"$", "(", "$(", "($"})
CLOSERS = re.compile(r"[)%]+")
SGML_WRAPPER = re.compile(r"\A\s*<DOCUMENT>.*?<TEXT>|</TEXT>\s*</DOCUMENT>\s*\Z", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class Line:
    """One line of a document. `table` is the table's ordinal for a row, None for prose."""

    text: str
    table: int | None = None


def squash(text: str) -> str:
    """Whitespace runs (newlines and no-break spaces included) to one space; zero-width spaces removed."""
    return " ".join(text.replace("\u200b", "").split())


def glue(cells: list[str]) -> list[str]:
    """Join currency signs, parentheses and percent signs that sit in their own cell to the neighbouring number."""
    out: list[str] = []
    carry = ""
    for cell in cells:
        if cell in OPENERS:
            carry += cell
        elif CLOSERS.fullmatch(cell) and out and not carry:
            out[-1] += cell
        else:
            out.append(carry + cell)
            carry = ""
    if carry:
        out.append(carry)
    return out


class _Lines(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[Line] = []
        self.skip = 0
        self.depth = 0  # table nesting; rows are read at depth 1 only
        self.tables = -1
        self.text: list[str] = []
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def flush(self) -> None:
        text = squash("".join(self.text))
        self.text = []
        if text:
            self.lines.append(Line(text))

    def end_cell(self) -> None:
        if self.cell is not None and self.row is not None:
            self.row.append(squash("".join(self.cell)))
        self.cell = None

    def end_row(self) -> None:
        self.end_cell()
        if self.row is not None:
            cells = glue([cell for cell in self.row if cell])
            if cells:
                self.lines.append(Line(" | ".join(cells), self.tables))
        self.row = None

    def space_or_break(self) -> None:
        if self.cell is not None:
            self.cell.append(" ")
        else:
            self.flush()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.flush()
                self.tables += 1
                return
        if self.depth == 1 and tag == "tr":
            self.end_row()
            self.row = []
        elif self.depth == 1 and tag in CELL:
            self.end_cell()
            if self.row is None:
                self.row = []
            self.cell = []
        elif tag in BLOCK or (self.depth > 1 and tag in CELL | {"tr"}):
            self.space_or_break()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "table" and self.depth == 1:
            self.end_row()
            self.flush()
            self.depth = 0
        elif tag == "table" and self.depth > 1:
            self.depth -= 1
            self.space_or_break()
        elif self.depth == 1 and tag in CELL:
            self.end_cell()
        elif self.depth == 1 and tag == "tr":
            self.end_row()
        elif tag in BLOCK or (self.depth > 1 and tag in CELL | {"tr"}):
            self.space_or_break()

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        (self.cell if self.cell is not None else self.text).append(data)

    def close(self) -> None:
        super().close()
        self.end_row()
        self.flush()


def lines(html: str) -> list[Line]:
    """The document's prose lines and table rows, in reading order."""
    parser = _Lines()
    parser.feed(SGML_WRAPPER.sub("", html))
    parser.close()
    return parser.lines


def decode(raw: bytes) -> str:
    """Filing bytes as text: UTF-8, else Windows-1252 (older EDGAR documents), never an exception."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")
