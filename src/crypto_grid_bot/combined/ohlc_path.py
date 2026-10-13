"""Pure held-position OHLC schedule for the two approved modeled scenarios.

Exit rows are instructions, never fills. The consumer must execute legal reductions
before later vertex marks, retaining every unfilled remainder and dust valuation.
No intrabar clock time is invented. Sources identify the input bar; the eventual
portfolio replay supplies asset/order IDs, fills and accounting evidence.
"""

from dataclasses import dataclass
from decimal import Decimal

from crypto_grid_bot.backtest.klines import Kline

from .experiment import SCENARIOS


@dataclass(frozen=True, slots=True)
class PathEvent:
    phase: str
    kind: str
    price: Decimal


@dataclass(frozen=True, slots=True)
class HeldPath:
    interval_start_ms: int
    interval_end_ms: int
    scenario: str
    source_refs: tuple[str, ...]
    events: tuple[PathEvent, ...]


def _price(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and 0 < value <= Decimal("1e36")


def plan_held_path(
    bar: Kline,
    scenario: str,
    *,
    side: int,
    stop: Decimal,
    target: Decimal | None = None,
    target_eligible: bool = True,
    source_refs: tuple[str, ...],
) -> HeldPath:
    """Schedule the old adverse stop ahead of any favorable same-bar target.

    Intended for inventory already exposed at interval open. Intrabar entries need
    an entry-phase-aware schedule: this function must not invent their earlier
    exposure. ``target_eligible=False`` suppresses unproven same-bar grid targets;
    it does not establish when that inventory entered. Trailing changes belong to
    completed-bar processing after this schedule, never retroactive execution.
    """
    if (
        not isinstance(bar, Kline)
        or type(bar.open_ms) is not int
        or bar.open_ms < 0
        or bar.open_ms % 3_600_000
        # The last development bar opens before, and ends AT, the reserved boundary.
        or bar.open_ms + 3_600_000 > 1_735_689_600_000
        or scenario not in SCENARIOS
        or type(side) is not int
        or side not in (-1, 1)
        or type(target_eligible) is not bool
        or not all(_price(p) for p in (bar.open, bar.high, bar.low, bar.close, stop))
        or (target is not None and not _price(target))
        or bar.low > min(bar.open, bar.close)
        or bar.high < max(bar.open, bar.close)
        or not isinstance(source_refs, tuple)
        or not source_refs
        or any(not isinstance(ref, str) or not ref.strip() for ref in source_refs)
    ):
        raise ValueError("identified valid pre-reserved hourly bar and fixed scenario required")
    long = side == 1
    if target is not None and ((target <= stop) if long else (target >= stop)):
        raise ValueError("target must be beyond the protective stop")
    stop_touched = bar.low <= stop if long else bar.high >= stop
    phases = (
        ("open", "low", "high", "close")
        if scenario == SCENARIOS[0]
        else ("open", "high", "low", "close")
    )
    events: list[PathEvent] = []
    exited = False
    for phase in phases:
        price = getattr(bar, phase)
        # The opening mark is genuine gap stress; later adverse vertices must not
        # mark inventory that a completed stop execution has already removed.
        if phase == "open":
            events.append(PathEvent(phase, "valuation", price))
        if not exited and stop_touched and ((price <= stop) if long else (price >= stop)):
            events.append(PathEvent(phase, "stop", price if phase == "open" else stop))
            exited = True
        elif (
            not exited
            and not stop_touched
            and target_eligible
            and target is not None
            and ((price >= target) if long else (price <= target))
        ):
            events.append(PathEvent(phase, "target", target))
            exited = True
        if phase != "open":
            events.append(PathEvent(phase, "valuation", price))
    return HeldPath(bar.open_ms, bar.open_ms + 3_600_000, scenario, source_refs, tuple(events))
