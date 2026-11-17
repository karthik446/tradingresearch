"""Dataset release (TRAINING-SPIKE §7.4): the teacher analyses of the registered split's train/val sessions as
gigai-core `DatasetItem` files. The private form is verbatim (personal use). The public form ships every
Alpaca-derived absolute price as `{{px:<source_id>}}` and every headline as `{{news:<source_id>}}`, keyed to the
content-addressed SourceRef ids; `hydrate` refills it from the reader's own Alpaca pull and checks the bytes against
the private digests DATASHEET.md carries. No model call, no GitHub call, no tag.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from gigai_core import DatasetItem, open_run

from . import alpaca, bakeoff, edgar, journal, news, teacher
from . import analyze as an
from . import split as sp
from .records import Analysis, IndicatorSnapshot, SourceRef, Thesis, TrainingSplit, clean_route

LICENCE = "CDLA-Permissive-2.0"  # TRAINING-SPIKE §7.4 L752
ARM = "teacher"
FORMS = ("public", "private")
VAL_SHARE = 10  # the latest tenth of the item sessions is val (at least one session once there are two)
ROW = re.compile(r"src_[0-9a-f]{16} \| ")  # a SOURCES table line of an analyze prompt
PLACEHOLDER = re.compile(r"\{\{(px|news):(src_[0-9a-f]{16})\}\}")
NUMBER = r"\$?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?(?!\w)(?!\.\d)%?"
# templating and the shown-text check: placeholders, `{value}` and ISO dates are skipped whole; a word holding digits
# (`sma_200`, `1d`) is an identifier, the way analyze's ALLOWED_DIGITS reads claim text
TOKEN = re.compile(r"\{\{(?:px|news):[^{}]*\}\}|\{value\}|\b\d{4}-\d{2}-\d{2}\b|(?P<num>" + NUMBER + r")|\w+")
# the price check reads every digit run (Unicode digits; NFKC first, so `１２` and `½` count): `.` `,` `/` between runs
# join them (`12,50`, `7/8`) and letters may follow (`101.87usd`, `$1.2k`); a word that starts with a letter or `_`
# (`sma_200`) is still an identifier
SCAN = re.compile(r"\{\{(?:px|news):[^{}]*\}\}|\{value\}|\b\d{4}-\d{2}-\d{2}\b|[^\W\d]\w*"
                  r"|(?P<num>\$?(?:\d+|(?=[.,]\d))(?:[.,/]\d+)*(?:[eE][+-]?\d+)?%?)")
SEPARATORS = str.maketrans({"\u066b": ".", "\u066c": ",", "\u2044": "/"})  # Arabic decimal/thousands, fraction slash
SHEET_FILE = re.compile(r"- private `([^`]+)`: sha256 `([0-9a-f]{64})`, (\d+) items")
SHEET_ITEM = re.compile(r"- item `([^`]+)`: sha256 `([0-9a-f]{64})`")

# https://raw.githubusercontent.com/Community-Data-License-Agreements/Releases/main/CDLA-Permissive-2.0.txt
LICENCE_TEXT = """Community Data License Agreement - Permissive - Version 2.0

This is the Community Data License Agreement - Permissive, Version 2.0 (the "agreement"). Data Provider(s) and Data \
Recipient(s) agree as follows:

1. Provision of the Data

1.1. A Data Recipient may use, modify, and share the Data made available by Data Provider(s) under this agreement if \
that Data Recipient follows the terms of this agreement.

1.2. This agreement does not impose any restriction on a Data Recipient's use, modification, or sharing of any \
portions of the Data that are in the public domain or that may be used, modified, or shared under any other legal \
exception or limitation.

2. Conditions for Sharing Data

2.1. A Data Recipient may share Data, with or without modifications, so long as the Data Recipient makes available \
the text of this agreement with the shared Data.

3. No Restrictions on Results

3.1. This agreement does not impose any restriction or obligations with respect to the use, modification, or sharing \
of Results.

4. No Warranty; Limitation of Liability

4.1. All Data Recipients receive the Data subject to the following terms:

THE DATA IS PROVIDED ON AN "AS IS" BASIS, WITHOUT REPRESENTATIONS, WARRANTIES OR CONDITIONS OF ANY KIND, EITHER \
EXPRESS OR IMPLIED INCLUDING, WITHOUT LIMITATION, ANY WARRANTIES OR CONDITIONS OF TITLE, NON-INFRINGEMENT, \
MERCHANTABILITY OR FITNESS FOR A PARTICULAR PURPOSE.

NO DATA PROVIDER SHALL HAVE ANY LIABILITY FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL \
DAMAGES (INCLUDING WITHOUT LIMITATION LOST PROFITS), HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN \
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE DATA OR \
RESULTS, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.

5. Definitions

5.1. "Data" means the material received by a Data Recipient under this agreement.

5.2. "Data Provider" means any person who is the source of Data provided under this agreement and in reliance on a \
Data Recipient's agreement to its terms.

5.3. "Data Recipient" means any person who receives Data directly or indirectly from a Data Provider and agrees to \
the terms of this agreement.

5.4. "Results" means any outcome obtained by computational analysis of Data, including for example machine learning \
models and models' insights.
"""


class Refused(Exception):
    """A publish or hydrate that would write a wrong or unsafe release, with the reason; nothing is written."""


# ---------- prices and placeholders ----------

def px(source_id: str) -> str:
    return "{{px:" + source_id + "}}"


def news_placeholder(source_id: str) -> str:
    return "{{news:" + source_id + "}}"


def shown(value: float) -> int | float:
    """A price the way the SOURCES table shows it, read back as JSON: what a teacher copying the table writes."""
    return json.loads(an.plain(value))


def price_rows(snapshot: IndicatorSnapshot) -> dict[str, float]:
    """The snapshot's absolute prices (unit USD) by computed source id: the Alpaca-derived numbers §7.4 L737 keeps
    out of a public release. EDGAR USD facts are not computed rows; they ship verbatim."""
    return {row.source_id: row.value for row in an.snapshot_rows(snapshot)[1]
            if row.unit == "USD" and row.value is not None}


def table_rows(prompt: str) -> list[list[str]]:
    """The prompt's SOURCES rows as [source_id, name, value, unit] cells."""
    return [line.split(" | ") for line in prompt.split("\n") if ROW.match(line)]


def readings(token: str) -> set[float]:
    """Every value a scanned number may stand for: each digit run, each side of a `/`, and commas read both as
    thousands groups and as the decimal mark (`12,50`)."""
    body = token.strip("$%")
    sides = body.split("/")
    out = set()
    for text in {*re.findall(r"\d+", body), *(s.replace(",", mark) for s in sides for mark in ("", "."))}:
        try:
            out.add(float(text))
        except ValueError:  # `1.2.3`: its runs are already read
            continue
    return out


def price_like(token: str, prices: list[float]) -> bool:
    """A free-text number that could leak a price: near one of the item's prices, or (not a percent) written the way
    prices are, with `$`, a comma, a decimal point, a fraction slash or an exponent."""
    near = any(an.close_to(value, p) for value in readings(token) for p in prices)
    return near if token.endswith("%") else near or any(c in token for c in "$,./eE")


def free_text_hits(text: str, prices: list[float]) -> list[str]:
    text = unicodedata.normalize("NFKC", text).translate(SEPARATORS)
    return [m.group() for m in SCAN.finditer(text) if m.group("num") and price_like(m.group(), prices)]


def shown_hits(text: str, prices: list[float]) -> list[str]:
    """Numbers in a prompt or system turn that are a price as the table shows it (a row left untemplated)."""
    texts = {an.plain(p) for p in prices}
    return [m.group() for m in TOKEN.finditer(text)
            if m.group("num") and m.group().strip("$%").replace(",", "") in texts]


def strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in strings(item)]
    return []


def headline_labels(prompt: str) -> dict[str, str]:
    """Each headline row's quoted text as the prompt shows it, by news source id."""
    return {cells[0]: cells[2] for cells in table_rows(prompt) if cells[1].startswith(an.HEADLINE_NAME)}


def headline_hits(texts: list[str], labels: dict[str, str]) -> list[str]:
    """Headlines still in reply text after templating (copied without the row's quotes, or in another case)."""
    return [f"headline {sid}" for sid, label in labels.items()
            if any(label[1:-1].removesuffix("…").casefold() in t.casefold() for t in texts)]


def template_text(text: str, by_text: dict[str, str], labels: dict[str, str]) -> str:
    """Each headline's quoted text becomes its placeholder, then every number written exactly as a price's table text
    becomes that price's placeholder (a `$` stays)."""
    for sid, label in sorted(labels.items(), key=lambda kv: -len(kv[1])):
        text = text.replace(label, news_placeholder(sid))

    def swap(m: re.Match) -> str:
        token = m.group()
        if not m.group("num") or token.endswith("%") or token.lstrip("$") not in by_text:
            return token
        return ("$" if token.startswith("$") else "") + px(by_text[token.lstrip("$")])
    return TOKEN.sub(swap, text)


def template_value(value: object, by_text: dict[str, str], labels: dict[str, str]) -> object:
    if isinstance(value, str):
        return template_text(value, by_text, labels)
    if isinstance(value, dict):
        return {key: template_value(item, by_text, labels) for key, item in value.items()}
    if isinstance(value, list):
        return [template_value(item, by_text, labels) for item in value]
    return value


def matched_prices(claim: dict, parents: dict[str, tuple[str, ...]], prices: dict[str, float]) -> tuple[str, ...]:
    """The price sources a claim's value restates: a fact's cited ones, an inference's parents', within REL_TOL."""
    value = claim.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ()
    if claim.get("tag") == "fact":
        pool = [s for s in claim.get("source_ids") or [] if s in prices]
    else:
        pool = [s for parent in claim.get("derived_from") or [] for s in parents.get(str(parent), ())]
    return tuple(dict.fromkeys(s for s in pool if an.close_to(float(value), prices[s])))


def template_expected(expected: dict, prices: dict[str, float],
                      labels: dict[str, str]) -> tuple[dict, list[str]]:
    """The reply with each price-restating claim value as a placeholder and each headline and price text in free text
    templated; plus the claim values that restate a price but not exactly as the table shows it (they cannot ship)."""
    by_text = {an.plain(v): sid for sid, v in reversed(prices.items())}  # the first row wins
    parents: dict[str, tuple[str, ...]] = {}
    claims, left = [], []
    for claim in expected["claims"]:
        out = template_value({k: v for k, v in claim.items() if k != "value"}, by_text, labels)
        matched = matched_prices(claim, parents, prices)
        parents[str(claim.get("id"))] = matched
        value = claim.get("value")
        exact = [s for s in matched if shown(prices[s]) == value and type(shown(prices[s])) is type(value)]
        if "value" in claim:
            out["value"] = px(exact[0]) if exact else value
        if matched and not exact:
            left.append(f"value={value}")
        claims.append({k: out[k] for k in claim})  # the reply's key order, so a hydrated line has the same bytes
    return {k: claims if k == "claims" else template_value(v, by_text, labels) for k, v in expected.items()}, left


def template_prompt(prompt: str, prices: dict[str, float]) -> str:
    """Each price row's value cell and each headline row's quoted text as its placeholder; every other row verbatim."""
    lines = []
    for line in prompt.split("\n"):
        cells = line.split(" | ")
        if ROW.match(line) and cells[0] in prices:
            if cells[2] != an.plain(prices[cells[0]]):
                raise Refused(f"row {cells[0]} shows {cells[2]!r}, the snapshot says {an.plain(prices[cells[0]])}")
            cells[2] = px(cells[0])
        elif ROW.match(line) and cells[1].startswith(an.HEADLINE_NAME):
            cells[2] = news_placeholder(cells[0])
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def public_item(item: DatasetItem, prices: dict[str, float]) -> tuple[DatasetItem, list[str]]:
    """The public form of a private item, plus every price-check and headline hit left in it (an item with hits never
    ships)."""
    labels = headline_labels(item.prompt)
    expected, left = template_expected(item.expected, prices, labels)
    out = item.model_copy(update={"prompt": template_prompt(item.prompt, prices), "expected": expected})
    values, texts = list(prices.values()), strings(expected)
    hits = [t for s in texts for t in free_text_hits(s, values)] + headline_hits(texts, labels)
    hits += [t for text in (out.prompt, out.system or "") for t in shown_hits(text, values)]
    return out, hits + left


# ---------- the row filter ----------

@dataclass(frozen=True)
class Selected:
    """A teacher analysis that passed the row filter, with what its item is built from."""

    analysis: Analysis
    system: str
    prompt: str
    reply: dict
    theses: tuple[Thesis, ...]
    source_ids: dict[str, str | int]


@dataclass(frozen=True)
class Selection:
    split: TrainingSplit
    parts: sp.Split
    rows: tuple[Selected, ...]
    excluded: dict[str, int]
    read: int


def exclusion(a: Analysis, parts: sp.Split, teacher_model: str | None) -> str | None:
    """The first journal-level reason `a` stays out (TRAINING-SPIKE §7.4 in/out table), or None."""
    if a.terms_class != "trainable":
        return "not_trainable"
    if a.arm != ARM:
        return "main_arm"
    if not clean_route(a.provider_route):
        return "dirty_route"
    if a.model not in teacher.TEACHERS:
        return "not_a_pinned_teacher"
    if teacher_model is not None and a.model != teacher_model:
        return "other_teacher"
    if a.session in parts.test_sessions:
        return "test_split"
    if a.session not in parts.train_val_sessions:
        return "embargoed"
    return None


def reply_of(data_dir: Path, a: Analysis) -> tuple[str, str, dict] | str:
    """(system, prompt, reply) exactly as the teacher saw and wrote them, from the run file; or why not."""
    path = data_dir / "runs" / f"{a.run_id}.jsonl"
    if not path.exists():
        return "no_run_file"
    run = open_run(path)
    sample = next((s for s in run.samples if s.trace_id == a.sample_trace_id), None)
    item = run.items.get(sample.item_id) if sample is not None else None
    if item is None:
        return "no_run_file"
    if [t.role for t in sample.input] != ["system", "user"] or sample.input[1].content != item.prompt:
        return "not_table_prompt"  # a tool-loop prompt holds tool results, not the table the item is cut from
    kept, rejected = an.validate_claims(sample.output_parsed, item.expected["values"], a.analysis_id)
    if rejected or not kept:
        return "claims_invalid"
    return sample.input[0].content, item.prompt, sample.output_parsed


def stored_source(conn: sqlite3.Connection, source_id: str) -> SourceRef | None:
    row = conn.execute("SELECT body FROM source_ref WHERE source_id = ?", (source_id,)).fetchone()
    return None if row is None else SourceRef.model_validate_json(row[0])


def bars_start(ref: SourceRef) -> str | None:
    """The first session of the daily-bar frame a snapshot was computed from (`start=` in alpaca.bars_source's uri).
    `analyze.gather` reads every stored bar up to the session, so the frame starts at the journal's oldest bar."""
    start = parse_qs(urlsplit(ref.uri).query).get("start")
    return date.fromisoformat(start[0]).isoformat() if start else None


def source_ids_of(conn: sqlite3.Connection, data_dir: Path, a: Analysis, prompt: str) -> dict[str, str | int] | str:
    """§7.4 L725's source ids (the same in both forms), or why one cannot be found. A headline ships as its Alpaca
    news id, URL and content sha256; an EDGAR fact as its accession number; the bars as their id, frame start and
    feed (hydrate pulls the same frame)."""
    bars = stored_source(conn, a.snapshot.bars_source_id)
    start = None if bars is None else bars_start(bars)
    if bars is None or bars.feed is None or start is None:
        return "no_bars_source"
    ids: dict[str, str | int] = {"analysis_id": a.analysis_id, "input_hash": a.input_hash,
                                 "bars": a.snapshot.bars_source_id, "bars_start": start, "feed": bars.feed}
    stored: dict[str, news.Headline] | None = None
    for sid, name, *_ in table_rows(prompt):
        if name.startswith(an.HEADLINE_NAME):
            if stored is None:
                stored = {news.source_ref(h).source_id: h for h in news.headlines_for(data_dir, a.ticker, a.session)}
            if sid not in stored:
                return "headline_not_stored"
            h = stored[sid]
            ids |= {f"news:{sid}": h.article_id, f"news_url:{sid}": h.url, f"news_sha256:{sid}": h.content_sha256}
            continue
        ref = stored_source(conn, sid)
        if ref is not None and ref.kind == "edgar_fact":
            ids[f"edgar:{sid}"] = ref.uri.rpartition("accn=")[2]
    return ids


def teacher_theses(conn: sqlite3.Connection, analysis_id: str) -> list[Thesis]:
    rows = conn.execute("SELECT thesis_id FROM thesis WHERE analysis_id = ? AND arm = ? ORDER BY rowid",
                        (analysis_id, ARM))
    return [journal.get(conn, Thesis, thesis_id) for (thesis_id,) in rows]


def select_rows(conn: sqlite3.Connection, split: TrainingSplit, data_dir: Path,
                teacher_model: str | None = None) -> Selection:
    """Every journal analysis through the row filter; the first failing reason of each is counted. A kept row is a
    pinned teacher's first analysis of a ticker-day (bakeoff's rule) in the split's train/val sessions, with a
    claims_valid reply and every teacher thesis passing P2-P4 (an analysis with no thesis passes vacuously)."""
    parts = sp.derive(conn, split.split_id)
    kept: list[Selected] = []
    excluded: Counter[str] = Counter()
    seen: set[tuple[str, date, str]] = set()
    read = 0
    for (body,) in conn.execute("SELECT body FROM analysis ORDER BY created_at, rowid").fetchall():
        read += 1
        a = Analysis.model_validate_json(body)
        reason = exclusion(a, parts, teacher_model)
        if reason is None and (a.ticker, a.session, a.model) in seen:
            reason = "rerun"
        if reason is None:
            seen.add((a.ticker, a.session, a.model))
            reply = reply_of(data_dir, a)
            ids = source_ids_of(conn, data_dir, a, reply[1]) if not isinstance(reply, str) else reply
            theses = teacher_theses(conn, a.analysis_id)
            if isinstance(ids, str):
                reason = ids
            elif not all(bakeoff.passes(conn, t.thesis_id) for t in theses):
                reason = "checks_failed"
            else:
                kept.append(Selected(a, reply[0], reply[1], reply[2], tuple(theses), ids))
        if reason is not None:
            excluded[reason] += 1
    kept.sort(key=lambda r: (r.analysis.session, r.analysis.ticker, r.analysis.model))
    return Selection(split, parts, tuple(kept), dict(sorted(excluded.items())), read)


# ---------- items and files ----------

def item_id(a: Analysis) -> str:
    return f"{a.ticker}:{a.session}:{ARM}"


def private_item(row: Selected) -> DatasetItem:
    """§7.4 L725's mapping: the code-built context as the teacher saw it, its claims reply as the target."""
    a = row.analysis
    tags = sorted({f"horizon:{t.horizon}" for t in row.theses} | {f"setup:{t.setup_type}" for t in row.theses})
    return DatasetItem(id=item_id(a), cluster_id=a.session.isoformat(), expected=row.reply, prompt=row.prompt,
                       system=row.system, source_ids=row.source_ids, tags=tuple(tags), licence=LICENCE)


def val_sessions(rows: tuple[Selected, ...]) -> set[date]:
    """The latest tenth of the item sessions (clustered by session, later in time than train)."""
    days = sorted({r.analysis.session for r in rows})
    n = max(1, len(days) // VAL_SHARE) if len(days) >= 2 else 0
    return set(days[len(days) - n:])


def jsonl(items: list[DatasetItem]) -> list[bytes]:
    """One line per item, as gigai-core's items_sha256 hashes them (§7.4 L723)."""
    return [(item.model_dump_json(exclude_defaults=True) + "\n").encode() for item in items]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Release:
    out: Path
    form: str
    selection: Selection
    files: dict[str, list[DatasetItem]]  # file name -> items as written


def publish(conn: sqlite3.Connection, data_dir: Path, out: Path, name: str, form: str, *, split_id: str | None = None,
            teacher_model: str | None = None) -> Release:
    """Cut and write the release; refused with nothing written when the out directory is not empty, nothing passes
    the filter, two teachers share an item id, or (public) any item fails the price check."""
    if form not in FORMS:
        raise Refused(f"--form must be one of {', '.join(FORMS)}")
    if out.exists() and any(out.iterdir()):
        raise Refused(f"{out} is not empty; a release is never overwritten")
    split = sp.governing(conn, split_id)
    selection = select_rows(conn, split, data_dir, teacher_model)
    if not selection.rows:
        raise Refused(f"nothing to publish: 0 of {selection.read} analyses pass the row filter "
                      f"({reasons(selection.excluded)})")
    clash = Counter(item_id(r.analysis) for r in selection.rows)
    if doubled := sorted(i for i, n in clash.items() if n > 1):
        raise Refused(f"{', '.join(doubled)}: more than one teacher analysed it; pass --teacher (the bake-off winner)")
    val = val_sessions(selection.rows)
    private = {part: [private_item(r) for r in selection.rows if (r.analysis.session in val) == (part == "val")]
               for part in ("train", "val")}
    written = private
    if form == "public":
        prices = {item_id(r.analysis): price_rows(r.analysis.snapshot) for r in selection.rows}
        written, hits = {}, []
        for part, items in private.items():
            pairs = [public_item(item, prices[item.id]) for item in items]
            written[part] = [p for p, _ in pairs]
            hits += [f"{item.id}: {', '.join(h)}" for item, (_, h) in zip(items, pairs) if h]
        if hits:
            raise Refused("price check failed, nothing written; price-looking numbers or headline text left in:\n  "
                          + "\n  ".join(hits))
    files = {f"{name}.{part}.jsonl": items for part, items in written.items()}
    sheet = datasheet(name, form, selection, {f"{name}.{part}.jsonl": items for part, items in private.items()})
    out.mkdir(parents=True, exist_ok=True)
    assets = {fname: b"".join(jsonl(items)) for fname, items in files.items()}
    assets |= {"DATASHEET.md": sheet.encode(), "LICENSE": LICENCE_TEXT.encode()}
    for fname, data in assets.items():
        (out / fname).write_bytes(data)
    (out / "SHA256SUMS").write_text("".join(f"{sha256(data)}  {fname}\n" for fname, data in assets.items()))
    return Release(out, form, selection, files)


def reasons(excluded: dict[str, int]) -> str:
    return ", ".join(f"{reason} {n}" for reason, n in excluded.items()) or "none"


def datasheet(name: str, form: str, selection: Selection, private: dict[str, list[DatasetItem]]) -> str:
    """DATASHEET.md (§7.4 L724): what the set is, how it was cut, what it leaves out, and the private digests
    hydrate checks against."""
    split, parts = selection.split, selection.parts
    rows = {item_id(r.analysis): r for r in selection.rows}
    by_part = {fname.rsplit(".", 2)[1]: items for fname, items in private.items()}
    routes = sorted({(r.analysis.model, r.analysis.provider_route) for r in selection.rows})
    days = [r.analysis.session for r in selection.rows]
    lines = [
        f"# {name} ({form} form)", "",
        "Teacher analyses from tradingresearch as gigai-core `DatasetItem` lines (TRAINING-SPIKE §7.4). Each line is "
        "`item.model_dump_json(exclude_defaults=True)` plus a newline, so a file's sha256 is gigai-core "
        "`items_sha256` of its items. Not investment advice: research data about a model's reading of market data, "
        "not a recommendation to buy or sell anything.", "",
        "## Contents", "",
        f"- form: {form}" + (" (Alpaca-derived absolute prices are `{{px:<source_id>}}` and headlines are "
                             "`{{news:<source_id>}}`; `tr dataset hydrate` refills them from your own Alpaca data)"
                             if form == "public" else " (verbatim; personal use under Alpaca's terms, not for "
                                                     "redistribution)"),
        f"- licence: {LICENCE} (LICENSE); every item's `licence` field says so",
        f"- training split: `{split.split_id}`, cutoff {split.cutoff_session}, embargo {split.embargo_sessions} "
        f"sessions; train/val sessions are the split's train/val sessions, val is the latest tenth of the item "
        f"sessions (at least one once there are two)",
        f"- sessions: {min(days)} to {max(days)}; test-split sessions ({len(parts.test_sessions)} in the journal) and "
        f"embargoed sessions ({len(parts.embargoed_sessions)}) are never written",
        "- item: one teacher analysis of a ticker-day; `prompt` and `system` are the turns the teacher saw, `expected` "
        "is its claims reply; `id` = `ticker:session:teacher`, `cluster_id` = the session",
        "- teachers (model, pinned route): " + "; ".join(f"`{m}` via `{r}`" for m, r in routes),
        "- `source_ids`: `bars` (the daily-bar SourceRef id), `bars_start` (the first session of the frame the "
        "snapshot was computed from: `tr analyze` reads every stored bar up to the session, and the bars hash, EMA "
        "and ATR depend on that start; hydrate pulls from it), `feed`, and per headline and EDGAR fact the ids below",
        "- no Claude or closed OpenAI GPT output: every expected answer is a pinned open-weights teacher's", "",
        "## Row filter", "",
        f"Of {selection.read} journal analyses, an item is a pinned teacher's (`arm=\"teacher\"`, "
        "`terms_class=\"trainable\"`, a clean provider route) first analysis of a ticker-day in a train/val session, "
        "whose run file holds the table prompt, whose reply passes claims_valid (at least one claim, none rejected), "
        "and whose teacher theses all pass the P2-P4 code checks. Excluded (first failing reason):", "",
        *([f"- {reason}: {n}" for reason, n in selection.excluded.items()] or ["- none"]), "",
        "## Counts", "",
        "| split | teacher | items | theses by horizon |", "|---|---|---|---|",
    ]
    for part, items in by_part.items():
        for model in sorted({rows[i.id].analysis.model for i in items}):
            mine = [rows[i.id] for i in items if rows[i.id].analysis.model == model]
            horizons = Counter(t.horizon for r in mine for t in r.theses)
            lines.append(f"| {part} | `{model}` | {len(mine)} | "
                         + (", ".join(f"{h} {n}" for h, n in sorted(horizons.items())) or "none") + " |")
    lines += [
        "", "## Not included", "",
        "- raw bars, OHLC, VWAP, absolute prices and levels, volume (Alpaca Content); in the public form every such "
        "number is a placeholder keyed to its computed SourceRef id",
        "- Alpaca news headline, summary and content text; a headline ships as its Alpaca news id, URL and sha256 "
        "in `source_ids`",
        "- anything written by Claude or GPT: champion and challenger analyses and theses, judge verdicts",
        "- test-split items while held out; the losing teachers' bake-off items; the journal, traces, caches, keys",
        "", "## SEC", "",
        f"EDGAR XBRL facts ship verbatim with their accession number in `source_ids` (`edgar:<source_id>`). Source: "
        f"U.S. Securities and Exchange Commission, EDGAR company facts ({edgar.FACTS_URL.split('CIK')[0]}).",
        "", "## Private digests", "",
        "The verbatim (private) files; `tr dataset hydrate` must reproduce these bytes.", "",
    ]
    for fname, items in private.items():
        lines.append(f"- private `{fname}`: sha256 `{sha256(b''.join(jsonl(items)))}`, {len(items)} items")
    lines += ["", "### Private item digests", ""]
    lines += [f"- item `{item.id}`: sha256 `{sha256(line)}`"
              for items in private.values() for item, line in zip(items, jsonl(items))]
    return "\n".join(lines) + "\n"


def summary(release: Release) -> list[str]:
    s = release.selection
    counts = ", ".join(f"{fname} {len(items)}" for fname, items in release.files.items())
    return [f"wrote {release.form} release to {release.out}: {counts} items",
            f"split {s.split.split_id}; {len(s.rows)} of {s.read} analyses kept; excluded: {reasons(s.excluded)}"]


# ---------- hydrate ----------

@dataclass(frozen=True)
class AlpacaSource:
    """The reader's own Alpaca pull: the price rows and headlines a public release's placeholders point at."""

    http: httpx.Client
    data_dir: Path  # the minute-bar cache lives under it, as in `tr analyze`

    def snapshot(self, ticker: str, session: date, feed: str, start: date) -> tuple[SourceRef, IndicatorSnapshot]:
        """(bars SourceRef, snapshot), computed the way `analyze.gather` does from the frame the release names:
        gather reads every stored bar up to the session, so its frame starts at `bars_start`, not 300 sessions back."""
        conn = journal.connect(":memory:")
        frame = alpaca.daily_bars(self.http, [ticker, "SPY"], start, session, feed=feed, adjustment="split")
        for symbol in (ticker, "SPY"):  # SPY feeds only the regime label, which ships verbatim
            alpaca.store_daily(conn, frame[frame["ticker"] == symbol], feed=feed, adjustment="split")
        bars = alpaca.load_daily(conn, ticker, session, feed=feed)
        spy = alpaca.load_daily(conn, "SPY", session, feed=feed)
        if bars.empty or bars["session"].iloc[-1].date() != session:
            raise Refused(f"no {feed} daily bar for {ticker} on {session}")
        minutes = alpaca.minute_bars(self.http, self.data_dir / "bars_1m", ticker, session, feed=feed)
        source = alpaca.bars_source(bars, ticker=ticker, feed=feed, adjustment="split")
        return source, an.build_snapshot(ticker, bars, spy, minutes, source.source_id)

    def headlines(self, ticker: str, session: date) -> dict[str, str]:
        """Quoted headline text by news source id, as the SOURCES row shows it."""
        start, end = news.window(session)
        now = datetime.now(UTC)
        found = alpaca.news(self.http, [ticker], start.isoformat(), end.isoformat())
        return {r.source_id: r.label for r in (an.headline_row(news.normalise(a, now)) for a in found)}


def fill_value(value: object, fills: dict[tuple[str, str], tuple[str, object]]) -> object:
    """Placeholders back to text; a claim `value` that is one placeholder back to the number."""
    if isinstance(value, str):
        return PLACEHOLDER.sub(lambda m: fills[m.group(1), m.group(2)][0], value)
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            whole = PLACEHOLDER.fullmatch(item) if key == "value" and isinstance(item, str) else None
            out[key] = fills[whole.group(1), whole.group(2)][1] if whole else fill_value(item, fills)
        return out
    if isinstance(value, list):
        return [fill_value(item, fills) for item in value]
    return value


def coordinates(item: DatasetItem) -> tuple[str, date, str, str, date]:
    """(ticker, session, feed, bars id, bars start) of a public item; refused when the item lacks one."""
    try:
        ticker, day, _ = item.id.split(":")
        ids = item.source_ids
        return (ticker, date.fromisoformat(day), str(ids["feed"]), str(ids["bars"]),
                date.fromisoformat(str(ids["bars_start"])))
    except (KeyError, ValueError) as error:
        raise Refused(f"{item.id}: not an item of a public release ({type(error).__name__}: {error})") from None


def hydrate_item(item: DatasetItem, source: AlpacaSource) -> DatasetItem:
    """`item` with every placeholder refilled from the reader's data; refused when a source id does not reappear
    (the reader's bars or headlines differ, e.g. a split since the session)."""
    wanted = {(m.group(1), m.group(2)) for text in [item.prompt, item.system or "", *strings(item.expected)]
              for m in PLACEHOLDER.finditer(text)}
    if not wanted:
        return item
    ticker, session, feed, bars_id, start = coordinates(item)
    fills: dict[tuple[str, str], tuple[str, object]] = {}
    if any(kind == "px" for kind, _ in wanted):
        bars, snapshot = source.snapshot(ticker, session, feed, start)
        if bars.source_id != bars_id:
            raise Refused(f"{item.id}: your {feed} bars {start}..{session} hash to {bars.source_id}, the release "
                          f"used {bars_id} (different bars: a split or a correction since the session, or a gap in "
                          f"the publisher's stored bars)")
        fills |= {("px", sid): (an.plain(v), shown(v)) for sid, v in price_rows(snapshot).items()}
    if any(kind == "news" for kind, _ in wanted):
        fills |= {("news", sid): (label, label) for sid, label in source.headlines(ticker, session).items()}
    if missing := sorted(f"{{{{{k}:{s}}}}}" for k, s in wanted - fills.keys()):
        raise Refused(f"{item.id}: not reproduced from your Alpaca data: {', '.join(missing)}")
    return item.model_copy(update={"prompt": fill_value(item.prompt, fills),
                                   "system": None if item.system is None else fill_value(item.system, fills),
                                   "expected": fill_value(item.expected, fills)})


def read_sheet(path: Path) -> tuple[dict[str, tuple[str, int]], dict[str, str]]:
    """The private file digests and per-item line digests a DATASHEET.md carries."""
    text = path.read_text()
    files = {m.group(1): (m.group(2), int(m.group(3))) for m in SHEET_FILE.finditer(text)}
    if not files:
        raise Refused(f"{path} lists no private digests")
    return files, {m.group(1): m.group(2) for m in SHEET_ITEM.finditer(text)}


def hydrate(release: Path, out: Path, source: AlpacaSource) -> dict[str, int]:
    """Refill a public release into `out` and check each file against its private digest; refused with nothing
    written on the first mismatch, naming the first item whose bytes differ."""
    if out.exists() and any(out.iterdir()):
        raise Refused(f"{out} is not empty")
    files, per_item = read_sheet(release / "DATASHEET.md")
    data: dict[str, bytes] = {}
    for fname, (want, count) in files.items():
        try:
            items = [DatasetItem.model_validate_json(line)
                     for line in (release / fname).read_text().splitlines() if line]
        except ValueError as error:  # pydantic's ValidationError is a ValueError
            raise Refused(f"{fname}: not a DatasetItem line ({str(error).splitlines()[0]})") from None
        filled = [hydrate_item(item, source) for item in items]
        lines = jsonl(filled)
        got = sha256(b"".join(lines))
        if got != want or len(filled) != count:
            first = next((i.id for i, line in zip(filled, lines) if per_item.get(i.id) != sha256(line)), "none")
            raise Refused(f"{fname}: hydrated sha256 {got} ({len(filled)} items) is not the private {want} "
                          f"({count} items); first differing item: {first}")
        data[fname] = b"".join(lines)
    out.mkdir(parents=True, exist_ok=True)
    for fname, blob in data.items():
        (out / fname).write_bytes(blob)
    return {fname: count for fname, (_, count) in files.items()}
