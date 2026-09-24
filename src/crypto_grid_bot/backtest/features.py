"""Point-in-time, price-only strategy inputs from completed hourly candles.

Hypothesis ``price-only-v1`` (pre-registered; see docs/BACKTEST_METHOD.md). A decision
during the minute starting at ``m`` may only use hourly candles whose close time is
before ``m``. Historical news is unavailable, so ``news_risk`` is 0 and every report
marks the news component as ABSENT; that is not evidence that no news risk existed.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from crypto_grid_bot.backtest.klines import Kline

FEATURE_VERSION = "price-only-v1"
HOUR_MS = 3_600_000
BASELINE_HOURS = 720  # 30-day medians for volatility and liquidity baselines
COVERAGE_HOURS = 168
STALE_AFTER_MS = 2 * HOUR_MS  # latest completed candle older than this is stale
MINIMUM_BREADTH_MARKETS = 5


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _at(values: Sequence[float | None], index: int) -> float:
    value = values[index]
    if value is None:
        raise ValueError("feature requested before its warm-up completed")
    return value


def _dec(values: Sequence[Decimal | None], index: int) -> Decimal:
    value = values[index]
    if value is None:
        raise ValueError("feature requested before its warm-up completed")
    return value


class SeriesFeatures:
    """Indicators on one symbol's available hourly candles; gaps are skipped, not filled.

    ``full=False`` computes only what breadth needs (close and SMA50).
    """

    def __init__(self, symbol: str, candles: Sequence[Kline], *, full: bool = True) -> None:
        if any(b.open_ms <= a.open_ms for a, b in zip(candles, candles[1:], strict=False)):
            raise ValueError(f"{symbol} hourly candles must be strictly increasing")
        n = len(candles)
        self.symbol = symbol
        self.opens = [c.open_ms for c in candles]
        self.close = [float(c.close) for c in candles]
        self.sma50: list[float | None] = [None] * n
        for i in range(49, n):
            self.sma50[i] = sum(self.close[i - 49 : i + 1]) / 50
        self.sma20: list[Decimal | None] = [None] * n
        self.atr14: list[Decimal | None] = [None] * n
        self.atr_pct: list[float | None] = [None] * n
        self.ret24: list[float | None] = [None] * n
        self.er20: list[float | None] = [None] * n
        self.qv24: list[float | None] = [None] * n
        self.adx14: list[float | None] = [None] * n
        self.dd168: list[float | None] = [None] * n
        self.atr_pct_median: list[float | None] = [None] * n
        self.qv24_median: list[float | None] = [None] * n
        if full:
            self._compute(candles)

    def _compute(self, candles: Sequence[Kline]) -> None:
        n, close = len(candles), self.close
        closes = [c.close for c in candles]
        volume = [float(c.quote_volume) for c in candles]
        true_range = [Decimal(0)] * n
        for i in range(1, n):
            c, previous = candles[i], closes[i - 1]
            true_range[i] = max(c.high - c.low, abs(c.high - previous), abs(c.low - previous))
        for i in range(n):
            if i >= 19:
                self.sma20[i] = sum(closes[i - 19 : i + 1], Decimal(0)) / 20
            if i >= 14:
                atr = sum(true_range[i - 13 : i + 1], Decimal(0)) / 14
                self.atr14[i] = atr
                self.atr_pct[i] = float(atr) / close[i]
            if i >= 24:
                self.ret24[i] = close[i] / close[i - 24] - 1
            if i >= 20:
                path = sum(abs(close[k] - close[k - 1]) for k in range(i - 19, i + 1))
                self.er20[i] = abs(close[i] - close[i - 20]) / path if path else 0.0
            if i >= 23:
                self.qv24[i] = sum(volume[i - 23 : i + 1])
            if i >= 167:
                peak, worst = close[i - 167], 0.0
                for price in close[i - 166 : i + 1]:
                    peak = max(peak, price)
                    worst = max(worst, (peak - price) / peak)
                self.dd168[i] = worst
        for i in range(BASELINE_HOURS - 1, n):
            window = self.atr_pct[i - BASELINE_HOURS + 1 : i + 1]
            if all(value is not None for value in window):
                self.atr_pct_median[i] = median(v for v in window if v is not None)
            volumes = self.qv24[i - BASELINE_HOURS + 1 : i + 1]
            if all(value is not None for value in volumes):
                self.qv24_median[i] = median(v for v in volumes if v is not None)
        self._wilder_adx(candles)

    def _wilder_adx(self, candles: Sequence[Kline]) -> None:
        n, period, close = len(candles), 14, self.close
        if n <= 2 * period:
            return
        high = [float(c.high) for c in candles]
        low = [float(c.low) for c in candles]
        tr, plus, minus = [0.0] * n, [0.0] * n, [0.0] * n
        for i in range(1, n):
            up, down = high[i] - high[i - 1], low[i - 1] - low[i]
            plus[i] = up if up > down and up > 0 else 0.0
            minus[i] = down if down > up and down > 0 else 0.0
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        s_tr, s_plus, s_minus = sum(tr[1:15]), sum(plus[1:15]), sum(minus[1:15])
        dx: list[float] = []
        adx: float | None = None
        for i in range(period, n):
            if i > period:
                s_tr += tr[i] - s_tr / period
                s_plus += plus[i] - s_plus / period
                s_minus += minus[i] - s_minus / period
            plus_di = 100 * s_plus / s_tr if s_tr else 0.0
            minus_di = 100 * s_minus / s_tr if s_tr else 0.0
            total = plus_di + minus_di
            dx.append(100 * abs(plus_di - minus_di) / total if total else 0.0)
            if len(dx) == period:
                adx = sum(dx) / period
            elif adx is not None:
                adx = (adx * (period - 1) + dx[-1]) / period
            if adx is not None:
                self.adx14[i] = min(100.0, max(0.0, adx))

    def last_completed(self, minute_ms: int) -> int | None:
        """Index of the latest candle that closed before ``minute_ms``, if any."""
        index = bisect_right(self.opens, minute_ms - HOUR_MS) - 1
        return index if index >= 0 else None

    def coverage(self, minute_ms: int) -> float:
        """Share of the previous 168 hours with a completed candle; 0 when stale."""
        index = self.last_completed(minute_ms)
        if index is None or minute_ms - (self.opens[index] + HOUR_MS) > STALE_AFTER_MS:
            return 0.0
        # The 168 whole hours before the current hour, whatever the minute within it.
        first_open = (minute_ms // HOUR_MS - COVERAGE_HOURS) * HOUR_MS
        present = index + 1 - bisect_right(self.opens, first_open - 1)
        return min(1.0, present / COVERAGE_HOURS)

    def ready(self, index: int) -> bool:
        return all(
            series[index] is not None
            for series in (
                self.sma20,
                self.sma50,
                self.atr14,
                self.ret24,
                self.er20,
                self.qv24,
                self.adx14,
                self.dd168,
                self.atr_pct_median,
                self.qv24_median,
            )
        )


@dataclass(frozen=True)
class Inputs:
    """Strategy inputs, constant between completed-hour boundaries."""

    hour_open_ms: int  # open time of the traded pair's latest completed candle
    trend: float
    breadth: float
    momentum: float
    volatility_health: float
    liquidity_health: float
    adx: float
    market_quality: float
    range_quality: float
    net_grid_edge: float
    liquidity_quality: float
    downside_quality: float
    pair_quality: float
    minute_quote_volume: float  # 24h quote volume / 1440; depth is sized in replay
    fair_value: Decimal
    atr: Decimal
    # Flat or zero-volume history: ratios are undefined, so new entries are vetoed
    # (quality 0) while existing inventory keeps being marked and risk-managed.
    degenerate: bool = False


class FeatureEngine:
    def __init__(
        self,
        pair: SeriesFeatures,
        market: SeriesFeatures,
        basket: Sequence[SeriesFeatures],
        *,
        range_atr_multiple: float,
        levels: int,
        minimum_cost_multiple: float,
        round_trip_cost: float,
    ) -> None:
        if levels < 2 or round_trip_cost <= 0:
            raise ValueError("invalid feature engine parameters")
        self.pair, self.market, self.basket = pair, market, tuple(basket)
        self._multiple = range_atr_multiple
        self._levels = levels
        self._edge_scale = 2 * minimum_cost_multiple - 1
        self._cost = round_trip_cost

    def at(self, minute_ms: int) -> Inputs | None:
        """Inputs for a decision in the minute starting at ``minute_ms``; None in warm-up."""
        pair, market = self.pair, self.market
        p, m = pair.last_completed(minute_ms), market.last_completed(minute_ms)
        if p is None or m is None or not pair.ready(p) or not market.ready(m):
            return None
        votes: list[bool] = []
        for series in self.basket:
            index = series.last_completed(minute_ms)
            if index is None or series.coverage(minute_ms) == 0.0:
                continue
            sma50 = series.sma50[index]
            if sma50 is not None:
                votes.append(series.close[index] > sma50)
        breadth_ok = len(votes) >= MINIMUM_BREADTH_MARKETS
        pair_quality = pair.coverage(minute_ms)
        market_quality = min(market.coverage(minute_ms), pair_quality) if breadth_ok else 0.0

        atr_median, volume_median = _at(market.atr_pct_median, m), _at(market.qv24_median, m)
        fair, atr = _dec(pair.sma20, p), _dec(pair.atr14, p)
        degenerate = atr_median <= 0 or volume_median <= 0 or atr <= 0
        # Undefined ratios are reported neutral; the zero quality below is the veto.
        atr_ratio = _at(market.atr_pct, m) / atr_median if atr_median > 0 else 1.0
        volume_ratio = _at(market.qv24, m) / volume_median if volume_median > 0 else 1.0
        if degenerate:
            market_quality = 0.0
        half = float(atr) * self._multiple
        lower, upper = float(fair) - half, float(fair) + half
        spacing = (upper / lower) ** (1 / (self._levels - 1)) - 1 if lower > 0 else 0.0
        pair_volume = _at(pair.qv24, p)
        return Inputs(
            hour_open_ms=pair.opens[p],
            trend=math.tanh((float(_dec(market.sma20, m)) / _at(market.sma50, m) - 1) / 0.02),
            breadth=2 * sum(votes) / len(votes) - 1 if breadth_ok else 0.0,
            momentum=math.tanh(_at(market.ret24, m) / 0.05),
            volatility_health=-math.tanh(max(0.0, atr_ratio - 1)),
            liquidity_health=-math.tanh(2 * max(0.0, 1 - volume_ratio)),
            adx=_at(market.adx14, m),
            market_quality=market_quality,
            range_quality=_clamp(1 - _at(pair.er20, p)),
            net_grid_edge=_clamp((spacing / self._cost - 1) / self._edge_scale),
            liquidity_quality=_clamp(math.log10(max(pair_volume, 1.0) / 1e5) / 2),
            downside_quality=_clamp(1 - _at(pair.dd168, p) / 0.20),
            pair_quality=pair_quality,
            minute_quote_volume=pair_volume / 1440,
            fair_value=fair,
            atr=atr,
            degenerate=degenerate,
        )
