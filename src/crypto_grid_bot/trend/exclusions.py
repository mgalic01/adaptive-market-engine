"""Daily target overrides from predeclared, reviewed data exclusions."""

from collections.abc import Mapping, Set
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.backtest.window import DEVELOPMENT_END, development_month
from crypto_grid_bot.market_data.parsing import symbol_name
from crypto_grid_bot.trend.data import mandatory_close_hour

DAY = 86400000


@dataclass(frozen=True, slots=True)
class CloseRequirement:
    symbol: str
    excluded_month: str
    decision_ms: int
    fill_ms: int | None


class UnavailableClose(ValueError):
    """Data-declared strategy invalidity, distinct from missing input evidence."""

    def __init__(self, requirements: tuple[CloseRequirement, ...]) -> None:
        super().__init__("no unmasked hour for a required pre-exclusion close")
        self.requirements = requirements


class ExclusionCalendar:
    def __init__(self, excluded_months: Mapping[str, Set[str]]) -> None:
        self._months = {}
        for symbol, months in excluded_months.items():
            symbol_name(symbol)
            self._months[symbol] = frozenset(development_month(month) for month in months)

    def zero_symbols(self, decision_ms: int, *, run_end_ms: int | None = None) -> frozenset[str]:
        """Midnight decision fills from 01:00; force the preceding last day too.

        This does not certify close availability. The manifest adapter must reject
        unavailable pre-exclusion closes before dispatching a historical run.
        """
        if type(decision_ms) is not int or decision_ms < 0 or decision_ms % DAY:
            raise ValueError("expected midnight decision timestamp")
        day = datetime.fromtimestamp(decision_ms // 1000, UTC)
        month = development_month(day.strftime("%Y-%m"))
        tomorrow = day + timedelta(days=1)
        next_month = tomorrow.strftime("%Y-%m") if tomorrow.day == 1 else None
        if run_end_ms is not None:
            if type(run_end_ms) is not int or run_end_ms % DAY or run_end_ms <= decision_ms:
                raise ValueError("invalid exclusive run end")
            if decision_ms + DAY >= run_end_ms:
                next_month = None
        return frozenset(
            symbol
            for symbol, months in self._months.items()
            if month in months or next_month in months
        )

    def check_close_availability(
        self,
        start_ms: int,
        end_ms_exclusive: int,
        unmasked_hours: Mapping[str, frozenset[int]],
    ) -> tuple[CloseRequirement, ...]:
        """Preflight a fresh flat run from validated execution-hour inventory.

        The caller limits exclusions to the coin's portfolio lifetime. Runs start
        and end at midnight. A run starting inside an exclusion starts flat; a
        consecutive excluded month creates no new closing obligation.
        """
        self.zero_symbols(start_ms)
        if (
            type(end_ms_exclusive) is not int
            or end_ms_exclusive % DAY
            or end_ms_exclusive <= start_ms
        ):
            raise ValueError("invalid exclusive run end")
        self.zero_symbols(end_ms_exclusive - DAY)
        if not self._months.keys() <= unmasked_hours.keys():
            raise ValueError("missing execution-hour inventory")
        _, allowed_end = month_bounds_ms(DEVELOPMENT_END)
        for symbol, hours in unmasked_hours.items():
            symbol_name(symbol)
            if any(
                type(stamp) is not int or not 0 <= stamp < allowed_end or stamp % 3600000
                for stamp in hours
            ):
                raise ValueError("invalid execution-hour inventory timestamp")
        requirements = []
        for symbol, months in sorted(self._months.items()):
            for month in sorted(months):
                boundary, _ = month_bounds_ms(month)
                decision = boundary - DAY
                previous = datetime.fromtimestamp(decision // 1000, UTC).strftime("%Y-%m")
                # A fresh account is flat at its initial decision. That forced
                # zero cannot require an execution hour to close a position.
                if start_ms < decision < boundary < end_ms_exclusive and previous not in months:
                    requirements.append(
                        CloseRequirement(
                            symbol,
                            month,
                            decision,
                            mandatory_close_hour(month, unmasked_hours[symbol]),
                        )
                    )
        result = tuple(requirements)
        if any(item.fill_ms is None for item in result):
            raise UnavailableClose(result)
        return result
