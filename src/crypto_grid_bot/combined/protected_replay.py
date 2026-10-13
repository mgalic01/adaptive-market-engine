"""Single held-asset protective replay fragment, not a full strategy runner.

Modeled phases have no occurrence timestamp. The engine clock is the completed
bar's availability time; these snapshots must not be relabeled as native hourly
observations. No entries, funding, finality acknowledgements or recovery admission
are synthesized here. Unresolved portfolio protection fails this fragment closed.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from crypto_grid_bot.backtest.klines import Kline

from .account import FillEvent
from .engine import EngineSnapshot, PortfolioEngine, Quote
from .execution import VenueRules, _decimal, adverse_price, executable_reduction
from .ohlc_path import HeldPath, plan_held_path


@dataclass(frozen=True, slots=True)
class PhaseObservation:
    available_ms: int
    phase: str
    snapshot: EngineSnapshot


@dataclass(frozen=True, slots=True)
class ProtectedInterval:
    path: HeldPath
    observations: tuple[PhaseObservation, ...]
    fills: tuple[FillEvent, ...]
    failure: str | None


def replay_protected_interval(
    engine: PortfolioEngine,
    bars: tuple[tuple[str, Kline], ...],
    rules: Mapping[str, VenueRules],
    scenario: str,
    *,
    source_refs: tuple[str, ...],
) -> ProtectedInterval:
    """Execute a held asset's old stop before valuing later modeled extremes.

    One legal reduction is attempted at the trigger. Partial/dust inventory remains
    in the account and subsequent vertices are retained; it is never declared flat.
    The caller must use a separate coordinator for a multi-asset portfolio.
    Any other protective obligation encountered makes this fragment incomplete,
    even if a later old-stop execution removes that position.
    """
    held = engine.held_execution_terms()
    if len(bars) != 1 or len(held) != 1:
        raise ValueError("fragment requires exactly one held asset and one bar")
    symbol, bar = bars[0]
    position, stop, fee, slip = held[0]
    if symbol != position.symbol or symbol not in rules or bar.open_ms < engine.clock:
        raise ValueError("matching filters and nonoverlapping interval required")
    side = 1 if position.quantity > 0 else -1
    path = plan_held_path(bar, scenario, side=side, stop=stop, source_refs=source_refs)
    observations: list[PhaseObservation] = []
    fills: list[FillEvent] = []
    failure = None
    now = path.interval_end_ms
    for index, event in enumerate(path.events):
        quotes = {symbol: Quote(event.price, now)}
        try:
            if event.kind == "stop":
                engine.request_close(symbol, position.owner, side, reason="stop")
                reduction = executable_reduction(
                    abs(position.quantity), event.price, rules[symbol], side=-side, slippage=slip
                )
                if reduction.quantity:
                    price = adverse_price(
                        _decimal(Fraction(event.price) * (1 - side * Fraction(slip))),
                        -side,
                        rules[symbol],
                    )
                    identity = f"held:{symbol}:{path.interval_start_ms}:{scenario}:{index}"
                    if engine.booked_fill(identity) is not None:
                        raise ValueError("modeled execution identity already booked")
                    fill = FillEvent(
                        identity,
                        now,
                        symbol,
                        position.owner,
                        position.venue,
                        -side,
                        reduction.quantity,
                        price,
                        _decimal(Fraction(reduction.quantity) * Fraction(price) * Fraction(fee)),
                    )
                    try:
                        snapshot = engine.settle(identity, now, quotes, rules, reductions=(fill,))
                    finally:
                        booked = engine.booked_fill(identity)
                        if booked is not None:
                            fills.append(booked)
                        observations.extend(
                            PhaseObservation(now, f"{event.phase}:{row.phase}", row.snapshot)
                            for row in engine.settlement_observations(identity)
                        )
                else:
                    snapshot = engine.observe(now, quotes, rules)
                    observations.append(PhaseObservation(now, event.phase, snapshot))
            else:
                snapshot = engine.observe(now, quotes, rules)
                observations.append(PhaseObservation(now, event.phase, snapshot))
            if snapshot.close_required:
                failure = "unresolved_protective_close"
            if snapshot.liquidation or "execution_integrity_failure" in snapshot.reasons:
                failure = "portfolio_safety_failure"
        except (ValueError, ArithmeticError, TypeError, AttributeError) as exc:
            failure = f"execution_failure:{type(exc).__name__}"
            break
    return ProtectedInterval(path, tuple(observations), tuple(fills), failure)
