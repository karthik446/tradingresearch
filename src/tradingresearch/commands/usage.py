"""`tr usage`: the OpenRouter key's total spend so far (a free read)."""

from __future__ import annotations

from .. import openrouter
from ..config import require


def cmd_usage(args, cfg) -> None:
    print(f"openrouter key usage ${openrouter.key_usage(require(cfg.openrouter_key, 'OPENROUTER_API_KEY')):.6f}")


def register(sub) -> None:
    p = sub.add_parser("usage", help="the OpenRouter key's total spend so far (log it before and after paid runs)")
    p.set_defaults(func=cmd_usage)
