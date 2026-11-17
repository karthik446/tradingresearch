"""Write the 12 `numeric` rows of evals/retrieval_query.jsonl from the SEC's XBRL company facts. No model, no network.

Each row asks for one reported quarterly number (revenue, net income, diluted EPS, operating income, gross profit,
or cash at quarter end) from a 10-Q in the retrieval index. The number comes from the cached companyfacts JSON (the
fact whose `accn` is that 10-Q's accession); the gold quote is the start of the table row that prints it, cut after
the first value cell, e.g. `Net Income Attributable to Shareowners of The Coca-Cola Company | $4,009`. Up to 3 golds:
the 10-Q first, then the ticker's other documents visible at `as_of` that print the same row (the earnings release).
`as_of` is the first NYSE session whose cutoff comes after the 10-Q was accepted.

Deterministic: the same index and companyfacts give the same 12 rows. The hand-written `lookup` and `event` rows
already in the file are kept; the numeric rows are replaced and numbered after them.

    TR_DATA_DIR=$PWD/data-dev uv run python evals/make_numeric_queries.py [--index <digest>]
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from tradingresearch import sessions
from tradingresearch.config import settings
from tradingresearch.retrieval import evaluate, manifest

QUERIES = Path(__file__).parent / "retrieval_query.jsonl"
COUNT = 12
MAX_PER_TICKER = 2

NAMES = {"AAPL": "Apple", "AMZN": "Amazon", "CAT": "Caterpillar", "HD": "Home Depot", "JPM": "JPMorgan Chase",
         "KO": "Coca-Cola", "MSFT": "Microsoft", "NVDA": "NVIDIA", "UNH": "UnitedHealth", "XOM": "Exxon Mobil"}

# (name, XBRL concepts tried in order, unit, row-label words, question template); `{end}` is the quarter end
CONCEPTS = (
    ("revenue", ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"), "USD",
     ("revenue", "net sales"), "What was {name}'s total revenue for the quarter ended {end}?"),
    ("net_income", ("NetIncomeLoss",), "USD", ("net income", "net earnings"),
     "What net income did {name} report for the quarter ended {end}?"),
    ("eps_diluted", ("EarningsPerShareDiluted",), "USD/shares", ("diluted",),
     "What were {name}'s diluted earnings per share for the quarter ended {end}?"),
    ("operating_income", ("OperatingIncomeLoss",), "USD", ("operating income", "income from operations"),
     "What was {name}'s operating income for the quarter ended {end}?"),
    ("gross_profit", ("GrossProfit",), "USD", ("gross profit", "gross margin"),
     "What gross profit did {name} report for the quarter ended {end}?"),
    ("cash", ("CashAndCashEquivalentsAtCarryingValue",), "USD", ("cash and cash equivalents",),
     "How much cash and cash equivalents did {name} hold at {end}?"),
)


def quarter_fact(facts: dict, concepts: tuple[str, ...], unit: str, accession: str) -> dict | None:
    """The fact the 10-Q reports for its own quarter: the three-month duration (or, for a balance, the instant)
    ending on the latest date that filing reports."""
    for concept in concepts:
        rows = facts["facts"].get("us-gaap", {}).get(concept, {}).get("units", {}).get(unit, [])
        rows = [r for r in rows if r["accn"] == accession and r["form"] == "10-Q"]
        if not rows:
            continue
        end = max(r["end"] for r in rows)
        for r in rows:
            if r["end"] != end:
                continue
            if "start" not in r:
                return r | {"concept": concept}
            days = (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days
            if 80 <= days <= 100:
                return r | {"concept": concept}
    return None


def rendered(value: float, unit: str) -> str | None:
    """The number as a filing's table prints it: USD in millions with separators, per-share to 2 decimals."""
    if unit == "USD/shares":
        return f"{value:.2f}"
    if value % 1_000_000:
        return None  # not a whole number of millions, so no table prints it this way
    return f"{abs(value) / 1_000_000:,.0f}"


def row_quote(text: str, number: str, words: tuple[str, ...]) -> str | None:
    """`<label> | <first value cell>` of the first table row whose label has one of `words` and whose first value
    cell is `number` (with or without `$` and parentheses)."""
    for line in text.splitlines():
        cells = line.split(" | ")
        if len(cells) < 2 or not any(w in cells[0].lower() for w in words):
            continue
        if cells[1].strip("$() ") == number and len(f"{cells[0]} | {cells[1]}".split()) <= 25:
            return f"{cells[0]} | {cells[1]}"
    return None


def first_session_after(moment) -> date:
    day = moment.date()
    while not (sessions.is_session(day) and evaluate.cutoff(day) >= moment):
        day += timedelta(days=1)
    return day


def candidates(index: manifest.Index, edgar: Path) -> list[dict]:
    """Every (10-Q, concept) whose quarterly fact is printed in a table row of the index."""
    ciks = {row["ticker"]: int(row["cik_str"])
            for row in json.loads((edgar / "company_tickers.json").read_text()).values()}
    by_doc: dict[str, list[manifest.Record]] = {}
    for record in index.records:
        by_doc.setdefault(record.doc_id, []).append(record)
    tenqs = sorted(d for d, records in by_doc.items() if records[0].kind == "10-Q")
    found = []
    for doc in tenqs:
        ticker, available = index.docs[doc]
        facts = json.loads((edgar / "companyfacts" / f"CIK{ciks[ticker]:010d}.json").read_text())
        as_of = first_session_after(available)
        end = evaluate.cutoff(as_of)
        others = sorted(d for d, (t, at) in index.docs.items() if t == ticker and at <= end and d != doc)
        for name, concepts, unit, words, template in CONCEPTS:
            fact = quarter_fact(facts, concepts, unit, doc.split("/")[0])
            number = rendered(fact["val"], unit) if fact else None
            if number is None:
                continue
            golds = []
            for gold_doc in [doc, *others]:
                quote = next((q for r in by_doc[gold_doc] if (q := row_quote(r.text, number, words))), None)
                if quote and len(golds) < evaluate.MAX_GOLDS:
                    golds.append({"doc": gold_doc, "quote": quote})
            if not golds or golds[0]["doc"] != doc:
                continue
            quarter_end = date.fromisoformat(fact["end"])
            answer = f"${number}" if unit == "USD/shares" else f"${number} million"
            found.append({"ticker": ticker, "as_of": as_of.isoformat(), "kind": "numeric",
                          "text": template.format(name=NAMES[ticker], end=f"{quarter_end:%B} {quarter_end.day}, "
                                                                          f"{quarter_end.year}"),
                          "gold": golds, "answer": answer,
                          "notes": f"generated: {fact['concept']} {fact['val']} ({unit}), accn {fact['accn']}",
                          "concept": name})
    return found


def pick(found: list[dict]) -> list[dict]:
    """COUNT rows, one concept at a time in CONCEPTS order, each from the ticker with the fewest rows so far (newest
    10-Q first), at most MAX_PER_TICKER per ticker and never the same ticker and concept twice."""
    chosen: list[dict] = []
    per_ticker: dict[str, int] = {}
    while len(chosen) < COUNT:
        before = len(chosen)
        for name, *_ in CONCEPTS:
            taken = {(c["ticker"], c["concept"]) for c in chosen}
            options = [c for c in found if c["concept"] == name and (c["ticker"], name) not in taken
                       and per_ticker.get(c["ticker"], 0) < MAX_PER_TICKER]
            if not options or len(chosen) == COUNT:
                continue
            best = min(options, key=lambda c: (per_ticker.get(c["ticker"], 0), c["ticker"],
                                               -date.fromisoformat(c["as_of"]).toordinal()))
            chosen.append(best)
            per_ticker[best["ticker"]] = per_ticker.get(best["ticker"], 0) + 1
        if len(chosen) == before:
            raise SystemExit(f"only {len(chosen)} numeric rows can be generated, {COUNT} wanted")
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", help="index digest or prefix (default: the newest)")
    args = parser.parse_args()
    data = settings().data_dir
    index = manifest.load(data / "retrieval", args.index)
    rows = pick(candidates(index, data / "edgar"))
    kept = [row for row in evaluate.read(QUERIES) if row["kind"] != "numeric"] if QUERIES.exists() else []
    numeric = [{"id": f"q{len(kept) + n:02d}", **{k: v for k, v in row.items() if k != "concept"}}
               for n, row in enumerate(sorted(rows, key=lambda r: (r["ticker"], r["as_of"], r["text"])), start=1)]
    QUERIES.write_text("".join(json.dumps(row) + "\n" for row in kept + numeric))
    print(f"{len(numeric)} numeric rows from index {index.digest}, {len(kept)} other rows kept -> {QUERIES}")


if __name__ == "__main__":
    main()
