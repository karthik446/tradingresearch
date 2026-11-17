"""Lines to chunks (RETRIEVAL-SPIKE §1.4 steps 2-3): atomic units, table context, greedy packing.

- **Units.** A prose line splits into sentences; a table row is one unit, so a number never leaves its row label.
  A unit is never split; one longer than `max_tokens` becomes a chunk of its own.
- **Table context.** Every chunk holding rows of a table starts with that table's context: the prose line just
  before the table and its header rows (up to 3 rows before the first data row). A new table starts a new chunk.
- **Packing.** Whole units are added in order until the next one would pass `max_tokens`.
- **Counting.** `count_tokens` is the documented fallback counter (`COUNTER`): no pinned bge tokenizer file is
  available offline without a new download, so tokens are word runs and single punctuation marks. bge-small
  measured 1.0-1.3x more on real filings (SPIKE §1.3). The counter is recorded in the manifest, so an index built
  with another counter has another digest.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from .extract import Line, lines as html_lines

CHUNKER_VERSION = "chunk-v2"  # v2: the EDGAR SGML wrapper of an exhibit file is no longer text (extract.SGML_WRAPPER)
COUNTER = r"regex-v1: len(re.findall(r'\w+|[^\w\s]', text))"
DEFAULT_MAX_TOKENS = 256
HEADER_ROWS = 3

_TOKEN = re.compile(r"\w+|[^\w\s]")
_BOUNDARY = re.compile(r"[.!?][\"”)]?\s+(?=[A-Z$“\"(])")
_DATA_CELL = re.compile(r"[$(]*-?\d[\d,]*(\.\d+)?%?\)?")
_YEAR = re.compile(r"(19|20)\d\d")
_INITIALS = re.compile(r"(?:[a-z]\.)+")
ABBREVIATIONS = frozenset({
    "inc.", "corp.", "co.", "ltd.", "llc.", "no.", "nos.", "vs.", "e.g.", "i.e.", "etc.", "approx.", "mr.", "ms.",
    "mrs.", "dr.", "st.", "jr.", "sr.", "fig.", "jan.", "feb.", "mar.", "apr.", "jun.", "jul.", "aug.", "sep.", "sept.",
    "oct.", "nov.", "dec.",
})


def count_tokens(text: str) -> int:
    return len(_TOKEN.findall(text))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # f"{doc_id}#{ordinal}"
    doc_id: str
    ordinal: int
    text: str
    sha256: str
    tokens: int


@dataclass(frozen=True)
class Unit:
    text: str
    line: int  # source line number: sentences of one line are rejoined with a space, lines with a newline
    table: int | None


def _abbreviation(word: str) -> bool:
    word = word.lower().lstrip("(\"“").rstrip("\"”)")
    return word in ABBREVIATIONS or bool(_INITIALS.fullmatch(word))


def sentences(text: str) -> list[str]:
    """A prose line split after `.`, `!` or `?` (and a closing quote) before a capital, `$`, quote or `(`.

    No split after an abbreviation such as "Inc.", "No.", "Sep." or initials such as "U.S." and "J.".
    """
    out, start = [], 0
    for match in _BOUNDARY.finditer(text):
        cut = match.start() + len(match.group().rstrip())
        if _abbreviation(text[start:cut].rsplit(None, 1)[-1]):
            continue
        out.append(text[start:cut])
        start = match.end()
    out.append(text[start:])
    return [sentence for sentence in out if sentence]


def is_data_row(row: str) -> bool:
    """At least one cell is a number (not a 4-digit year): `$82,904`, `(321)`, `12%`, `1.23`."""
    return any(_DATA_CELL.fullmatch(cell) and not _YEAR.fullmatch(cell) for cell in row.split(" | "))


def units_and_context(lines: list[Line]) -> tuple[list[Unit], dict[int, list[str]]]:
    """The document's units in order, and each table's context lines (caption, then header rows)."""
    units: list[Unit] = []
    context: dict[int, list[str]] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.table is None:
            units += [Unit(sentence, i, None) for sentence in sentences(line.text)]
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].table == line.table:
            j += 1
        rows = [row.text for row in lines[i:j]]
        first_data = next((n for n, row in enumerate(rows) if is_data_row(row)), None)
        header = rows[:min(first_data, HEADER_ROWS)] if first_data else []
        caption = [lines[i - 1].text] if i and lines[i - 1].table is None else []
        context[line.table] = caption + header
        units += [Unit(row, i + len(header) + n, line.table) for n, row in enumerate(rows[len(header):])]
        i = j
    return units, context


def _render(context: list[str], units: list[Unit]) -> str:
    lines: list[str] = list(context)
    last = None
    for unit in units:
        if unit.line == last:
            lines[-1] += " " + unit.text
        else:
            lines.append(unit.text)
        last = unit.line
    return "\n".join(lines)


def chunk_lines(doc_id: str, lines: list[Line], max_tokens: int = DEFAULT_MAX_TOKENS,
                count: Callable[[str], int] = count_tokens) -> list[Chunk]:
    """Greedy packing of whole units; context lines count towards `max_tokens`."""
    units, context = units_and_context(lines)
    packs: list[tuple[list[str], list[Unit], int]] = []  # (context, units, tokens)
    table: int | None = None
    for unit in units:
        size = count(unit.text)
        new_table = unit.table is not None and (not packs or unit.table != table)
        overflow = bool(packs) and bool(packs[-1][1]) and packs[-1][2] + size > max_tokens
        if new_table or overflow or not packs:
            if unit.table is not None:
                table = unit.table
                ctx = context[unit.table]
            else:
                table, ctx = None, []
            packs.append((ctx, [], sum(count(text) for text in ctx)))
        ctx, members, tokens = packs[-1]
        members.append(unit)
        packs[-1] = (ctx, members, tokens + size)
    chunks = []
    for ordinal, (ctx, members, tokens) in enumerate(packs):
        text = _render(ctx, members)
        chunks.append(Chunk(f"{doc_id}#{ordinal}", doc_id, ordinal, text, sha256(text), tokens))
    return chunks


def chunk_document(doc_id: str, content: str, media: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> list[Chunk]:
    """`media` is "html" (a filing) or "text" (a headline: one prose line)."""
    lines = html_lines(content) if media == "html" else [Line(" ".join(content.split()))]
    return chunk_lines(doc_id, [line for line in lines if line.text], max_tokens)
