"""In-memory window replay; source validation and registered dispatch live upstream."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.exclusions import CloseRequirement, ExclusionCalendar, UnavailableClose
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.runner import HOUR, TrendRunner
from crypto_grid_bot.trend.signals import RULES

DAY = 24 * HOUR


@dataclass(frozen=True, slots=True)
class ReplayResult:
    runner: TrendRunner | None
    reason: str | None
    close_requirements: tuple[CloseRequirement, ...]


def replay_window(
    decisions: DailyDecisions,
    filters: Mapping[str, OrderFilters],
    hourly: Mapping[str, Sequence[Kline]],
    funding: Mapping[int, Mapping[str, Decimal]],
    start_ms: int,
    end_ms_exclusive: int,
    picks: Mapping[int, str | None],
    *,
    multiple: int = 2,
    cost_multiple: int = 1,
) -> ReplayResult:
    """One fresh account across supplied pick changes; no loading or dispatch.

    Hourly rows are already repaired/masked; monthly funding integrity and source
    hashes must be checked by the historical adapter before calling this routine.
    Engine errors propagate. Only explicit strategy outcomes return a reason.
    """
    if type(multiple) is not int or multiple not in (1, 2, 3):
        raise ValueError("invalid size multiple")
    if type(cost_multiple) is not int or cost_multiple not in (1, 2):
        raise ValueError("invalid cost multiple")
    if set(hourly) != set(filters) or set(filters) != set(decisions.first_months):
        raise ValueError("replay input universes disagree")
    if start_ms not in picks or any(
        type(t) is not int
        or t % DAY
        or not start_ms <= t < end_ms_exclusive
        or (rule is not None and rule not in RULES)
        for t, rule in picks.items()
    ):
        raise ValueError("invalid or missing initial rule pick")
    indexed = {}
    for symbol, rows in hourly.items():
        stamps = [row.open_ms for row in rows]
        if stamps != sorted(set(stamps)):
            raise ValueError("hourly rows must be unique and sorted")
        indexed[symbol] = {row.open_ms: row for row in rows}
    by_hour: dict[int, dict[int, dict[str, Decimal]]] = {}
    for stamp, rates in funding.items():
        if type(stamp) is not int or stamp < 0:
            raise ValueError("invalid funding timestamp")
        development_month(datetime.fromtimestamp(stamp // 1000, UTC).strftime("%Y-%m"))
        if not rates or not rates.keys() <= filters.keys():
            raise ValueError("invalid funding group")
        if any(not isinstance(rate, Decimal) or not rate.is_finite() for rate in rates.values()):
            raise ValueError("invalid funding rate")
        if start_ms <= stamp < end_ms_exclusive:
            by_hour.setdefault(stamp - stamp % HOUR, {})[stamp] = dict(rates)
    first_months = decisions.first_months
    excluded = {
        symbol: frozenset(month for month in months if month >= first_months[symbol])
        for symbol, months in decisions.excluded_months.items()
    }
    calendar = ExclusionCalendar(excluded)
    try:
        requirements = calendar.check_close_availability(
            start_ms,
            end_ms_exclusive,
            {symbol: frozenset(rows) for symbol, rows in indexed.items()},
        )
    except UnavailableClose as exc:
        return ReplayResult(None, "unavailable_exclusion_close", exc.requirements)
    runner = TrendRunner(
        filters,
        multiple=multiple,
        cost_multiple=cost_multiple,
        excluded_months=excluded,
    )
    closes = {}
    current_rule = picks[start_ms]
    for hour in range(start_ms, end_ms_exclusive, HOUR):
        month = datetime.fromtimestamp(hour // 1000, UTC).strftime("%Y-%m")
        eligible = {
            s
            for s, first in first_months.items()
            if first <= month and month not in excluded.get(s, ())
        }
        bars = {}
        for symbol in sorted(eligible):
            row = indexed[symbol].get(hour)
            if row is not None:
                bars[symbol] = (row.open, row.low, row.high)
                closes[symbol] = row.close
        groups = {
            stamp: {s: rate for s, rate in rates.items() if s in eligible}
            for stamp, rates in by_hour.get(hour, {}).items()
        }
        groups = {stamp: rates for stamp, rates in groups.items() if rates}
        targets = {}
        reasons = {}
        if hour % DAY == 0:
            previous_rule = current_rule
            current_rule = picks.get(hour, current_rule)
            decision = decisions.at(
                hour, current_rule, multiple=multiple, pick_changed=current_rule != previous_rule
            )
            targets, reasons = decision.targets, decision.exit_reasons
        result = runner.step(hour, bars, targets, groups, exit_reasons=reasons)
        if result.reason is not None:
            return ReplayResult(runner, result.reason, requirements)
    runner.finish(closes)
    return ReplayResult(runner, None, requirements)
