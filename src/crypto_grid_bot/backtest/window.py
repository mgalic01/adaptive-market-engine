"""The development window: which archive months this project may read.

Months after ``DEVELOPMENT_END`` are the reserved evaluation window. They may be
fetched, opened or inspected only with the owner's explicit go (START_HERE step 1).

This lives in its own module, importing nothing from the backtest package, so that
every layer can enforce it: the downloader, spec and manifest checks, and both
archive readers (klines and funding). Before this module existed, only the audit layer
called it.
"""

from __future__ import annotations

from datetime import datetime

from crypto_grid_bot.market_data.parsing import DataError

DEVELOPMENT_END = "2024-12"


def development_month(month: str) -> str:
    """``month`` if it is inside the development window; DataError otherwise."""
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise DataError("month must be YYYY-MM") from exc
    if month > DEVELOPMENT_END:
        raise DataError(f"{month} is in the reserved window; audits stop at {DEVELOPMENT_END}")
    return month
