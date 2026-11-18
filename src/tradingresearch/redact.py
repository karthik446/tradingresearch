"""Key and token scrubbing (GUARDS-SPIKE §5.3, ADR-004 Gaps). Pure code, no model call.

`scrub` replaces every key-shaped string, plus the exact values of the configured keys once `configure` has seen
them, with `[REDACTED:<name>]`. The name is the pattern's name or the settings field's name, never the value. The
repo-written trace path (`experiment.run_items`) writes through `Scrubbing`, which writes one `redact` audit line per
span it changed. `scan` walks a directory read-only for `tr guards scan`. Provider error and reply text go through
`clip` and `scrub` once the adapters call them (see ADR-004 Gaps for the call sites still to wire).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path
from typing import Any, TypeVar

from gigai_core import CoreModel

from . import guards
from .config import Secret

VERSION = "2"  # an audit line's rule_version; bump it when PATTERNS change
CLIP = 300  # the characters of an error body a provider keeps (the cut the adapters already make)
MIN_SECRET = 8  # a configured value shorter than this is not matched exactly (it would redact ordinary words)

# Patterns run on decoded text: a record's string values one by one (`model`), a JSON line's strings (`scan`), or raw
# text. LEFT starts a match only where no letter or digit runs into it (`task-ant-colony` stays), or right after an
# escaped `\n`, `\r` or `\t`, as a non-JSON log line may hold. Each key pattern takes any length after its prefix,
# so a key cut at CLIP characters is still caught. A key split by a newline loses only its head: the tail is kept.
LEFT = r"(?:(?<=\\[nrt])|(?<![A-Za-z0-9_]))"
HEADER_VALUE = r"[\"']?\s*[:=]\s*[\"']?(?!\[REDACTED:)[^\s\"'\\,;}]+"  # an already replaced value is not matched again
APCA = r"APCA[-_]API[-_](?:KEY[-_]ID|SECRET[-_]KEY)"
X_API_KEY = r"x[-_]api[-_]key"
PATTERNS: dict[str, re.Pattern[str]] = {
    "sk_or_key": re.compile(LEFT + r"sk-or-v1-[0-9a-f]+"),  # an OpenRouter key
    "sk_ant_key": re.compile(LEFT + r"sk-ant-[A-Za-z0-9_-]+"),  # an Anthropic key
    "sk_proj_key": re.compile(LEFT + r"sk-proj-[A-Za-z0-9_-]+"),  # an OpenAI project key
    # a token is 20 or more base64url/JWT characters with a digit among them, so "bearer bond-equivalent-yield" stays
    "bearer_token": re.compile(r"(?i)" + LEFT + r"bearer\s+(?=[A-Za-z0-9._~+/=-]*[0-9])[A-Za-z0-9._~+/=-]{20,}"),
    "apca_header": re.compile(r"(?i)" + LEFT + APCA + HEADER_VALUE),
    "x_api_key_header": re.compile(r"(?i)" + LEFT + X_API_KEY + HEADER_VALUE),  # its value, any shape
    "pk_key_id": re.compile(LEFT + r"(?:PK|AK)[A-Z0-9]{18}\b"),  # an Alpaca key id
}
# a dict key naming a credential header: its whole string value is replaced when no pattern above took it
HEADER_KEYS: dict[str, re.Pattern[str]] = {
    "apca_header": re.compile(rf"(?i){APCA}"),
    "x_api_key_header": re.compile(rf"(?i){X_API_KEY}"),
}

_known: dict[str, str] = {}  # settings field name -> the exact value (`configure`); never printed


def marker(name: str) -> str:
    return f"[REDACTED:{name}]"


def remember(name: str, value: str) -> None:
    """Match `value` exactly from now on, under `name`; a value shorter than MIN_SECRET is ignored."""
    if len(value) >= MIN_SECRET:
        _known[name] = value


def configure(cfg) -> None:
    """Every `Secret` field of the settings, matched exactly under its field name (a key a pattern may miss, such as
    Alpaca's secret)."""
    for f in fields(cfg):
        if isinstance(value := getattr(cfg, f.name), Secret):
            remember(f.name, value.reveal())


def forget() -> None:
    _known.clear()


def scrubbed(text: str) -> tuple[str, list[str]]:
    """`text` with every hit replaced, and the name of each hit (one entry per occurrence)."""
    names: list[str] = []
    for name, value in sorted(_known.items(), key=lambda kv: -len(kv[1])):
        if count := text.count(value):
            names += [name] * count
            text = text.replace(value, marker(name))
    for name, pattern in PATTERNS.items():
        text, count = pattern.subn(marker(name), text)
        names += [name] * count
    return text, names


def scrub(text: str) -> str:
    return scrubbed(text)[0]


def clip(text: str, limit: int = CLIP) -> str:
    """An error body as a provider keeps it: scrubbed whole, then cut, so a key across the cut is never half kept."""
    return scrub(text)[:limit]


M = TypeVar("M", bound=CoreModel)
MARKER = re.compile(r"\[REDACTED:\w+\]")


def tree(value: Any) -> tuple[Any, list[str]]:
    """A decoded JSON value with every string in it scrubbed, dict keys included, and the names of the hits. A string
    under a key that names a credential header (`HEADER_KEYS`) is replaced whole when no pattern took it."""
    if isinstance(value, str):
        return scrubbed(value)
    if isinstance(value, list):
        items = [tree(item) for item in value]
        return [clean for clean, _ in items], [name for _, found in items for name in found]
    if not isinstance(value, dict):
        return value, []
    out: dict[Any, Any] = {}
    names: list[str] = []
    for key, item in value.items():
        clean_key, found = scrubbed(key) if isinstance(key, str) else (key, [])
        clean, more = tree(item)
        header = isinstance(key, str) and next((n for n, p in HEADER_KEYS.items() if p.fullmatch(key.strip())), None)
        if header and isinstance(item, str) and not more and item.strip() and not MARKER.fullmatch(item.strip()):
            clean, more = marker(header), [header]
        out[clean_key] = clean
        names += found + more
    return out, names


def model(record: M) -> tuple[M, list[str]]:
    """A record (a span, a Sample) with every string value and dict key in it scrubbed, rebuilt from the scrubbed
    values; the record itself when nothing hit. Strings are scrubbed decoded, never inside JSON text, where a newline
    is `\\n` and a pattern's left edge would miss the key after it."""
    clean, names = tree(record.model_dump(mode="json"))
    return (type(record).model_validate_json(json.dumps(clean)) if names else record), names


class Scrubbing:
    """A trace sink that scrubs each span before `sink` writes it, and writes one `redact` audit line per pattern hit
    in a span (rule = the pattern name; the detail is the span kind and the count, never the text)."""

    def __init__(self, sink, auditor: guards.Auditor) -> None:
        self.sink, self.auditor = sink, auditor
        self.path = sink.path

    def write(self, span) -> None:
        clean, names = model(span)
        if names:
            subject = guards.AuditSubject(kind="span", id=clean.span_id, sha256=guards.sha256(clean.model_dump_json()))
            for name, count in sorted(Counter(names).items()):
                self.auditor.write("redact", "redact", name, VERSION, subject, f"{clean.kind} span: {count} hit(s)")
        self.sink.write(clean)

    def close(self) -> None:
        self.sink.close()


def scan(root: Path) -> tuple[int, list[tuple[Path, int, str, int]]]:
    """Every file under `root`, read only: the number of files, and each hit as (file, line, name, count)."""
    files, hits = 0, []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        files += 1
        for number, line in lines(path):
            for name, count in sorted(Counter(line_hits(line)).items()):
                hits.append((path, number, name, count))
    return files, hits


def line_hits(line: str) -> list[str]:
    """The hits in one line: a JSON line (a trace span, a run sample) by its decoded strings, as `model` scrubs them;
    any other line as it is."""
    try:
        value = json.loads(line)
    except (ValueError, RecursionError):
        return scrubbed(line)[1]
    return tree(value)[1]


def lines(path: Path) -> Iterator[tuple[int, str]]:
    """A file's lines, any bytes decoded (a key is ASCII, so a binary file such as journal.db is still searched)."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        yield from enumerate(fh, 1)
