"""Evidence-only attribution and observation summaries; never strategy inputs.

Contributions include whole lifecycle gross PnL, with open marked PnL explicitly
identified. Funding is signed wallet cash flow. Completeness is structural only:
source reference strings are retained, not fetched or cryptographically verified.
"""

from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Context, Decimal, DecimalException, localcontext
from fractions import Fraction
from types import MappingProxyType

from crypto_grid_bot.combined.evidence import PHASES
from crypto_grid_bot.combined.observation_policy import PolicyEvidence, validate_boundaries


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
    """One funnel stage; a refusal keeps every reason, ``reason`` being the first."""

    timestamp_ms: int
    asset: str
    direction: str
    structure: str
    stage: str
    reason: str | None
    id: str | None = None
    source_refs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.source_refs, str) or isinstance(self.reasons, str):
            raise ValueError("source_refs and reasons must be collections, not strings")
        object.__setattr__(self, "source_refs", tuple(self.source_refs))
        reasons = tuple(self.reasons) or ((self.reason,) if self.reason is not None else ())
        if reasons and reasons[0] != self.reason:
            raise ValueError("the first of an opportunity's reasons is its reason")
        object.__setattr__(self, "reasons", reasons)


# The stretches of the recovery controller a record can describe.
RECOVERY_KINDS = ("liquidation", "cooldown", "episode", "terminal")


@dataclass(frozen=True, slots=True)
class RecoveryEpisode:
    """One stretch of recovery, priced from its start mark to its end mark.

    ``kind`` says which: the forced ``liquidation`` after a stop, a ``cooldown``, an
    ``episode`` (one restart at the 25% allowance, to its 3% stop, normal restoration or
    the window end) or the ``terminal`` state. ``end_reason`` says what ended it. Only a
    ``terminal`` stretch may open at or below zero equity: capital exhaustion is one way
    into that state, and the record keeps the exhausted mark as its opening.
    """

    start_ms: int
    end_ms: int | None
    equity_start: Decimal
    equity_end: Decimal | None
    id: str | None = None
    source_refs: tuple[str, ...] = ()
    # Retained equity observation IDs of the endpoints. Several marks can share a
    # timestamp, so an ID, not the time alone, identifies the endpoint state.
    start_observation_id: str | None = None
    end_observation_id: str | None = None
    kind: str = "episode"
    end_reason: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.source_refs, str):
            raise ValueError("source_refs must be a collection, not a string")
        object.__setattr__(self, "source_refs", tuple(self.source_refs))
        if self.kind not in RECOVERY_KINDS:
            raise ValueError(f"recovery kind must be one of {', '.join(RECOVERY_KINDS)}")


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
class DrawdownEpisode:
    """A fall from the lifetime peak to its lowest mark before equity regains the peak.

    ``recovery_ms`` is the first mark back at or above the peak; None when the window
    ended first. ``depth`` is (peak - trough) / peak.
    """

    peak_ms: int
    peak_equity: Decimal
    trough_ms: int
    trough_equity: Decimal
    recovery_ms: int | None
    depth: Decimal


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
    is not authenticated; it cannot skip a retained capital or equity observation.
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
    policy_evidence: PolicyEvidence | None = None
    # Issues the evidence producer declared (for example a failed replay); retained so
    # a recomputation from the report's own fields reproduces it exactly.
    producer_issues: tuple[str, ...] = ()
    # The registered window's skipped hours the report was built against; retained for
    # the same reason. A daily return may span only these midnights.
    skipped_hours: tuple[int, ...] = ()
    # What the producer discloses (data gaps, native timing, rulings applied). Information
    # only: never an input to completeness, metrics or acceptance.
    disclosures: tuple[str, ...] = ()
    # The registered capital scenario (``experiment.capital_label``); None when unstated.
    capital_label: str | None = None
    # The window's three deepest falls from the lifetime peak, deepest first.
    drawdown_episodes: tuple[DrawdownEpisode, ...] = ()
    # Maximum observed gross leverage: the highest gross notional over equity at any
    # engine mark, exact. None when the producer has no engine marks, or a mark held
    # exposure without positive equity (unbounded). Information only, like disclosures.
    max_gross_leverage: Fraction | None = None


# Design package D: "Trade-to-equity residual <=1e-18 USDT only, all residuals retained and
# reported." A residual within it is disclosed, never an issue; a larger one is an issue.
RESIDUAL_TOLERANCE = Fraction(1, 10**18)
# Every report whose run applies today's saved exchange filters to historical data says so
# in these words (design: "Historical use of present-day saved filters is disclosed").
SAVED_FILTERS_DISCLOSURE = "present_day_saved_exchange_filters_on_historical_data"
# The capital scenarios ``experiment.capital_label`` names: the owner's three starting
# capitals, all USDT (owner decision, 2026-10-14; it replaced 10,000 USDT plus EUR 100 at
# the ECB rate). Each label, in the registration's cell order, with the capital id it names
# and the opening equity, in USDT, it requires. No capital converts a currency. Read-only,
# so ``experiment.CAPITALS``, built from it at import, can never drift from it.
CAPITAL_LABELS: Mapping[str, tuple[str, int]] = MappingProxyType(
    {
        "research_10000_usdt": ("research", 10000),
        "medium_1000_usdt": ("medium", 1000),
        "small_100_usdt": ("small", 100),
    }
)


def capital_label_id(label: object) -> str | None:
    """The capital id a capital label names (``CAPITAL_LABELS``); None for anything else."""
    named = CAPITAL_LABELS.get(label) if isinstance(label, str) else None
    return None if named is None else named[0]


def _capital_label_matches(label: str, opening: Fraction) -> bool:
    """A label of ``CAPITAL_LABELS`` whose report opens with exactly its USDT amount."""
    named = CAPITAL_LABELS.get(label)
    return named is not None and opening == named[1]


def utc_text(timestamp_ms: int) -> str:
    """A UTC instant as ISO 8601 text for a disclosure; milliseconds only when present."""
    moment = datetime.fromtimestamp(timestamp_ms // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{moment}.{timestamp_ms % 1000:03d}Z" if timestamp_ms % 1000 else f"{moment}Z"


def span_text(name: str, stamps: Iterable[int]) -> str:
    """``<name>=<count> first=<time> last=<time>``: a long series kept to one line."""
    ordered = sorted(stamps)
    if not ordered:
        raise ValueError("a disclosed span needs at least one time")
    return f"{name}={len(ordered)} first={utc_text(ordered[0])} last={utc_text(ordered[-1])}"


def skipped_hours_disclosures(skipped_hours: tuple[int, ...]) -> tuple[str, ...]:
    """The registered skipped hours, listed in full: every arm skips them alike."""
    if not isinstance(skipped_hours, tuple) or any(type(h) is not int for h in skipped_hours):
        raise ValueError("skipped hours must be a tuple of integer hour stamps")
    if not skipped_hours:
        return ()
    hours = ",".join(utc_text(hour) for hour in skipped_hours)
    return (f"registered_skipped_hours: count={len(skipped_hours)} at={hours}",)


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


def _drawdown_episodes(
    initial: Decimal, points: tuple[EquityPoint, ...]
) -> tuple[DrawdownEpisode, ...]:
    """The three deepest falls from the lifetime peak, deepest first (earlier on a tie).

    The opening capital is the first peak, at the first mark's time; a mark equal to the
    peak regains it and becomes the peak a later fall starts from.
    """
    if not points:
        return ()
    peak, peak_equity, peak_ms = Fraction(initial), initial, points[0].timestamp_ms
    trough: tuple[Fraction, Decimal, int] | None = None
    found: list[tuple[Fraction, DrawdownEpisode]] = []

    def close(recovery_ms: int | None) -> None:
        if trough is not None:
            depth = (peak - trough[0]) / peak
            found.append(
                (
                    depth,
                    DrawdownEpisode(
                        peak_ms,
                        peak_equity,
                        trough[2],
                        trough[1],
                        recovery_ms,
                        _decimal(depth, ratio=True),
                    ),
                )
            )

    for point in points:
        value = Fraction(point.equity)
        if value >= peak:
            close(point.timestamp_ms)
            trough = None
            peak, peak_equity, peak_ms = value, point.equity, point.timestamp_ms
        elif trough is None or value < trough[0]:
            trough = (value, point.equity, point.timestamp_ms)
    close(None)
    ranked = sorted(found, key=lambda pair: -pair[0])
    return tuple(episode for _, episode in ranked[:3])


def _opportunity_episodes(
    events: tuple[Opportunity, ...], gap: int, issues: list[str]
) -> tuple[OpportunityEpisode, ...]:
    groups: list[list[Opportunity]] = []
    # Stable time sorting per asset preserves same-timestamp stage order as supplied.
    for asset in sorted({event.asset for event in events}):
        current: list[Opportunity] = []
        for event in sorted(
            (event for event in events if event.asset == asset),
            key=lambda event: event.timestamp_ms,
        ):
            delayed_fill = (
                event.stage == "filled"
                and bool(current)
                and current[-1].stage in ("submitted", "filled")
                and event.direction == current[-1].direction
                and event.structure == current[-1].structure
            )
            if (
                current
                and not delayed_fill
                and (
                    event.direction != current[-1].direction
                    or event.structure != current[-1].structure
                    or event.timestamp_ms - current[-1].timestamp_ms > gap
                )
            ):
                groups.append(current)
                current = []
            current.append(event)
        if current:
            groups.append(current)
    results = []
    for group in groups:
        # These are sparse episode observations, not a complete DecisionEvent journal.
        # A repeated detection restarts the local funnel without inventing an episode.
        prior_rank: int | None = None
        blocked = False
        for event in group:
            if event.stage == "detected":
                prior_rank, blocked = 0, False
            elif event.stage == "blocked":
                if (
                    prior_rank is None
                    or prior_rank == len(PHASES) - 1
                    or blocked
                    or not event.reason
                ):
                    issues.append(f"invalid_opportunity_stage_order:{event.id}")
                blocked = True
            elif event.stage not in PHASES:
                issues.append(f"invalid_opportunity_stage:{event.id}")
            else:
                rank = PHASES.index(event.stage)
                if prior_rank is None or rank < prior_rank or blocked:
                    issues.append(f"invalid_opportunity_stage_order:{event.id}")
                prior_rank = rank
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
                tuple(dict.fromkeys(reason for event in group for reason in event.reasons)),
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
    policy_evidence: PolicyEvidence | None = None,
    skipped_hours: tuple[int, ...] = (),
) -> tuple[Metric, ...]:
    try:
        boundaries = (
            validate_boundaries(policy_evidence, tuple((p.timestamp_ms, p.id) for p in points))
            if policy_evidence is not None
            else {}
        )
    except (ValueError, TypeError, AttributeError):
        boundaries = {}
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
    # A daily return may span a registered skipped midnight (owner, 2026-10-11): the
    # two days merge into one sample, and the definition names the merged dates. Any
    # other missing daily sample leaves Sharpe unavailable.
    skipped = frozenset(skipped_hours)
    merged: list[int] = []
    steps_valid = True
    for a, b in zip(samples, samples[1:], strict=False):
        spanned = range(a.timestamp_ms + 86_400_000, b.timestamp_ms, 86_400_000)
        if b.timestamp_ms <= a.timestamp_ms or not all(day in skipped for day in spanned):
            steps_valid = False
            break
        merged.extend(spanned)
    if merged and steps_valid:
        dates = ", ".join(
            datetime.fromtimestamp(day // 1000, UTC).date().isoformat() for day in merged
        )
        definitions["sharpe"] += f" A return spans each skipped UTC midnight: {dates}."
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
            or (policy_evidence is not None and p.timestamp_ms not in boundaries)
            or p.timestamp_ms % 86_400_000
            or (
                boundaries[p.timestamp_ms].selected_equity_id != p.id
                if p.timestamp_ms in boundaries
                else marks.get(p.timestamp_ms) != {p.equity}
            )
            for p in samples
        )
        or not steps_valid
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
    point_times = sorted(point.timestamp_ms for point in points)
    capital_times = sorted(row.timestamp_ms for row in capital_observations)

    def strictly_inside(times: list[int], start: int, end: int) -> bool:
        index = bisect_right(times, start)
        return index < len(times) and times[index] < end

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
            and (policy_evidence is None or interval.start_ms in boundaries)
            and (
                (
                    boundaries[interval.start_ms].capital_id == observation.id
                    and boundaries[interval.start_ms].observation_ids[-1] == point.id
                    and observation.phase_id == boundaries[interval.start_ms].role
                )
                if interval.start_ms in boundaries
                else (
                    equity_counts[interval.start_ms] == 1 and capital_counts[interval.start_ms] == 1
                )
            )
            and not strictly_inside(capital_times, interval.start_ms, interval.end_ms)
            and not strictly_inside(point_times, interval.start_ms, interval.end_ms)
            and observation.timestamp_ms == point.timestamp_ms == interval.start_ms
            and observation.equity == point.equity == interval.equity
            and observation.spot_value == interval.spot_value
            and observation.futures_collateral == interval.futures_collateral
        )

    terminal_capital = [
        row
        for row in capital_observations
        if row.timestamp_ms == end
        and (end not in boundaries or row.id == boundaries[end].capital_id)
    ]
    terminal_verified = bool(
        points
        and end is not None
        and (
            equity_counts[end] == 1
            or (
                end in boundaries
                and boundaries[end].role == "terminal"
                and boundaries[end].selected_equity_id == points[-1].id
            )
        )
        and len(terminal_capital) == 1
        and points[-1].id
        and points[-1].source_refs
        and terminal_capital[0].id
        and terminal_capital[0].phase_id
        and (
            policy_evidence is None
            or (end in boundaries and terminal_capital[0].phase_id == "terminal")
        )
        and terminal_capital[0].source_refs
        and terminal_capital[0].equity_observation_id == points[-1].id
        and terminal_capital[0].equity == points[-1].equity
    )

    if not utilization:
        add("utilization", None, "utilization_unavailable")
    elif (
        not opening_known
        or duration <= 0
        or utilization[0].start_ms != start
        or utilization[-1].end_ms != end
        or any(a.end_ms != b.start_ms for a, b in zip(utilization, utilization[1:], strict=False))
        or any(
            row.equity <= 0
            or (row.start_ms not in boundaries and marks.get(row.start_ms) != {row.equity})
            for row in utilization
        )
    ):
        add("utilization", None, "incomplete_or_unmatched_utilization")
    elif not terminal_verified:
        add("utilization", None, "unverified_terminal_capital_observation")
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
    policy_evidence: PolicyEvidence | None = None,
    producer_issues: tuple[str, ...] = (),
    skipped_hours: tuple[int, ...] = (),
    disclosures: tuple[str, ...] = (),
    capital_label: str | None = None,
    max_gross_leverage: Fraction | None = None,
) -> Report:
    """Summarize observations without counterfactual claims or silent deduplication.

    MFE/giveback are supplied quote-currency observations, never derived from net
    PnL. Bad intervals are adjacent observed marks, NOT calendar returns; drawdown
    episodes are the three deepest falls from the lifetime peak. Recovery
    change is end minus start equity under the no-external-transfer account model,
    NOT an incremental causal benefit; its return is that change over a positive opening.
    Every recovery record must open above zero equity except a ``terminal`` one, which
    capital exhaustion can open at or below zero: it keeps its marked change and has no
    return, and its nonpositive mark is already the ``nonpositive_equity_observation``
    issue. Ratios use Decimal precision60; money sums
    and the reconciliation residual remain exact. Optional unknown fields do not
    themselves make structurally valid evidence incomplete. Required performance metrics
    must be available for complete=True; structural_complete separately describes the
    original evidence checks. Explicit daily samples and utilization intervals are
    reporting conventions only, never strategy inputs or acceptance-rule changes.
    ``skipped_hours`` are the registered window's skipped hours; a daily return may
    span only a skipped midnight. Acceptance checks them against the registration.
    ``disclosures``, ``capital_label`` and ``max_gross_leverage`` are carried unchanged
    and judge nothing; the label must agree with the initial equity, or the report is
    malformed. A nonzero reconciliation residual up to ``RESIDUAL_TOLERANCE`` is retained
    and disclosed once, as ``accounting_residual_within_tolerance:<value>``; only a larger
    one is the ``contribution_equity_residual`` issue.
    """
    opening = _number(initial)
    if opening <= 0 or type(opportunity_gap_ms) is not int or opportunity_gap_ms <= 0:
        raise ValueError("positive initial equity and observation gap required")
    if isinstance(source_refs, str):
        raise ValueError("source_refs must be a collection, not a string")
    points, rows = tuple(equitypoints), tuple(contributions)
    events, episodes, sources = tuple(opportunities), tuple(recovery), tuple(source_refs)
    capital_observations = tuple(capital_observations)
    for source in sources:
        _text(source)
    if isinstance(producer_issues, str) or any(
        not isinstance(issue, str) or not issue.strip() for issue in producer_issues
    ):
        raise ValueError("producer issues must be nonempty strings")
    if not isinstance(skipped_hours, tuple) or any(type(h) is not int for h in skipped_hours):
        raise ValueError("skipped hours must be a tuple of integer hour stamps")
    if not isinstance(disclosures, tuple) or any(
        not isinstance(note, str) or not note.strip() for note in disclosures
    ):
        raise ValueError("disclosures must be a tuple of nonempty strings")
    if capital_label is not None and (
        not isinstance(capital_label, str) or not _capital_label_matches(capital_label, opening)
    ):
        raise ValueError("capital label must name a capital scenario matching the initial equity")
    if max_gross_leverage is not None and (
        type(max_gross_leverage) is not Fraction or max_gross_leverage < 0
    ):
        raise ValueError("maximum gross leverage must be a nonnegative exact Fraction")
    issues: list[str] = list(producer_issues)
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
        if point.equity <= 0:
            issues.append("nonpositive_equity_observation")
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
        if row.status == "open_marked" and row.exit_reason is not None:
            issues.append("open_marked_exit_reason")
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
        for reason in event.reasons:
            _text(reason)
    changes = []
    mark_counts = Counter(point.timestamp_ms for point in points)
    points_by_id = {point.id: point for point in points if point.id is not None}

    def endpoint(observation_id: str | None, timestamp: int, equity: Decimal) -> bool:
        if observation_id is not None:
            point = points_by_id.get(observation_id)
            return point is not None and (point.timestamp_ms, point.equity) == (timestamp, equity)
        return mark_counts[timestamp] == 1 and marks.get(timestamp) == {equity}

    prior_episode: RecoveryEpisode | None = None
    for episode in episodes:
        _time(episode.start_ms)
        if prior_episode is not None:
            if episode.start_ms < prior_episode.start_ms:
                issues.append("nonchronological_recovery_episodes")
            if prior_episode.end_ms is None or episode.start_ms < prior_episode.end_ms:
                issues.append("overlapping_recovery_episodes")
        prior_episode = episode
        start = _number(episode.equity_start)
        if start <= 0 and episode.kind != "terminal":
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
            if endpoint(
                episode.start_observation_id, episode.start_ms, episode.equity_start
            ) and endpoint(episode.end_observation_id, episode.end_ms, episode.equity_end):
                delta = end - start
            else:
                issues.append("unverified_recovery_endpoint")
        elif not endpoint(episode.start_observation_id, episode.start_ms, episode.equity_start):
            # An ongoing final episode has no return yet. Its sourced opening
            # must still identify one retained in-window mark; no phase is chosen.
            issues.append("unverified_recovery_endpoint")
        changes.append(
            RecoveryChange(
                episode,
                _decimal(delta) if delta is not None else None,
                # A terminal stretch opened by exhaustion has no positive base: no return.
                _decimal(delta / start, ratio=True) if delta is not None and start > 0 else None,
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
        if abs(difference) > RESIDUAL_TOLERANCE:
            issues.append("contribution_equity_residual")
        elif difference:
            note = f"accounting_residual_within_tolerance:{residual:f}"
            if note not in disclosures:  # a recomputation from the report's own fields
                disclosures = (*disclosures, note)
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
    opportunity_groups = _opportunity_episodes(events, opportunity_gap_ms, issues)
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
    if policy_evidence is not None:
        try:
            validate_boundaries(policy_evidence, tuple((p.timestamp_ms, p.id) for p in points))
        except (ValueError, TypeError, AttributeError):
            issues.append("invalid_observation_policy_evidence")
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
        policy_evidence,
        skipped_hours,
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
        policy_evidence,
        tuple(producer_issues),
        skipped_hours,
        disclosures,
        capital_label,
        _drawdown_episodes(initial, points),
        max_gross_leverage,
    )
