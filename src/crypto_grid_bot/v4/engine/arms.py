"""The twelve arms of the V4 run, the 48 cells they make, and the fixed sizing constants.

Implements the spec's "Versions in the run" (arm table and the neighbours' lookbacks) and
"Account and execution" (costs). The run has 12 arms x 2 capitals x 2 cost levels = 48 cells.
This engine runs the eleven ``v4`` and ``hold`` arms; ``v3_as_built`` is the ``v3`` family, which
runs through its own CLI and pack (ruling R3 of step 4a).

* ``v4_main``, ``v4_long_only``, ``v4_vol25`` and ``v4_vol60`` share the main lookbacks.
* ``v4_faster`` and ``v4_slower`` scale only the signal lookbacks, by x0.75 and x1.25,
  rounded as the spec's table gives them. Everything else, sizing included, is fixed below.
* ``v4_btc200_shorts`` and ``v4_confirm3`` (v4-d22) are ``v4_main`` plus one rule each: a short
  filter on BTC's slow vote, and a count of readings that must agree before a signal changes
  direction.
* The three hold arms are spot accounts with no volatility target and no lookbacks.
  ``hold_btc_trend`` is in BTC while BTC's slow vote is +1.

``DIAGNOSTIC_ARMS`` are the eight arms of step 3, the ones the v4-cells workflow may run before the
registered run (v4-d22: the others are first run there).
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
# The one coin of hold_btc and hold_btc_trend, and the coin whose slow vote ``short_filter`` reads.
BTC = "BTCUSDT"

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
    """One arm of the run.

    ``family`` says which runner replays it: ``v4`` (the trend engine), ``hold`` (the spot hold
    accounts) or ``v3`` (V3's own selector, through its own CLI). ``vol_target``, ``long_only``
    and ``lookbacks`` are the V4 arms' sizing and signal settings; a hold or V3 arm has no
    volatility target and no lookbacks. The two optional rules belong to v4-d22's arms and leave
    every other arm unchanged:

    * ``short_filter``: ``"btc_sma200"`` allows shorts only while BTCUSDT's slow vote is -1
      (its close below its slow SMA); None puts no condition on shorts.
    * ``confirm_readings``: the number of consecutive daily readings in one direction needed
      before a coin's signal changes direction; None acts on the first reading.

    A long-only arm takes neither rule; one with either is a ValueError. The confirmation reads
    each reading's raw ``s`` and gives the arm its effective signal in place of ``s``, so on a
    long-only arm it would replace ``L`` with a signal that can be short; and a long-only arm has
    no short for the filter to allow or block.
    """

    name: str
    family: Literal["v4", "hold", "v3"]
    vol_target: Decimal | None
    long_only: bool
    lookbacks: Lookbacks | None
    short_filter: Literal["btc_sma200"] | None = None
    confirm_readings: int | None = None

    def __post_init__(self) -> None:
        if self.long_only and self.confirm_readings is not None:
            raise ValueError(
                f"{self.name}: a long-only arm cannot take confirm_readings, which reads the raw s"
            )
        if self.long_only and self.short_filter is not None:
            raise ValueError(
                f"{self.name}: a long-only arm has no short for short_filter to allow or block"
            )


_ARM_LIST = (
    ArmSpec("v4_main", "v4", Decimal("0.40"), False, MAIN_LOOKBACKS),
    ArmSpec("v4_long_only", "v4", Decimal("0.40"), True, MAIN_LOOKBACKS),
    ArmSpec("v4_vol25", "v4", Decimal("0.25"), False, MAIN_LOOKBACKS),
    ArmSpec("v4_vol60", "v4", Decimal("0.60"), False, MAIN_LOOKBACKS),
    ArmSpec("v4_faster", "v4", Decimal("0.40"), False, FASTER_LOOKBACKS),
    ArmSpec("v4_slower", "v4", Decimal("0.40"), False, SLOWER_LOOKBACKS),
    ArmSpec(
        "v4_btc200_shorts", "v4", Decimal("0.40"), False, MAIN_LOOKBACKS, short_filter="btc_sma200"
    ),
    ArmSpec("v4_confirm3", "v4", Decimal("0.40"), False, MAIN_LOOKBACKS, confirm_readings=3),
    ArmSpec("hold_universe", "hold", None, False, None),
    ArmSpec("hold_btc", "hold", None, False, None),
    ArmSpec("hold_btc_trend", "hold", None, False, None),
    ArmSpec("v3_as_built", "v3", None, False, None),
)

ARMS: Mapping[str, ArmSpec] = MappingProxyType({spec.name: spec for spec in _ARM_LIST})

# The arms of step 3's diagnostic run, in ARMS order: the only ones the v4-cells workflow runs.
DIAGNOSTIC_ARMS = (
    "v4_main",
    "v4_long_only",
    "v4_vol25",
    "v4_vol60",
    "v4_faster",
    "v4_slower",
    "hold_universe",
    "hold_btc",
)


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
