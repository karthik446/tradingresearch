"""Trading cost model in basis points of the entry price (SPIKE §6.6). No orders are placed; this only charges R."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Costs:
    """Per-side components; the defaults give 6.0 bps round trip, 8.0 when the exit is a stop or invalidation."""

    half_spread_bps: float = 2.5
    slippage_bps: float = 0.5
    stop_exit_extra_bps: float = 2.0
    commission_bps: float = 0.0  # per side; readers set their broker's

    def round_trip_bps(self, *, stop_exit: bool) -> float:
        side = self.half_spread_bps + self.slippage_bps + self.commission_bps
        return 2 * side + (self.stop_exit_extra_bps if stop_exit else 0.0)


def cost_r(cost_bps: float, entry: float, stop: float) -> float:
    """cost_bps × entry / 10,000 / |entry − stop| (SPIKE §6.6)."""
    return cost_bps * entry / 10_000 / abs(entry - stop)
