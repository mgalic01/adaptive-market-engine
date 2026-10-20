"""The pinned V4 data configuration, its validation and the end-month guard.

The window is fixed in ``config/v4_data.json``: it opens on 2017-08-17 (the first day
Binance has spot data) and closes at ``end_month``. Nothing past ``end_month`` may be
requested; ``refuse_after_end`` is the one place that says so.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

EARLIEST_START_DAY = "2017-08-17"

_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MONTH = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PIN_KEYS = frozenset({"path", "sha256"})


@dataclass(frozen=True)
class DataConfig:
    start_day: str
    end_month: str
    stablecoins: frozenset[str]
    leveraged_suffixes: tuple[str, ...]
    wrapped: frozenset[str]
    stable_band: Decimal
    stable_share: Decimal
    stable_days: int
    min_daily_bars: int
    volume_days: int
    top_n: int
    filter_snapshots: dict[str, dict[str, str]]


_KEYS = frozenset(f.name for f in fields(DataConfig))


def _month_index(month: str, what: str) -> int:
    """Months since year 0, so a month range is plain integer arithmetic."""
    match = _MONTH.fullmatch(month) if isinstance(month, str) else None
    if match is None:
        raise ValueError(f"{what} must be YYYY-MM, got {month!r}")
    return int(match.group(1)) * 12 + int(match.group(2)) - 1


def months(start: str, end: str) -> tuple[str, ...]:
    """Every month from ``start`` to ``end`` inclusive, in order; empty if end < start."""
    first = _month_index(start, "start month")
    last = _month_index(end, "end month")
    return tuple(f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(first, last + 1))


def refuse_after_end(month: str, config: DataConfig) -> None:
    """Raise ``ValueError`` for any month later than the config's ``end_month``."""
    if _month_index(month, "month") > _month_index(config.end_month, "end_month"):
        raise ValueError(f"month {month} is after end_month {config.end_month}")


def _start_day(value: Any) -> str:
    if not isinstance(value, str) or _DAY.fullmatch(value) is None:
        raise ValueError(f"start_day must be YYYY-MM-DD, got {value!r}")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"start_day is not a calendar day: {value!r}") from None
    if day < date.fromisoformat(EARLIEST_START_DAY):
        raise ValueError(f"start_day {value} is before {EARLIEST_START_DAY}")
    return value


def _end_month(value: Any, start_day: str) -> str:
    if _month_index(value, "end_month") < _month_index(start_day[:7], "start_day"):
        raise ValueError(f"end_month {value} is before the month of start_day {start_day}")
    return str(value)


def _count(value: Any, name: str) -> int:
    # `type(...) is int` keeps out booleans, which are ints to isinstance.
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return value


def _fraction(value: Any, name: str) -> Decimal:
    """A decimal string in (0, 1]; strings load exactly, JSON floats would not."""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a decimal string, got {value!r}")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{name} must be a decimal string, got {value!r}") from None
    if not number.is_finite() or not Decimal(0) < number <= Decimal(1):
        raise ValueError(f"{name} must be in (0, 1], got {value!r}")
    return number


def _names(value: Any, name: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ValueError(f"{name} must be a non-empty list of non-empty strings, got {value!r}")
    return tuple(value)


def _filter_snapshots(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"filter_snapshots must be a non-empty object, got {value!r}")
    pins: dict[str, dict[str, str]] = {}
    for venue, pin in value.items():
        if not venue or not isinstance(pin, dict) or set(pin) != _PIN_KEYS:
            raise ValueError(f"filter_snapshots[{venue!r}] must be exactly {{path, sha256}}")
        path, digest = pin["path"], pin["sha256"]
        if not isinstance(path, str) or not path:
            raise ValueError(f"filter_snapshots[{venue!r}].path must be a non-empty string")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ValueError(f"filter_snapshots[{venue!r}].sha256 must be 64 lowercase hex digits")
        pins[venue] = {"path": path, "sha256": digest}
    return pins


def load_data_config(path: Path) -> DataConfig:
    """Load and validate the pinned config; refuse unknown, missing or malformed fields."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: the config must be a JSON object")
    missing = sorted(_KEYS - raw.keys())
    unknown = sorted(raw.keys() - _KEYS)
    if missing:
        raise ValueError(f"{path}: missing keys: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"{path}: unknown keys: {', '.join(unknown)}")
    start_day = _start_day(raw["start_day"])
    return DataConfig(
        start_day=start_day,
        end_month=_end_month(raw["end_month"], start_day),
        stablecoins=frozenset(_names(raw["stablecoins"], "stablecoins")),
        leveraged_suffixes=_names(raw["leveraged_suffixes"], "leveraged_suffixes"),
        wrapped=frozenset(_names(raw["wrapped"], "wrapped")),
        stable_band=_fraction(raw["stable_band"], "stable_band"),
        stable_share=_fraction(raw["stable_share"], "stable_share"),
        stable_days=_count(raw["stable_days"], "stable_days"),
        min_daily_bars=_count(raw["min_daily_bars"], "min_daily_bars"),
        volume_days=_count(raw["volume_days"], "volume_days"),
        top_n=_count(raw["top_n"], "top_n"),
        filter_snapshots=_filter_snapshots(raw["filter_snapshots"]),
    )
