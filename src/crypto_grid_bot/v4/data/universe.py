"""Candidates and the monthly universe for the V4 data step: each month's top 10 by volume.

At 00:00 UTC on the first of each month, every Binance spot USDT symbol that ever traded
(delisted ones included) is judged from its daily bars alone, then ranked. The rules are the
spec's (section "Universe"); this module is pure: no network, no files, no clock.

A selection at month M sees only bars whose open is before M's first millisecond. For each
symbol with at least one such bar, the first rule that applies decides, in this order:

* ``"stablecoin"``, ``"leveraged"``, ``"wrapped"``: ``static_exclusion`` (the spec's lists and
  ruling R1 for leveraged tokens);
* ``"stable_price"``: ``stable_price`` over the 90 days before the selection;
* ``"history"``: fewer than ``config.min_daily_bars`` daily bars before the selection (bars,
  not calendar days: a relisted symbol's gap is no history);
* ``"dead_market"``: no daily bar in the 7 UTC days before the selection (spec revision
  ``db211ad``), so every ranked candidate has a volume observation;
* ``"no_recent_hourly"``: only with ``usable_hours``, see below.

A symbol with no bar before the selection is not trading yet; it is neither a candidate nor
excluded, and appears nowhere in that month's record.

The survivors are ranked by the mean daily quote volume over the 30 UTC days before the
selection, counting only the days that have a bar; ties go alphabetically. ``ranked`` is that
whole ranking, as ``(symbol, mean, bars in the 30-day window)``. The mean is a Decimal division
at a pinned precision, so it does not depend on the caller's Decimal context.

The top ``config.top_n`` of the ranking form the month's ``selected``, in rank order; fewer if
fewer qualify (a short universe is permitted). With ``usable_hours``, the hourly check of spec
revision ``f7a9cae`` applies: ranked candidates are taken in order, one with no unmasked
hourly spot open in the 168 hours before the selection is skipped (``"no_recent_hourly"``), and
the taking stops at ``top_n`` selected or after rank ``HOURLY_RANK_DEPTH``. Without it, the
candidates stage of the data step, there is no hourly check. ``ranked`` is the same either way.

The result runs from the first month whose ``selected`` is not empty to
``config.end_month``; every month in between is kept, empty or not. The months before it are
omitted (the window opens at the first month with a selection). With ``usable_hours`` that is
the first month with a hour-checked selection, which can be later than the candidates stage's.
The first month returned enters all of its ``selected`` and has nothing that ``left``;
afterwards ``entered`` and ``left`` are relative to the previous month's ``selected``
(``entered`` in this month's rank order, ``left`` in the previous month's).
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Context, Decimal, localcontext
from itertools import pairwise
from typing import NamedTuple

from crypto_grid_bot.backtest.klines import INTERVAL_MS, month_bounds_ms
from crypto_grid_bot.v4.data.bars import DailyBar
from crypto_grid_bot.v4.data.config import DataConfig, months

# Spec revision f7a9cae: the hourly check looks no further down the ranking than this.
HOURLY_RANK_DEPTH = 20
# Spec revision db211ad: a candidate needs a daily bar in this many UTC days before the selection.
DEAD_MARKET_DAYS = 7
# A candidate needs an unmasked hourly spot open in this many hours before the selection.
HOURLY_WINDOW_HOURS = 168

_QUOTE = "USDT"
_DAY_MS = INTERVAL_MS["1d"]
_HOUR_MS = INTERVAL_MS["1h"]
# Quote volumes have at most 8 decimals and fewer than 20 integer digits, so a sum of a few
# dozen is exact in 40 digits; only the division by the day count rounds.
_CONTEXT = Context(prec=40, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class MonthlyUniverse:
    """One month's selection record (the module docstring says what each field holds)."""

    month: str
    selected: tuple[str, ...]
    ranked: tuple[tuple[str, Decimal, int], ...]
    excluded: tuple[tuple[str, str], ...]
    entered: tuple[str, ...]
    left: tuple[str, ...]


class _Series(NamedTuple):
    """A symbol's daily bars, and their opens for bisection."""

    bars: Sequence[DailyBar]
    opens: list[int]


def _base(symbol: str) -> str:
    """The base asset of a USDT symbol; ``ValueError`` for any other shape."""
    base = symbol.removesuffix(_QUOTE)
    if base == symbol or not base:
        raise ValueError(f"symbol must be a base asset followed by {_QUOTE}, got {symbol!r}")
    return base


def _open_ms(bar: DailyBar) -> int:
    return bar.open_ms


def static_exclusion(symbol: str, bases: frozenset[str], config: DataConfig) -> str | None:
    """Why a symbol is out whatever its prices, or None: ``"stablecoin"``, ``"leveraged"`` or
    ``"wrapped"``, checked in that order.

    ``symbol`` is the full USDT symbol (``"BTCUPUSDT"``) and ``bases`` the bases of every
    discovered USDT symbol. A base is a leveraged token only if it is a stem plus one of the
    config's suffixes and the stem is itself in ``bases`` (ruling R1): BTCUP is, JUP and SYRUP
    are not, and a suffix word on its own has an empty stem.
    """
    base = _base(symbol)
    if base in config.stablecoins:
        return "stablecoin"
    for suffix in config.leveraged_suffixes:
        stem = base.removesuffix(suffix)
        if stem and stem != base and stem in bases:
            return "leveraged"
    if base in config.wrapped:
        return "wrapped"
    return None


def stable_price(bars: Sequence[DailyBar], at_ms: int, config: DataConfig) -> bool:
    """Whether a symbol is pegged at the selection instant ``at_ms``.

    It counts the bars opening in the ``config.stable_days`` days before ``at_ms`` (the
    window is ``[at_ms - days, at_ms)``) whose close is within ``config.stable_band`` of 1.0,
    the band's ends included. The symbol is stable if at least ``stable_share`` of those days
    qualify: 81 of 90 for the spec's values. A day without a bar is not within the band
    (ruling P2), and a bar at or after ``at_ms`` is never looked at. ``bars`` must be sorted by
    ``open_ms``.
    """
    with localcontext(_CONTEXT):
        low, high = Decimal(1) - config.stable_band, Decimal(1) + config.stable_band
        needed = int((config.stable_share * config.stable_days).to_integral_value(ROUND_CEILING))
    first = bisect_left(bars, at_ms - config.stable_days * _DAY_MS, key=_open_ms)
    last = bisect_left(bars, at_ms, key=_open_ms)
    return sum(1 for bar in bars[first:last] if low <= bar.close <= high) >= needed


def _mean(values: Sequence[Decimal]) -> Decimal:
    with localcontext(_CONTEXT):
        return sum(values, Decimal(0)) / len(values)


def _require_increasing(values: Sequence[int], what: str) -> None:
    if any(later <= earlier for earlier, later in pairwise(values)):
        raise ValueError(f"{what} must be strictly increasing")


def _has_recent_hour(hours: Sequence[int] | None, at_ms: int) -> bool:
    """Whether some open lies in ``[at_ms - 168 h, at_ms)``; ``hours`` is sorted."""
    if not hours:
        return False
    index = bisect_left(hours, at_ms)
    return index > 0 and hours[index - 1] >= at_ms - HOURLY_WINDOW_HOURS * _HOUR_MS


def _select_month(
    at_ms: int,
    series: Mapping[str, _Series],
    bases: frozenset[str],
    config: DataConfig,
    usable_hours: Mapping[str, Sequence[int]] | None,
) -> tuple[tuple[str, ...], tuple[tuple[str, Decimal, int], ...], list[tuple[str, str]]]:
    """The selection at ``at_ms``: (selected, the full ranking, the excluded pairs unsorted)."""
    excluded: list[tuple[str, str]] = []
    ranked: list[tuple[str, Decimal, int]] = []
    for symbol in sorted(series):  # alphabetical, so the stable sort below breaks ties by name
        bars, opens = series[symbol]
        before = bisect_left(opens, at_ms)  # the bars open before the selection
        if before == 0:
            continue
        reason = static_exclusion(symbol, bases, config)
        if reason is None and stable_price(bars, at_ms, config):
            reason = "stable_price"
        if reason is None and before < config.min_daily_bars:
            reason = "history"
        if reason is None and opens[before - 1] < at_ms - DEAD_MARKET_DAYS * _DAY_MS:
            reason = "dead_market"
        if reason is not None:
            excluded.append((symbol, reason))
            continue
        # The last bar is at most 7 days old and the window at least 7 days long: not empty.
        first = bisect_left(opens, at_ms - config.volume_days * _DAY_MS, 0, before)
        volumes = [bar.quote_volume for bar in bars[first:before]]
        ranked.append((symbol, _mean(volumes), len(volumes)))
    ranked.sort(key=lambda entry: entry[1], reverse=True)  # stable, so equal means stay by name
    if usable_hours is None:
        return tuple(symbol for symbol, _, _ in ranked[: config.top_n]), tuple(ranked), excluded
    selected: list[str] = []
    for symbol, _, _ in ranked[:HOURLY_RANK_DEPTH]:
        if len(selected) == config.top_n:
            break
        if _has_recent_hour(usable_hours.get(symbol), at_ms):
            selected.append(symbol)
        else:
            excluded.append((symbol, "no_recent_hourly"))
    return tuple(selected), tuple(ranked), excluded


def select_universe(
    daily: Mapping[str, Sequence[DailyBar]],
    config: DataConfig,
    *,
    usable_hours: Mapping[str, Sequence[int]] | None = None,
) -> tuple[MonthlyUniverse, ...]:
    """Every month's universe, from the first month with a selection to ``config.end_month``.

    ``daily`` maps each discovered USDT symbol (``"BTCUSDT"``) to its daily bars, strictly
    increasing by open. ``usable_hours`` maps a symbol to the sorted opens (ms) of its unmasked
    hourly spot bars; a symbol missing from it has none. With ``usable_hours=None`` there is no
    hourly check. The module docstring has the rules.

    Raises ``ValueError`` for a symbol that is not ``<base>USDT``, for bars or hours that are
    not strictly increasing, for a ``volume_days`` shorter than the 7-day dead-market window
    (a live symbol could then have no volume to rank), and, with ``usable_hours``, for a
    ``top_n`` deeper than ``HOURLY_RANK_DEPTH`` (it could never be filled).
    """
    if config.volume_days < DEAD_MARKET_DAYS:
        raise ValueError(
            f"volume_days {config.volume_days} is shorter than the {DEAD_MARKET_DAYS}-day "
            "dead-market window"
        )
    if usable_hours is not None and config.top_n > HOURLY_RANK_DEPTH:
        raise ValueError(
            f"top_n {config.top_n} is deeper than the hourly check's rank {HOURLY_RANK_DEPTH}"
        )
    bases = frozenset(_base(symbol) for symbol in daily)
    series: dict[str, _Series] = {}
    for symbol, bars in daily.items():
        opens = [bar.open_ms for bar in bars]
        _require_increasing(opens, f"the daily bars of {symbol}")
        series[symbol] = _Series(bars, opens)
    if usable_hours is not None:
        for symbol, hours in usable_hours.items():
            _require_increasing(hours, f"usable_hours of {symbol}")

    universes: list[MonthlyUniverse] = []
    previous: tuple[str, ...] = ()
    for month in months(config.start_day[:7], config.end_month):
        selected, ranked, excluded = _select_month(
            month_bounds_ms(month)[0], series, bases, config, usable_hours
        )
        if not universes and not selected:
            continue
        universes.append(
            MonthlyUniverse(
                month=month,
                selected=selected,
                ranked=ranked,
                excluded=tuple(sorted(excluded)),
                entered=tuple(symbol for symbol in selected if symbol not in previous),
                left=tuple(symbol for symbol in previous if symbol not in selected),
            )
        )
        previous = selected
    return tuple(universes)
