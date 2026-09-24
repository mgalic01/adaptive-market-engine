"""Geometric grid construction with affordability and cost checks."""

from __future__ import annotations

import math

from crypto_grid_bot.domain import GridPlan


class GridNotViable(ValueError):
    """Raised when a safe grid cannot be built with the supplied capital."""


class GridBuilder:
    def __init__(
        self,
        *,
        minimum_levels: int,
        maximum_levels: int,
        minimum_cost_multiple: float,
        range_atr_multiple: float,
    ) -> None:
        if not 2 <= minimum_levels <= maximum_levels:
            raise ValueError("invalid grid level bounds")
        if any(not math.isfinite(x) or x <= 0 for x in (minimum_cost_multiple, range_atr_multiple)):
            raise ValueError("grid multipliers must be finite and positive")
        self._minimum_levels = minimum_levels
        self._maximum_levels = maximum_levels
        self._minimum_cost_multiple = minimum_cost_multiple
        self._range_atr_multiple = range_atr_multiple

    def build(
        self,
        *,
        symbol: str,
        fair_value: float,
        atr: float,
        capital: float,
        min_notional: float,
        round_trip_cost_pct: float,
        capital_utilization: float,
    ) -> GridPlan:
        if any(not math.isfinite(x) or x <= 0 for x in (fair_value, atr, capital, min_notional)):
            raise GridNotViable("prices, capital, ATR, and minimum notional must be positive")
        if not 0 < capital_utilization <= 1:
            raise GridNotViable("capital_utilization must be between 0 and 1")
        if not math.isfinite(round_trip_cost_pct) or round_trip_cost_pct <= 0:
            raise GridNotViable("a finite positive cost estimate is required")

        deployable = capital * capital_utilization
        affordable_levels = int(deployable // min_notional)
        level_count = min(self._maximum_levels, affordable_levels)
        if level_count < self._minimum_levels:
            raise GridNotViable("capital cannot fund the minimum number of grid levels")

        half_range = atr * self._range_atr_multiple
        lower = fair_value - half_range
        upper = fair_value + half_range
        if lower <= 0 or not math.isfinite(upper):
            raise GridNotViable("ATR-derived lower bound is not positive")

        ratio = (upper / lower) ** (1 / (level_count - 1))
        if not math.isfinite(ratio):
            raise GridNotViable("grid ratio overflow")
        spacing_pct = (ratio - 1) * 100
        required_spacing = round_trip_cost_pct * self._minimum_cost_multiple
        if spacing_pct < required_spacing:
            raise GridNotViable(
                f"grid spacing {spacing_pct:.4f}% is below required {required_spacing:.4f}%"
            )

        levels = tuple(lower * math.pow(ratio, index) for index in range(level_count))
        return GridPlan(symbol, lower, upper, levels, deployable, spacing_pct)
