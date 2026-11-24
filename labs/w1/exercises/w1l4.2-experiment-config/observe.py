"""Observe w1l4.2: what the runner would do with your config, without spending. Uses its own pre-flight (`load`).

uv run python labs/w1/exercises/w1l4.2-experiment-config/observe.py   (from the repo root)
"""

from pathlib import Path

from tradingresearch.experiment import load

cfg = load(Path("experiments/prompt-v2.toml"))
items = len(cfg.tickers) * len(cfg.sessions)
print(f"experiment {cfg.name}: {items} ticker-days x {len(cfg.arms)} arm(s), {len(cfg.tickers)} clusters")
print("arms:", ", ".join(f"{arm.name}={arm.prompt}" for arm in cfg.arms))
print("graders:", ", ".join(cfg.graders))
print(f"worst-case cap: ${cfg.max_usd_per_arm * len(cfg.arms):.2f} ({len(cfg.arms)} x ${cfg.max_usd_per_arm:.2f})")
