"""The grid's minute flow gate, precomputed as two bits per window hour.

A replay reads these bits instead of minute bars, which for ten coins over a whole
window would not fit in memory. They are what the replay's own calls read from
``routing.MinuteFlowGate``: the frame of hour ``h`` feeds minute ``h`` and reads the
gate; the interval of bar ``h`` then feeds the bar's other minutes and withholds its
resting grid buys if the gate was blocked at the opening or after any of them.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.baseline_records import refuse_sealed
from crypto_grid_bot.combined.routing import MinuteFlowGate
from crypto_grid_bot.market_data.parsing import symbol_name

HOUR = 3_600_000
_MINUTE = 60_000
_LOOK_BACK = 15 * _MINUTE  # the gate reads the fifteen minutes before each minute
_RESERVED = 1_735_689_600_000


@dataclass(frozen=True, slots=True)
class FlowSchedule:
    """One coin's flow gate at each hour of ``[start_ms, end_ms)``.

    Hour ``start_ms + i * HOUR`` is bit ``i``, least significant bit first in each byte.
    ``open_allowed``: the gate allows after the minutes through the hour's first one.
    ``withheld``: it blocks then or after any later minute of that bar. ``present``:
    some minute bar opens in ``[start_ms - 15 min, end_ms)``, the gate's read range.
    """

    symbol: str
    start_ms: int
    end_ms: int
    open_allowed: bytes
    withheld: bytes
    present: bool

    def allowed_at(self, hour: int) -> bool:
        """The gate at bar ``hour``'s opening minute."""
        return _bit(self.open_allowed, self._index(hour))

    def withheld_at(self, hour: int) -> bool:
        """Whether bar ``hour``'s resting grid buys are withheld."""
        return _bit(self.withheld, self._index(hour))

    def _index(self, hour: int) -> int:
        if type(hour) is not int or hour % HOUR or not self.start_ms <= hour < self.end_ms:
            raise ValueError(f"{self.symbol}: flow schedule read outside its window hours")
        return (hour - self.start_ms) // HOUR


def _bit(bits: bytes, index: int) -> bool:
    return bool(bits[index >> 3] >> (index & 7) & 1)


def _checked(symbol: str, minutes: Iterable[Kline]) -> Iterator[Kline]:
    """``minutes`` as read; each must be a kline on a minute boundary, after the one
    before it and before the reserved boundary."""
    previous: int | None = None
    for bar in minutes:
        if not isinstance(bar, Kline):
            raise ValueError(f"{symbol}: minute klines required")
        refuse_sealed((bar.open_ms,), f"{symbol} minutes")
        if bar.open_ms % _MINUTE or bar.open_ms == previous:
            raise ValueError(f"{symbol}: unique aligned minute bars required")
        if previous is not None and bar.open_ms < previous:
            raise ValueError(f"{symbol}: minute bars in ascending order required")
        previous = bar.open_ms
        yield bar


def build_flow_schedule(
    symbol: str, minutes: Iterable[Kline], start_ms: int, end_ms: int
) -> FlowSchedule:
    """The flow gate fed ``minutes`` over ``[start_ms, end_ms)``, in the replay's calls.

    ``minutes`` is read once, in ascending order and to its end, so a minute after the
    window is checked too. At most the minutes the gate reads next, up to an hour's,
    are held at once, never the stream. Shares divide in the current decimal context,
    as the replay's gate did.
    """
    symbol_name(symbol)
    if (
        type(start_ms) is not int
        or type(end_ms) is not int
        or start_ms % HOUR
        or end_ms % HOUR
        or not 0 <= start_ms < end_ms <= _RESERVED
    ):
        raise ValueError(f"{symbol}: a pre-reserved window of whole hours required")
    first = start_ms - _LOOK_BACK
    stream = _checked(symbol, minutes)
    ahead = next(stream, None)
    held: dict[int, Kline] = {}
    present = False

    def feed(through: int) -> None:
        """Hold the gate's next minutes through ``through``, and one beyond them.

        The gate has read every minute held before. The one beyond leaves the hold
        empty when the gate is built only if no minute is left for it to read, the
        case its no-bars path is for."""
        nonlocal ahead
        held.clear()
        while ahead is not None and ahead.open_ms <= through:
            hold(ahead)
            ahead = next(stream, None)
        if ahead is not None:
            hold(ahead)

    def hold(bar: Kline) -> None:
        nonlocal present
        if bar.open_ms >= first:  # earlier minutes are never read
            held[bar.open_ms] = bar
            present = present or bar.open_ms < end_ms

    feed(start_ms - _MINUTE)  # the look-back, read when the gate is built
    gate = MinuteFlowGate(held, start_ms)
    size = ((end_ms - start_ms) // HOUR + 7) // 8
    open_allowed, withheld = bytearray(size), bytearray(size)
    for index, hour in enumerate(range(start_ms, end_ms, HOUR)):
        feed(hour)
        gate.advance(hour)  # the frame at ``hour``
        opened = gate.allowed
        feed(hour + HOUR - _MINUTE)
        blocked = gate.advance(hour + HOUR - _MINUTE)  # the interval of bar ``hour``
        if opened:
            open_allowed[index >> 3] |= 1 << (index & 7)
        if blocked or not opened:
            withheld[index >> 3] |= 1 << (index & 7)
    for _later in stream:  # checked, never read by the gate
        pass
    return FlowSchedule(symbol, start_ms, end_ms, bytes(open_allowed), bytes(withheld), present)
