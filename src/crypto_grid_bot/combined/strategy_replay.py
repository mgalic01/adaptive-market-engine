"""One complete V3.1 strategy replay over a single shared account.

One run is one component arm, one modeled scenario, one capital, one cost profile
and one window, over in-memory, already registered inputs. Nothing is fetched, no
order leaves this process, and the run never retries. Frozen V0-V3 baselines have
their own adapters; this driver refuses them.

Each hourly boundary T is processed in the owner-approved order:

1. the previous bar's modeled intrabar path, stamped at its availability T: old
   stops before targets, resting grid buys before that vertex's stop, no same-bar
   target for an intrabar purchase (``portfolio_path``);
2. completed-bar management at T: trend reversal and grid range exits become close
   obligations, and trailing stops tighten from completed information only. The
   path already executed every old stop, so management never executes one again;
3. the boundary frame at T: funding due at T on the holdings that survived the
   previous interval, then every legal protective reduction at the bar's opening
   quote (``boundary_execution``), then entry decisions in symbol order, trend
   opening fills at the same opening quote and grid basket placement.

The terminal boundary marks the last bar's close and excludes next-window funding,
management and entries. Engine timestamps denote availability, not intrabar times.
"""

from bisect import bisect_right
from dataclasses import dataclass, field, replace
from decimal import Decimal

from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.market_data.parsing import symbol_name

from .account import FillEvent, FundingEvent
from .allocation import allocate_grid
from .arms import arm_settings
from .assessment import AssessmentSeries
from .boundary_execution import BoundaryExecution, BoundaryExecutor, FundingFixing
from .correlation import correlation_groups
from .decisions import Costs, DecisionCoordinator, DecisionResult, FundingEstimate, VenueInputs
from .engine import EngineSnapshot, PortfolioEngine, Quote, SettlementObservation
from .evidence import DecisionEvent, Evidence
from .execution import VenueRules
from .experiment import SCENARIOS
from .lifecycle import manage
from .models import Assessment
from .portfolio_path import PortfolioObservation, RestingBuy, replay_held_portfolio
from .protection import ProtectionState, manage_completed_bar
from .routing import FlowGate, completed_flow, qualify

HOUR = 3_600_000
FOUR_HOURS = 4 * HOUR
DAY = 24 * HOUR
_RESERVED = 1_735_689_600_000
_TREND = frozenset({"spot_trend", "futures_trend"})
# Opening refusals that leave nothing booked: the admission is canceled and final.
_OPENING_REFUSALS = frozenset(
    {
        "opening_admission_no_longer_active",
        "opening_protection_unresolved",
        "opening_current_held_market_required",
    }
)


@dataclass(frozen=True, slots=True)
class VenueMarket:
    """Complete hourly bars of one venue, with its pinned filters and costs."""

    hourly: tuple[Kline, ...]
    rules: VenueRules
    costs: Costs


@dataclass(frozen=True, slots=True)
class SymbolMarket:
    """Registered inputs of one asset. Spot drives the causal assessment."""

    symbol: str
    spot: VenueMarket
    daily: tuple[Kline, ...]
    futures: VenueMarket | None = None
    funding: tuple[FundingRecord, ...] = ()
    minutes: tuple[Kline, ...] = ()


@dataclass(frozen=True, slots=True)
class ReplayRun:
    arm: str
    scenario: str
    initial_cash: Decimal
    start_ms: int
    end_ms: int
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NativeObservation:
    """One retained engine mark; ``kind`` is frame, path or terminal."""

    timestamp_ms: int
    id: str
    kind: str
    phase: str
    event_id: str
    snapshot: EngineSnapshot


@dataclass(frozen=True, slots=True)
class BoundaryMark:
    """Every observation at one hourly boundary, in booking order."""

    timestamp_ms: int
    role: str
    interval_start_ms: int
    interval_end_ms: int
    observation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TraceFill:
    """A booked fill with its lifecycle role and attribution."""

    fill: FillEvent
    increase: bool
    exit_reason: str | None
    regime: str | None


@dataclass(frozen=True, slots=True)
class TraceDecision:
    assessment: Assessment
    result: DecisionResult


@dataclass(frozen=True, slots=True)
class StrategyTrace:
    run: ReplayRun
    observations: tuple[NativeObservation, ...]
    boundaries: tuple[BoundaryMark, ...]
    events: tuple[TraceFill | FundingEvent, ...]
    decisions: tuple[TraceDecision, ...]
    evidence: tuple[DecisionEvent, ...]
    finality: tuple[tuple[str, tuple[str, ...]], ...]
    releases: tuple[tuple[str, tuple[tuple[Decimal, tuple[str, ...]], ...]], ...]
    retained_dust: tuple[str, ...]
    failure: str | None


@dataclass
class _Book:
    intent_id: str
    spacing: Decimal
    regime: str
    opportunity: str
    prefix: str
    pending: dict[str, RestingBuy] = field(default_factory=dict)
    cycled: bool = False  # some child filled: a later flat state is a completed cycle


def _sealed(stamps: list[int], what: str) -> None:
    """Data at or after the reserved boundary stays sealed: refuse it, never ignore it."""
    if any(type(stamp) is not int or stamp >= _RESERVED for stamp in stamps):
        raise ValueError(f"{what}: input at or after the reserved boundary is refused")


def _bars(rows: tuple[Kline, ...], start: int, end: int, what: str) -> dict[int, Kline]:
    """Index bars; only the window's own hours must be structurally sound.

    History before the window is checked causally by the assessment, and bars after
    the window are never read, so defects there cannot change this run.
    """
    if not isinstance(rows, tuple) or any(not isinstance(row, Kline) for row in rows):
        raise ValueError(f"{what}: immutable klines required")
    _sealed([row.open_ms for row in rows], what)
    stamps = [row.open_ms for row in rows if start <= row.open_ms < end]
    if any(stamp % HOUR for stamp in stamps) or stamps != sorted(set(stamps)):
        raise ValueError(f"{what}: unique sorted hourly bars required")
    indexed = {row.open_ms: row for row in rows if start <= row.open_ms < end}
    if any(hour not in indexed for hour in range(start, end, HOUR)):
        raise ValueError(f"{what}: every window hour is required")
    return indexed


def _funding(
    records: tuple[FundingRecord, ...], start: int, end: int, symbol: str
) -> tuple[FundingRecord, ...]:
    """Every settlement the window needs must be on record: none is assumed zero.

    Needed are the latest record at or before the start (the first estimate) through
    the last slot before the end. Older history and later records are not read, so a
    defect there cannot change this run (Codex 4242566622).
    """
    if not isinstance(records, tuple) or not records:
        raise ValueError(f"{symbol}: funding records required with futures inputs")
    if any(not isinstance(r, FundingRecord) for r in records):
        raise ValueError(f"{symbol}: funding records required with futures inputs")
    _sealed([r.calc_time_ms for r in records], f"{symbol} funding")
    ordered = sorted(records, key=lambda r: r.calc_time_ms)
    starts = [r for r in ordered if r.scheduled_ms <= start]
    if not starts:
        raise ValueError(f"{symbol}: funding records must cover the whole window")
    needed = [r for r in ordered if starts[-1].scheduled_ms <= r.scheduled_ms < end]
    if any(not r.valid for r in needed):
        raise ValueError(f"{symbol}: valid funding records required")
    slots = [r.scheduled_ms for r in needed]
    if len(set(slots)) != len(slots):
        raise ValueError(f"{symbol}: duplicate funding slot")
    for before, after in zip(needed, needed[1:], strict=False):
        if after.scheduled_ms - before.scheduled_ms != (before.interval_hours or 0) * HOUR:
            raise ValueError(f"{symbol}: funding schedule has a gap or cadence change")
    last = needed[-1]
    if last.scheduled_ms + (last.interval_hours or 0) * HOUR < end:
        raise ValueError(f"{symbol}: funding records must cover the whole window")
    return tuple(needed)


def _validate(run: ReplayRun, markets: tuple[SymbolMarket, ...], futures_required: bool) -> None:
    if (
        not isinstance(run, ReplayRun)
        or run.scenario not in SCENARIOS
        or not isinstance(run.initial_cash, Decimal)
        or not run.initial_cash.is_finite()
        or not 0 < run.initial_cash <= Decimal("1e36")
        or type(run.start_ms) is not int
        or type(run.end_ms) is not int
        or run.start_ms % DAY
        or run.end_ms % DAY
        # A window may end AT the reserved boundary: its last bar is development data.
        or not 0 <= run.start_ms < run.end_ms <= _RESERVED
        or not isinstance(run.source_refs, tuple)
        or not run.source_refs
        or any(not isinstance(ref, str) or not ref.strip() for ref in run.source_refs)
    ):
        raise ValueError("valid pre-reserved UTC-day run identity required")
    if (
        not isinstance(markets, tuple)
        or not markets
        or any(not isinstance(m, SymbolMarket) for m in markets)
        or len({m.symbol for m in markets}) != len(markets)
    ):
        raise ValueError("unique symbol markets required")
    for market in markets:
        symbol_name(market.symbol)
        for venue in (market.spot, market.futures):
            if venue is not None and (
                not isinstance(venue, VenueMarket)
                or not isinstance(venue.rules, VenueRules)
                or not isinstance(venue.costs, Costs)
            ):
                raise ValueError(f"{market.symbol}: venue rules and costs required")
        _bars(market.spot.hourly, run.start_ms, run.end_ms, f"{market.symbol} spot")
        if market.futures is None and futures_required:
            # A futures-enabled arm judges its whole registered universe (Codex 4242566627).
            raise ValueError(f"{market.symbol}: futures inputs required by this arm")
        if market.futures is not None:
            _bars(market.futures.hourly, run.start_ms, run.end_ms, f"{market.symbol} futures")
            _funding(market.funding, run.start_ms, run.end_ms, market.symbol)
        elif market.funding:
            raise ValueError(f"{market.symbol}: funding without futures inputs")
        if not isinstance(market.daily, tuple) or not isinstance(market.minutes, tuple):
            raise ValueError(f"{market.symbol}: immutable daily and minute inputs required")
        if any(not isinstance(bar, Kline) for bar in (*market.daily, *market.minutes)):
            raise ValueError(f"{market.symbol}: daily and minute klines required")
        _sealed([bar.open_ms for bar in market.daily], f"{market.symbol} daily")
        _sealed([bar.open_ms for bar in market.minutes], f"{market.symbol} minutes")


def _regime(assessment: Assessment) -> str:
    return f"{assessment.daily}/{assessment.four_hour}/{assessment.structure}"


def replay_strategy(run: ReplayRun, markets: tuple[SymbolMarket, ...]) -> StrategyTrace:
    """Replay one registered run once; every failure is retained, never retried.

    Input defects raise before the first mutation. After that, an execution or
    integrity failure, a liquidation or an unresolvable obligation stops the run
    and is returned with everything observed until then.
    """
    if not isinstance(run, ReplayRun):
        raise ValueError("replay run identity required")
    settings = arm_settings(run.arm)
    _validate(run, markets, settings.routing.futures_trend)
    by_symbol = {m.symbol: m for m in markets}
    symbols = sorted(by_symbol)
    spot = {s: _bars(by_symbol[s].spot.hourly, run.start_ms, run.end_ms, s) for s in symbols}
    futures = {
        s: _bars(m.futures.hourly, run.start_ms, run.end_ms, s)
        for s, m in by_symbol.items()
        if m.futures is not None
    }
    needed = {s: _funding(by_symbol[s].funding, run.start_ms, run.end_ms, s) for s in futures}
    funding_at = {s: {r.scheduled_ms: r for r in needed[s]} for s in futures}
    published = {s: sorted(needed[s], key=lambda r: r.usable_ms) for s in futures}
    published_ms = {s: [r.usable_ms for r in published[s]] for s in futures}
    series = {s: AssessmentSeries(s, by_symbol[s].spot.hourly, by_symbol[s].daily) for s in symbols}
    daily = {s: by_symbol[s].daily for s in symbols}
    gates = {s: FlowGate() for s in symbols}
    minute_index = {s: {bar.open_ms: bar for bar in by_symbol[s].minutes} for s in symbols}
    engine = PortfolioEngine(
        run.initial_cash,
        automatic_recovery=settings.automatic_recovery,
        simulated_venue=True,
    )
    evidence = Evidence()
    coordinator = DecisionCoordinator(engine, evidence)
    executor = BoundaryExecutor(engine)
    refs = run.source_refs
    observations: list[NativeObservation] = []
    boundaries: list[BoundaryMark] = []
    events: list[TraceFill | FundingEvent] = []
    decisions: list[TraceDecision] = []
    books: dict[str, _Book] = {}
    protection: dict[str, ProtectionState] = {}
    groups_by_day: dict[int, tuple[tuple[str, str], ...]] = {}
    pending_ids: list[str] = []
    dust: tuple[str, ...] = ()

    def venue_bar(symbol: str, venue: str, hour: int) -> Kline:
        return (spot if venue == "spot" else futures)[symbol][hour]

    def venue_rules(symbol: str, venue: str) -> VenueRules:
        market = by_symbol[symbol]
        source = market.spot if venue == "spot" else market.futures
        if source is None:
            raise ValueError("held venue has no registered inputs")
        return source.rules

    def held_market(
        hour: int, price: str = "open", stamp: int | None = None
    ) -> tuple[dict[str, Quote], dict[str, VenueRules]]:
        quotes, rules = {}, {}
        for position, *_ in engine.held_execution_terms():
            row = venue_bar(position.symbol, position.venue, hour)
            quotes[position.symbol] = Quote(getattr(row, price), hour if stamp is None else stamp)
            rules[position.symbol] = venue_rules(position.symbol, position.venue)
        return quotes, rules

    def record(rows: tuple[SettlementObservation, ...], hour: int, kind: str) -> None:
        for row in rows:
            identity = f"{kind}:{hour}:{len(observations)}:{row.phase}"
            observations.append(
                NativeObservation(hour, identity, kind, row.phase, row.event_id, row.snapshot)
            )
            pending_ids.append(identity)

    def record_marks(rows: list[EngineSnapshot], hour: int, source: str) -> None:
        for snapshot in rows:
            identity = f"frame:{hour}:{len(observations)}:decision"
            observations.append(
                NativeObservation(hour, identity, "frame", "decision", source, snapshot)
            )
            pending_ids.append(identity)

    def record_path(rows: tuple[PortfolioObservation, ...], stamp: int) -> None:
        for row in rows:
            observations.append(
                NativeObservation(stamp, row.id, "path", row.phase, row.id, row.snapshot)
            )
            pending_ids.append(row.id)

    def reasons_before(rows: tuple[SettlementObservation, ...], fill: FillEvent) -> str | None:
        for before, row in zip(rows, rows[1:], strict=False):
            if row.phase == "reduction" and row.event_id == fill.event_id:
                why = dict(before.snapshot.close_reasons).get(fill.symbol, ())
                return "+".join(why) if why else None
        return None

    def finalize(hour: int) -> None:
        # The replay is the only source of simulated fills, so a canceled order
        # can never fill later: its finality is established by this process.
        for key in engine.canceled_unreconciled:
            engine.acknowledge_finality(key, source_refs=(f"replay:simulated-cancel:{hour}",))
        active = {a.intent_id for a in engine.reservations}
        held = {p.symbol for p, *_ in engine.held_execution_terms()}
        for symbol in tuple(books):
            if books[symbol].intent_id not in active:
                books[symbol].pending.clear()
            if symbol not in held and not books[symbol].pending:
                del books[symbol]
        for symbol in tuple(protection):
            if symbol not in held:
                del protection[symbol]

    def estimate(symbol: str, hour: int) -> FundingEstimate | None:
        index = bisect_right(published_ms[symbol], hour)
        if not index:
            return None
        latest = published[symbol][index - 1]
        return FundingEstimate(latest.rate, latest.usable_ms, (latest.interval_hours or 0) * HOUR)

    def interval(hour: int) -> str | None:
        """Bar [hour, hour+1h), stamped at its availability hour+1h."""
        nonlocal dust
        held = {p.symbol: p for p, *_ in engine.held_execution_terms()}
        resting = tuple(row for book in books.values() for row in book.pending.values())
        need = set(held) | {row.symbol for row in resting}
        if not need:
            return None
        venues = {s: held[s].venue if s in held else "spot" for s in need}
        result = replay_held_portfolio(
            engine,
            tuple((s, venue_bar(s, venues[s], hour)) for s in sorted(need)),
            {s: venue_rules(s, venues[s]) for s in need},
            run.scenario,
            source_refs=refs,
            grid_spacing=tuple(
                (s, books[s].spacing) for s in sorted(held) if held[s].owner == "spot_grid"
            ),
            resting=resting,
        )
        stamp = hour + HOUR
        record_path(result.observations, stamp)
        by_id = {row.id: row for row in result.observations}
        for fill in result.fills:
            increase = fill.side == 1 and fill.owner == "spot_grid" and ":buy:" in fill.event_id
            reason = None
            if not increase:
                before = by_id.get(f"{fill.event_id}:0:before")
                why = dict(before.snapshot.close_reasons).get(fill.symbol, ()) if before else ()
                if fill.lot_id and before is not None and before.phase.endswith(":target"):
                    reason = "grid_target"
                else:
                    reason = "+".join(why) if why else None
            book = books.get(fill.symbol) if increase else None
            events.append(TraceFill(fill, increase, reason, book.regime if book else None))
            if book is not None and fill.lot_id is not None:
                evidence.record(
                    DecisionEvent(
                        f"{book.prefix}:filled:{fill.lot_id}",
                        book.opportunity,
                        stamp,
                        fill.symbol,
                        "filled",
                        True,
                        (),
                        (
                            ("fill_id", fill.event_id),
                            ("child_id", fill.lot_id),
                            ("quantity", str(fill.quantity)),
                            ("price", str(fill.price)),
                        ),
                        refs,
                    )
                )
        for child in result.filled_children:
            for book in books.values():
                if book.pending.pop(child, None) is not None:
                    book.cycled = True
        dust = result.retained_dust
        finalize(stamp)
        return result.failure

    def management(hour: int) -> None:
        """Completed-bar obligations at ``hour``; they execute in the next frame."""
        # The path's last mark at ``hour`` is the current state; observing again
        # without venue filters would wrongly mark every holding stale.
        latest = observations[-1].snapshot if observations else None
        for position, stop, _fee, slippage in engine.held_execution_terms():
            symbol, side = position.symbol, 1 if position.quantity > 0 else -1
            if position.owner not in _TREND:
                continue
            assessment = series[symbol].at(hour, hour)
            decision = manage(
                assessment,
                position.owner,
                side,
                short_qualification=settings.routing.short_qualification,
            )
            if decision.close_reason is not None:
                engine.request_close(symbol, position.owner, side, reason=decision.close_reason)
                continue
            if (
                not settings.trailing
                or latest is None
                or symbol in latest.close_required
                or symbol not in protection
            ):
                continue
            state, _ = manage_completed_bar(
                protection[symbol],
                venue_bar(symbol, position.venue, hour - HOUR),
                atr=assessment.atr,
                atr_fresh=assessment.four_hour_closed_ms == hour // FOUR_HOURS * FOUR_HOURS,
                slippage=slippage,
                trailing=True,
            )
            protection[symbol] = state
            if (state.stop - stop) * side > 0:
                engine.tighten_stop(symbol, position.owner, side, state.stop)
        held = {p.symbol for p, *_ in engine.held_execution_terms()}
        for symbol, book in sorted(books.items()):
            decision = manage(series[symbol].at(hour, hour), "spot_grid", 1)
            if decision.close_reason is not None:
                engine.request_close(symbol, "spot_grid", 1, reason=decision.close_reason)
                book.pending.clear()
            elif book.cycled and symbol not in held and book.pending:
                # Ruling (spec "Rebuild only flat"): a basket back to flat after a
                # completed cycle is withdrawn, so the next decision can rebuild it
                # at the current price; an untouched basket keeps its levels.
                engine.cancel(book.intent_id)
                book.pending.clear()
        finalize(hour)

    def frame(hour: int) -> str | None:
        day = hour // DAY
        if day not in groups_by_day:
            groups_by_day[day] = correlation_groups(daily, hour)
        engine.set_correlation_groups(groups_by_day[day])
        quotes, rules = held_market(hour)
        for position, stop, _fee, _slip in engine.held_execution_terms():
            side = 1 if position.quantity > 0 else -1
            price = quotes[position.symbol].price
            if (price <= stop) if side == 1 else (price >= stop):
                engine.request_close(position.symbol, position.owner, side, reason="stop")
        due = tuple(s for s in sorted(futures) if hour in funding_at[s])
        fixings = tuple(
            FundingFixing(
                f"funding:{s}:{funding_at[s][hour].calc_time_ms}",
                s,
                hour,
                funding_at[s][hour].rate,
                futures[s][hour].open,
            )
            for s in due
        )
        boundary = executor.settle(
            f"frame:{hour}",
            hour,
            quotes,
            rules,
            due_funding=due,
            fixings=fixings,
            source_refs=refs,
        )
        failure = settled(boundary, hour)
        if failure is not None:
            return failure
        finalize(hour)
        minute = hour // 60_000 * 60_000
        for symbol in symbols:
            index = minute_index[symbol]
            window = tuple(
                index[stamp]
                for stamp in range(minute - 15 * 60_000, minute, 60_000)
                if stamp in index
            )
            gates[symbol].update(completed_flow(window, hour))
        for symbol in symbols:
            failure = decide(symbol, hour, groups_by_day[day])
            if failure is not None:
                return failure
        # Obligations created by this frame's entries (post-fill cut-backs) execute
        # at the same opening quote, not an hour later (critic minor 2).
        quotes, rules = held_market(hour)
        latest = observations[-1].snapshot
        sellable = set(latest.close_required) | {s for s, _ in latest.reduce_to}
        if sellable - set(engine.close_dust(rules)):
            return settled(
                executor.settle(
                    f"frame:{hour}:post-entry",
                    hour,
                    quotes,
                    rules,
                    due_funding=(),
                    fixings=(),
                    source_refs=refs,
                ),
                hour,
            )
        return None

    def settled(boundary: BoundaryExecution, hour: int) -> str | None:
        record(boundary.observations, hour, "frame")
        events.extend(boundary.funding)
        for fill in boundary.fills:
            events.append(TraceFill(fill, False, reasons_before(boundary.observations, fill), None))
        return boundary.failure

    def owned() -> set[str]:
        held = {p.symbol for p, *_ in engine.held_execution_terms()}
        return held | set(books)

    def decide(symbol: str, hour: int, groups: tuple[tuple[str, str], ...]) -> str | None:
        # One strategy owns an asset: held inventory or a resting grid basket.
        if symbol in owned():
            return None
        market = by_symbol[symbol]
        assessment = series[symbol].at(hour, hour)
        routing = replace(settings.routing, flow_allowed=gates[symbol].allowed)
        if qualify(assessment, routing).side == 0:
            return None  # No directional or range signal: nothing is detected.
        quotes, rules = held_market(hour)
        spot_inputs = VenueInputs(
            market.spot.rules, market.spot.costs, quote=Quote(spot[symbol][hour].open, hour)
        )
        futures_inputs = (
            None
            if market.futures is None
            else VenueInputs(
                market.futures.rules,
                market.futures.costs,
                funding=estimate(symbol, hour),
                funding_admission=settings.funding_admission,
                quote=Quote(futures[symbol][hour].open, hour),
            )
        )
        opportunity = f"{symbol}:{hour}"
        with engine.capture_marks() as marks:
            result = coordinator.decide(
                opportunity,
                assessment,
                routing,
                quotes,
                spot_inputs,
                futures_inputs,
                refs,
                position_rules=rules,
                groups=groups,
            )
        record_marks(marks, hour, f"decision:{opportunity}")
        decisions.append(TraceDecision(assessment, result))
        intent, admission = result.intent, result.admission
        if intent is None or admission is None or not admission.accepted:
            return None
        if intent.owner in _TREND:
            with engine.capture_marks() as marks:
                opening = coordinator.execute_opening(opportunity, quotes, rules)
            record_marks(marks, hour, f"opening:{opportunity}")
            record(opening.observations, hour, "frame")
            if opening.fill is not None:
                events.append(TraceFill(opening.fill, True, None, _regime(assessment)))
                protection[symbol] = ProtectionState(
                    intent.side,
                    opening.fill.price,
                    intent.stop,
                    intent.stop,
                    opening.fill.price,
                    False,
                )
            if opening.failure is not None:
                if opening.fill is None and opening.failure in _OPENING_REFUSALS:
                    _withdraw(intent.intent_id, symbol, hour, opportunity, opening.failure)
                    return None
                return opening.failure
            return None
        allocation = allocate_grid(result)
        if not allocation.accepted:
            _withdraw(intent.intent_id, symbol, hour, opportunity, allocation.reason)
            return None
        engine.release_unallocated(
            intent.intent_id,
            allocation.quantity,
            source_refs=(f"replay:grid-allocation:{intent.intent_id}",),
        )
        plan = result.plan
        if plan is None or plan.spacing is None:
            raise ValueError("admitted grid basket lacks its geometry")
        books[symbol] = _Book(
            intent.intent_id,
            plan.spacing,
            _regime(assessment),
            opportunity,
            f"{len(opportunity)}:{opportunity}",
            {
                child.child_id: RestingBuy(
                    intent.intent_id,
                    child.child_id,
                    symbol,
                    child.limit,
                    child.quantity,
                    intent.fee_rate,
                    intent.stop,
                )
                for child in allocation.children
            },
        )
        return None

    def _withdraw(intent_id: str, symbol: str, hour: int, opportunity: str, why: str) -> None:
        engine.cancel(intent_id)  # final at once: this replay is the only venue
        evidence.record(
            DecisionEvent(
                f"{len(opportunity)}:{opportunity}:filled:refused",
                opportunity,
                hour,
                symbol,
                "filled",
                False,
                (why,),
                (),
                refs,
            )
        )

    def boundary(hour: int, role: str) -> None:
        start = hour - HOUR if role == "terminal" else hour
        boundaries.append(BoundaryMark(hour, role, start, start + HOUR, tuple(pending_ids)))
        pending_ids.clear()

    failure: str | None = None
    try:
        for hour in range(run.start_ms, run.end_ms, HOUR):
            if hour > run.start_ms:
                failure = interval(hour - HOUR)
                if failure is not None:
                    break
                management(hour)
            failure = frame(hour)
            boundary(hour, "opening" if hour == run.start_ms else "settled")
            if failure is not None:
                break
        if failure is None:
            failure = interval(run.end_ms - HOUR)
        if failure is None:
            quotes, rules = held_market(run.end_ms - HOUR, "close", run.end_ms)
            batch = f"terminal:{run.end_ms}"
            engine.settle(batch, run.end_ms, quotes, rules)
            record(engine.settlement_observations(batch), run.end_ms, "terminal")
            boundary(run.end_ms, "terminal")
    except (ValueError, ArithmeticError) as exc:
        # Execution, accounting and data failures are retained run outcomes; anything
        # else is a programming defect and propagates loudly instead.
        failure = f"replay_failure:{type(exc).__name__}:{exc}"
    return StrategyTrace(
        run,
        tuple(observations),
        tuple(boundaries),
        tuple(events),
        tuple(decisions),
        evidence.events,
        engine.finality_evidence,
        engine.release_evidence,
        dust,
        failure,
    )
