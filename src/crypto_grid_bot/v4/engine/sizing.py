"""Volatility sizing of V4 from the full-strength book, the coin and total caps, and the band.

Implements the spec's "Sizing: volatility targeting, V3's method" (steps 1 to 3, with owner
decision v4-d12's full-strength scale) and its "Fewer trades" paragraph.

The math is V3's ``trend.sizing`` (``daily_returns`` and ``size_portfolio``), copied, not
called: V3 refuses every month after 2024-12. The operation order is V3's, so that when every
|s| is 1 (the full-strength book is then the raw book) ``size_book`` equals V3's
``size_portfolio`` weight for weight; the differential test checks that on pre-2025 bars.

* **Returns** (Ruling R4): close to close between consecutive UTC days only. A missing bar
  gives no return for its own day or the next, so a return never spans a gap.
* **Step 1.** sigma is the sample deviation (n - 1) of the coin's last 60 returns at or
  before the decision day, times the square root of 365. ``raw = s x (1 / sigma)`` and
  ``full = sign(s) x (1 / sigma)``; a coin with fewer than 60 returns, sigma 0 or s 0 has
  both at 0.
* **Step 2.** The common days are the calendar days of the last 60, the decision day
  included, on which every coin with a nonzero ``full`` has a return. Fewer than 40 flattens
  the book. Sigma is the sample covariance over them (n - 1), times 365, and
  ``c = vol_target / sqrt(full' Sigma full)``, with the product evaluated left to right. A
  zero product flattens the book; a negative one is refused, as V3 refuses it. Each weight is
  ``c x raw``, so agreement sets the size: the scale never sees |s|.
* **Step 3.** Each |weight| is capped at ``coin_cap``, then, if the sum of |weights| exceeds
  ``total_cap``, every weight is scaled by ``total_cap / sum``.
* **The band** decides whether a coin trades to its target. It compares weights and works on
  exact fractions, so a position exactly on the band's edge never trades.

Only future returns are validated and then ignored; they never enter a statistic. Every
Decimal operation runs under the engine's one context.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from types import MappingProxyType

from crypto_grid_bot.backtest.klines import INTERVAL_MS, Kline
from crypto_grid_bot.trend.sizing import DailyReturn
from crypto_grid_bot.v4.engine.arms import (
    BAND_ABSOLUTE,
    BAND_RELATIVE,
    COIN_CAP,
    COVARIANCE_DAYS,
    MIN_COMMON_DAYS,
    SIGMA_RETURNS,
    TOTAL_CAP,
)
from crypto_grid_bot.v4.engine.numbers import CONTEXT, to_fraction

DAY_MS = INTERVAL_MS["1d"]

_ZERO = Decimal(0)
_ONE = Decimal(1)
_YEAR_DAYS = Decimal(365)
# The bounds of the data layer's price reader, and V3's bound on a simple return.
_MAX_PRICE = Decimal("1e18")
_MAX_EXPONENT = 18
_MAX_RETURN = Decimal("1e36")

with localcontext(CONTEXT):
    _ROOT_YEAR = _YEAR_DAYS.sqrt()

_BAND_RELATIVE = to_fraction(BAND_RELATIVE)
_BAND_ABSOLUTE = to_fraction(BAND_ABSOLUTE)


@dataclass(frozen=True, slots=True)
class CoinSizing:
    """One coin's sizing, step by step, for the daily record.

    ``sigma`` is ``None`` when the coin has fewer than 60 returns. ``raw`` and ``full`` are the
    step-1 weights (0 for a coin without a usable sigma or signal). ``scaled`` is ``c x raw``
    before any cap, ``after_coin_cap`` the same after the coin cap and ``after_total_cap`` the
    final weight. All three are 0 for a coin outside the book and for a flat book.
    """

    sigma: Decimal | None
    raw: Decimal
    full: Decimal
    scaled: Decimal
    after_coin_cap: Decimal
    after_total_cap: Decimal


@dataclass(frozen=True, slots=True)
class SizingResult:
    """The target weights (fractions of equity), every coin of the signals, and how they came.

    ``scale`` is c, or ``None`` when the book is flat; ``flat_reason`` then says why, in V3's
    words: ``no_nonzero_raw_weights``, ``insufficient_common_days`` or
    ``zero_portfolio_volatility``. ``common_days`` counts the days the covariance used.
    """

    weights: Mapping[str, Decimal]
    coins: Mapping[str, CoinSizing]
    scale: Decimal | None
    common_days: int
    flat_reason: str | None = None


def _check_day(stamp: object, what: str) -> int:
    if type(stamp) is not int or stamp < 0 or stamp % DAY_MS:
        raise ValueError(f"{what} must be a UTC midnight timestamp in milliseconds, got {stamp!r}")
    return stamp


def _check_close(close: object) -> Decimal:
    if not isinstance(close, Decimal) or not close.is_finite():
        raise ValueError(f"a daily close must be a finite Decimal, got {close!r}")
    exponent = close.as_tuple().exponent
    if (
        not isinstance(exponent, int)
        or not -_MAX_EXPONENT <= exponent <= _MAX_EXPONENT
        or not _ZERO < close <= _MAX_PRICE
    ):
        raise ValueError(f"a daily close is outside the data layer's numeric bounds: {close}")
    return close


def daily_returns(bars: Sequence[Kline]) -> tuple[DailyReturn, ...]:
    """Close-to-close simple returns between consecutive UTC days; never across a missing day.

    The return is dated on the later day. Bars must be strictly ordered, at UTC midnight, with
    closes inside the data layer's bounds.
    """
    result: list[DailyReturn] = []
    previous: Kline | None = None
    with localcontext(CONTEXT):
        for bar in bars:
            _check_day(bar.open_ms, "a daily bar's open time")
            if previous is not None and bar.open_ms <= previous.open_ms:
                raise ValueError("daily bars must be strictly ordered")
            _check_close(bar.close)
            if previous is not None and bar.open_ms - previous.open_ms == DAY_MS:
                result.append(DailyReturn(bar.open_ms, bar.close / previous.close - _ONE))
            previous = bar
    return tuple(result)


def _check_limit(label: str, value: object) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= _ZERO:
        raise ValueError(f"{label} must be a positive finite Decimal, got {value!r}")


def _check_signals(signals: Mapping[str, Decimal]) -> None:
    for name, value in signals.items():
        if not isinstance(name, str):
            raise ValueError(f"a signal needs a coin symbol, got {name!r}")
        if not isinstance(value, Decimal) or not value.is_finite() or not -_ONE <= value <= _ONE:
            raise ValueError(f"signal of {name} must be a finite Decimal within [-1, 1]")


def _history(
    names: Sequence[str], returns: Mapping[str, Sequence[DailyReturn]], day_ms: int
) -> dict[str, dict[int, Decimal]]:
    """Each coin's returns at or before ``day_ms`` by day; the whole series is validated."""
    history: dict[str, dict[int, Decimal]] = {}
    for name in names:
        rows: dict[int, Decimal] = {}
        previous = -1
        for row in returns.get(name, ()):
            _check_day(row.day_ms, f"a return date of {name}")
            if row.day_ms <= previous:
                raise ValueError(f"return dates of {name} must be strictly ordered")
            if (
                not isinstance(row.value, Decimal)
                or not row.value.is_finite()
                or not -_ONE < row.value <= _MAX_RETURN
            ):
                raise ValueError(f"invalid simple return for {name}: {row.value!r}")
            previous = row.day_ms
            if row.day_ms <= day_ms:
                rows[row.day_ms] = row.value
        history[name] = rows
    return history


def _sigma(observations: Sequence[Decimal]) -> Decimal:
    """Annualised sample deviation of exactly ``SIGMA_RETURNS`` returns (V3's operations)."""
    mean = sum(observations, _ZERO) / Decimal(SIGMA_RETURNS)
    variance = sum(((value - mean) ** 2 for value in observations), _ZERO) / Decimal(
        SIGMA_RETURNS - 1
    )
    return variance.sqrt() * _ROOT_YEAR


def _result(
    names: Sequence[str],
    sigma: Mapping[str, Decimal | None],
    raw: Mapping[str, Decimal],
    full: Mapping[str, Decimal],
    steps: tuple[Mapping[str, Decimal], Mapping[str, Decimal], Mapping[str, Decimal]],
    scale: Decimal | None,
    common_days: int,
    flat_reason: str | None,
) -> SizingResult:
    scaled, coin_capped, total_capped = steps
    coins = {
        name: CoinSizing(
            sigma[name], raw[name], full[name], scaled[name], coin_capped[name], total_capped[name]
        )
        for name in names
    }
    weights = {name: total_capped[name] for name in names}
    return SizingResult(
        MappingProxyType(weights), MappingProxyType(coins), scale, common_days, flat_reason
    )


def size_book(
    signals: Mapping[str, Decimal],
    returns: Mapping[str, Sequence[DailyReturn]],
    day_ms: int,
    *,
    vol_target: Decimal,
    coin_cap: Decimal = COIN_CAP,
    total_cap: Decimal = TOTAL_CAP,
) -> SizingResult:
    """Target weights after ``day_ms`` closes: the spec's sizing steps 1 to 3.

    ``signals`` maps each coin to its net signal s in [-1, 1]; a coin that is not to be held
    (not in the universe, say) is passed with s = 0, which still records its sigma. ``returns``
    holds each coin's daily returns, oldest first. Individual volatility reads the last 60
    returns; the covariance reads the common observations within the last 60 calendar days,
    ``day_ms`` included.
    """
    _check_day(day_ms, "day_ms")
    _check_limit("vol_target", vol_target)
    _check_limit("coin_cap", coin_cap)
    _check_limit("total_cap", total_cap)
    _check_signals(signals)
    names = sorted(signals)
    history = _history(names, returns, day_ms)
    with localcontext(CONTEXT):
        sigma: dict[str, Decimal | None] = dict.fromkeys(names)
        raw = dict.fromkeys(names, _ZERO)
        full = dict.fromkeys(names, _ZERO)
        for name in names:
            observations = list(history[name].values())[-SIGMA_RETURNS:]
            if len(observations) < SIGMA_RETURNS:
                continue
            volatility = _sigma(observations)
            sigma[name] = volatility
            if signals[name] == _ZERO or volatility == _ZERO:
                continue
            inverse = _ONE / volatility
            raw[name] = signals[name] * inverse
            full[name] = (_ONE if signals[name] > _ZERO else -_ONE) * inverse

        zeros = dict.fromkeys(names, _ZERO)
        flat = (zeros, zeros, zeros)
        active = [name for name in names if full[name] != _ZERO]
        if not active:
            return _result(names, sigma, raw, full, flat, None, 0, "no_nonzero_raw_weights")
        common = set(range(day_ms - (COVARIANCE_DAYS - 1) * DAY_MS, day_ms + DAY_MS, DAY_MS))
        for name in active:
            common.intersection_update(history[name])
        days = sorted(common)
        if len(days) < MIN_COMMON_DAYS:
            return _result(
                names, sigma, raw, full, flat, None, len(days), "insufficient_common_days"
            )

        # The sample covariance over the common days, annualised. Deviations are taken once per
        # coin; a pair's sum is the same in either order, so the matrix is filled by symmetry.
        count = Decimal(len(days))
        deviations: dict[str, list[Decimal]] = {}
        for name in active:
            mean = sum((history[name][day] for day in days), _ZERO) / count
            deviations[name] = [history[name][day] - mean for day in days]
        covariance: dict[tuple[str, str], Decimal] = {}
        for index, a in enumerate(active):
            for b in active[index:]:
                products = (x * y for x, y in zip(deviations[a], deviations[b], strict=True))
                covariance[a, b] = covariance[b, a] = (
                    sum(products, _ZERO) / Decimal(len(days) - 1) * _YEAR_DAYS
                )
        # The written product, left to right: (full' Sigma) full.
        left = {b: sum((full[a] * covariance[a, b] for a in active), _ZERO) for b in active}
        variance = sum((left[b] * full[b] for b in active), _ZERO)
        if variance < _ZERO:
            raise ValueError("negative portfolio variance at the engine's Decimal precision")
        estimate = variance.sqrt()
        if estimate == _ZERO:
            return _result(
                names, sigma, raw, full, flat, None, len(days), "zero_portfolio_volatility"
            )

        scale = vol_target / estimate
        scaled = dict(zeros)
        coin_capped = dict(zeros)
        for name in active:
            scaled[name] = raw[name] * scale
            coin_capped[name] = max(-coin_cap, min(coin_cap, scaled[name]))
        gross = sum((abs(coin_capped[name]) for name in names), _ZERO)
        total_capped = coin_capped
        if gross > total_cap:
            factor = total_cap / gross
            total_capped = {name: value * factor for name, value in coin_capped.items()}
        steps = (scaled, coin_capped, total_capped)
        return _result(names, sigma, raw, full, steps, scale, len(days), None)


def _sign(value: Fraction) -> int:
    return (value > 0) - (value < 0)


def band_trades(target: Decimal, current: Decimal) -> bool:
    """Whether a coin trades to ``target`` from ``current``, both weights (fractions of equity).

    It trades when the signs differ (a zero current with a nonzero target is a sign change, and
    a zero target with a position open is one too) or when
    ``|target - current| > max(0.25 x |target|, 0.01)``. Both 0 is no trade. The comparison is
    exact, so a position exactly on the edge stays where it is.
    """
    want = to_fraction(target)
    held = to_fraction(current)
    if _sign(want) != _sign(held):
        return True
    return abs(want - held) > max(_BAND_RELATIVE * abs(want), _BAND_ABSOLUTE)
