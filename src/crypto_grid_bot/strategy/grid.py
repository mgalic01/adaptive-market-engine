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
        fta_resistance: float | None = None,
    ) -> GridPlan:
        """Build a geometric grid plan.

        ``capital`` is what the grid may deploy in full; the caller applies any
        utilisation haircut (the paper engine's ``GRID_BUDGET_FRACTION``).

        ``fta_resistance`` is the price of the nearest resistance zone above the
        grid (from structure.py's find_fta). When supplied and the FTA lies within
        the grid's upper half (lower < fta_resistance <= upper), the highest grid
        levels that exceed ``fta_resistance`` are capped at
        ``fta_resistance * 0.999`` — placing the last sell target just below the
        resistance wall rather than into it.  The 0.999 factor (0.1% buffer) is
        deliberately small: it keeps the target actionable and avoids it landing
        exactly at a known seller cluster where fills are harder to obtain.

        The caller is responsible for computing ``fta_resistance`` from
        structure.py; grid.py does not import that module.
        """
        if any(not math.isfinite(x) or x <= 0 for x in (fair_value, atr, capital, min_notional)):
            raise GridNotViable("prices, capital, ATR, and minimum notional must be positive")
        if not math.isfinite(round_trip_cost_pct) or round_trip_cost_pct <= 0:
            raise GridNotViable("a finite positive cost estimate is required")

        affordable_levels = int(capital // min_notional)
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

        # FTA resistance cap: if the caller supplies a resistance price that falls
        # within the grid's upper half (i.e. above the midpoint and at or below
        # the grid's upper bound), cap any level that would exceed or equal it at
        # fta_resistance * 0.999.  Levels below fta_resistance are untouched.
        # We only apply the cap when fta_resistance is strictly inside the grid
        # (lower < fta_resistance <= upper) to avoid distorting a well-formed grid
        # on an irrelevant signal.
        fta_used: float | None = None
        if (
            fta_resistance is not None
            and math.isfinite(fta_resistance)
            and lower < fta_resistance <= upper
        ):
            cap = fta_resistance * 0.999
            levels = tuple(min(lvl, cap) for lvl in levels)
            fta_used = fta_resistance

        return GridPlan(symbol, lower, upper, levels, capital, spacing_pct, fta_used)
