"""The synthetic V4 world writer for the engine's tests.

The module moved to ``src/crypto_grid_bot/v4/synthetic.py`` (step 4b, task 1), so that the
rehearsal and timing worlds of ``scripts/v4_rehearsal.py`` can use it. This file keeps every
test's ``from v4_synthetic import ...`` working: it re-exports the module, and lists the names
the tests import (none of them private) in ``__all__``. Its module docstring describes the
helpers.
"""

from crypto_grid_bot.v4.synthetic import *  # noqa: F403
from crypto_grid_bot.v4.synthetic import (
    CONFIG_SHA256,
    DAILY_PACK,
    DAY,
    FUTURES_RULES,
    HOUR,
    HOURLY_INDEX,
    SPOT_RULES,
    CoinSpec,
    PerpetualSpec,
    Series,
    World,
    day_hours,
    every_month,
    hours_in,
    month_start,
    path,
    read_data_json,
    repack,
    write_data_json,
    write_world,
)

__all__ = [
    "CONFIG_SHA256",
    "DAILY_PACK",
    "DAY",
    "FUTURES_RULES",
    "HOUR",
    "HOURLY_INDEX",
    "SPOT_RULES",
    "CoinSpec",
    "PerpetualSpec",
    "Series",
    "World",
    "day_hours",
    "every_month",
    "hours_in",
    "month_start",
    "path",
    "read_data_json",
    "repack",
    "write_data_json",
    "write_world",
]
