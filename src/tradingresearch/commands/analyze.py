"""`tr analyze`: one checked Analysis for a ticker-day (SPIKE §7, paid call)."""

from __future__ import annotations

from .. import analyze as an, openrouter
from ..config import require
from .common import context_for


def cmd_analyze(args, cfg) -> None:
    key = require(cfg.openrouter_key, "OPENROUTER_API_KEY")
    conn, ctx = context_for(args, cfg)
    provider = openrouter.OpenRouter(key)
    try:
        result = an.analyze(conn, ctx, provider, model=args.model, max_usd=args.max_usd,
                            prices=openrouter.prices([args.model]), data_dir=cfg.data_dir, prompt_version=args.prompt)
    finally:
        provider.close()
    a = result.analysis
    print(f"analysis {a.analysis_id}  {a.ticker} {a.session}  prompt={a.prompt_version}  model={a.model}  "
          f"route={a.provider_route}")
    print(f"context_tokens={a.context_tokens}  input_hash={a.input_hash[:19]}…  spent=${result.spent_usd:.4f}")
    print(f"run={result.run_path}")
    for c in a.claims:
        shown = c.text.replace("{value}", an.plain(c.value)) if c.value is not None else c.text
        refs = ",".join(c.source_ids or c.derived_from)
        print(f"  [{c.tag:<9}] {shown}  <- {refs}")
    print(f"valid {len(a.claims)}, rejected {len(result.rejected)}")
    for r in result.rejected:
        print(f"  REJECTED {r.claim}: {r.reason}: {r.detail}")


def register(sub) -> None:
    p = sub.add_parser("analyze", help="write a checked Analysis for one ticker-day (paid call)")
    p.add_argument("ticker")
    p.add_argument("--session")
    p.add_argument("--prompt", default=an.DEFAULT_PROMPT, help="prompt version: prompts/<version>.txt")
    p.add_argument("--model", default=an.DEFAULT_MODEL)
    p.add_argument("--max-usd", type=float, default=0.25)
    p.set_defaults(func=cmd_analyze)
