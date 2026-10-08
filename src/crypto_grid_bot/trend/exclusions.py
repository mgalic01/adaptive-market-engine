"""Daily target overrides from predeclared, reviewed data exclusions."""

from collections.abc import Mapping, Set
from datetime import UTC, datetime, timedelta

from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.market_data.parsing import symbol_name

DAY = 86400000


class ExclusionCalendar:
    def __init__(self, excluded_months: Mapping[str, Set[str]]) -> None:
        self._months = {}
        for symbol, months in excluded_months.items():
            symbol_name(symbol)
            self._months[symbol] = frozenset(development_month(month) for month in months)

    def zero_symbols(self, decision_ms: int) -> frozenset[str]:
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
        return frozenset(
            symbol
            for symbol, months in self._months.items()
            if month in months or next_month in months
        )
