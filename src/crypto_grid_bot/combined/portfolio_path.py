"""Synchronized held-inventory OHLC phases over one shared account.

This coordinator supplies modeled protective executions, not strategy entries or
historical execution authorization. All assets must have the same complete input
interval. Phase timestamps denote bar availability, never observed tick times.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from crypto_grid_bot.backtest.klines import Kline

from .account import FillEvent
from .engine import EngineSnapshot, PortfolioEngine, Quote
from .execution import VenueRules, _decimal, adverse_price, executable_reduction
from .ohlc_path import HeldPath, plan_held_path


@dataclass(frozen=True, slots=True)
class PortfolioObservation:
    available_ms: int
    phase: str
    id: str
    snapshot: EngineSnapshot


@dataclass(frozen=True, slots=True)
class PortfolioInterval:
    paths: tuple[tuple[str, HeldPath], ...]
    observations: tuple[PortfolioObservation, ...]
    fills: tuple[FillEvent, ...]
    failure: str | None
    grid_spacing: tuple[tuple[str, Decimal], ...] = ()
    # Close obligations left only on inventory no legal order can reduce at fresh marks.
    retained_dust: tuple[str, ...] = ()


def replay_held_portfolio(
    engine: PortfolioEngine,
    bars: tuple[tuple[str, Kline], ...],
    rules: Mapping[str, VenueRules],
    scenario: str,
    *,
    source_refs: tuple[str, ...],
    grid_spacing: tuple[tuple[str, Decimal], ...] = (),
) -> PortfolioInterval:
    """Settle stops and portfolio closes before proceeding to later phase marks.

    Within a phase old stops execute in symbol order against the previously available
    other-asset marks, then the full vector advances together to the vertex. Any
    resulting portfolio close is settled immediately at that available vector.
    Venue maximums split reductions; minimum-size dust remains valued and owned,
    keeps its close obligation and is reported as retained dust, not a failure.
    A finite 10,000-fill safety budget fails incomplete rather than looping without
    bound on malformed or impractically tiny venue order limits.
    Grid spacing must come from retained admitted geometry; the full strategy
    coordinator binds that provenance. Targets derive from actual lot entry prices.
    Every lot here is held at open; intrabar purchases need separate eligibility.
    """
    terms = {row[0].symbol: row for row in engine.held_execution_terms()}
    if (
        not isinstance(bars, tuple)
        or not bars
        or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in bars)
        or any(not isinstance(symbol, str) or not isinstance(bar, Kline) for symbol, bar in bars)
        or len({symbol for symbol, _ in bars}) != len(bars)
        or {symbol for symbol, _ in bars} != set(terms)
        or any(not isinstance(rules.get(symbol), VenueRules) for symbol in terms)
    ):
        raise ValueError("complete unique held-asset bars and venue filters required")
    market = dict(bars)
    grid_symbols = {symbol for symbol, row in terms.items() if row[0].owner == "spot_grid"}
    if (
        not isinstance(grid_spacing, tuple)
        or any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not isinstance(pair[0], str)
            or not isinstance(pair[1], Decimal)
            or not pair[1].is_finite()
            or not 0 < pair[1] <= Decimal("1e36")
            for pair in grid_spacing
        )
        or len({symbol for symbol, _ in grid_spacing}) != len(grid_spacing)
        or {symbol for symbol, _ in grid_spacing} != grid_symbols
    ):
        raise ValueError("one retained positive spacing per held grid required")
    spacing = dict(grid_spacing)
    starts = {bar.open_ms for bar in market.values()}
    if len(starts) != 1 or next(iter(starts)) < engine.clock:
        raise ValueError("one nonoverlapping portfolio interval required")
    paths = tuple(
        (
            symbol,
            plan_held_path(
                market[symbol],
                scenario,
                side=1 if terms[symbol][0].quantity > 0 else -1,
                stop=terms[symbol][1],
                source_refs=source_refs,
            ),
        )
        for symbol in sorted(terms)
    )
    target_paths = tuple(
        (
            symbol,
            lot.lot_id,
            plan_held_path(
                market[symbol],
                scenario,
                side=1,
                stop=terms[symbol][1],
                target=_decimal(Fraction(lot.entry_price) + Fraction(spacing[symbol])),
                source_refs=source_refs,
            ),
        )
        for symbol in sorted(grid_symbols)
        for lot in sorted(terms[symbol][0].lots, key=lambda item: (item.entry_price, item.lot_id))
    )
    now = paths[0][1].interval_end_ms
    prefix = f"portfolio:{paths[0][1].interval_start_ms}:{scenario}"
    quotes = {symbol: Quote(market[symbol].open, now) for symbol in terms}
    observations: list[PortfolioObservation] = []
    fills: list[FillEvent] = []
    failure = None
    dust: tuple[str, ...] = ()
    sequence = 0

    def observe(phase: str) -> EngineSnapshot:
        nonlocal sequence
        snapshot = engine.observe(now, quotes, rules)
        sequence += 1
        observations.append(PortfolioObservation(now, phase, f"{prefix}:mark:{sequence}", snapshot))
        return snapshot

    def reduce(
        symbol: str,
        phase: str,
        lot_id: str | None = None,
        execution_reference: Decimal | None = None,
    ) -> bool:
        nonlocal sequence
        current = {row[0].symbol: row for row in engine.held_execution_terms()}
        if symbol not in current:
            return False
        position, _, fee, slip = current[symbol]
        quantity = abs(position.quantity)
        if lot_id is not None:
            lot = next((lot for lot in position.lots if lot.lot_id == lot_id), None)
            if lot is None:
                return False
            quantity = abs(lot.quantity)
        side = -1 if position.quantity > 0 else 1
        quote = quotes[symbol].price if execution_reference is None else execution_reference
        reduction = executable_reduction(quantity, quote, rules[symbol], side=side, slippage=slip)
        if not reduction.quantity:
            return False
        if len(fills) >= 10_000:
            raise ValueError("protective fill budget exhausted")
        sequence += 1
        identity = f"{prefix}:fill:{sequence}:{symbol}"
        if engine.booked_fill(identity) is not None:
            raise ValueError("modeled execution identity already booked")
        price = adverse_price(
            _decimal(Fraction(quote) * (1 + side * Fraction(slip))), side, rules[symbol]
        )
        fill = FillEvent(
            identity,
            now,
            symbol,
            position.owner,
            position.venue,
            side,
            reduction.quantity,
            price,
            _decimal(Fraction(reduction.quantity) * Fraction(price) * Fraction(fee)),
            lot_id,
        )
        try:
            engine.settle(identity, now, quotes, rules, reductions=(fill,))
        finally:
            booked = engine.booked_fill(identity)
            if booked is not None:
                fills.append(booked)
            observations.extend(
                PortfolioObservation(now, phase, f"{identity}:{index}:{row.phase}", row.snapshot)
                for index, row in enumerate(engine.settlement_observations(identity))
            )
        return True

    def drain(phase: str, snapshot: EngineSnapshot) -> EngineSnapshot:
        while snapshot.close_required:
            progressed = False
            for symbol in sorted(snapshot.close_required):
                progressed = reduce(symbol, phase) or progressed
            if not progressed:
                break
            snapshot = observations[-1].snapshot
        return snapshot

    phases = (
        ("open", "low", "high", "close")
        if scenario == "open_low_high_close"
        else ("open", "high", "low", "close")
    )
    try:
        for phase in phases:
            if phase == "open":
                drain(phase, observe(phase))
            for symbol, path in paths:
                stops = [
                    event for event in path.events if event.phase == phase and event.kind == "stop"
                ]
                if not stops:
                    continue
                current = {row[0].symbol: row for row in engine.held_execution_terms()}
                if symbol not in current:
                    continue
                position = current[symbol][0]
                quotes[symbol] = Quote(stops[0].price, now)
                engine.request_close(
                    symbol, position.owner, 1 if position.quantity > 0 else -1, reason="stop"
                )
                drain(f"{phase}:stop", observe(f"{phase}:stop"))
            for symbol, lot_id, path in target_paths:
                targets = [
                    event
                    for event in path.events
                    if event.phase == phase and event.kind == "target"
                ]
                if not targets:
                    continue
                current = {row[0].symbol: row for row in engine.held_execution_terms()}
                if symbol not in current or not any(
                    lot.lot_id == lot_id for lot in current[symbol][0].lots
                ):
                    continue
                if phase != "open":
                    quotes[symbol] = Quote(targets[0].price, now)
                drain(f"{phase}:target", observe(f"{phase}:target"))
                while reduce(symbol, f"{phase}:target", lot_id, targets[0].price):
                    drain(f"{phase}:target", observations[-1].snapshot)
            if phase != "open":
                quotes = {symbol: Quote(getattr(bar, phase), now) for symbol, bar in market.items()}
                drain(phase, observe(phase))
        final = observations[-1].snapshot
        dust = engine.close_dust(rules)
        if set(final.close_required) - set(dust) or final.unresolved_execution:
            failure = "unresolved_execution_obligations"
        if any(
            row.snapshot.liquidation
            or not row.snapshot.account.integrity_ok
            or "execution_integrity_failure" in row.snapshot.reasons
            for row in observations
        ):
            failure = "portfolio_safety_failure"
    except (ValueError, ArithmeticError, TypeError, AttributeError) as exc:
        failure = f"execution_failure:{type(exc).__name__}"
        dust = ()
    return PortfolioInterval(
        paths, tuple(observations), tuple(fills), failure, tuple(sorted(grid_spacing)), dust
    )
