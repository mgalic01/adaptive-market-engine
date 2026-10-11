"""Evidence-only attribution and observation summaries; never strategy inputs.

Contributions include whole lifecycle gross PnL, with open marked PnL explicitly
identified. Funding is signed wallet cash flow. Completeness is structural only:
source reference strings are retained, not fetched or cryptographically verified.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Context, Decimal, DecimalException, localcontext
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp_ms: int
    equity: Decimal
    id: str | None = None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.source_refs, str):
            raise ValueError("source_refs must be a collection, not a string")
        object.__setattr__(self, "source_refs", tuple(self.source_refs))


@dataclass(frozen=True, slots=True)
class Contribution:
    id: str
    strategy: str
    asset: str
    direction: str
    regime: str | None
    gross_pnl: Decimal
    fees: Decimal
    funding_signed: Decimal
    turnover: Decimal
    exit_reason: str | None
    entry_ms: int
    status: str
    exit_ms: int | None = None
    mfe: Decimal | None = None
    giveback: Decimal | None = None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.source_refs, str):
            raise ValueError("source_refs must be a collection, not a string")
        object.__setattr__(self, "source_refs", tuple(self.source_refs))


@dataclass(frozen=True, slots=True)
class Opportunity:
    timestamp_ms: int
    asset: str
    direction: str
    structure: str
    stage: str
    reason: str | None
    id: str | None = None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.source_refs, str):
            raise ValueError("source_refs must be a collection, not a string")
        object.__setattr__(self, "source_refs", tuple(self.source_refs))


@dataclass(frozen=True, slots=True)
class RecoveryEpisode:
    start_ms: int
    end_ms: int | None
    equity_start: Decimal
    equity_end: Decimal | None
    id: str | None = None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.source_refs, str):
            raise ValueError("source_refs must be a collection, not a string")
        object.__setattr__(self, "source_refs", tuple(self.source_refs))


@dataclass(frozen=True, slots=True)
class DimensionTotal:
    key: str | None
    gross_pnl: Decimal
    fees: Decimal
    funding_signed: Decimal
    net_pnl: Decimal
    turnover: Decimal


@dataclass(frozen=True, slots=True)
class BadInterval:
    start_ms: int
    end_ms: int
    net_change: Decimal
    return_fraction: Decimal | None


@dataclass(frozen=True, slots=True)
class OpportunityEpisode:
    asset: str
    direction: str
    structure: str
    start_ms: int
    end_ms: int
    observation_count: int
    stages: tuple[str, ...]
    reasons: tuple[str, ...]
    entry_delay_ms: int | None
    observation_ids: tuple[str | None, ...]
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecoveryChange:
    episode: RecoveryEpisode
    marked_change: Decimal | None
    return_fraction: Decimal | None


@dataclass(frozen=True, slots=True)
class Metric:
    name: str
    value: Decimal | None
    definition: str
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class CapitalObservation:
    """Supplied account snapshot; identity links are structural, not authentication.

    Phase IDs describe source events. They do not authorize a sampling policy or
    permit selection between distinct same-time account observations.
    """

    timestamp_ms: int
    equity: Decimal
    spot_value: Decimal
    futures_collateral: Decimal
    id: str | None = None
    phase_id: str | None = None
    equity_observation_id: str | None = None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.source_refs, str):
            raise ValueError("source_refs must be a collection, not a string")
        object.__setattr__(self, "source_refs", tuple(self.source_refs))


@dataclass(frozen=True, slots=True)
class UtilizationInterval:
    """Supplied left-constant marked capital observation over [start_ms, end_ms).

    Spot inventory value plus futures collateral, divided by equity. This is not
    gross exposure/leverage or pending-order cash. The supplied constancy claim
    is not authenticated; it cannot skip another retained capital observation.
    No interpolation or sampling convention is inferred.
    """

    start_ms: int
    end_ms: int
    spot_value: Decimal
    futures_collateral: Decimal
    equity: Decimal
    id: str | None = None
    source_refs: tuple[str, ...] = ()

    observation_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.source_refs, str):
            raise ValueError("source_refs must be a collection, not a string")
        object.__setattr__(self, "source_refs", tuple(self.source_refs))


@dataclass(frozen=True, slots=True)
class Report:
    initial_equity: Decimal
    final_equity: Decimal | None
    net_profit: Decimal | None
    net_return: Decimal | None
    max_drawdown: Decimal | None
    fees: Decimal
    funding_signed: Decimal
    turnover: Decimal
    reconciliation_residual: Decimal | None
    by_strategy: tuple[DimensionTotal, ...]
    by_asset: tuple[DimensionTotal, ...]
    by_direction: tuple[DimensionTotal, ...]
    by_regime: tuple[DimensionTotal, ...]
    largest_positive_asset_share: Decimal | None
    bad_intervals: tuple[BadInterval, ...]
    opportunity_episodes: tuple[OpportunityEpisode, ...]
    observation_gap_ms: int
    recovery_changes: tuple[RecoveryChange, ...]
    closed_count: int
    open_marked_count: int
    exit_reason_counts: tuple[tuple[str | None, int], ...]
    mfe_available: int
    giveback_available: int
    unknown_fields: tuple[str, ...]
    complete: bool
    issues: tuple[str, ...]
    equity_points: tuple[EquityPoint, ...]
    contributions: tuple[Contribution, ...]
    opportunities: tuple[Opportunity, ...]
    recovery: tuple[RecoveryEpisode, ...]
    source_refs: tuple[str, ...]
    metrics: tuple[Metric, ...]
    metrics_start_ms: int | None
    daily_samples: tuple[EquityPoint, ...]
    utilization: tuple[UtilizationInterval, ...]
    structural_complete: bool
    capital_observations: tuple[CapitalObservation, ...]


def _number(value: Decimal, *, nonnegative: bool = False) -> Fraction:
    if not isinstance(value, Decimal) or not value.is_finite() or (nonnegative and value < 0):
        raise ValueError("finite Decimal with appropriate sign required")
    return Fraction(value)


def _time(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("nonnegative integer timestamp required")


def _text(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty source text required")


def _provenance(
    records: tuple[
        EquityPoint
        | Contribution
        | Opportunity
        | RecoveryEpisode
        | UtilizationInterval
        | CapitalObservation,
        ...,
    ],
    kind: str,
    issues: list[str],
) -> None:
    """IDs are caller-supplied stable source identities, never synthesized from order."""
    seen: set[str] = set()
    for index, row in enumerate(records):
        if row.id is None:
            issues.append(f"missing_{kind}_id:{index}")
        else:
            _text(row.id)
            if row.id in seen:
                raise ValueError(f"duplicate {kind} ID; evidence not deduplicated")
            seen.add(row.id)
        if not row.source_refs:
            issues.append(f"missing_{kind}_source_refs:{row.id if row.id is not None else index}")
        for reference in row.source_refs:
            _text(reference)
        if len(set(row.source_refs)) != len(row.source_refs):
            raise ValueError(f"duplicate {kind} source reference")


def _decimal(value: Fraction, *, ratio: bool = False) -> Decimal:
    precision = (
        60 if ratio else len(str(abs(value.numerator))) + 4 * len(str(value.denominator)) + 10
    )
    with localcontext(Context(prec=precision)):
        return Decimal(value.numerator) / Decimal(value.denominator)


def _sum(rows: tuple[Contribution, ...], field: str) -> Fraction:
    return sum((Fraction(getattr(row, field)) for row in rows), Fraction(0))


def _dimensions(rows: tuple[Contribution, ...], field: str) -> tuple[DimensionTotal, ...]:
    keys = sorted(
        {getattr(row, field) for row in rows}, key=lambda key: (key is not None, key or "")
    )
    totals = []
    for key in keys:
        group = tuple(row for row in rows if getattr(row, field) == key)
        gross, fees, funding = (
            _sum(group, column) for column in ("gross_pnl", "fees", "funding_signed")
        )
        totals.append(
            DimensionTotal(
                key,
                _decimal(gross),
                _decimal(fees),
                _decimal(funding),
                _decimal(gross - fees + funding),
                _decimal(_sum(group, "turnover")),
            )
        )
    return tuple(totals)


def _opportunity_episodes(
    events: tuple[Opportunity, ...], gap: int
) -> tuple[OpportunityEpisode, ...]:
    groups: list[list[Opportunity]] = []
    # Stable time sorting per asset preserves same-timestamp stage order as supplied.
    for asset in sorted({event.asset for event in events}):
        current: list[Opportunity] = []
        for event in sorted(
            (event for event in events if event.asset == asset),
            key=lambda event: event.timestamp_ms,
        ):
            if current and (
                event.direction != current[-1].direction
                or event.structure != current[-1].structure
                or event.timestamp_ms - current[-1].timestamp_ms > gap
            ):
                groups.append(current)
                current = []
            current.append(event)
        if current:
            groups.append(current)
    results = []
    for group in groups:
        detections = [event.timestamp_ms for event in group if event.stage == "detected"]
        fills = [event.timestamp_ms for event in group if event.stage == "filled"]
        delay = (
            fills[0] - detections[0] if detections and fills and fills[0] >= detections[0] else None
        )
        first, last = group[0], group[-1]
        results.append(
            OpportunityEpisode(
                first.asset,
                first.direction,
                first.structure,
                first.timestamp_ms,
                last.timestamp_ms,
                len(group),
                tuple(dict.fromkeys(event.stage for event in group)),
                tuple(dict.fromkeys(event.reason for event in group if event.reason is not None)),
                delay,
                tuple(event.id for event in group),
                tuple(dict.fromkeys(ref for event in group for ref in event.source_refs)),
            )
        )
    return tuple(results)


def _metrics(
    initial: Decimal,
    points: tuple[EquityPoint, ...],
    start: int | None,
    samples: tuple[EquityPoint, ...],
    utilization: tuple[UtilizationInterval, ...],
    capital_observations: tuple[CapitalObservation, ...],
    net_return: Decimal | None,
    drawdown: Decimal | None,
) -> tuple[Metric, ...]:
    definitions = {
        "cagr": "Compounded net growth over elapsed time; 365.25-day year; no external transfers.",
        "return_drawdown": "Net return divided by observed lifetime maximum drawdown; not CAGR/DD.",
        "sharpe": "UTC daily boundary simple net returns; zero risk-free rate; "
        "sample standard deviation (n-1); annualization sqrt(365).",
        "utilization": "Time-weighted left-constant (marked spot inventory + futures collateral) "
        "/ equity; excludes pending cash and futures notional; supplied intervals only.",
    }
    result: list[Metric] = []

    def add(name: str, value: Decimal | None, reason: str | None = None) -> None:
        result.append(Metric(name, value, definitions[name], reason))

    if start is not None:
        _time(start)
    for point in samples:
        _time(point.timestamp_ms)
        _number(point.equity)
    for interval in utilization:
        _time(interval.start_ms)
        _time(interval.end_ms)
        _number(interval.spot_value, nonnegative=True)
        _number(interval.futures_collateral, nonnegative=True)
        _number(interval.equity)
        if interval.end_ms <= interval.start_ms:
            raise ValueError("positive utilization interval required")
    opening_known = bool(
        points
        and start is not None
        and points[0].timestamp_ms == start
        and points[0].equity == initial
    )
    end = points[-1].timestamp_ms if points else None
    duration = end - start if end is not None and start is not None else 0
    if not opening_known:
        add("cagr", None, "opening_time_unavailable")
    elif duration <= 0:
        add("cagr", None, "nonpositive_duration")
    elif points[-1].equity <= 0:
        add("cagr", None, "nonpositive_terminal_equity")
    else:
        try:
            with localcontext(Context(prec=60)):
                value = (points[-1].equity / initial) ** (Decimal(31_557_600_000) / duration) - 1
            add("cagr", value)
        except DecimalException:
            add("cagr", None, "numeric_range")
    if net_return is None or drawdown is None:
        add("return_drawdown", None, "equity_unavailable")
    elif drawdown == 0:
        add("return_drawdown", None, "zero_drawdown")
    else:
        add("return_drawdown", _decimal(Fraction(net_return) / Fraction(drawdown), ratio=True))
    marks: dict[int, set[Decimal]] = {}
    for point in points:
        marks.setdefault(point.timestamp_ms, set()).add(point.equity)
    # Timestamp-only samples cannot choose among distinct same-time event marks.
    # Repeated identical values are unambiguous; no implicit last-mark rule applies.
    retained_points = set(points)
    if not samples:
        add("sharpe", None, "daily_samples_unavailable")
    elif (
        not opening_known
        or len(samples) < 3
        or samples[0] != points[0]
        or samples[-1] != points[-1]
        or any(
            p not in retained_points
            or p.timestamp_ms % 86_400_000
            or marks.get(p.timestamp_ms) != {p.equity}
            for p in samples
        )
        or any(
            b.timestamp_ms - a.timestamp_ms != 86_400_000
            for a, b in zip(samples, samples[1:], strict=False)
        )
    ):
        add("sharpe", None, "incomplete_or_unmatched_daily_samples")
    elif any(p.equity <= 0 for p in samples):
        add("sharpe", None, "nonpositive_daily_equity")
    else:
        returns = [
            Fraction(b.equity) / Fraction(a.equity) - 1
            for a, b in zip(samples, samples[1:], strict=False)
        ]
        mean = sum(returns, Fraction(0)) / len(returns)
        variance = sum(((r - mean) * (r - mean) for r in returns), Fraction(0)) / (len(returns) - 1)
        if not variance:
            add("sharpe", None, "zero_variance")
        else:
            with localcontext(Context(prec=60)):
                value = (
                    _decimal(mean, ratio=True)
                    / _decimal(variance, ratio=True).sqrt()
                    * Decimal(365).sqrt()
                )
            add("sharpe", value)
    capital_by_id = {row.id: row for row in capital_observations}
    equity_by_id = {point.id: point for point in points}
    equity_counts = Counter(point.timestamp_ms for point in points)
    capital_counts = Counter(row.timestamp_ms for row in capital_observations)

    def capital_matches(interval: UtilizationInterval) -> bool:
        observation = capital_by_id.get(interval.observation_id)
        if observation is None or observation.id is None:
            return False
        point = equity_by_id.get(observation.equity_observation_id)
        return bool(
            observation.phase_id
            and observation.source_refs
            and point is not None
            and point.id is not None
            and point.source_refs
            and equity_counts[interval.start_ms] == 1
            and capital_counts[interval.start_ms] == 1
            and not any(
                interval.start_ms < row.timestamp_ms < interval.end_ms
                for row in capital_observations
            )
            and observation.timestamp_ms == point.timestamp_ms == interval.start_ms
            and observation.equity == point.equity == interval.equity
            and observation.spot_value == interval.spot_value
            and observation.futures_collateral == interval.futures_collateral
        )

    if not utilization:
        add("utilization", None, "utilization_unavailable")
    elif (
        not opening_known
        or duration <= 0
        or utilization[0].start_ms != start
        or utilization[-1].end_ms != end
        or any(a.end_ms != b.start_ms for a, b in zip(utilization, utilization[1:], strict=False))
        or any(row.equity <= 0 or marks.get(row.start_ms) != {row.equity} for row in utilization)
    ):
        add("utilization", None, "incomplete_or_unmatched_utilization")
    elif any(not capital_matches(row) for row in utilization):
        add("utilization", None, "unmatched_capital_observation")
    else:
        weighted = sum(
            (
                (Fraction(row.spot_value) + Fraction(row.futures_collateral))
                / Fraction(row.equity)
                * (row.end_ms - row.start_ms)
                for row in utilization
            ),
            Fraction(0),
        )
        add("utilization", _decimal(weighted / duration, ratio=True))
    return tuple(result)


def analyze(
    initial: Decimal,
    equitypoints: tuple[EquityPoint, ...],
    contributions: tuple[Contribution, ...],
    opportunities: tuple[Opportunity, ...],
    recovery: tuple[RecoveryEpisode, ...],
    source_refs: tuple[str, ...],
    *,
    opportunity_gap_ms: int = 3_600_000,
    metrics_start_ms: int | None = None,
    daily_samples: tuple[EquityPoint, ...] = (),
    utilization: tuple[UtilizationInterval, ...] = (),
    capital_observations: tuple[CapitalObservation, ...] = (),
) -> Report:
    """Summarize observations without counterfactual claims or silent deduplication.

    MFE/giveback are supplied quote-currency observations, never derived from net
    PnL. Bad intervals are adjacent observed marks, NOT calendar returns. Recovery
    change is end minus start equity under the no-external-transfer account model,
    NOT an incremental causal benefit. Ratios use Decimal precision60; money sums
    and the reconciliation residual remain exact. Optional unknown fields do not
    themselves make structurally valid evidence incomplete. Required performance metrics
    must be available for complete=True; structural_complete separately describes the
    original evidence checks. Explicit daily samples and utilization intervals are
    reporting conventions only, never strategy inputs or acceptance-rule changes.
    """
    opening = _number(initial)
    if opening <= 0 or type(opportunity_gap_ms) is not int or opportunity_gap_ms <= 0:
        raise ValueError("positive initial equity and observation gap required")
    points, rows = tuple(equitypoints), tuple(contributions)
    events, episodes, sources = tuple(opportunities), tuple(recovery), tuple(source_refs)
    capital_observations = tuple(capital_observations)
    for source in sources:
        _text(source)
    issues: list[str] = []
    for kind, records in (
        ("equity", points),
        ("contribution", rows),
        ("opportunity", events),
        ("recovery", episodes),
        ("daily_sample", tuple(daily_samples)),
        ("utilization", tuple(utilization)),
        ("capital_observation", capital_observations),
    ):
        _provenance(records, kind, issues)
    marks: dict[int, set[Decimal]] = {}
    previous = -1
    for point in points:
        _time(point.timestamp_ms)
        _number(point.equity)
        if point.timestamp_ms < previous:
            raise ValueError("equity observations must be chronological")
        previous = point.timestamp_ms
        marks.setdefault(point.timestamp_ms, set()).add(point.equity)
    equity_by_id = {point.id: point for point in points}
    for observation in capital_observations:
        _time(observation.timestamp_ms)
        _number(observation.equity)
        _number(observation.spot_value, nonnegative=True)
        _number(observation.futures_collateral, nonnegative=True)
        for field in ("phase_id", "equity_observation_id"):
            value = getattr(observation, field)
            if value is None:
                issues.append(f"missing_capital_observation_{field}:{observation.id}")
            else:
                _text(value)
        matched_point = equity_by_id.get(observation.equity_observation_id)
        if (
            matched_point is None
            or matched_point.id is None
            or matched_point.timestamp_ms != observation.timestamp_ms
            or matched_point.equity != observation.equity
        ):
            issues.append(f"unmatched_capital_equity_observation:{observation.id}")
    for interval in utilization:
        if interval.observation_id is not None:
            _text(interval.observation_id)
    ids: set[str] = set()
    for row in rows:
        for text in (row.id, row.strategy, row.asset, row.direction):
            _text(text)
        if row.id in ids:
            raise ValueError("duplicate contribution ID; evidence not deduplicated")
        ids.add(row.id)
        if row.direction not in {"long", "short"} or row.status not in {"closed", "open_marked"}:
            raise ValueError("explicit direction and closed/open_marked status required")
        _time(row.entry_ms)
        if row.exit_ms is not None:
            _time(row.exit_ms)
            if row.exit_ms < row.entry_ms:
                raise ValueError("exit precedes entry")
        if (row.status == "closed") != (row.exit_ms is not None):
            raise ValueError("status and exit timestamp disagree")
        if points and (
            not points[0].timestamp_ms <= row.entry_ms <= points[-1].timestamp_ms
            or (row.exit_ms is not None and row.exit_ms > points[-1].timestamp_ms)
        ):
            issues.append("contribution_outside_equity_window")
        for optional_text in (row.regime, row.exit_reason):
            if optional_text is not None:
                _text(optional_text)
        for amount in (row.gross_pnl, row.funding_signed):
            _number(amount)
        for amount in (row.fees, row.turnover):
            _number(amount, nonnegative=True)
        for optional_amount in (row.mfe, row.giveback):
            if optional_amount is not None:
                _number(optional_amount, nonnegative=True)
    for event in events:
        _time(event.timestamp_ms)
        if points and not points[0].timestamp_ms <= event.timestamp_ms <= points[-1].timestamp_ms:
            issues.append("opportunity_outside_equity_window")
        for text in (event.asset, event.direction, event.structure, event.stage):
            _text(text)
        if event.direction not in {"long", "short"}:
            raise ValueError("opportunity direction required")
        if event.reason is not None:
            _text(event.reason)
    changes = []
    for episode in episodes:
        _time(episode.start_ms)
        start = _number(episode.equity_start)
        if start <= 0:
            raise ValueError("positive recovery opening equity required")
        if (episode.end_ms is None) != (episode.equity_end is None):
            raise ValueError("recovery endpoint must be jointly known or unknown")
        delta = None
        if episode.end_ms is not None and episode.equity_end is not None:
            _time(episode.end_ms)
            if episode.end_ms < episode.start_ms:
                raise ValueError("recovery end precedes start")
            end = _number(episode.equity_end)
            # Timestamp alone cannot identify an endpoint when several distinct
            # event marks share it. Never choose a favorable mark or interpolate.
            if marks.get(episode.start_ms) == {episode.equity_start} and marks.get(
                episode.end_ms
            ) == {episode.equity_end}:
                delta = end - start
            else:
                issues.append("unverified_recovery_endpoint")
        else:
            issues.append("unverified_recovery_endpoint")
        changes.append(
            RecoveryChange(
                episode,
                _decimal(delta) if delta is not None else None,
                _decimal(delta / start, ratio=True) if delta is not None else None,
            )
        )
    fees, funding, gross, turnover = (
        _sum(rows, field) for field in ("fees", "funding_signed", "gross_pnl", "turnover")
    )
    if not sources:
        issues.append("missing_source_refs")
    final, profit, ratio, drawdown, residual = None, None, None, None, None
    bad = []
    if not points:
        issues.append("missing_equity_observations")
    else:
        final = points[-1].equity
        net = Fraction(final) - opening
        profit, ratio = _decimal(net), _decimal(net / opening, ratio=True)
        peak, worst = opening, Fraction(0)
        for point in points:
            marked = Fraction(point.equity)
            peak = max(peak, marked)
            worst = max(worst, (peak - marked) / peak)
        drawdown = _decimal(worst, ratio=True)
        difference = Fraction(final) - opening - gross + fees - funding
        residual = _decimal(difference)
        if difference:
            issues.append("contribution_equity_residual")
        for before, after in zip(points, points[1:], strict=False):
            delta = Fraction(after.equity) - Fraction(before.equity)
            if delta < 0:
                interval_return = delta / Fraction(before.equity) if before.equity > 0 else None
                bad.append(
                    BadInterval(
                        before.timestamp_ms,
                        after.timestamp_ms,
                        _decimal(delta),
                        _decimal(interval_return, ratio=True)
                        if interval_return is not None
                        else None,
                    )
                )
    assets = _dimensions(rows, "asset")
    winners = [Fraction(asset.net_pnl) for asset in assets if asset.net_pnl > 0]
    concentration = _decimal(max(winners) / sum(winners), ratio=True) if winners else None
    opportunity_groups = _opportunity_episodes(events, opportunity_gap_ms)
    exits = Counter(row.exit_reason for row in rows if row.status == "closed")
    unknown = set()
    for field in ("regime", "mfe", "giveback"):
        if any(getattr(row, field) is None for row in rows):
            unknown.add(field)
    if any(row.exit_reason is None for row in rows if row.status == "closed"):
        unknown.add("exit_reason")
    if any(group.entry_delay_ms is None for group in opportunity_groups):
        unknown.add("entry_delay")
    if any(change.marked_change is None for change in changes):
        unknown.add("recovery_endpoint")
    structural_complete = not issues
    metrics = _metrics(
        initial,
        points,
        metrics_start_ms,
        tuple(daily_samples),
        tuple(utilization),
        capital_observations,
        ratio,
        drawdown,
    )
    issues.extend(
        f"metric_unavailable:{m.name}:{m.unavailable_reason}" for m in metrics if m.value is None
    )
    return Report(
        initial,
        final,
        profit,
        ratio,
        drawdown,
        _decimal(fees),
        _decimal(funding),
        _decimal(turnover),
        residual,
        _dimensions(rows, "strategy"),
        assets,
        _dimensions(rows, "direction"),
        _dimensions(rows, "regime"),
        concentration,
        tuple(bad),
        opportunity_groups,
        opportunity_gap_ms,
        tuple(changes),
        sum(row.status == "closed" for row in rows),
        sum(row.status == "open_marked" for row in rows),
        tuple(sorted(exits.items(), key=lambda pair: (pair[0] is not None, pair[0] or ""))),
        sum(row.mfe is not None for row in rows),
        sum(row.giveback is not None for row in rows),
        tuple(sorted(unknown)),
        not issues,
        tuple(issues),
        points,
        rows,
        events,
        episodes,
        sources,
        metrics,
        metrics_start_ms,
        tuple(daily_samples),
        tuple(utilization),
        structural_complete,
        capital_observations,
    )
