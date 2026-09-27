"""The development window: which archive months this project may read.

Months after ``DEVELOPMENT_END`` are the reserved evaluation window. They may be
fetched, opened or inspected only with the owner's explicit go (START_HERE step 1).

This lives in its own module so that every layer can enforce it. ``audit`` imports
``replay``, which imports ``dataset``, so ``dataset`` cannot import the guard from
``audit`` without a cycle; before this module existed, only the audit layer called it
and the downloader and replay loaders did not.
"""

from __future__ import annotations

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.market_data.parsing import DataError

DEVELOPMENT_END = "2024-12"


def development_month(month: str) -> str:
    """``month`` if it is inside the development window; DataError otherwise."""
    month_bounds_ms(month)  # validates the YYYY-MM form
    if month > DEVELOPMENT_END:
        raise DataError(f"{month} is in the reserved window; audits stop at {DEVELOPMENT_END}")
    return month
