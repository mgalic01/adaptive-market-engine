"""Synchronized held-inventory OHLC phases over one shared account.

This coordinator supplies modeled protective executions and the fills of already
admitted resting spot-grid limit buys, not new entries or historical execution
authorization. All priced assets must have the same complete input interval; a
holding without a bar is declared unpriced. Phase timestamps denote bar
availability, never observed tick times.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from crypto_grid_bot.backtest.klines import Kline

from .account import FillEvent
from .engine import EngineSnapshot, PortfolioEngine, Quote
from .execution import VenueRules, _decimal, adverse_price, executable_reduction, executable_trim
from .ohlc_path import HeldPath, plan_held_path


@dataclass(frozen=True, slots=True)
class PortfolioObservation:
    available_ms: int
    phase: str
    id: str
    snapshot: EngineSnapshot


@dataclass(frozen=True, slots=True)
class RestingBuy:
    """One admitted spot-grid child limit buy resting through the interval.

    ``stop`` is the basket's admitted common stop; ``intent_id`` is the basket
    admission whose remaining quantity the fill consumes.
    """

    intent_id: str
    child_id: str
    symbol: str
    limit: Decimal
    quantity: Decimal
    fee_rate: Decimal
    stop: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioInterval:
    paths: tuple[tuple[str, HeldPath], ...]
    observations: tuple[PortfolioObservation, ...]
    fills: tuple[FillEvent, ...]
    failure: str | None
    grid_spacing: tuple[tuple[str, Decimal], ...] = ()
    # Close obligations left only on inventory no legal order can reduce at fresh marks.
    retained_dust: tuple[str, ...] = ()
    # Resting children filled in this interval; their lots earn no same-bar target.
    filled_children: tuple[str, ...] = ()


def _positive(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and 0 < value <= Decimal("1e36")


def _resting_valid(resting: object, terms: Mapping[str, tuple[object, ...]]) -> bool:
    if not isinstance(resting, tuple) or any(not isinstance(row, RestingBuy) for row in resting):
        return False
    stops: dict[str, Decimal] = {}
    for row in resting:
        if (
            not all(
                isinstance(text, str) and text.strip() for text in (row.intent_id, row.child_id)
            )
            or not isinstance(row.symbol, str)
            or not all(_positive(value) for value in (row.limit, row.quantity, row.stop))
            or not isinstance(row.fee_rate, Decimal)
            or not row.fee_rate.is_finite()
            or not 0 <= row.fee_rate < 1
            or row.stop >= row.limit
            or stops.setdefault(row.symbol, row.stop) != row.stop
        ):
            return False
        held = terms.get(row.symbol)
        if held is not None and getattr(held[0], "owner", None) != "spot_grid":
            return False
    return len({row.child_id for row in resting}) == len(resting)


def replay_held_portfolio(
    engine: PortfolioEngine,
    bars: tuple[tuple[str, Kline], ...],
    rules: Mapping[str, VenueRules],
    scenario: str,
    *,
    source_refs: tuple[str, ...],
    grid_spacing: tuple[tuple[str, Decimal], ...] = (),
    resting: tuple[RestingBuy, ...] = (),
    unpriced: tuple[str, ...] = (),
) -> PortfolioInterval:
    """Settle stops and portfolio closes before proceeding to later phase marks.

    Within a phase old stops execute in symbol order against the previously available
    other-asset marks, then the full vector advances together to the vertex. Any
    resulting portfolio close is settled immediately at that available vector. A close
    or cut-back of another asset forced at a sub-event (a buy, stop or target inside a
    phase) keeps those marks but executes at that asset's own stop when it is touched
    in this phase and not yet executed, else at the adverse one of its quote at the
    start of the phase and its vertex at the end: no favorable intrabar choice.
    Venue maximums split reductions; minimum-size dust remains valued and owned,
    keeps its close obligation and is reported as retained dust, not a failure.
    A finite 10,000-fill safety budget fails incomplete rather than looping without
    bound on malformed or impractically tiny venue order limits.
    Grid spacing must come from retained admitted geometry; the full strategy
    coordinator binds that provenance. Targets derive from actual lot entry prices
    and apply only to lots held at open. A resting limit buy fills at its limit,
    with no favorable gap credit, at the first vertex at or below it, before that
    vertex's stop; its lot can be stopped in the same bar but earns no target.
    Active pending children are not obligations; canceled unreconciled ones are.
    Holdings named in ``unpriced`` have no bar this interval: they get no path and
    no fill of any kind, keep their last mark, and their obligations are carried to
    a later priced boundary instead of failing (missing bars preserve close
    obligations, never fills). They supply no bar and need no filters here.
    """
    terms = {row[0].symbol: row for row in engine.held_execution_terms()}
    if not _resting_valid(resting, terms):
        raise ValueError("valid unique spot-grid resting buys required")
    resting_symbols = {row.symbol for row in resting}
    if (
        not isinstance(unpriced, tuple)
        or any(
            not isinstance(symbol, str) or symbol not in terms or symbol in resting_symbols
            for symbol in unpriced
        )
        or len(set(unpriced)) != len(unpriced)
    ):
        raise ValueError("unpriced symbols must be distinct holdings without resting buys")
    symbols = (set(terms) | resting_symbols) - set(unpriced)
    if (
        not isinstance(bars, tuple)
        or not bars
        or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in bars)
        or any(not isinstance(symbol, str) or not isinstance(bar, Kline) for symbol, bar in bars)
        or len({symbol for symbol, _ in bars}) != len(bars)
        or {symbol for symbol, _ in bars} != symbols
        or any(not isinstance(rules.get(symbol), VenueRules) for symbol in symbols)
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
            or not _positive(pair[1])
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
    basket_stop = {row.symbol: row.stop for row in resting}

    def stop_of(symbol: str) -> Decimal:
        return terms[symbol][1] if symbol in terms else basket_stop[symbol]

    def side_of(symbol: str) -> int:
        return 1 if symbol not in terms or terms[symbol][0].quantity > 0 else -1

    paths = tuple(
        (
            symbol,
            plan_held_path(
                market[symbol],
                scenario,
                side=side_of(symbol),
                stop=stop_of(symbol),
                source_refs=source_refs,
            ),
        )
        for symbol in sorted(symbols)
    )
    # Each asset's planned stop fill by phase; the path already applies gap handling.
    stop_prices = {
        (symbol, event.phase): event.price
        for symbol, path in paths
        for event in path.events
        if event.kind == "stop"
    }
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
        for symbol in sorted(grid_symbols & symbols)
        for lot in sorted(terms[symbol][0].lots, key=lambda item: (item.entry_price, item.lot_id))
    )
    now = paths[0][1].interval_end_ms
    prefix = f"portfolio:{paths[0][1].interval_start_ms}:{scenario}"
    quotes = {symbol: Quote(market[symbol].open, now) for symbol in symbols}
    # The current phase's quotes before any of its sub-events, and the assets whose
    # stop has executed in it.
    opening = dict(quotes)
    stopped: set[str] = set()
    observations: list[PortfolioObservation] = []
    fills: list[FillEvent] = []
    filled: list[str] = []
    pending = sorted(resting, key=lambda row: (row.symbol, -row.limit, row.child_id))
    failure = None
    dust: tuple[str, ...] = ()
    sequence = 0

    def observe(phase: str) -> EngineSnapshot:
        nonlocal sequence
        snapshot = engine.observe(now, quotes, rules)
        sequence += 1
        observations.append(PortfolioObservation(now, phase, f"{prefix}:mark:{sequence}", snapshot))
        return snapshot

    def settled(identity: str, phase: str) -> None:
        booked = engine.booked_fill(identity)
        if booked is not None:
            fills.append(booked)
        observations.extend(
            PortfolioObservation(now, phase, f"{identity}:{index}:{row.phase}", row.snapshot)
            for index, row in enumerate(engine.settlement_observations(identity))
        )

    def reduce(
        symbol: str,
        phase: str,
        lot_id: str | None = None,
        execution_reference: Decimal | None = None,
        keep: Decimal | None = None,
    ) -> bool:
        nonlocal sequence
        current = {row[0].symbol: row for row in engine.held_execution_terms()}
        if symbol not in current or symbol not in market:
            return False  # an unpriced holding cannot execute
        position, _, fee, slip = current[symbol]
        quantity = abs(position.quantity)
        if lot_id is not None:
            lot = next((lot for lot in position.lots if lot.lot_id == lot_id), None)
            if lot is None:
                return False
            quantity = abs(lot.quantity)
        side = -1 if position.quantity > 0 else 1
        quote = quotes[symbol].price if execution_reference is None else execution_reference
        if keep is not None:
            reduction = executable_trim(
                quantity, keep, quote, rules[symbol], side=side, slippage=slip
            )
        else:
            reduction = executable_reduction(
                quantity, quote, rules[symbol], side=side, slippage=slip
            )
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
            settled(identity, phase)
        return True

    def buy(row: RestingBuy, phase: str) -> None:
        nonlocal sequence
        if len(fills) >= 10_000:
            raise ValueError("protective fill budget exhausted")
        sequence += 1
        identity = f"{prefix}:buy:{sequence}:{row.child_id}"
        if engine.booked_fill(identity) is not None:
            raise ValueError("modeled execution identity already booked")
        # A gap below the limit never traded at the limit: the fill keeps its limit
        # price, but the position is valued at the actual open (Codex 4242566607).
        # Within a bar the modeled path passes through the limit, so it is the mark.
        gapped = phase.startswith("open")
        quotes[row.symbol] = Quote(market[row.symbol].open if gapped else row.limit, now)
        fill = FillEvent(
            identity,
            now,
            row.symbol,
            "spot_grid",
            "spot",
            1,
            row.quantity,
            row.limit,
            _decimal(Fraction(row.quantity) * Fraction(row.limit) * Fraction(row.fee_rate)),
            row.child_id,
        )
        try:
            engine.settle(identity, now, quotes, rules, increases=((row.intent_id, fill),))
        finally:
            settled(identity, phase)
        if engine.booked_fill(identity) is not None:
            filled.append(row.child_id)

    def forced_reference(symbol: str, phase: str) -> Decimal:
        """Where another asset's reduction forced at a sub-event of ``phase`` executes.

        Its own stop, touched in this phase and not yet executed, fills when touched,
        so an earlier forced exit is no worse; otherwise the adverse one of its quote
        at the start of the phase and its vertex at the end of it.
        """
        own = stop_prices.get((symbol, phase))
        if own is not None and symbol not in stopped:
            return own
        vertex: Decimal = getattr(market[symbol], phase)
        ends = (opening[symbol].price, vertex)
        return min(ends) if side_of(symbol) == 1 else max(ends)

    def drain(phase: str, snapshot: EngineSnapshot, trigger: str | None = None) -> EngineSnapshot:
        """Settle obligations; at a sub-event, ``trigger`` is the asset whose event it is."""

        def reference(symbol: str) -> Decimal | None:
            if trigger is None or symbol == trigger or symbol not in market:
                return None  # vertex drains and the triggering asset keep their quote
            return forced_reference(symbol, phase.split(":")[0])

        # Full closes first, then cut-backs to their targets (owner decision 2026-10-11).
        while snapshot.close_required or snapshot.reduce_to:
            progressed = False
            targets = {s: k for s, k in snapshot.reduce_to if s not in snapshot.close_required}
            for symbol in sorted(snapshot.close_required):
                progressed = (
                    reduce(symbol, phase, execution_reference=reference(symbol)) or progressed
                )
            for symbol, kept in sorted(targets.items()):
                progressed = (
                    reduce(symbol, phase, execution_reference=reference(symbol), keep=kept)
                    or progressed
                )
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
            opening, stopped = dict(quotes), set()
            if phase == "open":
                drain(phase, observe(phase))
            # A canceled basket (a close request cancels its pending order) stops resting.
            active = {a.intent_id for a in engine.reservations}
            for row in tuple(pending):
                vertex = getattr(market[row.symbol], phase)
                if row.intent_id not in active:
                    pending.remove(row)
                elif vertex <= row.limit:
                    pending.remove(row)
                    buy(row, f"{phase}:buy")
                    drain(f"{phase}:buy", observations[-1].snapshot, row.symbol)
                    active = {a.intent_id for a in engine.reservations}
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
                stopped.add(symbol)
                drain(f"{phase}:stop", observe(f"{phase}:stop"), symbol)
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
                drain(f"{phase}:target", observe(f"{phase}:target"), symbol)
                while reduce(symbol, f"{phase}:target", lot_id, targets[0].price):
                    drain(f"{phase}:target", observations[-1].snapshot, symbol)
            if phase != "open":
                quotes = {symbol: Quote(getattr(bar, phase), now) for symbol, bar in market.items()}
                drain(phase, observe(phase))
        final = observations[-1].snapshot
        dust = engine.close_dust(rules)
        active = {a.intent_id for a in engine.reservations}
        if set(final.close_required) - set(dust) - set(unpriced) or any(
            key not in active for key in final.unresolved_execution
        ):
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
        paths,
        tuple(observations),
        tuple(fills),
        failure,
        tuple(sorted(grid_spacing)),
        dust,
        tuple(filled),
    )
