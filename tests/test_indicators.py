"""Golden values computed by hand (the arithmetic is in each comment), not copied from the code's output."""

import numpy as np
import pandas as pd
import pytest

from tradingresearch import indicators as ind


def bars(h, l, c=None, o=None, v=None):
    h, l = list(map(float, h)), list(map(float, l))
    c = c if c is not None else [(a + b) / 2 for a, b in zip(h, l)]
    return pd.DataFrame({"o": o or c, "h": h, "l": l, "c": list(map(float, c)), "v": v or [100] * len(h)})


def test_sma_and_ema_seeded_with_sma():
    close = pd.Series([1.0, 2, 3, 4, 5])
    assert ind.sma(close, 3).iloc[-1] == 4.0  # (3+4+5)/3
    # seed at index 2 = (1+2+3)/3 = 2; α = 2/(3+1) = 0.5; 0.5·4 + 0.5·2 = 3; 0.5·5 + 0.5·3 = 4
    assert ind.ema(close, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    assert np.isnan(ind.ema(close, 3).iloc[1])


def test_wilder_skips_leading_nan():
    # seed at index 3 = (3+6+9)/3 = 6; then (6·2 + 0)/3 = 4
    assert ind.wilder(pd.Series([np.nan, 3.0, 6, 9, 0]), 3).tolist()[3:] == [6.0, 4.0]


def test_rsi_wilder():
    # Δ = [., 1, 1, -1, 2]; gains [., 1, 1, 0, 2]; losses [., 0, 0, 1, 0]
    # index 3: avg_gain 2/3, avg_loss 1/3, RS 2, RSI 100 - 100/3 = 66.667
    # index 4: avg_gain (2/3·2 + 2)/3 = 10/9, avg_loss (1/3·2 + 0)/3 = 2/9, RS 5, RSI 100 - 100/6 = 83.333
    out = ind.rsi(pd.Series([10.0, 11, 12, 11, 13]), 3)
    assert out.iloc[3] == pytest.approx(200 / 3)
    assert out.iloc[4] == pytest.approx(500 / 6)


def test_rsi_is_100_without_losses():
    assert ind.rsi(pd.Series([1.0, 2, 3, 4, 5]), 3).iloc[-1] == 100.0


def test_atr_wilder():
    # TR: [., max(2,2,0)=2, max(1,2,1)=2, max(1,0.5,1.5)=1.5, max(2,3.5,1.5)=3.5]
    # seed at index 3 = (2+2+1.5)/3 = 11/6; then (11/6·2 + 3.5)/3 = 43/18
    b = bars(h=[10, 11, 12, 11, 14], l=[8, 9, 11, 10, 12], c=[9, 10, 11.5, 10.5, 13])
    out = ind.atr(b, 3)
    assert out.iloc[3] == pytest.approx(11 / 6)
    assert out.iloc[4] == pytest.approx(43 / 18)


def test_vwap_session_uses_each_bar_vw():
    minutes = pd.DataFrame({"vw": [10.0, 11, 12], "v": [100, 200, 100]})
    assert ind.vwap_session(minutes) == 11.0  # (1000 + 2200 + 1200) / 400


def test_snapshot_values_window_rules():
    h = [12.0] * 20 + [11.0, 11.0]
    h[5] = 15.0  # the 20-session high, inside the window
    l = [9.0] * 22
    c = [10.0] * 22
    o = [10.0] * 21 + [10.5]  # opens 5% above the previous close
    v = [100] * 21 + [250]
    b = bars(h=h, l=l, c=c, o=o, v=v)
    b.loc[21, "h"] = 10.6  # today's range 1.6: the narrowest of the last 7
    values = ind.snapshot_values(b)
    assert values["rel_volume"] == 2.5  # 250 / median(100 × 20)
    assert values["high_20"] == 15.0  # bars 1..20; bar 5 has 15
    assert values["low_20"] == 9.0
    assert values["gap_pct"] == pytest.approx(5.0)  # (10.5 - 10)/10·100
    assert values["nr7"] == 1.0
    assert "sma_200" not in values  # 22 bars: the window is not full, so the key is absent


def test_volume_profile_spreads_by_overlap():
    # [10,12] v=200 puts 100 in each of two bins; [11,12] v=300 puts 300 in the upper bin
    centres, volume = ind.volume_profile(bars(h=[12, 12], l=[10, 11], v=[200, 300]), width=1.0)
    assert centres.tolist() == [10.5, 11.5]
    assert volume.tolist() == [100.0, 400.0]


def test_hvn_nodes_merge_at_volume_weighted_mean():
    # ATR 4 → bin width 1 over [10, 20]: 10 bins. Three days [10,20] v=1000 → 300 per bin.
    # [14,15] v=900 → bin 14.5 = 1200. [16,17] v=600 → bin 16.5 = 900. Median bin = 300.
    # Peaks 14.5 and 16.5 are 2.0 apart ≤ 0.5·ATR = 2 → one level at (14.5·1200 + 16.5·900)/2100 = 15.357,
    # strength 2100/300 = 7.0; distance from close 18 = (18 - 15.357)/4 = 0.661
    b = bars(h=[20, 20, 20, 15, 17], l=[10, 10, 10, 14, 16], v=[1000, 1000, 1000, 900, 600])
    [level] = ind.hvn_levels(b, atr_now=4.0, close=18.0)
    assert level.kind == "hvn"
    assert level.price == pytest.approx(32250 / 2100)
    assert level.strength == pytest.approx(7.0)
    assert level.distance_atr == pytest.approx((18 - 32250 / 2100) / 4)


def test_pivot_high_needs_five_lower_bars_each_side():
    h = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10]
    b = bars(h=h, l=[x - 1 for x in h])
    [level] = ind.pivot_levels(b, atr_now=2.0, close=15.0)
    assert (level.kind, level.price, level.distance_atr) == ("pivot_high", 20.0, -2.5)


def test_congestion_takes_the_largest_k():
    # the last 6 bars sit in [9, 11] (range 2 ≤ 1.5·ATR = 3); the 7th back reaches 15
    b = bars(h=[15] + [11] * 6, l=[9] * 7)
    got = ind.congestion(b, atr_now=2.0)
    assert (got.low, got.high, got.sessions, got.range_atr) == (9.0, 11.0, 6, 1.0)


def test_no_congestion_when_five_bars_are_too_wide():
    assert ind.congestion(bars(h=[15, 11, 11, 11, 11], l=[9] * 5), atr_now=2.0) is None


def test_regime_trend_and_volatility():
    # A steady rise with a constant 1.0 range: close > sma50 > sma200 (bull), and atr_pct falls as price rises,
    # so today's is below its trailing median (normal). The mirror: bear, and atr_pct rises (high).
    up = np.linspace(100, 160, 300)
    assert ind.regime(bars(h=up + 0.5, l=up - 0.5, c=up)) == "bull-normal"
    down = up[::-1]
    assert ind.regime(bars(h=down + 0.5, l=down - 0.5, c=down)) == "bear-high"


@pytest.mark.oracle
def test_matches_talib_after_seeding():
    talib = pytest.importorskip("talib")
    rng = np.random.default_rng(7)
    c = 100 + rng.standard_normal(300).cumsum()
    b = bars(h=c + rng.uniform(0.1, 2, 300), l=c - rng.uniform(0.1, 2, 300), c=c)
    np.testing.assert_allclose(ind.rsi(b["c"]).iloc[14:], talib.RSI(c, 14)[14:])
    np.testing.assert_allclose(ind.atr(b).iloc[14:], talib.ATR(b["h"].values, b["l"].values, c, 14)[14:])
    np.testing.assert_allclose(ind.ema(b["c"], 21).iloc[20:], talib.EMA(c, 21)[20:])
