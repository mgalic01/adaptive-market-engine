"""Causal connected correlation groups for a single portfolio admission snapshot.

Use the latest 60 common *one-day* simple close returns. Missing dates never
become multiday returns. A stale series, malformed completed history, insufficient
common history or zero variance makes a pair unknown and therefore connected.
Future/incomplete bar values are not inspected. Group IDs are the lexical first
symbol in each connected component, and are snapshot-specific, not durable IDs.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from fractions import Fraction
from itertools import combinations

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.market_data.parsing import symbol_name

_DAY = 86_400_000
_RESERVED = 1_735_689_600_000


def _returns(bars: Sequence[Kline], decision_ms: int) -> dict[int, Fraction] | None:
    closes: dict[int, Fraction] = {}
    previous = -1
    for bar in bars:
        if type(bar.open_ms) is not int or bar.open_ms < 0:
            return None
        # Completion, not array position, bounds what can be observed.
        if bar.open_ms + _DAY > decision_ms:
            continue
        if bar.open_ms % _DAY or bar.open_ms <= previous:
            return None
        previous = bar.open_ms
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
        ):
            return None
        if (
            bar.low <= 0
            or bar.low > min(bar.open, bar.close)
            or bar.high < max(bar.open, bar.close)
            or bar.taker_buy_base > bar.volume
        ):
            return None
        closes[bar.open_ms] = Fraction(bar.close)
    if decision_ms // _DAY * _DAY - _DAY not in closes:
        return None
    return {
        timestamp: close / closes[timestamp - _DAY] - 1
        for timestamp, close in closes.items()
        if timestamp - _DAY in closes
    }


def _connected(left: dict[int, Fraction] | None, right: dict[int, Fraction] | None) -> bool:
    if left is None or right is None:
        return True
    common = sorted(left.keys() & right.keys())[-60:]
    if len(common) < 60:
        return True
    xs = [left[timestamp] for timestamp in common]
    ys = [right[timestamp] for timestamp in common]
    sx, sy = sum(xs), sum(ys)
    variance_x = 60 * sum(x * x for x in xs) - sx * sx
    variance_y = 60 * sum(y * y for y in ys) - sy * sy
    if variance_x == 0 or variance_y == 0:
        return True
    covariance = 60 * sum(x * y for x, y in zip(xs, ys, strict=True)) - sx * sy
    # |Pearson| >= 4/5, exactly: no square-root or Decimal rounding boundary.
    return 25 * covariance * covariance >= 16 * variance_x * variance_y


def correlation_groups(
    daily: Mapping[str, Sequence[Kline]], decision_ms: int
) -> tuple[tuple[str, str], ...]:
    """Return the sorted symbol/group mapping expected by PortfolioView.

    A decision in the reserved 2025+ window is rejected even for empty input.
    The caller supplies in-memory development bars; this function performs no IO.
    """
    if type(decision_ms) is not int or not 0 <= decision_ms < _RESERVED:
        raise ValueError("decision must be a nonnegative development timestamp before 2025")
    symbols = sorted(daily)
    for symbol in symbols:
        symbol_name(symbol)
    histories = {symbol: _returns(daily[symbol], decision_ms) for symbol in symbols}
    parents = {symbol: symbol for symbol in symbols}

    def root(symbol: str) -> str:
        while parents[symbol] != symbol:
            symbol = parents[symbol]
        return symbol

    for left, right in combinations(symbols, 2):
        if _connected(histories[left], histories[right]):
            a, b = sorted((root(left), root(right)))
            parents[b] = a
    return tuple((symbol, root(symbol)) for symbol in symbols)
