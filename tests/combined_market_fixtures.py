"""Synthetic V3.1 market inputs: deterministic, labelled synthetic, never market data."""

import math
from decimal import Decimal as D

from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.decisions import Costs
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.combined.strategy_replay import ReplayRun, SymbolMarket, VenueMarket

HOUR = 3_600_000
DAY = 24 * HOUR
HISTORY_DAYS = 100
START = 1_600_000_000_000 // DAY * DAY + HISTORY_DAYS * DAY  # a UTC midnight in 2020
RULES = VenueRules(D(".001"), D(0), D(1000), D(5), D(".01"))
COSTS = Costs(D(".001"), D(".0005"), D(".004"))


def _price(value: float) -> D:
    return D(str(round(value, 2)))


def hourly(path, hours: int, *, start: int = START - HISTORY_DAYS * DAY, wick: float = 0.01):
    """Bars whose open/close follow ``path(i)`` with symmetric wicks of ``wick``."""
    rows = []
    for i in range(hours):
        open_, close = path(i), path(i + 1)
        high = max(open_, close) * (1 + wick)
        low = min(open_, close) * (1 - wick)
        rows.append(
            Kline(
                start + i * HOUR,
                _price(open_),
                _price(high),
                _price(low),
                _price(close),
                D(10),
                D(1000),
                D(5),
            )
        )
    return tuple(rows)


def daily(bars):
    days = {}
    for bar in bars:
        days.setdefault(bar.open_ms // DAY * DAY, []).append(bar)
    return tuple(
        Kline(
            day,
            rows[0].open,
            max(r.high for r in rows),
            min(r.low for r in rows),
            rows[-1].close,
            sum((r.volume for r in rows), D(0)),
            sum((r.quote_volume for r in rows), D(0)),
            sum((r.taker_buy_base for r in rows), D(0)),
        )
        for day, rows in sorted(days.items())
        if len(rows) == 24
    )


def minutes(start: int, end: int, buy_share: str = ".6"):
    share = D(buy_share)
    return tuple(
        Kline(t, D(100), D(100), D(100), D(100), D(10), D(1000), D(10) * share)
        for t in range(start, end, 60_000)
    )


def funding(start: int, end: int, rate: str = ".0001"):
    first = start // (8 * HOUR) * (8 * HOUR)
    return tuple(FundingRecord(t, 8, D(rate)) for t in range(first, end + 8 * HOUR, 8 * HOUR))


def uptrend(i: int) -> float:
    return 100 * 1.0006**i


def downtrend(i: int) -> float:
    return 400 * 0.9994**i


def ranging(i: int) -> float:
    return 100 * (1 + 0.02 * math.sin(i * 2 * math.pi / 48))


def market(symbol: str, path, days: int, *, futures: bool = False, flow: bool = False):
    hours = (HISTORY_DAYS + days) * 24
    spot = hourly(path, hours)
    end = START + days * DAY
    return SymbolMarket(
        symbol,
        VenueMarket(spot, RULES, COSTS),
        daily(spot),
        VenueMarket(hourly(path, hours), RULES, COSTS) if futures else None,
        funding(START - HISTORY_DAYS * DAY, end) if futures else (),
        minutes(START - 60 * 60_000, end) if flow else (),
    )


def run(arm: str, days: int, *, scenario: str = "open_low_high_close", cash: str = "10000"):
    return ReplayRun(arm, scenario, D(cash), START, START + days * DAY, ("synthetic:fixture",))
