"""The development window: which archive months this project may read.

Months after ``DEVELOPMENT_END`` are the reserved evaluation window. They may be
fetched, opened or inspected only with the owner's explicit go (START_HERE step 1).

This lives in its own module, importing nothing from the backtest package, so that
every layer can enforce it: the downloader, spec and manifest checks, and both
archive readers (klines and funding). Before this module existed, only the audit layer
called it.
"""

from __future__ import annotations

import re
from datetime import datetime

from crypto_grid_bot.market_data.parsing import DataError

DEVELOPMENT_END = "2024-12"
_MONTH = re.compile(r"[0-9]{4}-[0-9]{2}")


def _year_month(month: str) -> tuple[int, int]:
    return int(month[:4]), int(month[5:])


def development_month(month: str) -> str:
    """``month`` if it is inside the development window; DataError otherwise.

    The form is exactly ``YYYY-MM``, zero-padded. ``strptime`` alone would accept
    ``2024-9``, and everything downstream compares months as text: ``DatasetSpec.months``
    would then iterate ``"2024-12" <= "2024-6"`` to the end of the year, and the archive
    path regex would refuse the same month one layer down. Refusing the unpadded form
    here keeps every layer's reading of a month the same.
    """
    if type(month) is not str or _MONTH.fullmatch(month) is None:
        raise DataError("month must be YYYY-MM, zero-padded")
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise DataError("month must be YYYY-MM") from exc
    if _year_month(month) > _year_month(DEVELOPMENT_END):
        raise DataError(f"{month} is in the reserved window; audits stop at {DEVELOPMENT_END}")
    return month
