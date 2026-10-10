"""Precomputed causal price assessment; execution/funding context is separate.

Indicator arrays may include future bars, but every lookup selects only a completed
bar and its trailing prefix. Returned records contain no future series references.
"""

from bisect import bisect_left
from collections.abc import Sequence
from decimal import Decimal, localcontext
from statistics import median

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.models import Assessment
from crypto_grid_bot.market_data.parsing import symbol_name
from crypto_grid_bot.strategy.indicators import sma, wilder_atr, wilder_rsi
from crypto_grid_bot.strategy.perception import Perception, TrendState, four_hour_bars

HOUR = 3_600_000
FOUR_HOURS = 4 * HOUR
DAY = 24 * HOUR


def _validate(
    bars: Sequence[Kline], interval: int
) -> tuple[list[Kline], tuple[int, ...], int | None]:
    """Precompute the first time a timestamp integrity defect becomes visible.

    An inversion is visible only when both bars have closed. A suffix minimum
    finds all inversions (including across a still-future intervening bar) in O(n).
    Sort the usable unique bars once so future disorder cannot hide an earlier
    completed bar. Assessments at/after the first defect raise, never repair it.
    Noninteger/negative timestamps have no supported causal placement and fail here.
    """
    times = [bar.open_ms for bar in bars]
    if any(type(time) is not int or time < 0 for time in times):
        raise ValueError("nonnegative integer market timestamp required")
    errors = [time + interval for time in times if time % interval]
    suffix_min: int | None = None
    for time in reversed(times):
        if suffix_min is not None and time >= suffix_min:
            errors.append(time + interval)
        suffix_min = time if suffix_min is None else min(suffix_min, time)
    valid: list[Kline] = []
    invalid: list[int] = []
    seen: set[int] = set()
    for bar in bars:
        if bar.open_ms % interval or bar.open_ms in seen:
            continue
        seen.add(bar.open_ms)
        values = (
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.quote_volume,
            bar.taker_buy_base,
        )
        if any(
            not isinstance(value, Decimal)
            or not value.is_finite()
            or value < 0
            or value > Decimal("1e36")
            for value in values
        ) or (
            bar.low <= 0
            or bar.low > min(bar.open, bar.close)
            or bar.high < max(bar.open, bar.close)
            or bar.taker_buy_base > bar.volume
        ):
            invalid.append(bar.open_ms)
        else:
            valid.append(bar)
    return (
        sorted(valid, key=lambda bar: bar.open_ms),
        tuple(sorted(invalid)),
        min(errors, default=None),
    )


class _Gaps:
    def __init__(self, times: tuple[int, ...], step: int) -> None:
        self.times, self.step = times, step
        self.ranges = tuple(
            (a + step, b) for a, b in zip(times, times[1:], strict=False) if b - a > step
        )

    def at(self, completed_ms: int) -> tuple[tuple[int, int], ...]:
        end = completed_ms // self.step * self.step
        result = [(start, min(stop, end)) for start, stop in self.ranges if start < end]
        i = bisect_left(self.times, end)
        if i and self.times[i - 1] + self.step < end:
            tail = (self.times[i - 1] + self.step, end)
            if tail not in result:
                result.append(tail)
        return tuple(result)


class AssessmentSeries:
    """Build indicator arrays once; repeated decisions do not rerun all indicators."""

    def __init__(self, symbol: str, hourly: Sequence[Kline], daily: Sequence[Kline]) -> None:
        symbol_name(symbol)
        hourly, self._invalid_hours, hourly_error = _validate(hourly, HOUR)
        daily, self._invalid_days, daily_error = _validate(daily, DAY)
        self._timestamp_error = min(
            (time for time in (hourly_error, daily_error) if time is not None), default=None
        )
        self.symbol = symbol
        self._perception = Perception(hourly, daily)
        self._hour_times = frozenset(k.open_ms for k in hourly)
        self._day_times = frozenset(k.open_ms for k in daily)
        self._four = four_hour_bars(hourly)
        self._four_times = tuple(k.open_ms for k in self._four)
        self._hour_gaps = _Gaps(tuple(k.open_ms for k in hourly), HOUR)
        self._day_gaps = _Gaps(tuple(k.open_ms for k in daily), DAY)
        self._four_gaps = _Gaps(self._four_times, FOUR_HOURS)
        self._atr = wilder_atr(self._four)
        closes = [k.close for k in self._four]
        self._sma = sma(closes, 20)
        self._rsi = wilder_rsi(closes)

    def at(self, decision_ms: int, quote_ms: int) -> Assessment:
        if type(decision_ms) is not int or decision_ms < 0 or type(quote_ms) is not int:
            raise ValueError("integer nonnegative decision timestamp required")
        if self._timestamp_error is not None and decision_ms >= self._timestamp_error:
            raise ValueError("visible unaligned, duplicate or unordered market timestamp")
        snap = self._perception.at(decision_ms)
        due_hour = decision_ms // HOUR * HOUR - HOUR
        due_four = decision_ms // FOUR_HOURS * FOUR_HOURS - FOUR_HOURS
        due_day = decision_ms // DAY * DAY - DAY
        hourly_ok, daily_ok = due_hour in self._hour_times, due_day in self._day_times
        i = bisect_left(self._four_times, due_four)
        four_ok = i < len(self._four_times) and self._four_times[i] == due_four
        reasons: list[str] = []
        if due_hour in self._invalid_hours:
            reasons.append("invalid_hourly_bar")
        if due_day in self._invalid_days:
            reasons.append("invalid_daily_bar")
        for name, ready in (("hourly", hourly_ok), ("four_hour", four_ok), ("daily", daily_ok)):
            if not ready:
                reasons.append(f"missing_{name}_bar")
        if not 0 <= decision_ms - quote_ms <= HOUR:
            reasons.append("quote_unavailable")
        if snap.h4_state == TrendState.UNAVAILABLE or snap.d1_state == TrendState.UNAVAILABLE:
            reasons.append("trend_unavailable")
        close = atr = rsi = extension = ratio = high = low = high_dist = low_dist = None
        structure = "unavailable"
        if four_ok:
            close, atr, rsi = self._four[i].close, self._atr[i], self._rsi[i]
            reference = self._sma[i]
            history = self._atr[max(0, i - 120) : i]
            ready_atrs = [v for v in history if v is not None and v > 0]
            if len(ready_atrs) != 120 or atr is None or atr <= 0:
                reasons.append("volatility_warmup")
            if i >= 20:
                high = max(b.high for b in self._four[i - 20 : i])
                low = min(b.low for b in self._four[i - 20 : i])
            if atr is not None and atr > 0 and reference is not None:
                with localcontext() as ctx:
                    ctx.prec = 60
                    extension = abs(close - reference) / atr
                    if len(ready_atrs) == 120:
                        ratio = atr / median(ready_atrs)
                    if high is not None and low is not None:
                        high_dist, low_dist = (close - high) / atr, (close - low) / atr
                if ratio is not None and ratio >= 3:
                    structure = "stress"
                elif snap.h4_state == snap.d1_state == TrendState.RANGE:
                    structure = "range"
                elif snap.h4_state in (TrendState.UP, TrendState.DOWN):
                    # Structure is 4h-only; cross-timeframe admission is a separate gate,
                    # including the explicit daily-UNCLEAR short ablation.
                    up = snap.h4_state == TrendState.UP
                    beyond = (
                        high is not None
                        and low is not None
                        and (close > high if up else close < low)
                    )
                    if beyond:
                        structure = "breakout"
                    elif extension <= 1:
                        structure = "pullback"
                    elif close > reference if up else close < reference:
                        structure = "continuation"
                    else:
                        structure = "conflict"
                else:
                    structure = "conflict"
        else:
            reasons.append("volatility_warmup")
        return Assessment(
            symbol=self.symbol,
            decision_ms=decision_ms,
            quote_ms=quote_ms,
            available=not reasons,
            reasons=tuple(reasons),
            daily=snap.d1_state,
            four_hour=snap.h4_state,
            structure=structure,
            close=close,
            atr=atr,
            rsi=rsi,
            extension=extension,
            volatility_ratio=ratio,
            prior_high=high,
            prior_low=low,
            high_distance_atr=high_dist,
            low_distance_atr=low_dist,
            hourly_closed_ms=due_hour + HOUR if hourly_ok else None,
            four_hour_closed_ms=due_four + FOUR_HOURS if four_ok else None,
            daily_closed_ms=due_day + DAY if daily_ok else None,
            hourly_gaps=self._hour_gaps.at(decision_ms),
            four_hour_gaps=self._four_gaps.at(decision_ms),
            daily_gaps=self._day_gaps.at(decision_ms),
            invalid_hourly_open_ms=self._invalid_hours[
                : bisect_left(self._invalid_hours, due_hour + 1)
            ],
            invalid_daily_open_ms=self._invalid_days[
                : bisect_left(self._invalid_days, due_day + 1)
            ],
        )


def assess(
    symbol: str, decision_ms: int, hourly: Sequence[Kline], daily: Sequence[Kline], quote_ms: int
) -> Assessment:
    """Convenience one-shot API; a replay reuses AssessmentSeries instead."""
    return AssessmentSeries(symbol, hourly, daily).at(decision_ms, quote_ms)
