"""V4 data step: the pinned config, its validation and the end-month guard."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crypto_grid_bot.v4.data.config import (
    DataConfig,
    load_data_config,
    months,
    refuse_after_end,
)

COMMITTED = Path("config/v4_data.json")
PREPARE = Path("config/v3_1_prepare.json")


def test_committed_config_loads_with_the_spec_values():
    c = load_data_config(COMMITTED)
    assert c.start_day == "2017-08-17" and c.top_n == 10 and c.min_daily_bars == 200
    assert c.volume_days == 30 and c.stable_days == 90
    assert c.stable_band == Decimal("0.02") and c.stable_share == Decimal("0.9")
    assert c.stablecoins == {
        *("USDC", "BUSD", "TUSD", "USDP", "PAX", "DAI", "FDUSD"),
        *("USDD", "UST", "EUR", "GBP", "AUD", "TRY", "BRL"),
    }
    assert c.leveraged_suffixes == ("UP", "DOWN", "BULL", "BEAR")
    assert c.wrapped == frozenset({"WBTC", "WBETH", "BETH", "STETH"})
    assert c.end_month == "2026-09"


def test_committed_filter_snapshots_are_the_v3_1_prepare_pins():
    pinned = json.loads(PREPARE.read_text(encoding="utf-8"))["filter_snapshots"]
    assert load_data_config(COMMITTED).filter_snapshots == pinned


def test_the_config_is_frozen():
    c = load_data_config(COMMITTED)
    with pytest.raises(AttributeError):
        c.top_n = 5  # type: ignore[misc]


def test_months_is_inclusive_and_ordered():
    assert months("2024-11", "2025-02") == ("2024-11", "2024-12", "2025-01", "2025-02")


def test_months_of_one_month_and_of_a_reversed_range():
    assert months("2026-09", "2026-09") == ("2026-09",)
    assert months("2026-09", "2026-08") == ()


@pytest.mark.parametrize("bad", ["2026-9", "2026-13", "2026-00", "202609", "2026-09-01", ""])
def test_months_refuses_a_malformed_month(bad):
    with pytest.raises(ValueError, match="YYYY-MM"):
        months(bad, "2026-09")
    with pytest.raises(ValueError, match="YYYY-MM"):
        months("2026-01", bad)


def test_months_after_end_month_are_refused():
    c = replace(load_data_config(COMMITTED), end_month="2026-09")
    refuse_after_end("2026-09", c)
    refuse_after_end("2017-08", c)
    with pytest.raises(ValueError, match="after end_month"):
        refuse_after_end("2026-10", c)
    with pytest.raises(ValueError, match="after end_month"):
        refuse_after_end("2027-01", c)


def test_refuse_after_end_refuses_a_malformed_month():
    c = load_data_config(COMMITTED)
    with pytest.raises(ValueError, match="YYYY-MM"):
        refuse_after_end("2026-9", c)


def _write_changed(tmp_path: Path, change: dict[str, Any], drop: tuple[str, ...] = ()) -> Path:
    raw = json.loads(COMMITTED.read_text(encoding="utf-8"))
    raw.update(change)
    for key in drop:
        del raw[key]
    path = tmp_path / "v4_data.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_a_copy_of_the_committed_config_loads_unchanged(tmp_path):
    assert load_data_config(_write_changed(tmp_path, {})) == load_data_config(COMMITTED)


@pytest.mark.parametrize(
    "change",
    [
        {"top_n": 0},
        {"end_month": "2026-13"},
        {"stable_share": "1.5"},
        {"extra": 1},
        # counts must be positive JSON integers, never strings, floats or booleans
        {"top_n": -1},
        {"top_n": "10"},
        {"top_n": 10.0},
        {"top_n": True},
        {"min_daily_bars": 0},
        {"volume_days": 2.5},
        {"stable_days": None},
        # shares and bands are exact decimal strings in (0, 1]
        {"stable_share": "0"},
        {"stable_share": "-0.1"},
        {"stable_share": 0.9},
        {"stable_share": "abc"},
        {"stable_share": "NaN"},
        {"stable_band": "0"},
        {"stable_band": 0.02},
        # start_day: a real calendar day, not before 2017-08-17
        {"start_day": "2017-08-16"},
        {"start_day": "2017-8-17"},
        {"start_day": "20170817"},
        {"start_day": "2018-02-30"},
        # end_month: YYYY-MM, and not before the month of start_day
        {"end_month": "2026-9"},
        {"end_month": "2026-09-01"},
        {"end_month": "2017-07"},
        # name lists: non-empty lists of non-empty strings
        {"stablecoins": []},
        {"stablecoins": "USDC"},
        {"stablecoins": ["USDC", 1]},
        {"leveraged_suffixes": [""]},
        {"wrapped": []},
        # filter snapshots: venue -> exactly {path, sha256}, sha256 a 64-char hex digest
        {"filter_snapshots": {}},
        {"filter_snapshots": {"spot": {"path": "a.json"}}},
        {"filter_snapshots": {"spot": {"path": "a.json", "sha256": "abc"}}},
        {"filter_snapshots": {"spot": {"path": "a.json", "sha256": "0" * 64, "x": "y"}}},
        {"filter_snapshots": {"spot": {"path": "", "sha256": "0" * 64}}},
        {"filter_snapshots": {"spot": "a.json"}},
        {"filter_snapshots": [["spot", "a.json"]]},
    ],
)
def test_invalid_or_unknown_config_fields_are_refused(tmp_path, change):
    with pytest.raises(ValueError):
        load_data_config(_write_changed(tmp_path, change))


@pytest.mark.parametrize("key", sorted(json.loads(COMMITTED.read_text(encoding="utf-8"))))
def test_a_missing_config_key_is_refused(tmp_path, key):
    with pytest.raises(ValueError, match=key):
        load_data_config(_write_changed(tmp_path, {}, drop=(key,)))


def test_a_config_that_is_not_a_json_object_is_refused(tmp_path):
    path = tmp_path / "v4_data.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_data_config(path)


def test_dataconfig_has_exactly_the_documented_fields():
    assert list(DataConfig.__dataclass_fields__) == [
        "start_day",
        "end_month",
        "stablecoins",
        "leveraged_suffixes",
        "wrapped",
        "stable_band",
        "stable_share",
        "stable_days",
        "min_daily_bars",
        "volume_days",
        "top_n",
        "filter_snapshots",
    ]
