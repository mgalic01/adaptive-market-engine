"""Continuous per-coin daily signals for the frozen V3 experiment."""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.window import development_month

DAY_MS = 86_400_000
ZERO = Decimal(0)
ONE = Decimal(1)
RULES = tuple(f"R{i}" for i in range(1, 7)) + tuple(f"R{i}L" for i in range(1, 7))


def _sign(value: Decimal) -> Decimal:
    return ONE if value > 0 else (-ONE if value < 0 else ZERO)


@dataclass(frozen=True, slots=True)
class SignalPoint:
    day_ms: int
    directional: tuple[Decimal, ...]
    sma50: Decimal | None
    ema21: Decimal | None
    ema55: Decimal | None
    atr10: Decimal | None
    upper: Decimal | None
    lower: Decimal | None

    def rule(self, name: str) -> Decimal:
        if name not in RULES:
            raise ValueError("unknown frozen V3 rule")
        value = self.directional[int(name[1]) - 1]
        return max(ZERO, value) if name.endswith("L") else value


class SignalState:
    """One continuous series; missing dates add no update and reset no state."""

    def __init__(self) -> None:
        self._bars: list[Kline] = []
        self._emas: dict[int, Decimal] = {}
        self._donchian = ZERO
        self._true_ranges: list[Decimal] = []
        self._atr: Decimal | None = None
        self._upper: Decimal | None = None
        self._lower: Decimal | None = None
        self._trend = ZERO

    def update(self, bar: Kline) -> SignalPoint:
        if type(bar.open_ms) is not int or bar.open_ms < 0 or bar.open_ms % DAY_MS:
            raise ValueError("daily bar must be UTC midnight")
        development_month(datetime.fromtimestamp(bar.open_ms // 1000, UTC).strftime("%Y-%m"))
        if self._bars and bar.open_ms <= self._bars[-1].open_ms:
            raise ValueError("daily bars must be strictly ordered")
        prices = (bar.open, bar.high, bar.low, bar.close)
        for value in prices:
            exponent = value.as_tuple().exponent
            if (
                not value.is_finite()
                or not isinstance(exponent, int)
                or not -18 <= exponent <= 18
                or not ZERO < value <= Decimal("1e18")
            ):
                raise ValueError("daily prices must satisfy the archive parser's numeric bounds")
        if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
            raise ValueError("invalid daily OHLC bounds")
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            closes = [row.close for row in self._bars] + [bar.close]
            count = len(closes)
            sma = sum(closes[-50:], ZERO) / Decimal(50) if count >= 50 else None
            for period in (21, 55):
                if count == period:
                    self._emas[period] = sum(closes, ZERO) / Decimal(period)
                elif count > period:
                    alpha = Decimal(2) / Decimal(period + 1)
                    self._emas[period] = alpha * bar.close + (ONE - alpha) * self._emas[period]
            r1 = _sign(bar.close - sma) if sma is not None else ZERO
            r2 = _sign(self._emas[21] - self._emas[55]) if count >= 55 else ZERO
            if count >= 56:
                prior55, prior20 = self._bars[-55:], self._bars[-20:]
                if bar.close > max(row.high for row in prior55):
                    self._donchian = ONE
                elif bar.close < min(row.low for row in prior55):
                    self._donchian = -ONE
                elif (
                    self._donchian > 0
                    and bar.close < min(row.low for row in prior20)
                    or self._donchian < 0
                    and bar.close > max(row.high for row in prior20)
                ):
                    self._donchian = ZERO
            target_day = bar.open_ms - 365 * DAY_MS
            position = bisect_right([row.open_ms for row in self._bars], target_day) - 1
            r4 = ZERO
            if position >= 0:
                prior = self._bars[position]
                if target_day - prior.open_ms <= 7 * DAY_MS:
                    r4 = _sign(bar.close / prior.close - ONE)
            if self._bars:
                previous_close = self._bars[-1].close
                true_range = max(
                    bar.high - bar.low,
                    abs(bar.high - previous_close),
                    abs(bar.low - previous_close),
                )
                if self._atr is None:
                    self._true_ranges.append(true_range)
                    if len(self._true_ranges) == 10:
                        self._atr = sum(self._true_ranges, ZERO) / Decimal(10)
                else:
                    self._atr = (Decimal(9) * self._atr + true_range) / Decimal(10)
                if self._atr is not None:
                    mid = (bar.high + bar.low) / Decimal(2)
                    basic_upper = mid + Decimal(3) * self._atr
                    basic_lower = mid - Decimal(3) * self._atr
                    if self._upper is None or self._lower is None:
                        self._upper, self._lower = basic_upper, basic_lower
                        self._trend = ONE if bar.close >= mid else -ONE
                    else:
                        if basic_upper < self._upper or previous_close > self._upper:
                            self._upper = basic_upper
                        if basic_lower > self._lower or previous_close < self._lower:
                            self._lower = basic_lower
                        if self._trend > 0 and bar.close < self._lower:
                            self._trend = -ONE
                        elif self._trend < 0 and bar.close > self._upper:
                            self._trend = ONE
            signals = (r1, r2, self._donchian, r4, self._trend)
            blend = sum(signals, ZERO) / Decimal(5)
            self._bars.append(bar)
            return SignalPoint(
                bar.open_ms,
                (*signals, blend),
                sma,
                self._emas.get(21),
                self._emas.get(55),
                self._atr,
                self._upper,
                self._lower,
            )


def signal_series(bars: Sequence[Kline]) -> tuple[SignalPoint, ...]:
    state = SignalState()
    return tuple(state.update(bar) for bar in bars)
