"""Evidence-only attribution and observation summaries; never strategy inputs.

Contributions include whole lifecycle gross PnL, with open marked PnL explicitly
identified. Funding is signed wallet cash flow. Completeness is structural only:
source reference strings are retained, not fetched or cryptographically verified.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp_ms: int
    equity: Decimal


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


@dataclass(frozen=True, slots=True)
class Opportunity:
    timestamp_ms: int
    asset: str
    direction: str
    structure: str
    stage: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class RecoveryEpisode:
    start_ms: int
    end_ms: int | None
    equity_start: Decimal
    equity_end: Decimal | None


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


@dataclass(frozen=True, slots=True)
class RecoveryChange:
    episode: RecoveryEpisode
    marked_change: Decimal | None
    return_fraction: Decimal | None


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
            )
        )
    return tuple(results)


def analyze(
    initial: Decimal,
    equitypoints: tuple[EquityPoint, ...],
    contributions: tuple[Contribution, ...],
    opportunities: tuple[Opportunity, ...],
    recovery: tuple[RecoveryEpisode, ...],
    source_refs: tuple[str, ...],
    *,
    opportunity_gap_ms: int = 3_600_000,
) -> Report:
    """Summarize observations without counterfactual claims or silent deduplication.

    MFE/giveback are supplied quote-currency observations, never derived from net
    PnL. Bad intervals are adjacent observed marks, NOT calendar returns. Recovery
    change is end minus start equity under the no-external-transfer account model,
    NOT an incremental causal benefit. Ratios use Decimal precision60; money sums
    and the reconciliation residual remain exact. Optional unknown fields do not
    themselves make structurally valid evidence incomplete.
    """
    opening = _number(initial)
    if opening <= 0 or type(opportunity_gap_ms) is not int or opportunity_gap_ms <= 0:
        raise ValueError("positive initial equity and observation gap required")
    points, rows = tuple(equitypoints), tuple(contributions)
    events, episodes, sources = tuple(opportunities), tuple(recovery), tuple(source_refs)
    for source in sources:
        _text(source)
    previous = -1
    for point in points:
        _time(point.timestamp_ms)
        _number(point.equity)
        if point.timestamp_ms < previous:
            raise ValueError("equity observations must be chronological")
        previous = point.timestamp_ms
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
            delta = _number(episode.equity_end) - start
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
    issues = []
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
    )
