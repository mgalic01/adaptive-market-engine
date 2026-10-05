"""Variant F of experiment spec v1 (§3 F): the order-flow entry block's signal.

``share`` is the taker-buy base volume over the base volume of the 15 one-minute bars
that opened in the 15 minutes before a decision's minute, all completed by then. It is
unavailable when any of them is missing (a zero-volume minute is valid) or when their
base volume is zero. F's own flag turns on below 0.40 or when the share is unavailable,
off from 0.45, and starts on, so F fails closed; the engine (``runner.py``) turns it into
restrictions on buys only.

Pure and Decimal; nothing reads files or the clock.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Protocol

FLOW_BARS = 15
MINUTE_MS = 60_000
BLOCK_BELOW = Decimal("0.40")  # strict
UNBLOCK_FROM = Decimal("0.45")  # inclusive
ZERO = Decimal(0)


class FlowBar(Protocol):
    """A completed 1m bar; ``backtest.klines.Kline`` satisfies it."""

    @property
    def open_ms(self) -> int: ...

    @property
    def volume(self) -> Decimal: ...

    @property
    def taker_buy_base(self) -> Decimal: ...


def taker_buy_share(bars: Iterable[FlowBar], minute_ms: int) -> Decimal | None:
    """F's share for a decision in the minute that opens at ``minute_ms``, from ``bars``,
    the latest bars before it, oldest first; None when unavailable. Only the bars of the
    15 minutes before ``minute_ms`` are read: one missing, stale or newer makes the share
    unavailable."""
    window = list(bars)[-FLOW_BARS:]
    expected = range(minute_ms - FLOW_BARS * MINUTE_MS, minute_ms, MINUTE_MS)
    if [bar.open_ms for bar in window] != list(expected):
        return None
    volume = sum((bar.volume for bar in window), ZERO)
    if volume == ZERO:
        return None
    return sum((bar.taker_buy_base for bar in window), ZERO) / volume


def flow_blocked(blocked: bool, share: Decimal | None) -> bool:
    """F's flag after a decision with ``share``, from ``blocked`` before it: on below 0.40
    or when unavailable, off from 0.45, and unchanged in between."""
    if share is None or share < BLOCK_BELOW:
        return True
    return blocked and share < UNBLOCK_FROM
