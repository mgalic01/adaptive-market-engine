"""The eight arms of the V4 run, the 32 cells they make, and the fixed sizing constants.

Implements the spec's "Versions in the run" (arm table and the neighbours' lookbacks) and
"Account and execution" (costs). ``v3_as_built`` is not an engine arm (ruling R1), and nor is
``hold_btc_trend``: both are built in step 4. The run has 8 arms x 2 capitals x 2 cost levels =
32 cells here.

* ``v4_main``, ``v4_long_only``, ``v4_vol25`` and ``v4_vol60`` share the main lookbacks.
* ``v4_faster`` and ``v4_slower`` scale only the signal lookbacks, by x0.75 and x1.25,
  rounded as the spec's table gives them. Everything else, sizing included, is fixed below.
* The two hold arms are spot accounts with no signal, so they have no volatility target and
  no lookbacks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

from crypto_grid_bot.combined.decisions import Costs
from crypto_grid_bot.combined.driver.venues import cost_profile

# Sizing, safety and hold constants. None of these varies between arms.
SIGMA_RETURNS = 60
COVARIANCE_DAYS = 60
MIN_COMMON_DAYS = 40
COIN_CAP = Decimal("0.30")
TOTAL_CAP = Decimal("2.7")
BAND_RELATIVE = Decimal("0.25")
BAND_ABSOLUTE = Decimal("0.01")
CEILING = Decimal(3)
CEILING_TARGET = Decimal("2.7")
CUSHION_FLOOR = 3
CUSHION_TARGET = 4
MAINTENANCE_RATE = Decimal("0.01")
INITIAL_MARGIN_DIVISOR = 3
COST_RESERVE = Decimal("0.02")
DEAD_MARKET_HOURS = 168
DEAD_MARKET_PENALTY = Decimal("0.10")
HOLD_INVESTED = Decimal("0.99")

CAPITALS = (1000, 10000)
COST_MULTIPLES = (1, 2)


@dataclass(frozen=True, slots=True)
class Lookbacks:
    """The signal lookbacks, in daily bars, in the order the signal rules use them."""

    fast: int
    ema_fast: int
    ema_slow: int
    donchian_entry: int
    donchian_exit: int
    slow: int
    trend_sma: int
    trend_slope: int
    trend_window: int


MAIN_LOOKBACKS = Lookbacks(20, 21, 55, 55, 20, 200, 50, 10, 20)
FASTER_LOOKBACKS = Lookbacks(15, 16, 41, 41, 15, 150, 38, 8, 15)
SLOWER_LOOKBACKS = Lookbacks(25, 26, 69, 69, 25, 250, 62, 12, 25)


@dataclass(frozen=True, slots=True)
class ArmSpec:
    name: str
    family: Literal["v4", "hold"]
    vol_target: Decimal | None
    long_only: bool
    lookbacks: Lookbacks | None


_ARM_LIST = (
    ArmSpec("v4_main", "v4", Decimal("0.40"), False, MAIN_LOOKBACKS),
    ArmSpec("v4_long_only", "v4", Decimal("0.40"), True, MAIN_LOOKBACKS),
    ArmSpec("v4_vol25", "v4", Decimal("0.25"), False, MAIN_LOOKBACKS),
    ArmSpec("v4_vol60", "v4", Decimal("0.60"), False, MAIN_LOOKBACKS),
    ArmSpec("v4_faster", "v4", Decimal("0.40"), False, FASTER_LOOKBACKS),
    ArmSpec("v4_slower", "v4", Decimal("0.40"), False, SLOWER_LOOKBACKS),
    ArmSpec("hold_universe", "hold", None, False, None),
    ArmSpec("hold_btc", "hold", None, False, None),
)

ARMS: Mapping[str, ArmSpec] = MappingProxyType({spec.name: spec for spec in _ARM_LIST})


@dataclass(frozen=True, slots=True)
class CellSpec:
    """One cell of the run: an arm at one starting capital and one cost level."""

    arm: str
    capital: int
    cost_multiple: int

    def __post_init__(self) -> None:
        # `type(...) is int` keeps out booleans (True == 1) and floats (10000.0 == 10000).
        if not isinstance(self.arm, str) or self.arm not in ARMS:
            raise ValueError(f"unknown arm {self.arm!r}: one of {', '.join(ARMS)} required")
        if type(self.capital) is not int or self.capital not in CAPITALS:
            raise ValueError(f"capital must be one of {CAPITALS}, got {self.capital!r}")
        if type(self.cost_multiple) is not int or self.cost_multiple not in COST_MULTIPLES:
            raise ValueError(
                f"cost multiple must be one of {COST_MULTIPLES}, got {self.cost_multiple!r}"
            )

    @property
    def cell_id(self) -> str:
        return f"{self.arm}-{self.capital}-{self.cost_multiple}x"

    def costs(self, venue: Literal["spot", "futures"]) -> Costs:
        """The venue's cost rates at this cell's multiple: the V3.1 profile, doubled at 2."""
        return cost_profile(self.cost_multiple, venue)


def all_cells() -> tuple[CellSpec, ...]:
    """Every cell of the run: arms in ``ARMS`` order, then capital, then cost multiple."""
    return tuple(
        CellSpec(arm, capital, multiple)
        for arm in ARMS
        for capital in CAPITALS
        for multiple in COST_MULTIPLES
    )
