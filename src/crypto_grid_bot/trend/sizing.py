"""Pure volatility sizing for frozen V3; no account mutation or order execution."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.window import development_month

DAY_MS = 86_400_000
ZERO = Decimal(0)
ONE = Decimal(1)


def _day(stamp: int) -> None:
    if type(stamp) is not int or stamp < 0 or stamp % DAY_MS:
        raise ValueError("expected a UTC daily timestamp")
    development_month(datetime.fromtimestamp(stamp // 1000, UTC).strftime("%Y-%m"))


@dataclass(frozen=True, slots=True)
class DailyReturn:
    day_ms: int
    value: Decimal


def daily_returns(bars: Sequence[Kline]) -> tuple[DailyReturn, ...]:
    """Only consecutive close-to-close UTC days; never bridge a missing day."""
    result = []
    previous = None
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        for bar in bars:
            _day(bar.open_ms)
            if previous is not None and bar.open_ms <= previous.open_ms:
                raise ValueError("daily bars must be strictly ordered")
            exponent = bar.close.as_tuple().exponent
            if (
                not bar.close.is_finite()
                or not isinstance(exponent, int)
                or not -18 <= exponent <= 18
                or not ZERO < bar.close <= Decimal("1e18")
            ):
                raise ValueError("close outside archive numeric bounds")
            if previous is not None and bar.open_ms - previous.open_ms == DAY_MS:
                result.append(DailyReturn(bar.open_ms, bar.close / previous.close - ONE))
            previous = bar
    return tuple(result)


@dataclass(frozen=True, slots=True)
class SizingResult:
    weights: dict[str, Decimal]
    raw_weights: dict[str, Decimal]
    volatility: dict[str, Decimal | None]
    common_days: tuple[int, ...]
    estimated_volatility: Decimal
    flat_reason: str | None
    scaled_weights: dict[str, Decimal | None] = field(default_factory=dict)
    binding_caps: dict[str, frozenset[str]] = field(default_factory=dict)


def size_portfolio(
    signals: Mapping[str, Decimal],
    returns: Mapping[str, Sequence[DailyReturn]],
    day_ms: int,
    *,
    excluded: frozenset[str] = frozenset(),
    multiple: int = 2,
) -> SizingResult:
    """Section 5 steps 1–3, measured after day_ms closes; no execution band here.

    Individual volatility uses the last 60 observations, while covariance uses
    common observations within the last 60 calendar days, including day_ms.
    Future observations are validated but never enter either statistic.
    """
    _day(day_ms)
    if type(multiple) is not int or multiple not in (1, 2, 3):
        raise ValueError("frozen V3 size multiple must be 1, 2 or 3")
    names = sorted(signals)
    for value in signals.values():
        if not value.is_finite() or not -ONE <= value <= ONE:
            raise ValueError("signal must be finite and within [-1, 1]")
    history: dict[str, dict[int, Decimal]] = {}
    for name in names:
        rows: dict[int, Decimal] = {}
        previous = -1
        for row in returns.get(name, ()):
            _day(row.day_ms)
            if row.day_ms <= previous:
                raise ValueError("return dates must be strictly ordered")
            if not row.value.is_finite() or not -ONE < row.value <= Decimal("1e36"):
                raise ValueError("invalid simple return")
            previous = row.day_ms
            if row.day_ms <= day_ms:
                rows[row.day_ms] = row.value
        history[name] = rows
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        raw = dict.fromkeys(names, ZERO)
        volatility: dict[str, Decimal | None] = dict.fromkeys(names, None)
        weights = dict.fromkeys(names, ZERO)
        unscaled: dict[str, Decimal | None] = dict.fromkeys(names, None)
        binding: dict[str, frozenset[str]] = dict.fromkeys(names, frozenset())
        for name in names:
            observations = list(history[name].values())[-60:]
            if len(observations) < 60:
                continue
            mean = sum(observations, ZERO) / Decimal(60)
            variance = sum(((value - mean) ** 2 for value in observations), ZERO) / Decimal(59)
            sigma = variance.sqrt() * Decimal(365).sqrt()
            volatility[name] = sigma
            if name in excluded or signals[name] == ZERO:
                continue
            if sigma != ZERO:
                raw[name] = signals[name] * (ONE / sigma)
        active = [name for name in names if raw[name] != ZERO]
        if not active:
            return SizingResult(
                weights, raw, volatility, (), ZERO, "no_nonzero_raw_weights", unscaled, binding
            )
        common = set(range(day_ms - 59 * DAY_MS, day_ms + DAY_MS, DAY_MS))
        for name in active:
            common.intersection_update(history[name])
        days = tuple(sorted(common))
        if len(days) < 40:
            return SizingResult(
                weights, raw, volatility, days, ZERO, "insufficient_common_days", unscaled, binding
            )
        means = {
            name: sum((history[name][day] for day in days), ZERO) / Decimal(len(days))
            for name in active
        }
        covariance = {
            (a, b): (
                sum(
                    ((history[a][day] - means[a]) * (history[b][day] - means[b]) for day in days),
                    ZERO,
                )
                / Decimal(len(days) - 1)
                * Decimal(365)
            )
            for a in active
            for b in active
        }
        # Evaluate the written product left-to-right: (raw^T Sigma) raw.
        left = {b: sum((raw[a] * covariance[a, b] for a in active), ZERO) for b in active}
        variance = sum((left[b] * raw[b] for b in active), ZERO)
        if variance < ZERO:
            raise ValueError("negative portfolio variance at frozen Decimal precision")
        estimate = variance.sqrt()
        if estimate == ZERO:
            return SizingResult(
                weights, raw, volatility, days, ZERO, "zero_portfolio_volatility", unscaled, binding
            )
        scale = Decimal("0.20") * multiple / estimate
        cap = Decimal("0.10") * multiple
        scaled: dict[str, Decimal | None] = dict.fromkeys(names, ZERO)
        for name in active:
            target = raw[name] * scale
            scaled[name] = target
            if abs(target) > cap:
                binding[name] = frozenset({"coin"})
            weights[name] = max(-cap, min(cap, target))
        gross = sum((abs(value) for value in weights.values()), ZERO)
        gross_cap = Decimal("0.80") * multiple
        if gross > gross_cap:
            factor = gross_cap / gross
            binding = {
                name: causes | {"gross"} if weights[name] != ZERO else causes
                for name, causes in binding.items()
            }
            weights = {name: value * factor for name, value in weights.items()}
        return SizingResult(weights, raw, volatility, days, estimate, None, scaled, binding)
