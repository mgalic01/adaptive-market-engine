"""Pure volatility sizing for frozen V3; no account mutation or order execution."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
