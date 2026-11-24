"""`tr analyze`: code computes every number, the model writes tagged claims that cite them, code checks every claim."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import cache
from pathlib import Path

import pandas as pd
from gigai_core import CallBudget, CallSettings, Dataset, DatasetItem, run as run_eval, save_run
from gigai_core.graders.protocol import CannotGrade
from gigai_core.score import Score
from pydantic import ValidationError
from tokenizers import Tokenizer

from . import alpaca, indicators, sessions
from .edgar import Edgar, fact_source, latest_frames
from .hashing import digest, new_id
from .records import Analysis, Claim, IndicatorSnapshot, SourceRef

DEFAULT_PROMPT = "analyze-1"
PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"  # prompts/<version>.txt: you write these, not code
DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"
STUDENT_TOKENIZER = ("Qwen/Qwen3.5-4B", "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a")  # TRAINING-SPIKE §3 pin
REL_TOL = 0.005  # a cited number may differ from its source by 0.5% (rounding in prose)


def system_prompt(version: str) -> str:
    path = PROMPTS_DIR / f"{version}.txt"
    if not path.exists():
        raise SystemExit(f"no prompt {path}")
    return path.read_text().strip()


OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "tag", "text", "value", "unit", "source_ids", "derived_from", "steps"],
                "properties": {
                    "id": {"type": "string"},
                    "tag": {"type": "string", "enum": ["fact", "inference", "opinion"]},
                    "text": {"type": "string"},
                    "value": {"type": ["number", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                    "derived_from": {"type": "array", "items": {"type": "string"}},
                    "steps": {"type": ["string", "null"]},
                },
            },
        }
    },
}


@dataclass(frozen=True)
class Row:
    """One line of the SOURCES table: one number (or one label, for the regime) with its own SourceRef."""

    source_id: str
    name: str
    value: float | None
    unit: str | None
    label: str | None = None


@dataclass(frozen=True)
class Context:
    ticker: str
    session: date
    snapshot: IndicatorSnapshot
    sources: list[SourceRef]
    rows: list[Row]

    def values(self) -> dict[str, float | None]:
        return {row.source_id: row.value for row in self.rows}


@dataclass(frozen=True)
class Rejection:
    claim: str  # the model's local id, c1, c2, ...
    reason: str
    detail: str


# ---------- context ----------

def unit_of(name: str) -> str:
    if name.startswith("dist_") or name == "congestion_range_atr":
        return "ATR"
    if name.endswith("_pct"):
        return "%"
    if name in ("rsi_14",):
        return "index"
    if name in ("rel_volume",):
        return "x"
    if name in ("nr7",):
        return "flag"
    if name == "congestion_sessions":
        return "sessions"
    return "USD"


def computed_source(ticker: str, session: date, name: str, payload: object, bars_source_id: str) -> SourceRef:
    content = digest({"ticker": ticker, "session": session.isoformat(), "name": name, "value": payload,
                      "bars": bars_source_id, "code": indicators.CODE_VERSION})
    return SourceRef(
        source_id="src_" + content.removeprefix("sha256:")[:16], kind="computed",
        uri=f"tradingresearch:indicators.py#{name}?ticker={ticker}&session={session}",
        retrieved_at=datetime.now(UTC), content_sha256=content, feed=None,
        licence_note="computed by tradingresearch from licensed bars",
    )


def snapshot_rows(snapshot: IndicatorSnapshot) -> tuple[list[SourceRef], list[Row]]:
    named: list[tuple[str, float | None, str | None]] = [(k, v, None) for k, v in snapshot.values.items()]
    for kind in ("hvn", "pivot_high", "pivot_low"):  # high_20 and low_20 are already in values
        same = sorted((lv for lv in snapshot.levels if lv.kind == kind), key=lambda lv: lv.price)
        for i, level in enumerate(same, start=1):  # numbered from the lowest price up
            named.append((f"level_{kind}_{i}", level.price, None))
            named.append((f"dist_level_{kind}_{i}_atr", level.distance_atr, None))
    if snapshot.congestion is not None:
        cg = snapshot.congestion
        named += [("congestion_low", cg.low, None), ("congestion_high", cg.high, None),
                  ("congestion_sessions", float(cg.sessions), None), ("congestion_range_atr", cg.range_atr, None)]
    named.append(("regime_spy", None, snapshot.regime))
    sources, rows = [], []
    for name, value, label in named:
        src = computed_source(snapshot.ticker, snapshot.session, name, value if label is None else label,
                              snapshot.bars_source_id)
        sources.append(src)
        rows.append(Row(src.source_id, name, value, None if label else unit_of(name), label))
    return sources, rows


FUNDAMENTALS = (  # label, concept choices, unit, frame kind, how many
    ("revenue", ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"), "USD", "quarter", 4),
    ("net_income", ("NetIncomeLoss",), "USD", "quarter", 4),
    ("eps_diluted", ("EarningsPerShareDiluted",), "USD/shares", "quarter", 4),
    ("revenue_annual", ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"), "USD", "year", 2),
)


def edgar_rows(edgar: Edgar, ticker: str, session: date) -> tuple[list[SourceRef], list[Row]]:
    """Recent framed facts, filed on or before the session (no peeking at later filings)."""
    facts, cik = edgar.company_facts(ticker), edgar.cik(ticker)
    sources, rows = [], []
    for label, concepts, unit, kind, count in FUNDAMENTALS:
        best: list[dict] = []
        concept_used = ""
        for concept in concepts:
            try:
                found = [r for r in latest_frames(facts, concept, kind, 50, unit) if r["filed"] <= session.isoformat()]
            except KeyError:
                continue
            if found and (not best or found[-1]["end"] > best[-1]["end"]):
                best, concept_used = found, concept
        for row in best[-count:]:
            src = fact_source(ticker, cik, concept_used, row)
            sources.append(src)
            rows.append(Row(src.source_id, f"{label}_{row['frame']}", float(row["val"]), unit))
    return sources, rows


def build_snapshot(ticker: str, bars: pd.DataFrame, spy: pd.DataFrame, minutes: pd.DataFrame | None,
                   bars_source_id: str) -> IndicatorSnapshot:
    atr_now = float(indicators.atr(bars).iloc[-1])
    return IndicatorSnapshot(
        ticker=ticker, session=bars["session"].iloc[-1].date(),
        values=indicators.snapshot_values(bars, minutes), levels=tuple(indicators.levels(bars)),
        congestion=indicators.congestion(bars, atr_now), regime=indicators.regime(spy),
        bars_source_id=bars_source_id, code_version=indicators.CODE_VERSION,
    )


def plain(value: float) -> str:
    """Plain digits, no exponent, so the value the model copies is written the way the table shows it."""
    return f"{value:.0f}" if abs(value) >= 1e6 else f"{value:.6g}"


def render(ctx: Context) -> str:
    lines = [f"TICKER: {ctx.ticker}", f"SESSION: {ctx.session.isoformat()} (the last completed NYSE session)", "",
             "SOURCES (source_id | name | value | unit)"]
    for row in ctx.rows:
        shown = row.label if row.label is not None else plain(row.value)
        lines.append(f"{row.source_id} | {row.name} | {shown} | {row.unit or '-'}")
    lines += ["", "Write the claims as JSON with the key \"claims\"."]
    return "\n".join(lines)


@cache
def student_tokenizer() -> Tokenizer:
    return Tokenizer.from_pretrained(STUDENT_TOKENIZER[0], revision=STUDENT_TOKENIZER[1])


def context_tokens(system: str, prompt: str) -> int:
    """Counted with the student's tokenizer, because the fine-tuning lane trains on this exact text."""
    return len(student_tokenizer().encode(system + "\n" + prompt).ids)


def input_hash(ctx: Context, prompt_version: str) -> str:
    return digest({"snapshot": ctx.snapshot.model_dump(mode="json"),
                   "sources": sorted(s.content_sha256 for s in ctx.sources), "prompt_version": prompt_version})


# ---------- validation ----------

ALLOWED_DIGITS = re.compile(r"\{value\}|\b\d{4}-\d{2}-\d{2}\b|\b(?=\w*[A-Za-z_])\w+\b")


def close_to(a: float, b: float) -> bool:
    return abs(a - b) <= REL_TOL * max(abs(a), abs(b), 1e-12)


def validate_claims(raw: object, values: dict[str, float | None], analysis_id: str) -> tuple[list[Claim], list[Rejection]]:
    """Every claim either becomes a Claim or gets a Rejection with a reason. A claim derived from a rejected one is
    rejected too, so no inference stands on an unchecked number."""
    items = raw.get("claims") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return [], [Rejection("-", "not_json_claims", "output has no 'claims' list")]
    ids = {item.get("id"): new_id("cl") for item in items if isinstance(item, dict)}
    kept: dict[str, Claim] = {}
    rejected: list[Rejection] = []
    for item in items:
        local = str(item.get("id")) if isinstance(item, dict) else "?"
        problem = check_one(item, values, kept, ids)
        if problem:
            rejected.append(Rejection(local, *problem))
            continue
        try:
            kept[local] = Claim(
                claim_id=ids[local], analysis_id=analysis_id, text=item["text"], tag=item["tag"], value=item["value"],
                unit=item["unit"], source_ids=tuple(item["source_ids"]),
                derived_from=tuple(kept[d].claim_id for d in item["derived_from"]), steps=item["steps"],
            )
        except (ValidationError, KeyError, TypeError) as exc:
            rejected.append(Rejection(local, "not_a_claim", str(exc).splitlines()[0][:160]))
    return list(kept.values()), rejected


def check_one(item: object, values: dict[str, float | None], kept: dict[str, Claim],
              ids: dict[str, str]) -> tuple[str, str] | None:
    if not isinstance(item, dict):
        return "not_a_claim", "claim is not an object"
    text, tag, value = str(item.get("text", "")), item.get("tag"), item.get("value")
    # TODO(w1l1.2) number_in_text: reject a claim whose text has a digit that is not inside {value}, a YYYY-MM-DD
    #   date or a word such as sma_200. ALLOWED_DIGITS (above) matches exactly those three; remove its matches
    #   from `text`, then look for a digit in what is left. Detail: the first 120 characters of the text.
    # TODO(w1l1.3) placeholders: "{value}" is the only placeholder (anything else in braces is bad_placeholder,
    #   detail: the others, sorted, joined by ", "), and it needs a value (empty_placeholder,
    #   detail: "text has {value} but value is null").
    cited = list(item.get("source_ids") or [])
    # TODO(w1l1.1) unknown_source: every id in `cited` must be a key of `values` (the SOURCES table).
    #   Detail: the unknown ids, in citation order, joined by ", ".
    if tag == "opinion" and value is not None:
        return "number_in_opinion", f"value={value}"
    if tag == "fact" and value is not None:
        if not any(values[s] is not None and close_to(float(value), values[s]) for s in cited):
            got = ", ".join(f"{values[s]}" for s in cited)
            return "unsourced_number", f"value={value}, cited sources hold {got}"
    if tag == "inference":
        # TODO(w1l1.4) cascade: every id in derived_from must be a claim already in `kept`. If one is not, reject
        #   with bad_derivation: "derives from a rejected or later claim: c5" when every missing id is a claim
        #   of this reply (`ids`), else "unknown claim id: c99". Missing ids joined by ", ".
        if value is not None:
            parents = [kept[d].value for d in item["derived_from"]]
            if not any(p is not None and close_to(float(value), p) for p in parents):
                return "unsourced_number", f"inference value={value} matches no parent claim"
    return None


class ClaimsValid:
    """A gigai-core code grader: the share of the model's claims that pass validate_claims. Stored in the run file."""

    id = "claims_valid"
    version = "2"
    kind = "code"

    def grade(self, sample, expected) -> Score:
        if sample.parse_status != "ok":
            raise CannotGrade("output did not parse")
        kept, rejected = validate_claims(sample.output_parsed, expected["values"], "an_grade")
        total = len(kept) + len(rejected)
        reasons = sorted({r.reason for r in rejected})
        return Score(value=len(kept) / total if total else 0.0, explanation=", ".join(reasons) or None)


# ---------- the command ----------

@dataclass
class Result:
    analysis: Analysis
    rejected: list[Rejection]
    spent_usd: float
    run_path: str
    trace_path: str


def gather(conn, http, edgar: Edgar, ticker: str, session: date, cache_dir, feed: str) -> Context:
    start = sessions.recent(300, session)[0]  # 300 sessions: sma_200 plus SPY's 252-session volatility median
    frame = alpaca.daily_bars(http, [ticker, "SPY"], start, session, feed=feed, adjustment="split")
    for symbol in (ticker, "SPY"):
        alpaca.store_daily(conn, frame[frame["ticker"] == symbol], feed=feed, adjustment="split")
    bars = alpaca.load_daily(conn, ticker, session, feed=feed)
    spy = alpaca.load_daily(conn, "SPY", session, feed=feed)
    if bars.empty or bars["session"].iloc[-1].date() != session:
        raise SystemExit(f"no {feed} daily bar for {ticker} on {session}")
    minutes = alpaca.minute_bars(http, cache_dir / "bars_1m", ticker, session, feed=feed)
    bars_src = alpaca.bars_source(bars, ticker=ticker, feed=feed, adjustment="split")
    snapshot = build_snapshot(ticker, bars, spy, minutes, bars_src.source_id)
    s_sources, s_rows = snapshot_rows(snapshot)
    e_sources, e_rows = edgar_rows(edgar, ticker, session)
    return Context(ticker, session, snapshot, [bars_src, *s_sources, *e_sources], s_rows + e_rows)


def item_for(ctx: Context) -> DatasetItem:
    """One ticker-day as a gigai-core dataset item. Cluster = ticker: days of one stock are not independent."""
    return DatasetItem(id=f"{ctx.ticker}:{ctx.session}", cluster_id=ctx.ticker, prompt=render(ctx),
                       expected={"values": ctx.values()}, tags=(ctx.ticker,))


def call_settings(model: str) -> CallSettings:
    return CallSettings(model=model, max_output_tokens=4000, output_mode="schema", json_schema=OUTPUT_SCHEMA)


def store(conn, ctx: Context, sample, run_id: str, *, model: str, prompt_version: str, route: str
          ) -> tuple[Analysis, list[Rejection]]:
    """Validate one sample's claims and write the Analysis (valid claims only) with its sources to the journal."""
    analysis_id = new_id("an")
    claims, rejected = validate_claims(sample.output_parsed, ctx.values(), analysis_id)
    analysis = Analysis(
        analysis_id=analysis_id, ticker=ctx.ticker, session=ctx.session, created_at=datetime.now(UTC),
        run_id=run_id, snapshot=ctx.snapshot, claims=tuple(claims), input_hash=input_hash(ctx, prompt_version),
        prompt_version=prompt_version, model=model, sample_trace_id=sample.trace_id, provider_route=route,
        terms_class="restricted" if model.startswith("anthropic/") else "unknown",
        context_tokens=context_tokens(system_prompt(prompt_version), render(ctx)),
    )
    from . import journal  # local import keeps this module importable without a database
    journal.add_analysis(conn, analysis, ctx.sources)
    return analysis, rejected


def save(run, data_dir) -> Path:
    run_path = data_dir / "runs" / f"{run.record.run_id}.jsonl"
    run_path.parent.mkdir(parents=True, exist_ok=True)
    save_run(run, run_path, inputs_by_reference=False)  # the prompt lives in the run file, not in a dataset file
    return run_path


def analyze(conn, ctx: Context, provider, *, model: str, max_usd: float, prices: dict, data_dir,
            prompt_version: str = DEFAULT_PROMPT) -> Result:
    item = item_for(ctx)
    run = run_eval(Dataset.of("analyze", [item]), provider, [ClaimsValid()], settings=call_settings(model),
                   budget=CallBudget(max_usd=max_usd, prices=prices), system=system_prompt(prompt_version),
                   trace_dir=data_dir / "traces", tag=prompt_version)
    run_path = save(run, data_dir)
    sample = run.samples[0]
    if sample.outcome != "succeeded":
        raise SystemExit(f"model call failed: {sample.error.code if sample.error else '?'} (run {run_path})")
    analysis, rejected = store(conn, ctx, sample, run.record.run_id, model=model, prompt_version=prompt_version,
                               route=provider.route_for(item.prompt) if hasattr(provider, "route_for") else "unknown")
    return Result(analysis, rejected, run.record.spent_usd, str(run_path), str(run.record.trace_path))
