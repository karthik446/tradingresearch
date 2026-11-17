"""`tr slo`: the after-close loop's SLOs (PLAN-60 week 3, `slo_check.py`). Exit 1 on a breach. No model call."""

from __future__ import annotations

from .. import slo_check


def cmd_slo(args, cfg) -> None:
    code = slo_check.run(args, cfg)
    if code:
        raise SystemExit(code)


def register(sub) -> None:
    p = sub.add_parser("slo", help="check finish by 17:30 ET, zero missed sessions, fresh data; exit 1 on a breach")
    slo_check.add_arguments(p)
    p.set_defaults(func=cmd_slo)
