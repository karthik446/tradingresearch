"""Indicators, levels, congestion and regime (SPIKE §5) in plain pandas/numpy.

Input: daily bars oldest first with columns o, h, l, c, v (adjustment=split, feed=sip). The model never computes
any of these; it only cites them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .records import Congestion, Level

CODE_VERSION = "indicators-1"


def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n).mean()


def ema(close: pd.Series, n: int) -> pd.Series:
    """α = 2/(n+1), seeded with the SMA of the first n closes (so the first value is at index n-1)."""
    alpha = 2 / (n + 1)
    values = close.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) < n:
        return pd.Series(out, index=close.index)
    out[n - 1] = values[:n].mean()
    for i in range(n, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=close.index)


def wilder(x: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing: the first average is the plain mean of the first n valid values, then (prev·(n-1) + x)/n."""
    values = x.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    valid = np.flatnonzero(~np.isnan(values))
    if len(valid) < n:
        return pd.Series(out, index=x.index)
    first = valid[0]
    seed = first + n - 1
    out[seed] = values[first : seed + 1].mean()
    for i in range(seed + 1, len(values)):
        out[i] = (out[i - 1] * (n - 1) + values[i]) / n
    return pd.Series(out, index=x.index)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()  # NaN at index 0, so the first RSI is at index n
    avg_gain = wilder(delta.clip(lower=0), n)
    avg_loss = wilder((-delta).clip(lower=0), n)
    with np.errstate(divide="ignore"):
        out = 100 - 100 / (1 + avg_gain / avg_loss)
    return out.where(avg_loss != 0, 100.0).where(avg_gain.notna())


def true_range(bars: pd.DataFrame) -> pd.Series:
    prev_close = bars["c"].shift(1)  # NaN on the first bar: no TR without a previous close
    ranges = pd.concat([bars["h"] - bars["l"], (bars["h"] - prev_close).abs(), (bars["l"] - prev_close).abs()], axis=1)
    return ranges.max(axis=1, skipna=False)


def atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(bars), n)


def vwap_session(minutes: pd.DataFrame) -> float:
    """Σ(vw·v)/Σv over the regular-session 1-minute bars, using each bar's own vw."""
    return float((minutes["vw"] * minutes["v"]).sum() / minutes["v"].sum())


def snapshot_values(bars: pd.DataFrame, minutes: pd.DataFrame | None = None) -> dict[str, float]:
    """The §5.1 values at the last bar. A value whose window is not full yet is left out, never NaN."""
    c, h, l, v = bars["c"], bars["h"], bars["l"], bars["v"]
    a = atr(bars)
    out: dict[str, float] = {"close": float(c.iloc[-1])}
    for n in (20, 50, 200):
        out[f"sma_{n}"] = sma(c, n).iloc[-1]
    for n in (9, 21):
        out[f"ema_{n}"] = ema(c, n).iloc[-1]
    out["rsi_14"] = rsi(c).iloc[-1]
    out["atr_14"] = a.iloc[-1]
    out["atr_pct"] = a.iloc[-1] / c.iloc[-1] * 100
    if len(bars) > 20:
        out["rel_volume"] = v.iloc[-1] / v.iloc[-21:-1].median()
        out["high_20"] = h.iloc[-21:-1].max()  # the previous 20 sessions, today excluded
        out["low_20"] = l.iloc[-21:-1].min()
    if len(bars) > 1:
        out["gap_pct"] = (bars["o"].iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100
    if len(bars) >= 7:
        day_range = (h - l).iloc[-7:]
        out["nr7"] = 1.0 if day_range.iloc[-1] == day_range.min() else 0.0
    if minutes is not None and len(minutes):
        out["vwap_session"] = vwap_session(minutes)
    for name in ("sma_20", "sma_50", "sma_200", "high_20", "low_20"):
        if name in out:
            out[f"dist_{name}_atr"] = (out["close"] - out[name]) / out["atr_14"]
    return {key: float(value) for key, value in out.items() if pd.notna(value)}


def volume_profile(bars: pd.DataFrame, width: float) -> tuple[np.ndarray, np.ndarray]:
    """Bin centres and volumes: each day's volume spread evenly over its [low, high], weighted by bin overlap."""
    lo, hi = bars["l"].min(), bars["h"].max()
    edges = lo + width * np.arange(int(np.ceil((hi - lo) / width)) + 1)
    if edges[-1] < hi:
        edges = np.append(edges, edges[-1] + width)
    volume = np.zeros(len(edges) - 1)
    for day_low, day_high, day_volume in zip(bars["l"], bars["h"], bars["v"]):
        if day_high == day_low:  # a flat bar: all volume in the bin holding the price
            volume[min(np.searchsorted(edges, day_low, side="right") - 1, len(volume) - 1)] += day_volume
            continue
        overlap = np.clip(np.minimum(edges[1:], day_high) - np.maximum(edges[:-1], day_low), 0, None)
        volume += day_volume * overlap / (day_high - day_low)
    return (edges[:-1] + edges[1:]) / 2, volume


def hvn_levels(bars: pd.DataFrame, atr_now: float, close: float, lookback: int = 60) -> list[Level]:
    window = bars.iloc[-lookback:]
    centres, volume = volume_profile(window, 0.25 * atr_now)
    median = float(np.median(volume))
    padded = np.concatenate([[0.0], volume, [0.0]])
    is_peak = (volume > padded[:-2]) & (volume > padded[2:]) & (volume >= 1.5 * median)
    nodes = [(float(p), float(vol)) for p, vol in zip(centres[is_peak], volume[is_peak])]
    merged: list[list[tuple[float, float]]] = []
    for node in nodes:  # nodes are in price order, so a node merges into the group just before it
        if merged and node[0] - merged[-1][-1][0] <= 0.5 * atr_now:
            merged[-1].append(node)
        else:
            merged.append([node])
    levels = []
    for group in merged:
        total = sum(vol for _, vol in group)
        price = sum(p * vol for p, vol in group) / total
        levels.append(Level(price=price, kind="hvn", strength=total / median, distance_atr=(close - price) / atr_now))
    return nearest(levels, close, per_side=3)


def pivot_levels(bars: pd.DataFrame, atr_now: float, close: float, lookback: int = 60, side: int = 5) -> list[Level]:
    """Pivot highs above the close and pivot lows below it; the 2 nearest of each."""
    window = bars.iloc[-lookback:].reset_index(drop=True)
    highs, lows = [], []
    for i in range(side, len(window) - side):
        around = window.iloc[i - side : i + side + 1].drop(index=i)
        if window["h"][i] > around["h"].max():
            highs.append(float(window["h"][i]))
        if window["l"][i] < around["l"].min():
            lows.append(float(window["l"][i]))
    def level(price: float, kind: str) -> Level:
        return Level(price=price, kind=kind, strength=1.0, distance_atr=(close - price) / atr_now)
    above = sorted(p for p in highs if p > close)[:2]
    below = sorted((p for p in lows if p < close), reverse=True)[:2]
    return [level(p, "pivot_high") for p in above] + [level(p, "pivot_low") for p in below]


def nearest(levels: list[Level], close: float, per_side: int) -> list[Level]:
    above = sorted((x for x in levels if x.price > close), key=lambda x: x.price)[:per_side]
    below = sorted((x for x in levels if x.price <= close), key=lambda x: -x.price)[:per_side]
    return below[::-1] + above


def congestion(bars: pd.DataFrame, atr_now: float) -> Congestion | None:
    """The largest k in 5..30 whose last-k-session range is at most 1.5·ATR. The range only grows with k."""
    best = None
    for k in range(5, min(30, len(bars)) + 1):
        window = bars.iloc[-k:]
        low, high = float(window["l"].min()), float(window["h"].max())
        if high - low > 1.5 * atr_now:
            break
        best = Congestion(low=low, high=high, sessions=k, range_atr=(high - low) / atr_now)
    return best


def regime(spy: pd.DataFrame) -> str:
    """trend-volatility on SPY: bull/bear/mixed by close, sma_50 and sma_200; high if atr_pct > its 252 median."""
    c = spy["c"]
    close, s50, s200 = c.iloc[-1], sma(c, 50).iloc[-1], sma(c, 200).iloc[-1]
    if np.isnan(s200):
        raise ValueError("regime needs at least 200 SPY sessions")
    trend = "bull" if close > s200 and s50 > s200 else "bear" if close < s200 and s50 < s200 else "mixed"
    atr_pct = atr(spy) / c * 100
    trailing = atr_pct.iloc[-253:-1]  # the previous 252 sessions, today excluded
    if trailing.isna().any() or len(trailing) < 252:
        raise ValueError("regime needs 252 sessions of SPY atr_pct before today (about 267 bars)")
    volatility = "high" if atr_pct.iloc[-1] > trailing.median() else "normal"
    return f"{trend}-{volatility}"


def levels(bars: pd.DataFrame) -> list[Level]:
    """HVN, pivot and 20-session levels at the last bar."""
    close, atr_now = float(bars["c"].iloc[-1]), float(atr(bars).iloc[-1])
    out = hvn_levels(bars, atr_now, close) + pivot_levels(bars, atr_now, close)
    prior = bars.iloc[-21:-1]
    for price, kind in ((float(prior["h"].max()), "high_20"), (float(prior["l"].min()), "low_20")):
        out.append(Level(price=price, kind=kind, strength=1.0, distance_atr=(close - price) / atr_now))
    return out
