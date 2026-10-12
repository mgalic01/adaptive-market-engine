"""One complete V3.1 strategy replay over a single shared account.

One run is one component arm, one modeled scenario, one capital, one cost profile
and one window, over in-memory, already registered inputs. Nothing is fetched, no
order leaves this process, and the run never retries. Frozen V0-V3 baselines have
their own adapters; this driver refuses them.

A grid-enabled arm needs each coin's minute input for the flow gate. A coin with no
minute bar at all in the gate's read range is a missing grid input: the replay still
runs (its trend components are unaffected) but the trace names the coin and the
report is incomplete. A sparse gap inside a present input only makes unavailable (so
blocked) the minutes whose fifteen-minute flow window it falls in.

A venue's hourly input may miss window hours: these data gaps are listed in the trace
and never stop the run. A coin without its bar gets no fill of any kind in that bar
and no quote at that boundary: its entry decision is refused for want of a quote and
is never routed to the other venue, and a holding keeps its last mark, which the
engine treats as stale and requires closed. An obligation on a coin without a price
is carried to the opening quote of its next bar. A holding without a bar in the
window's last hour is valued at its last available close, as a stale terminal mark.

Each coin's daily bars are rebuilt from its registered spot hourly bars under the frozen
V3 day rule (``trend.data.hourly_month``): a UTC day's bar aggregates its hours when at
least 20 of the 24 are usable, and a day with fewer has no bar. That day is a gap in the
assessment's daily gaps, and a decision due to read it is unavailable. The assessment and
the correlation groups read only these bars. The supplied daily bars of every day the run
reads (each closed by its last decision hour) must equal them: a mismatch is refused
before the replay starts. Only the day rule is applied. The registered spot hourly input
must already exclude reader-repaired and masked hours, and a window whose spot data
includes a month V3 excludes (more than 17% of its hours missing) must be refused at
registration: the replay does not apply month exclusion.

Funding is charged from the published records alone, whatever their cadence, and
only on futures holdings. A record within a minute of an hour, on either side,
settles on that hour. Any other record is off the hour: it is booked at the next
hour, on the holdings that survived to it, valued at that boundary's price up to an
hour after its own time, and its payment keeps both times. If its holding left during
that hour it is not charged; the trace records it. An off-hour record of the last hour
would book at the terminal boundary, which books no funding, so a holding it charges
stops the run (``funding_record_unbooked``).

Which end of an interval a record's ``interval_hours`` names at a cadence change is
not pinned yet, so the schedule is judged either way. Two consecutive records miss
settlements only when the spacing of their nearest hours (half an hour rounds up)
exceeds both intervals; every hour the earlier one's interval implies from its nearest
hour before the later one is then missing,
never assumed zero, and a futures position held there stops the run
(``funding_record_missing``). Any other pair not exactly one shared interval apart is
irregular: accepted and recorded in the trace. Two records booked at one boundary stop
the run only when that coin is held on futures there (``funding_records_collide``).
A settlement without its futures bar is valued at the last close before it, which the
payment records as a stale mark. Admission reads only the latest record published at
decision time, which at the window's start may predate the window (it is read, never
charged), so a cadence change or a gap refuses futures increases by itself.

Each hourly boundary T is processed in the owner-approved order:

1. the previous bar's modeled intrabar path, stamped at its availability T: old
   stops before targets, resting grid buys before that vertex's stop, no same-bar
   target for an intrabar purchase (``portfolio_path``). The flow gate is checked every
   minute; a symbol whose gate is blocked at the bar's opening or at any minute inside
   the bar has its resting buys withheld for that whole bar, since the path cannot tell
   when the limit was touched: its levels and reservation stay, and held lots keep their
   stops and targets;
2. completed-bar management at T: trend reversal and grid range exits become close
   obligations, and trailing stops tighten from completed information only. The
   path already executed every old stop, so management never executes one again;
3. the boundary frame at T: funding due at T on the holdings that survived the
   previous interval, then every legal protective reduction at the bar's opening
   quote (``boundary_execution``), then entry decisions in symbol order, trend
   opening fills at the same opening quote and grid basket placement.

The terminal boundary marks the last bar's close and excludes next-window funding,
management and entries. Engine timestamps denote availability, not intrabar times.

An unowned coin whose assessment is unavailable (a missing or invalid due bar, a
warm-up) and gives no signal is a refused detection in the funnel, with the
assessment's reasons. One contiguous run of such hours with the same reasons is one
episode: it is detected once, at its first hour, and its record spans to its last.
"""

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field, replace
from decimal import Decimal
from itertools import zip_longest

from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.market_data.parsing import symbol_name

from .account import FillEvent, FundingEvent
from .allocation import allocate_grid
from .arms import arm_settings
from .assessment import AssessmentSeries, daily_bars
from .boundary_execution import BoundaryExecution, BoundaryExecutor, FundingFixing
from .correlation import correlation_groups
from .decisions import Costs, DecisionCoordinator, DecisionResult, FundingEstimate, VenueInputs
from .engine import EngineSnapshot, PortfolioEngine, Quote, SettlementObservation, WorseFill
from .evidence import DecisionEvent, DecisionRecord, Evidence
from .execution import VenueRules
from .experiment import SCENARIOS
from .lifecycle import manage
from .models import Assessment
from .portfolio_path import PortfolioObservation, RestingBuy, replay_held_portfolio
from .protection import ProtectionState, manage_completed_bar
from .routing import MinuteFlowGate, qualify

HOUR = 3_600_000
FOUR_HOURS = 4 * HOUR
DAY = 24 * HOUR
_RESERVED = 1_735_689_600_000
# A funding record more than this from the nearest hour, either side, is off the hour.
_ON_HOUR_MS = 60_000
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
    """Hourly bars of one venue, with its pinned filters and costs."""

    hourly: tuple[Kline, ...]
    rules: VenueRules
    costs: Costs


@dataclass(frozen=True, slots=True)
class SymbolMarket:
    """Registered inputs of one asset. Spot drives the causal assessment.

    ``daily`` must equal the daily bars rebuilt from the spot hourly bars on every day
    the run reads; the replay reads only the rebuilt ones.
    """

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
class TraceUnavailable:
    """One episode of an unavailable assessment with no signal, and its first hour's."""

    assessment: Assessment
    record: DecisionRecord


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
    # Per symbol, the intervals (by opening hour) whose resting grid buys the flow gate
    # withheld: blocked at the interval's opening or at any minute inside it.
    withheld_buys: tuple[tuple[str, tuple[int, ...]], ...]
    # Symbols, sorted, whose minute input has no bar at all in the flow gate's read range
    # although the arm enables the spot grid; the report is incomplete for each.
    missing_grid_inputs: tuple[str, ...]
    # Per symbol and venue, the window hours (bar opens) that have no bar: data gaps.
    data_gaps: tuple[tuple[str, str, tuple[int, ...]], ...]
    # Holdings without a bar in the window's last hour: each was valued at its last
    # available close, recorded here with the time that close became available.
    stale_terminal_marks: tuple[tuple[str, int], ...]
    # Consecutive funding records spaced irregularly with no settlement missing, as
    # (symbol, earlier record's time, its interval hours, later time, its hours).
    funding_schedule_irregular: tuple[tuple[str, int, int, int, int], ...]
    # Off-hour records never charged because the futures holding left during the hour
    # before their booking: (symbol, record time, booking boundary).
    funding_records_unbooked_after_exit: tuple[tuple[str, int, int], ...]
    # Fills booked worse than planned, kept within or cut to their approved risk.
    worse_fills: tuple[WorseFill, ...]
    # Refused detections of unavailable assessments with no signal, one per episode.
    unavailable: tuple[TraceUnavailable, ...]
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
    the window are never read, so defects there cannot change this run. A missing
    window hour is a data gap, not a defect.
    """
    if not isinstance(rows, tuple) or any(not isinstance(row, Kline) for row in rows):
        raise ValueError(f"{what}: immutable klines required")
    _sealed([row.open_ms for row in rows], what)
    stamps = [row.open_ms for row in rows if start <= row.open_ms < end]
    if any(stamp % HOUR for stamp in stamps) or stamps != sorted(set(stamps)):
        raise ValueError(f"{what}: unique sorted hourly bars required")
    return {row.open_ms: row for row in rows if start <= row.open_ms < end}


def _missing_hours(indexed: dict[int, Kline], start: int, end: int) -> tuple[int, ...]:
    return tuple(hour for hour in range(start, end, HOUR) if hour not in indexed)


def _fixing_mark(bars: dict[int, Kline], symbol: str, hour: int) -> tuple[Decimal, int | None]:
    """The futures price that values a settlement booked at ``hour``, and its staleness.

    The bar's opening price; without that bar, the last close before it, a stale mark,
    returned with the time that close became available. Only holdings are charged,
    and a futures holding was opened on an earlier window bar, so such a close exists.
    """
    row = bars.get(hour)
    if row is not None:
        return row.open, None
    earlier = [stamp for stamp in bars if stamp < hour]
    if not earlier:
        raise ValueError(f"{symbol}: funding fixing at {hour} has no earlier futures close")
    last = bars[max(earlier)]
    return last.close, last.open_ms + HOUR


def _nearest_hour(stamp: int) -> int:
    return (stamp + HOUR // 2) // HOUR * HOUR


def _off_hour(record: FundingRecord) -> bool:
    """Settled more than a minute from the nearest hour, on either side."""
    return abs(record.calc_time_ms - _nearest_hour(record.calc_time_ms)) > _ON_HOUR_MS


def _slot_ms(record: FundingRecord) -> int:
    """The hour a record settles: the nearest one, or an off-hour record's own hour."""
    return record.scheduled_ms if _off_hour(record) else _nearest_hour(record.calc_time_ms)


def _booked_ms(record: FundingRecord) -> int:
    """The settlement hour that books a record; an off-hour record books the next hour."""
    return _slot_ms(record) + (HOUR if _off_hour(record) else 0)


def _interval_ms(record: FundingRecord) -> int:
    return (record.interval_hours or 0) * HOUR  # a valid record's interval is positive


def _funding(
    records: tuple[FundingRecord, ...], start: int, end: int, symbol: str
) -> tuple[tuple[FundingRecord, ...], tuple[FundingRecord, ...]]:
    """The records the window settles, and every record it reads, each valid and distinct.

    Settled are the latest record settled at or before the start through the last one
    settled before the end; an off-hour record of the last hour is settled, though it
    books at the end. The schedule itself is the replay's to judge. Admission also reads
    the latest record published at or before the start, the first estimate, which may
    predate the window; the read records are returned in publication order. Two records
    at one time would make the estimate depend on input order. Older history and later
    records are not read, so a defect there cannot change this run (Codex 4242566622).
    """
    if not isinstance(records, tuple) or not records:
        raise ValueError(f"{symbol}: funding records required with futures inputs")
    if any(not isinstance(r, FundingRecord) for r in records):
        raise ValueError(f"{symbol}: funding records required with futures inputs")
    _sealed([r.calc_time_ms for r in records], f"{symbol} funding")
    ordered = sorted(records, key=lambda r: r.calc_time_ms)
    starts = [r for r in ordered if _slot_ms(r) <= start]
    if not starts:
        raise ValueError(f"{symbol}: a funding record at or before the window start required")
    needed = [r for r in ordered if _slot_ms(starts[-1]) <= _slot_ms(r) < end]
    published = [r for r in ordered if r.usable_ms <= start]
    read_times = {r.calc_time_ms for r in needed}
    if published:
        read_times.add(published[-1].calc_time_ms)
    read = [r for r in ordered if r.calc_time_ms in read_times]
    if any(not r.valid for r in read):
        raise ValueError(f"{symbol}: valid funding records required")
    times = [r.calc_time_ms for r in read]
    if len(set(times)) != len(times):
        raise ValueError(f"{symbol}: duplicate funding record")
    return tuple(needed), tuple(sorted(read, key=lambda r: r.usable_ms))


def _schedule_gaps(
    records: tuple[FundingRecord, ...], start: int, end: int
) -> tuple[frozenset[int], tuple[tuple[int, int, int, int], ...]]:
    """Missing settlement slots, and irregular pairs of consecutive records.

    Which end of an interval ``interval_hours`` names at a cadence change is not pinned
    yet, so a pair misses settlements only when the spacing of their settlement hours
    exceeds both intervals: then every hour the earlier record's interval implies before
    the later one is missing. Slots are counted from each record's nearest hour (half
    an hour rounds up), whatever hour books it: 08:15 counts from 08:00 and 15:58 from
    16:00, while booking an off-hour record at the next boundary is unchanged. Any other
    pair not exactly one shared interval apart in booking hours is irregular, as
    (earlier time, its hours, later time, its hours): accepted, never a failure. After
    the last record, its own interval applies up to the end. Slots before the start
    never matter: nothing is held there.
    """
    missing: set[int] = set()
    irregular: list[tuple[int, int, int, int]] = []
    for before, after in zip(records, records[1:], strict=False):
        first, until = _nearest_hour(before.calc_time_ms), _nearest_hour(after.calc_time_ms)
        step = _interval_ms(before)
        if until - first > max(step, _interval_ms(after)):
            missing.update(range(first + step, until, step))
        elif _booked_ms(after) - _booked_ms(before) != step or step != _interval_ms(after):
            irregular.append(
                (
                    before.calc_time_ms,
                    step // HOUR,
                    after.calc_time_ms,
                    _interval_ms(after) // HOUR,
                )
            )
    last = records[-1]
    step = _interval_ms(last)
    missing.update(range(_nearest_hour(last.calc_time_ms) + step, end, step))
    return frozenset(slot for slot in missing if slot >= start), tuple(irregular)


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
        # The flow gate reads the fifteen minutes before each window minute; a duplicate
        # or misaligned minute there would make the result depend on input order.
        relevant = [
            bar.open_ms
            for bar in market.minutes
            if run.start_ms - 15 * 60_000 <= bar.open_ms < run.end_ms
        ]
        if any(stamp % 60_000 for stamp in relevant) or len(set(relevant)) != len(relevant):
            raise ValueError(f"{market.symbol}: unique aligned minute bars required")


def _daily(market: SymbolMarket, run: ReplayRun) -> tuple[Kline, ...]:
    """The daily bars the run reads, rebuilt from the registered spot hourly bars.

    A decision reads only days closed by then, so the run reads the days closed by its
    last decision hour. Each is rebuilt from its own hours, and the supplied bars of
    those days must equal the rebuilt ones. Later supplied bars are never read, so a
    defect there cannot change this run.
    """
    last = run.end_ms - HOUR
    rebuilt = daily_bars(
        [bar for bar in market.spot.hourly if bar.open_ms // DAY * DAY + DAY <= last]
    )
    supplied = [bar for bar in market.daily if bar.open_ms + DAY <= last]
    for given, expected in zip_longest(supplied, rebuilt):
        try:
            same = given == expected
        except ArithmeticError:  # a signaling NaN cannot be compared, so never matches
            same = False
        if not same:
            day = min(bar.open_ms for bar in (given, expected) if bar is not None)
            raise ValueError(
                f"{market.symbol} daily: the bar of {day} differs from its registered hourly bars"
            )
    return rebuilt


def _missing_grid_inputs(run: ReplayRun, markets: tuple[SymbolMarket, ...]) -> tuple[str, ...]:
    """Symbols with no minute bar in ``[start - 15 min, end)``, the flow gate's read range."""
    first = run.start_ms - 15 * 60_000
    return tuple(
        sorted(
            market.symbol
            for market in markets
            if not any(first <= bar.open_ms < run.end_ms for bar in market.minutes)
        )
    )


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
    daily = {s: _daily(by_symbol[s], run) for s in symbols}
    spot = {s: _bars(by_symbol[s].spot.hourly, run.start_ms, run.end_ms, s) for s in symbols}
    futures = {
        s: _bars(m.futures.hourly, run.start_ms, run.end_ms, s)
        for s, m in by_symbol.items()
        if m.futures is not None
    }
    gaps = tuple(
        (symbol, venue, hours)
        for symbol in symbols
        for venue, index in (("futures", futures.get(symbol)), ("spot", spot[symbol]))
        if index is not None and (hours := _missing_hours(index, run.start_ms, run.end_ms))
    )
    inputs = {s: _funding(by_symbol[s].funding, run.start_ms, run.end_ms, s) for s in futures}
    needed = {s: inputs[s][0] for s in futures}
    bookings = {s: [_booked_ms(r) for r in needed[s]] for s in futures}
    # Two records booked at one boundary cannot both be charged there: neither is.
    collided = {s: {b for b, n in Counter(bookings[s]).items() if n > 1} for s in futures}
    funding_at = {
        s: {b: r for b, r in zip(bookings[s], needed[s], strict=True) if b not in collided[s]}
        for s in futures
    }
    schedules = {s: _schedule_gaps(needed[s], run.start_ms, run.end_ms) for s in futures}
    missing_funding = {s: schedules[s][0] for s in futures}
    irregular = tuple((s, *pair) for s in sorted(futures) for pair in schedules[s][1])
    published = {s: inputs[s][1] for s in futures}
    published_ms = {s: [r.usable_ms for r in published[s]] for s in futures}
    series = {
        s: AssessmentSeries(s, by_symbol[s].spot.hourly, daily[s], source_refs=run.source_refs)
        for s in symbols
    }
    missing_inputs = _missing_grid_inputs(run, markets) if settings.routing.spot_grid else ()
    minute_index = {s: {bar.open_ms: bar for bar in by_symbol[s].minutes} for s in symbols}
    # Fed minute by minute from the window's first minute; each frame reads it at its hour.
    gates = {s: MinuteFlowGate(minute_index[s], run.start_ms) for s in symbols}
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
    withheld: dict[str, list[int]] = {}
    stale_marks: list[tuple[str, int]] = []
    unbooked_after_exit: list[tuple[str, int, int]] = []
    entering: set[str] = set()  # futures holdings entering the latest interval
    dust: tuple[str, ...] = ()
    unsignaled: dict[str, TraceUnavailable] = {}  # each symbol's open episode
    unavailable: list[TraceUnavailable] = []

    def venue_bar(symbol: str, venue: str, hour: int) -> Kline | None:
        """The venue's bar opening at ``hour``; None is a data gap."""
        return (spot if venue == "spot" else futures)[symbol].get(hour)

    def venue_rules(symbol: str, venue: str) -> VenueRules:
        market = by_symbol[symbol]
        source = market.spot if venue == "spot" else market.futures
        if source is None:
            raise ValueError("held venue has no registered inputs")
        return source.rules

    def held_market(
        hour: int, price: str = "open", stamp: int | None = None
    ) -> tuple[dict[str, Quote], dict[str, VenueRules]]:
        """Held venues' quotes and filters; a holding without its bar gets neither."""
        quotes, rules = {}, {}
        for position, *_ in engine.held_execution_terms():
            row = venue_bar(position.symbol, position.venue, hour)
            if row is None:
                continue
            quotes[position.symbol] = Quote(getattr(row, price), hour if stamp is None else stamp)
            rules[position.symbol] = venue_rules(position.symbol, position.venue)
        return quotes, rules

    def unpriced(quotes: dict[str, Quote]) -> tuple[str, ...]:
        """Holdings without a quote at this boundary: their obligations are carried."""
        held = (p.symbol for p, *_ in engine.held_execution_terms())
        return tuple(sorted(symbol for symbol in held if symbol not in quotes))

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

    def held_futures() -> list[str]:
        return sorted(p.symbol for p, *_ in engine.held_execution_terms() if p.venue == "futures")

    def fixing(symbol: str, hour: int) -> FundingFixing:
        """The record booked at ``hour``, valued at that boundary's futures price."""
        record = funding_at[symbol][hour]
        mark, stale_since = _fixing_mark(futures[symbol], symbol, hour)
        return FundingFixing(
            f"funding:{symbol}:{record.calc_time_ms}",
            symbol,
            hour,
            record.rate,
            mark,
            scheduled_ms=record.calc_time_ms if _off_hour(record) else None,
            stale_mark_ms=stale_since,
        )

    def unchargeable(hour: int, holders: list[str]) -> str | None:
        """A held futures position's settlement at ``hour`` that cannot be charged.

        A missing record or two records booked here stop the run; nothing is assumed.
        An off-hour record whose holding left during the hour before is kept as evidence.
        """
        for symbol in holders:
            if hour in missing_funding[symbol]:
                return f"funding_record_missing:{symbol}:{hour}"
            if hour in collided[symbol]:
                return f"funding_records_collide:{symbol}:{hour}"
        for symbol in sorted(entering - set(holders)):
            record = funding_at[symbol].get(hour)
            if record is not None and _off_hour(record):
                unbooked_after_exit.append((symbol, record.calc_time_ms, hour))
        return None

    def latest_funding(symbol: str, hour: int) -> FundingRecord | None:
        """The latest record published at ``hour``, if any."""
        index = bisect_right(published_ms[symbol], hour)
        return published[symbol][index - 1] if index else None

    def estimate(symbol: str, hour: int) -> FundingEstimate | None:
        latest = latest_funding(symbol, hour)
        if latest is None:
            return None
        return FundingEstimate(latest.rate, latest.usable_ms, _interval_ms(latest))

    def interval(hour: int) -> str | None:
        """Bar [hour, hour+1h), stamped at its availability hour+1h."""
        nonlocal dust
        held = {p.symbol: p for p, *_ in engine.held_execution_terms()}
        entering.clear()
        entering.update(s for s, p in held.items() if p.venue == "futures")
        # The gate as the opening frame left it, then every minute inside the bar: a
        # block at any of them withholds the bar's resting buys, since the path cannot
        # tell when a limit was touched (not canceled: levels and reservation stay).
        # Sales bypass the gate.
        blocked: set[str] = set()
        for symbol in symbols:
            opened = gates[symbol].allowed
            if gates[symbol].advance(hour + HOUR - 60_000) or not opened:
                blocked.add(symbol)
        for symbol, basket in sorted(books.items()):
            if basket.pending and symbol in blocked:
                withheld.setdefault(symbol, []).append(hour)
        # A coin without its bar gets no fill of any kind in this bar: its resting buys
        # sit out and a holding keeps its last mark (the engine then requires its close).
        resting = tuple(
            row
            for symbol, book in books.items()
            if symbol not in blocked and venue_bar(symbol, "spot", hour) is not None
            for row in book.pending.values()
        )
        need = set(held) | {row.symbol for row in resting}
        venues = {s: held[s].venue if s in held else "spot" for s in need}
        bars = {s: row for s in need if (row := venue_bar(s, venues[s], hour)) is not None}
        if not bars:
            return None
        result = replay_held_portfolio(
            engine,
            tuple((s, bars[s]) for s in sorted(bars)),
            {s: venue_rules(s, venues[s]) for s in bars},
            run.scenario,
            source_refs=refs,
            grid_spacing=tuple(
                (s, books[s].spacing) for s in sorted(held) if held[s].owner == "spot_grid"
            ),
            resting=resting,
            unpriced=tuple(sorted(need - set(bars))),
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
            completed = venue_bar(symbol, position.venue, hour - HOUR)
            if completed is None:
                continue  # no completed bar: nothing tightens the stop
            state, _ = manage_completed_bar(
                protection[symbol],
                completed,
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
        # Funding is due only on the futures holdings that survived the previous interval.
        holders = held_futures()
        failure = unchargeable(hour, holders)
        if failure is not None:
            return failure
        day = hour // DAY
        if day not in groups_by_day:
            groups_by_day[day] = correlation_groups(daily, hour)
        engine.set_correlation_groups(groups_by_day[day])
        quotes, rules = held_market(hour)
        for position, stop, _fee, _slip in engine.held_execution_terms():
            if position.symbol not in quotes:
                continue  # no opening quote to compare with its stop
            side = 1 if position.quantity > 0 else -1
            price = quotes[position.symbol].price
            if (price <= stop) if side == 1 else (price >= stop):
                engine.request_close(position.symbol, position.owner, side, reason="stop")
        due = tuple(s for s in holders if hour in funding_at[s])
        fixings = tuple(fixing(s, hour) for s in due)
        boundary = executor.settle(
            f"frame:{hour}",
            hour,
            quotes,
            rules,
            due_funding=due,
            fixings=fixings,
            source_refs=refs,
            unpriced=unpriced(quotes),
        )
        failure = settled(boundary, hour)
        if failure is not None:
            return failure
        finalize(hour)
        for symbol in symbols:
            gates[symbol].advance(hour)  # the gate at this frame's own minute
        for symbol in symbols:
            failure = decide(symbol, hour, groups_by_day[day])
            if failure is not None:
                return failure
        # Obligations created by this frame's entries (post-fill cut-backs) execute
        # at the same opening quote, not an hour later (critic minor 2).
        quotes, rules = held_market(hour)
        latest = observations[-1].snapshot
        sellable = set(latest.close_required) | {s for s, _ in latest.reduce_to}
        waiting = unpriced(quotes)
        if sellable - set(engine.close_dust(rules)) - set(waiting):
            return settled(
                executor.settle(
                    f"frame:{hour}:post-entry",
                    hour,
                    quotes,
                    rules,
                    due_funding=(),
                    fixings=(),
                    source_refs=refs,
                    unpriced=waiting,
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

    def venue_inputs(symbol: str, hour: int) -> tuple[VenueInputs, VenueInputs | None]:
        """Each venue's filters, costs and quote; futures also its funding estimate."""
        market = by_symbol[symbol]
        # A venue without its bar has no quote: the coordinator refuses that venue's
        # entry, and a missing spot quote never makes the futures fallback available.
        spot_bar = venue_bar(symbol, "spot", hour)
        spot_inputs = VenueInputs(
            market.spot.rules,
            market.spot.costs,
            quote=None if spot_bar is None else Quote(spot_bar.open, hour),
        )
        if market.futures is None:
            return spot_inputs, None
        futures_bar = venue_bar(symbol, "futures", hour)
        return spot_inputs, VenueInputs(
            market.futures.rules,
            market.futures.costs,
            funding=estimate(symbol, hour),
            funding_admission=settings.funding_admission,
            quote=None if futures_bar is None else Quote(futures_bar.open, hour),
        )

    def end_unsignaled(symbol: str) -> None:
        episode = unsignaled.pop(symbol, None)
        if episode is not None:
            unavailable.append(episode)

    def unsignaled_hour(
        symbol: str, hour: int, assessment: Assessment, groups: tuple[tuple[str, str], ...]
    ) -> None:
        """An unavailable assessment with no signal: extend its episode or detect one."""
        episode = unsignaled.get(symbol)
        if (
            episode is not None
            and episode.record.last_ms == hour - HOUR
            and episode.record.reasons == assessment.reasons
        ):
            unsignaled[symbol] = replace(episode, record=replace(episode.record, last_ms=hour))
            return
        end_unsignaled(symbol)
        # Only what the record carries: registered costs and the published funding values.
        market = by_symbol[symbol]
        funding = None if market.futures is None else latest_funding(symbol, hour)
        record = coordinator.record_unavailable(
            f"{symbol}:{hour}",
            assessment,
            refs,
            spot_costs=market.spot.costs,
            futures_costs=None if market.futures is None else market.futures.costs,
            funding_rate=None if funding is None else funding.rate,
            funding_published_ms=None if funding is None else funding.usable_ms,
            funding_interval_ms=None if funding is None else _interval_ms(funding),
            groups=groups,
        )
        unsignaled[symbol] = TraceUnavailable(assessment, record)

    def decide(symbol: str, hour: int, groups: tuple[tuple[str, str], ...]) -> str | None:
        # One strategy owns an asset: held inventory or a resting grid basket.
        if symbol in owned():
            end_unsignaled(symbol)
            return None
        assessment = series[symbol].at(hour, hour)
        routing = replace(settings.routing, flow_allowed=gates[symbol].allowed)
        if qualify(assessment, routing).side == 0:
            if assessment.available:
                end_unsignaled(symbol)  # No directional or range signal: nothing is detected.
            else:
                unsignaled_hour(symbol, hour, assessment, groups)
            return None
        end_unsignaled(symbol)
        quotes, rules = held_market(hour)
        spot_inputs, futures_inputs = venue_inputs(symbol, hour)
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
            failure = unchargeable(run.end_ms, held_futures())
        if failure is None:
            # A record settled off the hour in the last hour books at the terminal
            # boundary, which books no funding: a holding it charges stops the run.
            failure = next(
                (
                    f"funding_record_unbooked:{s}:{funding_at[s][run.end_ms].calc_time_ms}"
                    for s in held_futures()
                    if run.end_ms in funding_at[s]
                ),
                None,
            )
        if failure is None:
            quotes, rules = held_market(run.end_ms - HOUR, "close", run.end_ms)
            for position, *_ in engine.held_execution_terms():
                if position.symbol in quotes:
                    continue
                # Its last available close, stamped when it became available; with no
                # filters supplied the engine marks the holding stale.
                index = (spot if position.venue == "spot" else futures)[position.symbol]
                last = index[max(index)]
                quotes[position.symbol] = Quote(last.close, last.open_ms + HOUR)
                stale_marks.append((position.symbol, last.open_ms + HOUR))
            batch = f"terminal:{run.end_ms}"
            engine.settle(batch, run.end_ms, quotes, rules)
            record(engine.settlement_observations(batch), run.end_ms, "terminal")
            boundary(run.end_ms, "terminal")
    except (ValueError, ArithmeticError) as exc:
        # Execution, accounting and data failures are retained run outcomes; anything
        # else is a programming defect and propagates loudly instead.
        failure = f"replay_failure:{type(exc).__name__}:{exc}"
    unavailable.extend(unsignaled.values())  # episodes still open at the end
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
        tuple((symbol, tuple(hours)) for symbol, hours in sorted(withheld.items())),
        missing_inputs,
        gaps,
        tuple(stale_marks),
        irregular,
        tuple(unbooked_after_exit),
        engine.worse_fill_evidence,
        tuple(sorted(unavailable, key=lambda e: (e.record.first_ms, e.record.symbol))),
        failure,
    )
