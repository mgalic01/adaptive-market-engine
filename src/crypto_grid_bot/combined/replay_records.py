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
from dataclasses import dataclass, field, replace
from decimal import Decimal
from fractions import Fraction

from .account import AccountSnapshot, FundingEvent
from .artifacts import BundleRecords, RunRecord, SymbolGaps
from .evidence import DecisionEvent, DecisionRecord, IntentRecord
from .execution import _decimal
from .models import Assessment
from .observation_policy import POLICY_ID, Boundary, PolicyEvidence
from .recovery import RecoveryState
from .report import (
    SAVED_FILTERS_DISCLOSURE,
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
from .strategy_replay import NativeObservation, StrategyTrace, TraceFill

HOUR = 3_600_000
DAY = 86_400_000
# Rulings every V3.1 replay runs under (controller, 2026-10-11), disclosed on every report.
V3_1_RULINGS = (
    SAVED_FILTERS_DISCLOSURE,
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
    """Funnel stages of every detected signal; a refusal is a ``blocked`` stage with
    every reason it was refused for."""
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
                    None if event.accepted else event.reasons[0],
                    event.event_id,
                    event.source_refs,
                    () if event.accepted else event.reasons,
                )
            )
    return tuple(rows)


# The kind of record each non-normal recovery state belongs to; the half allowance is
# part of the episode that earned it.
_STRETCH_KIND = {
    RecoveryState.CLOSING: "liquidation",
    RecoveryState.COOLDOWN: "cooldown",
    RecoveryState.RECOVERY25: "episode",
    RecoveryState.RECOVERY50: "episode",
    RecoveryState.TERMINAL: "terminal",
}
# What ended a stretch, by its kind and the kind of the stretch after it (None: normal).
_ENDED_BY: dict[tuple[str, str | None], str] = {
    ("liquidation", "cooldown"): "liquidated",
    ("cooldown", "episode"): "restarted",
    ("cooldown", "liquidation"): "liquidation_incomplete",
    ("episode", "liquidation"): "episode_stop",
    ("episode", "cooldown"): "episode_stop",
    ("episode", None): "normal_restored",
}


def _recovery_record(
    kind: str,
    start: NativeObservation,
    end: NativeObservation,
    ended_by: str,
    refs: tuple[str, ...],
) -> RecoveryEpisode:
    return RecoveryEpisode(
        start.timestamp_ms,
        end.timestamp_ms,
        start.snapshot.account.equity,
        end.snapshot.account.equity,
        f"recovery:{kind}:{start.id}",
        refs,
        start.id,
        end.id,
        kind,
        ended_by,
    )


def recovery_episodes(trace: StrategyTrace) -> tuple[RecoveryEpisode, ...]:
    """One record per recovery stretch, bound to observation identities.

    The forced liquidation, each cooldown and each episode are their own records. An
    episode begins at a restart (entry into the 25% allowance) and ends at its 3% stop,
    at normal restoration or at the window's last observation. Every stretch begins at
    the observation that entered it and ends at the one that began the next stretch (the
    first normal one), so its incremental P&L is the equity change between the two. A
    trigger while flat has nothing to liquidate and gets no liquidation record.
    """
    refs = trace.run.source_refs
    episodes: list[RecoveryEpisode] = []
    current: tuple[str, NativeObservation] | None = None
    for observation in trace.observations:
        state = observation.snapshot.recovery.state
        following = None if state == RecoveryState.NORMAL else _STRETCH_KIND[state]
        if current is not None and following == current[0]:
            continue
        if current is not None:
            kind, start = current
            ended_by = (
                "terminal"
                if following == "terminal"
                else _ENDED_BY.get((kind, following), observation.snapshot.recovery.reason)
            )
            episodes.append(_recovery_record(kind, start, observation, ended_by, refs))
        current = None if following is None else (following, observation)
    if current is not None:
        kind, start = current
        episodes.append(_recovery_record(kind, start, trace.observations[-1], "window_end", refs))
    return tuple(episodes)


def _contributions_and_issues(
    trace: StrategyTrace,
) -> tuple[tuple[Contribution, ...], tuple[str, ...]]:
    """The lifecycles and the producer issues a report of this trace lists."""
    # A failed replay is incomplete evidence by declaration, not only by structure.
    issues = [f"replay_failure:{trace.failure}"] if trace.failure is not None else []
    # A grid arm without a coin's minute input cannot judge that coin's grid: incomplete.
    issues.extend(f"missing_grid_input:{symbol}" for symbol in trace.missing_grid_inputs)
    contributions = lifecycle_contributions(trace, issues)
    return contributions, tuple(issues)


def _episodes(records: Iterable[DecisionRecord]) -> list[DecisionRecord]:
    """One record per contiguous run of a symbol's identical refusals, in time order.

    Refusals in consecutive hours with the same phase, reasons, owner, side and
    missing-size cause are one record from the first hour to the last, in its first
    hour's context. An approval, a different refusal, an hour without a record (owned,
    no signal, skipped) or the run's end closes it; an approval is its own record.
    """

    def disposition(record: DecisionRecord) -> tuple[object, ...]:
        return (record.phase, record.reasons, record.owner, record.side, record.size_unavailable)

    kept: list[DecisionRecord] = []
    open_: dict[str, DecisionRecord] = {}
    for record in sorted(records, key=lambda r: (r.first_ms, r.symbol)):
        prior = open_.pop(record.symbol, None)
        if (
            prior is not None
            and not record.accepted
            and record.first_ms == prior.last_ms + HOUR
            and disposition(record) == disposition(prior)
        ):
            open_[record.symbol] = replace(prior, last_ms=record.last_ms)
            continue
        if prior is not None:
            kept.append(prior)
        if record.accepted:
            kept.append(record)
        else:
            open_[record.symbol] = record
    kept.extend(open_.values())
    return sorted(kept, key=lambda r: (r.first_ms, r.symbol))


def evidence_records(trace: StrategyTrace) -> BundleRecords:
    """The replay's versioned evidence records for its bundle; never a strategy input.

    The funnel journal keeps every hour; these records keep one decision record per
    approval and per episode of identical refusals (``_episodes``), with the assessment
    and intent of its first hour. Every record cites the run's sources once, by the run
    record's digest, plus its own references; each symbol's gaps and invalid opens are
    one table as of its last assessment. The run record carries the report's producer
    issues, so an open lifecycle valued at its last fill price stays marked.
    """
    contributions, issues = _contributions_and_issues(trace)
    run = RunRecord(trace.run.source_refs, issues)
    count = len(trace.run.source_refs)

    def own(refs: tuple[str, ...]) -> tuple[str, ...]:
        """The run's sources as its digest, then the record's own references."""
        if refs[:count] != trace.run.source_refs:
            raise ValueError("record is not tied to the run's sources")
        return (run.ref, *refs[count:])

    origin: dict[str, tuple[Assessment, IntentRecord | None]] = {}
    hourly: list[DecisionRecord] = []
    for decision in trace.decisions:
        assessment, result = decision.assessment, decision.result
        if result.record is None:
            continue
        intent = None
        if result.intent is not None:
            first = result.events[0]
            intent = IntentRecord(
                first.opportunity_id,
                assessment.assessment_id,
                first.timestamp_ms,
                result.intent,
                own(first.source_refs),
            )
        origin[result.record.record_id] = assessment, intent
        hourly.append(result.record)
    for episode in trace.unavailable:
        origin[episode.record.record_id] = episode.assessment, None
        hourly.append(episode.record)
    latest: dict[str, Assessment] = {}
    for assessment, _ in origin.values():
        prior = latest.get(assessment.symbol)
        if prior is None or assessment.decision_ms > prior.decision_ms:
            latest[assessment.symbol] = assessment
    decisions = _episodes(hourly)
    assessments: dict[str, Assessment] = {}
    intents: list[IntentRecord] = []
    for record in decisions:
        assessment, intent = origin[record.record_id]
        assessments.setdefault(
            assessment.assessment_id,
            replace(
                assessment,
                source_refs=own(assessment.source_refs),
                hourly_gaps=(),
                four_hour_gaps=(),
                daily_gaps=(),
                invalid_hourly_open_ms=(),
                invalid_daily_open_ms=(),
            ),
        )
        if intent is not None:
            intents.append(intent)
    return BundleRecords(
        run,
        tuple(
            SymbolGaps(
                symbol,
                last.decision_ms,
                last.hourly_gaps,
                last.four_hour_gaps,
                last.daily_gaps,
                last.invalid_hourly_open_ms,
                last.invalid_daily_open_ms,
            )
            for symbol, last in sorted(latest.items())
        ),
        tuple(assessments.values()),
        tuple(intents),
        tuple(replace(record, source_refs=own(record.source_refs)) for record in decisions),
        tuple(replace(row, source_refs=own(row.source_refs)) for row in contributions),
        tuple(replace(row, source_refs=own(row.source_refs)) for row in recovery_episodes(trace)),
    )


def _by_symbol(rows: Iterable[tuple[str, int]]) -> list[tuple[str, list[int]]]:
    """Times grouped per symbol, symbols in order."""
    grouped: dict[str, list[int]] = {}
    for symbol, stamp in rows:
        grouped.setdefault(symbol, []).append(stamp)
    return sorted(grouped.items())


def strategy_disclosures(
    trace: StrategyTrace, skipped_hours: tuple[int, ...] = ()
) -> tuple[str, ...]:
    """What one replay discloses, compact for a multi-year run.

    Long series are kept per symbol to a count and their first and last times; the
    short ones (skipped hours, irregular funding pairs) are listed in full. A stale
    fixing mark also gives the oldest mark and the largest staleness.
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
    stale: dict[str, list[tuple[int, int]]] = {}
    for payment in payments:
        if payment.stale_mark_ms is not None:
            stale.setdefault(payment.symbol, []).append(
                (payment.timestamp_ms, payment.stale_mark_ms)
            )
    for symbol, rows in sorted(stale.items()):
        oldest = min(mark for _, mark in rows)
        worst = max(booked - mark for booked, mark in rows)
        notes.append(
            f"funding_settled_at_stale_mark:{symbol}: "
            f"{span_text('settlements', (booked for booked, _ in rows))} "
            f"oldest_mark={utc_text(oldest)} max_staleness={_duration(worst)}"
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
        fills = [fill for fill in trace.worse_fills if fill.symbol == symbol]
        excess = sum((Fraction(fill.excess_risk) for fill in fills), Fraction(0))
        # Signed extra costs are never netted: a cheaper fill must not hide a costlier one.
        dearer = [Fraction(fill.extra_cost) for fill in fills if fill.extra_cost > 0]
        cheaper = [Fraction(fill.extra_cost) for fill in fills if fill.extra_cost < 0]
        notes.append(
            f"worse_fill:{symbol}: fills={len(fills)} excess_risk={_decimal(excess)} "
            f"positive_extra_cost_fills={len(dearer)} "
            f"positive_extra_cost={_decimal(sum(dearer, Fraction(0)))} "
            f"negative_extra_cost_fills={len(cheaper)} "
            f"negative_extra_cost={_decimal(sum(cheaper, Fraction(0)))}"
        )
    return tuple(notes)


def _duration(ms: int) -> str:
    """Whole hours as ``<n>h``, anything else in milliseconds."""
    return f"{ms // HOUR}h" if ms % HOUR == 0 else f"{ms}ms"


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
    contributions, issues = _contributions_and_issues(trace)
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
        producer_issues=issues,
        skipped_hours=skipped_hours,
        disclosures=strategy_disclosures(trace, skipped_hours),
        capital_label=capital_label,
    )
