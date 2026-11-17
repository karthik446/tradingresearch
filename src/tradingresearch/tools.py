"""The analyze tools (REPO-PLAN week 4 and §2.4 `mode = "tools"`): the Context rows an analysis already holds, served
on request instead of up front. Offline and deterministic. A bad call comes back as `{"error": ...}` text, never as an
exception, so the model reads what went wrong and can call again.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from gigai_core.providers import ToolSpec

from .analyze import FUNDAMENTALS, Context, Row, plain

METRICS = tuple(label for label, *_ in FUNDAMENTALS)
LEVEL_PREFIXES = ("level_", "dist_level_", "congestion_")
ROW_FORMAT = "each row is {source_id, name, value, unit}; the regime row has a label instead of a value"

TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_indicators",
        description=("Price and indicator rows for the ticker at the session close: close, moving averages "
                     "(sma_20/50/200, ema_9/21), rsi_14, atr_14 and atr_pct, rel_volume, the 20-session range "
                     "(high_20, low_20), gap_pct, nr7, vwap_session, distances in ATR (dist_*_atr), and regime_spy "
                     f"(the SPY market regime). Returns {{\"rows\": [...]}}; {ROW_FORMAT}. Cite a row by source_id."),
        parameters={
            "type": "object",
            "properties": {
                "names": {
                    "type": "array", "minItems": 1, "items": {"type": "string"},
                    "description": "Only these row names, e.g. [\"close\", \"rsi_14\"]. Omit for every row.",
                },
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_levels",
        description=("Support and resistance levels at the session close: high-volume nodes (level_hvn_N), pivot "
                     "highs and lows (level_pivot_high_N, level_pivot_low_N), numbered from the lowest price up, each "
                     "with its distance in ATR (dist_level_*_atr), and the congestion zone (congestion_low, "
                     "congestion_high, congestion_sessions, congestion_range_atr) when there is one. Returns "
                     f"{{\"rows\": [...]}}; {ROW_FORMAT}. Cite a row by source_id."),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        name="get_fundamentals",
        description=("SEC EDGAR facts filed on or before the session: quarterly revenue, net_income and eps_diluted "
                     "(last 4 quarters) and revenue_annual (last 2 years), one row per period named "
                     f"<metric>_<frame> (e.g. revenue_CY2026Q3). Returns {{\"rows\": [...]}}; {ROW_FORMAT}. "
                     "Cite a row by source_id."),
        parameters={
            "type": "object",
            "properties": {
                "metrics": {
                    "type": "array", "minItems": 1, "items": {"type": "string", "enum": list(METRICS)},
                    "description": "Only these metrics. Omit for every metric.",
                },
            },
            "additionalProperties": False,
        },
    ),
)
NAMES = tuple(spec.name for spec in TOOLS)


class ToolError(ValueError):
    """A call the model can fix: the message goes back to it as {"error": message}."""


def run_tool(ctx: Context, name: str, arguments: str) -> str:
    """One tool call on `ctx` as JSON text; every mistake in the call is an {"error": ...} result, never raised."""
    try:
        spec, handler = _lookup(name)
        rows = handler(ctx, _arguments(spec, arguments))
    except ToolError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"rows": [_shown(row) for row in rows]})


def _lookup(name: str) -> tuple[ToolSpec, Callable[[Context, dict], list[Row]]]:
    spec = next((s for s in TOOLS if s.name == name), None)
    if spec is None:
        raise ToolError(f"unknown tool {name!r}; the tools are {', '.join(NAMES)}")
    return spec, HANDLERS[name]


def _arguments(spec: ToolSpec, raw: str) -> dict:
    """The model's raw argument text checked against the tool's closed schema (every property is a string list)."""
    try:
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise ToolError(f"{spec.name}: arguments are not valid JSON ({exc.msg}); send a JSON object") from None
    if not isinstance(args, dict):
        raise ToolError(f"{spec.name}: arguments must be a JSON object, got {type(args).__name__}")
    properties = spec.parameters["properties"]
    unknown = sorted(set(args) - set(properties))
    if unknown:
        allowed = ", ".join(properties) or "none"
        raise ToolError(f"{spec.name}: unknown argument(s) {', '.join(unknown)}; allowed: {allowed}")
    for key, value in args.items():
        if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
            raise ToolError(f"{spec.name}: {key} must be a non-empty list of strings, got {json.dumps(value)}")
    return args


def _shown(row: Row) -> dict:
    """A row as the model sees it: the value rounded the way the fixed-context table shows it."""
    shown: dict = {"source_id": row.source_id, "name": row.name, "unit": row.unit}
    if row.label is not None:
        shown["label"] = row.label
    shown["value"] = None if row.value is None else float(plain(row.value))
    return shown


def _edgar_ids(ctx: Context) -> set[str]:
    return {s.source_id for s in ctx.sources if s.kind == "edgar_fact"}


def indicators(ctx: Context, args: dict) -> list[Row]:
    edgar = _edgar_ids(ctx)
    rows = [r for r in ctx.rows if r.source_id not in edgar and not r.name.startswith(LEVEL_PREFIXES)]
    wanted = args.get("names")
    if wanted is None:
        return rows
    missing = [w for w in wanted if w not in {r.name for r in rows}]
    if missing:
        raise ToolError(f"get_indicators: no row named {', '.join(missing)}; names: {', '.join(r.name for r in rows)}")
    return [r for r in rows if r.name in wanted]


def levels(ctx: Context, args: dict) -> list[Row]:
    edgar = _edgar_ids(ctx)
    return [r for r in ctx.rows if r.source_id not in edgar and r.name.startswith(LEVEL_PREFIXES)]


def fundamentals(ctx: Context, args: dict) -> list[Row]:
    wanted = args.get("metrics")
    bad = [m for m in wanted or [] if m not in METRICS]
    if bad:
        raise ToolError(f"get_fundamentals: unknown metric(s) {', '.join(bad)}; metrics: {', '.join(METRICS)}")
    edgar = _edgar_ids(ctx)
    rows = [r for r in ctx.rows if r.source_id in edgar]
    return [r for r in rows if wanted is None or r.name.rsplit("_", 1)[0] in wanted]


HANDLERS: dict[str, Callable[[Context, dict], list[Row]]] = {
    "get_indicators": indicators, "get_levels": levels, "get_fundamentals": fundamentals,
}
