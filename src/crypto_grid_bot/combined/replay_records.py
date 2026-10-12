"""Report evidence for one strategy replay; never a strategy input.

Every native observation is retained as an equity point. Each hourly boundary
lists every mark at its timestamp in booking order and selects the approved
settlement state: the opening's first mark (before execution costs), otherwise the
last. Lifecycles attribute every booked fill and funding payment, so their sum
reconciles exactly with the equity change; open lifecycles are marked at the last
observation's marks. Source references are retained, not authenticated.

Every report discloses the V3.1 rulings it ran under and what the trace recorded
about its inputs (data gaps, stale marks, off-hour or irregular funding, withheld
grid buys, worse fills). Disclosures are information, never a decision input: a
gapped run stays complete.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

from .account import AccountSnapshot, FundingEvent
from .evidence import DecisionEvent
from .execution import _decimal
from .observation_policy import POLICY_ID, Boundary, PolicyEvidence
from .recovery import RecoveryState
from .report import (
    CapitalObservation,
    Contribution,
    EquityPoint,
    Opportunity,
    RecoveryEpisode,
    Report,
    UtilizationInterval,
    analyze,
    skipped_hours_disclosures,
    span_text,
    utc_text,
)
from .strategy_replay import StrategyTrace, TraceFill

DAY = 86_400_000
# Rulings every V3.1 replay runs under (controller, 2026-10-11), disclosed on every report.
V3_1_RULINGS = (
    "v3_1_present_day_saved_exchange_filters_on_historical_data",
    "v3_1_held_coin_without_bar_closed_at_next_bar_pending_orders_canceled",
)


@dataclass
class _Lifecycle:
    id: str
    strategy: str
    asset: str
    direction: str
    regime: str | None
    entry_ms: int
    refs: tuple[str, ...]
    quantity: Fraction = Fraction(0)
    cash: Fraction = Fraction(0)
    fees: Fraction = Fraction(0)
    funding: Fraction = Fraction(0)
    turnover: Fraction = Fraction(0)
    reason: str | None = None
    fills: list[str] = field(default_factory=list)


def _capital(account: AccountSnapshot) -> tuple[Decimal, Decimal]:
    spot = sum(
        (Fraction(p.quantity) * Fraction(p.mark) for p in account.positions if p.venue == "spot"),
        Fraction(0),
    )
    collateral = sum(
        (Fraction(p.collateral) for p in account.positions if p.venue == "futures"), Fraction(0)
    )
    return _decimal(spot), _decimal(collateral)


def lifecycle_contributions(
    trace: StrategyTrace, issues: list[str] | None = None
) -> tuple[Contribution, ...]:
    """Whole lifecycles from flat to flat per asset, in booking order.

    An open lifecycle with no retained mark (only after a failed run) is valued at
    its last fill price and named in ``issues``, never silently or by a crash.
    """
    refs = trace.run.source_refs
    open_: dict[str, _Lifecycle] = {}
    rows: list[Contribution] = []

    def emit(life: _Lifecycle, gross: Fraction, exit_ms: int | None) -> None:
        rows.append(
            Contribution(
                life.id,
                life.strategy,
                life.asset,
                life.direction,
                life.regime,
                _decimal(gross),
                _decimal(life.fees),
                _decimal(life.funding),
                _decimal(life.turnover),
                (life.reason or "unattributed_reduction") if exit_ms is not None else None,
                life.entry_ms,
                "closed" if exit_ms is not None else "open_marked",
                exit_ms,
                None,
                None,
                (*life.refs, *(f"fill:{fill}" for fill in life.fills)),
            )
        )

    for event in trace.events:
        if isinstance(event, FundingEvent):
            if event.symbol not in open_:
                raise ValueError("funding booked without an open lifecycle")
            open_[event.symbol].funding += Fraction(event.amount)
            continue
        if not isinstance(event, TraceFill):
            raise ValueError("unknown trace event")
        fill = event.fill
        life = open_.get(fill.symbol)
        if life is None:
            if not event.increase:
                raise ValueError("reduction booked without an open lifecycle")
            life = _Lifecycle(
                f"lifecycle:{fill.symbol}:{fill.event_id}",
                fill.owner,
                fill.symbol,
                "long" if fill.side == 1 else "short",
                event.regime,
                fill.timestamp_ms,
                refs,
            )
            open_[fill.symbol] = life
        quantity, price = Fraction(fill.quantity), Fraction(fill.price)
        life.quantity += fill.side * quantity
        life.cash -= fill.side * quantity * price
        life.fees += Fraction(fill.fee)
        life.turnover += quantity * price
        life.fills.append(fill.event_id)
        if not event.increase:
            life.reason = event.exit_reason or life.reason
        if life.quantity == 0:
            emit(life, life.cash, fill.timestamp_ms)
            del open_[fill.symbol]
    marks = (
        {p.symbol: Fraction(p.mark) for p in trace.observations[-1].snapshot.account.positions}
        if trace.observations
        else {}
    )
    last_price = {
        event.fill.symbol: Fraction(event.fill.price)
        for event in trace.events
        if isinstance(event, TraceFill)
    }
    for symbol, life in sorted(open_.items()):
        if symbol not in marks:
            if issues is None:
                raise ValueError("open lifecycle has no retained mark")
            issues.append(f"unmarked_open_lifecycle:{life.id}")
        emit(life, life.cash + life.quantity * marks.get(symbol, last_price[symbol]), None)
    return tuple(sorted(rows, key=lambda row: (row.entry_ms, row.id)))


def opportunity_records(trace: StrategyTrace) -> tuple[Opportunity, ...]:
    """Funnel stages of every detected signal; a refusal is a ``blocked`` stage."""
    filled: dict[str, list[DecisionEvent]] = {}
    for event in trace.evidence:
        if event.phase == "filled":
            filled.setdefault(event.opportunity_id, []).append(event)
    rows: list[Opportunity] = []
    for decision in trace.decisions:
        qualification, assessment = decision.result.qualification, decision.assessment
        if qualification.side not in (1, -1) or not decision.result.events:
            continue
        direction = "long" if qualification.side == 1 else "short"
        opportunity = decision.result.events[0].opportunity_id
        for event in (*decision.result.events, *filled.get(opportunity, ())):
            rows.append(
                Opportunity(
                    event.timestamp_ms,
                    event.symbol,
                    direction,
                    assessment.structure,
                    event.phase if event.accepted else "blocked",
                    None if event.accepted else (event.reasons[0] if event.reasons else "refused"),
                    event.event_id,
                    event.source_refs,
                )
            )
    return tuple(rows)


def recovery_episodes(trace: StrategyTrace) -> tuple[RecoveryEpisode, ...]:
    """Contiguous non-normal recovery stretches, bound to observation identities."""
    refs = trace.run.source_refs
    episodes: list[RecoveryEpisode] = []
    start = None
    for observation in trace.observations:
        normal = observation.snapshot.recovery.state == RecoveryState.NORMAL
        if start is None and not normal:
            start = observation
        elif start is not None and normal:
            episodes.append(
                RecoveryEpisode(
                    start.timestamp_ms,
                    observation.timestamp_ms,
                    start.snapshot.account.equity,
                    observation.snapshot.account.equity,
                    f"recovery:{start.id}",
                    refs,
                    start.id,
                    observation.id,
                )
            )
            start = None
    if start is not None:
        episodes.append(
            RecoveryEpisode(
                start.timestamp_ms,
                None,
                start.snapshot.account.equity,
                None,
                f"recovery:{start.id}",
                refs,
                start.id,
                None,
            )
        )
    return tuple(episodes)


def _by_symbol(rows: Iterable[tuple[str, int]]) -> list[tuple[str, list[int]]]:
    grouped: dict[str, list[int]] = {}
    for symbol, stamp in rows:
        grouped.setdefault(symbol, []).append(stamp)
    return sorted(grouped.items())


def strategy_disclosures(
    trace: StrategyTrace, skipped_hours: tuple[int, ...] = ()
) -> tuple[str, ...]:
    """What one replay discloses, compact for a multi-year run.

    Long series are kept per symbol to a count and their first and last times; the
    short ones (skipped hours, irregular funding pairs) are listed in full.
    """
    notes = [*V3_1_RULINGS, *skipped_hours_disclosures(skipped_hours)]
    notes.extend(
        f"data_gap:{symbol}:{venue}: {span_text('hours', hours)}"
        for symbol, venue, hours in trace.data_gaps
    )
    notes.extend(
        f"stale_terminal_mark:{symbol}: last_close_available={utc_text(available)}"
        for symbol, available in trace.stale_terminal_marks
    )
    notes.extend(
        f"flow_gate_withheld_grid_buys:{symbol}: {span_text('intervals', hours)}"
        for symbol, hours in trace.withheld_buys
    )
    payments = [event for event in trace.events if isinstance(event, FundingEvent)]
    notes.extend(
        f"funding_off_hour_record_booked_next_hour:{symbol}: {span_text('records', times)}"
        for symbol, times in _by_symbol(
            (p.symbol, p.scheduled_ms) for p in payments if p.scheduled_ms is not None
        )
    )
    notes.extend(
        f"funding_settled_at_stale_mark:{symbol}: {span_text('settlements', times)}"
        for symbol, times in _by_symbol(
            (p.symbol, p.timestamp_ms) for p in payments if p.stale_mark_ms is not None
        )
    )
    notes.extend(
        f"funding_schedule_irregular:{symbol}: earlier={utc_text(earlier)}/{every}h "
        f"later={utc_text(later)}/{then}h"
        for symbol, earlier, every, later, then in trace.funding_schedule_irregular
    )
    notes.extend(
        f"funding_record_unbooked_after_exit:{symbol}: {span_text('records', times)}"
        for symbol, times in _by_symbol(
            (symbol, record) for symbol, record, _ in trace.funding_records_unbooked_after_exit
        )
    )
    for symbol in sorted({fill.symbol for fill in trace.worse_fills}):
        rows = [fill for fill in trace.worse_fills if fill.symbol == symbol]
        excess = sum((Fraction(row.excess_risk) for row in rows), Fraction(0))
        extra = sum((Fraction(row.extra_cost) for row in rows), Fraction(0))
        notes.append(
            f"worse_fill:{symbol}: fills={len(rows)} excess_risk={_decimal(excess)} "
            f"extra_cost={_decimal(extra)}"
        )
    return tuple(notes)


def strategy_report(
    trace: StrategyTrace,
    *,
    adapter_pin: str,
    skipped_hours: tuple[int, ...] = (),
    capital_label: str | None = None,
) -> Report:
    """Analyze one replay under the approved settlement policy and its adapter pin.

    ``skipped_hours`` are the registered window's: a daily return may span them.
    ``capital_label`` names the registered capital scenario on the report.
    """
    if not isinstance(adapter_pin, str) or not adapter_pin.strip():
        raise ValueError("adapter pin required")
    refs = trace.run.source_refs
    by_id = {o.id: o for o in trace.observations}
    points = tuple(
        EquityPoint(
            o.timestamp_ms,
            o.snapshot.account.equity,
            o.id,
            (*refs, f"{o.kind}:{o.phase}:{o.event_id}"),
        )
        for o in trace.observations
    )
    boundaries: list[Boundary] = []
    capitals: list[CapitalObservation] = []
    for mark in trace.boundaries:
        if not mark.observation_ids:
            continue
        last = by_id[mark.observation_ids[-1]]
        spot, collateral = _capital(last.snapshot.account)
        capital_id = f"capital:{mark.timestamp_ms}"
        capital = CapitalObservation(
            mark.timestamp_ms,
            last.snapshot.account.equity,
            spot,
            collateral,
            capital_id,
            mark.role,
            last.id,
            refs,
        )
        capitals.append(capital)
        boundaries.append(
            Boundary(
                mark.timestamp_ms,
                mark.role,
                mark.observation_ids,
                mark.observation_ids[0 if mark.role == "opening" else -1],
                capital_id,
                refs,
                mark.interval_start_ms,
                mark.interval_end_ms,
            )
        )
    points_by_id = {p.id: p for p in points}
    daily = tuple(
        points_by_id[b.selected_equity_id] for b in boundaries if b.timestamp_ms % DAY == 0
    )
    utilization = tuple(
        UtilizationInterval(
            boundary.timestamp_ms,
            following.timestamp_ms,
            capital.spot_value,
            capital.futures_collateral,
            capital.equity,
            f"utilization:{boundary.timestamp_ms}",
            refs,
            capital.id,
        )
        for boundary, following, capital in zip(boundaries, boundaries[1:], capitals, strict=False)
    )
    policy = PolicyEvidence(POLICY_ID, adapter_pin, tuple(boundaries), trace.run.scenario)
    # A failed replay is incomplete evidence by declaration, not only by structure.
    issues = [f"replay_failure:{trace.failure}"] if trace.failure is not None else []
    # A grid arm without a coin's minute input cannot judge that coin's grid: incomplete.
    issues.extend(f"missing_grid_input:{symbol}" for symbol in trace.missing_grid_inputs)
    contributions = lifecycle_contributions(trace, issues)
    return analyze(
        trace.run.initial_cash,
        points,
        contributions,
        opportunity_records(trace),
        recovery_episodes(trace),
        refs,
        metrics_start_ms=trace.run.start_ms,
        daily_samples=daily,
        utilization=utilization,
        capital_observations=tuple(capitals),
        policy_evidence=policy,
        producer_issues=tuple(issues),
        skipped_hours=skipped_hours,
        disclosures=strategy_disclosures(trace, skipped_hours),
        capital_label=capital_label,
    )
