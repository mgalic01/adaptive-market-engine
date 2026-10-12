"""Causal V3.1 market assessment, independent of any strategy P&L."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.combined.assessment import AssessmentSeries, assess, daily_bars
from crypto_grid_bot.strategy.indicators import wilder_rsi
from crypto_grid_bot.strategy.perception import TrendState
from crypto_grid_bot.trend.data import hourly_month

HOUR = 3_600_000
DAY = 24 * HOUR


def bars(count: int, interval: int, slope: str = "0.01") -> list[Kline]:
    result = []
    for i in range(count):
        price = D(100) + D(slope) * i
        result.append(
            Kline(
                i * interval, price, price + 1, price - 1, price + D(slope), D(1), price, D("0.5")
            )
        )
    return result


@pytest.fixture
def inputs() -> tuple[list[Kline], list[Kline], int]:
    return bars(60 * 24, HOUR), bars(60, DAY, "0.24"), 60 * DAY


def test_completed_uptrend_records_high_rsi_without_universal_veto(inputs):
    hourly, daily, now = inputs
    result = assess("BTCUSDT", now, hourly, daily, now)
    assert result.available
    assert result.daily == result.four_hour == TrendState.UP
    assert result.structure in {"pullback", "continuation", "breakout"}
    assert result.rsi == 100
    assert result.atr > 0
    assert result.volatility_ratio == 1
    assert result.hourly_closed_ms == result.four_hour_closed_ms == now
    assert result.daily_closed_ms == now
    assert result.schema == "combined-v1"
    assert result.reasons == ()
    with pytest.raises(FrozenInstanceError):
        result.available = False


def test_daily_rsi_is_recorded_from_completed_daily_closes_beside_four_hour_rsi(inputs):
    hourly, daily, now = inputs
    # The last completed day closes 0.5 below the prior close, inside its own range.
    daily[-1] = replace(daily[-1], close=daily[-1].open - D("0.5"))
    expected = wilder_rsi([bar.close for bar in daily])[-1]
    result = assess("BTCUSDT", now, hourly, daily, now)
    assert expected is not None and expected < 100
    assert result.daily_rsi == expected
    assert result.rsi == 100
    # The day still forming at the decision is never read.
    forming = replace(daily[-1], open_ms=now, close=daily[-1].low)
    assert assess("BTCUSDT", now, hourly, daily + [forming], now).daily_rsi == expected
    # Fourteen completed closes leave the daily RSI(14) warming up, not invented.
    assert assess("BTCUSDT", now, hourly, daily[-14:], now).daily_rsi is None


def test_assessment_has_a_stable_id_and_names_the_completed_bars_it_read(inputs):
    hourly, daily, now = inputs
    series = AssessmentSeries("BTCUSDT", hourly, daily, source_refs=("sha256:inputs",))
    result = series.at(now, now - 60_000)
    assert result.assessment_id == f"assessment:BTCUSDT:{now}:{now - 60_000}"
    assert series.at(now, now - 60_000).assessment_id == result.assessment_id
    assert result.source_refs == (
        "sha256:inputs",
        f"BTCUSDT:1h:{now - HOUR}",
        f"BTCUSDT:4h:{now - 4 * HOUR}",
        f"BTCUSDT:1d:{now - DAY}",
        f"BTCUSDT:quote:{now - 60_000}",
    )
    # A missing due bar is unavailable and is never named as a source.
    gapped = AssessmentSeries("BTCUSDT", hourly, daily[:-1]).at(now, now)
    assert not gapped.available
    assert gapped.source_refs == (
        f"BTCUSDT:1h:{now - HOUR}",
        f"BTCUSDT:4h:{now - 4 * HOUR}",
        f"BTCUSDT:quote:{now}",
    )


def test_future_suffix_never_changes_past_assessment(inputs):
    hourly, daily, now = inputs
    expected = assess("BTCUSDT", now, hourly, daily, now)
    full = AssessmentSeries("BTCUSDT", bars(65 * 24, HOUR), bars(65, DAY, "0.24"))
    assert full.at(now, now) == expected


@pytest.mark.parametrize("which", ["hourly", "daily"])
def test_due_missing_bar_is_unavailable_not_carried_forward(inputs, which):
    hourly, daily, now = inputs
    result = assess(
        "BTCUSDT",
        now,
        hourly[:-1] if which == "hourly" else hourly,
        daily[:-1] if which == "daily" else daily,
        now,
    )
    assert not result.available
    assert f"missing_{which}_bar" in result.reasons


def test_missing_internal_hour_invalidates_due_four_hour_bucket(inputs):
    hourly, daily, now = inputs
    result = assess("BTCUSDT", now, hourly[:-3] + hourly[-2:], daily, now)
    assert not result.available
    assert "missing_four_hour_bar" in result.reasons


def test_previous_120_atrs_required_not_shortened_to_available_history(inputs):
    hourly, daily, now = inputs
    result = assess("BTCUSDT", now, hourly[-100:], daily, now)
    assert not result.available
    assert "volatility_warmup" in result.reasons


@pytest.mark.parametrize("age", [HOUR + 1, -1])
def test_stale_or_future_quote_refuses_assessment(inputs, age):
    hourly, daily, now = inputs
    assert "quote_unavailable" in assess("BTCUSDT", now, hourly, daily, now - age).reasons


def test_quote_at_exact_one_hour_is_allowed(inputs):
    hourly, daily, now = inputs
    assert assess("BTCUSDT", now, hourly, daily, now - HOUR).available


@pytest.mark.parametrize("bad", [D("NaN"), D("Infinity"), D(-1)])
def test_invalid_market_value_fails_closed(inputs, bad):
    hourly, daily, now = inputs
    hourly[-1] = replace(hourly[-1], close=bad)
    result = assess("BTCUSDT", now, hourly, daily, now)
    assert not result.available
    assert "invalid_hourly_bar" in result.reasons


@pytest.mark.parametrize("bad", [D("NaN"), D("sNaN"), D("Infinity")])
def test_invalid_future_value_does_not_poison_a_past_decision(inputs, bad):
    hourly, daily, now = inputs
    expected = assess("BTCUSDT", now, hourly, daily, now)
    hourly.append(replace(hourly[-1], open_ms=now, close=bad))
    daily.append(replace(daily[-1], open_ms=now, close=bad))
    assert assess("BTCUSDT", now, hourly, daily, now) == expected


def test_historical_gaps_are_recorded_without_fabricating_bars(inputs):
    hourly, daily, now = inputs
    del hourly[1000]
    del daily[40]
    result = assess("BTCUSDT", now, hourly, daily, now)
    assert result.available
    assert (1000 * HOUR, 1001 * HOUR) in result.hourly_gaps
    assert (1000 * HOUR, 1004 * HOUR) in result.four_hour_gaps
    assert (40 * DAY, 41 * DAY) in result.daily_gaps


def test_future_gaps_not_visible_to_earlier_assessment(inputs):
    hourly, daily, now = inputs
    expected = assess("BTCUSDT", now, hourly, daily, now)
    assert (
        assess(
            "BTCUSDT",
            now,
            hourly + [replace(hourly[-1], open_ms=now + 9 * HOUR)],
            daily + [replace(daily[-1], open_ms=now + 2 * DAY)],
            now,
        )
        == expected
    )


def test_duplicate_or_unaligned_bar_is_integrity_error(inputs):
    hourly, daily, now = inputs
    with pytest.raises(ValueError):
        assess("BTCUSDT", now, hourly + [hourly[-1]], daily, now)
    with pytest.raises(ValueError):
        assess("BTCUSDT", now, [replace(hourly[0], open_ms=1)] + hourly[1:], daily, now)


def test_prior_band_excludes_current_bar(inputs):
    hourly, daily, now = inputs
    prior_max = max(k.high for k in hourly[-84:-4])
    result = assess("BTCUSDT", now, hourly, daily, now)
    assert result.prior_high == prior_max


def test_repeated_at_uses_precomputed_series_without_mutation(inputs):
    hourly, daily, now = inputs
    series = AssessmentSeries("BTCUSDT", hourly, daily)
    last = series.at(now, now)
    series.at(now - DAY, now - DAY)
    assert series.at(now, now) == last


@pytest.mark.parametrize("timeframe,step", [("hourly", HOUR), ("daily", DAY)])
@pytest.mark.parametrize("defect", ["duplicate", "unaligned", "unordered"])
def test_future_timestamp_error_only_raises_when_visible(inputs, timeframe, step, defect):
    hourly, daily, now = inputs
    expected = assess("BTCUSDT", now, hourly, daily, now)
    source = hourly if timeframe == "hourly" else daily
    future = replace(source[-1], open_ms=now + step)
    if defect == "duplicate":
        source.extend((future, future))
        visible = now + 2 * step
    elif defect == "unaligned":
        source.append(replace(future, open_ms=now + 1))
        visible = now + step + 1
    else:
        source.extend((future, replace(future, open_ms=now)))
        visible = now + 2 * step
    series = AssessmentSeries("BTCUSDT", hourly, daily)
    assert series.at(now, now) == expected
    series.at(visible - 1, visible - 1)
    with pytest.raises(ValueError, match="timestamp"):
        series.at(visible, visible)
    assert series.at(now, now) == expected


def test_unordered_future_bar_does_not_hide_an_earlier_completed_bar(inputs):
    hourly, daily, now = inputs
    earlier = replace(hourly[-1], open_ms=now)
    later = replace(hourly[-1], open_ms=now + 10 * HOUR)
    expected = assess("BTCUSDT", now + HOUR, hourly + [earlier], daily, now + HOUR)
    series = AssessmentSeries("BTCUSDT", hourly + [later, earlier], daily)
    assert series.at(now + HOUR, now + HOUR) == expected


@pytest.mark.parametrize("timestamp", [True, 1.5, "tomorrow"])
def test_noninteger_timestamp_is_an_unplaceable_constructor_error(inputs, timestamp):
    hourly, daily, _ = inputs
    with pytest.raises(ValueError, match="timestamp"):
        AssessmentSeries("BTCUSDT", hourly + [replace(hourly[-1], open_ms=timestamp)], daily)


def test_visible_inversion_is_detected_across_a_still_future_bar(inputs):
    hourly, daily, now = inputs
    suffix = [replace(hourly[-1], open_ms=now + i * HOUR) for i in (1, 100, 0)]
    series = AssessmentSeries("BTCUSDT", hourly + suffix, daily)
    series.at(now + HOUR, now + HOUR)
    with pytest.raises(ValueError, match="timestamp"):
        series.at(now + 2 * HOUR, now + 2 * HOUR)


def month_hours(month: str) -> list[Kline]:
    """Every hour of ``month``: rising, each bar inside its own range, fractional volumes."""
    start, end = month_bounds_ms(month)
    return [
        Kline(
            t,
            D(100) + i,
            D(102) + i,
            D(99) + i,
            D(101) + i,
            D(i + 1) / 4,
            D(i) + D("0.5"),
            D(i) / 8,
        )
        for i, t in enumerate(range(start, end, HOUR))
    ]


def test_daily_bars_are_the_frozen_v3_daily_bars():
    # Day 3 keeps 23 hours, day 5 exactly 20, day 7 only 19 and day 9 none.
    rows = month_hours("2021-03")
    gone = {
        3 * 24 + 5,
        *(5 * 24 + hour for hour in (0, 7, 15, 23)),
        *range(7 * 24, 7 * 24 + 5),
        *range(9 * 24, 10 * 24),
    }
    kept = [bar for i, bar in enumerate(rows) if i not in gone]
    frozen = hourly_month(kept, "2021-03")
    assert not frozen.excluded
    assert daily_bars(kept) == frozen.daily_bars
    days = {(bar.open_ms - rows[0].open_ms) // DAY for bar in frozen.daily_bars}
    assert {3, 5} <= days and not {7, 9} & days and len(days) == 29


@pytest.mark.parametrize("defect", ["invalid", "unaligned"])
def test_an_hour_the_assessment_cannot_read_counts_as_missing(defect):
    hours = month_hours("2021-03")[4:24]  # twenty hours: the day still has its bar
    assert len(daily_bars(hours)) == 1
    first = hours[0]
    if defect == "invalid":
        bad = replace(first, close=D("NaN"))
    else:
        bad = replace(first, open_ms=first.open_ms + 1)
    assert daily_bars([bad, *hours[1:]]) == ()


def test_a_month_v3_excludes_still_gets_its_day_rule_bars():
    # V3 gives no daily bar in a month missing more than 17% of its hours. The day rule
    # alone keeps every day of at least 20 hours: registration must refuse such a month.
    rows = month_hours("2021-03")
    partial = {*(10 * 24 + hour for hour in range(4)), *range(12 * 24, 12 * 24 + 5)}
    kept = [bar for i, bar in enumerate(rows) if i >= 5 * 24 and i not in partial]
    assert (len(rows) - len(kept)) * 100 > len(rows) * 17
    frozen = hourly_month(kept, "2021-03")
    assert frozen.excluded and frozen.daily_bars == ()
    # The same days' bars when the month keeps its first five days and is not excluded.
    whole = hourly_month([bar for i, bar in enumerate(rows) if i not in partial], "2021-03")
    assert not whole.excluded
    expected = tuple(bar for bar in whole.daily_bars if bar.open_ms >= rows[5 * 24].open_ms)
    assert daily_bars(kept) == expected
    days = {(bar.open_ms - rows[0].open_ms) // DAY for bar in expected}
    assert days == set(range(5, 31)) - {12}  # day 10 keeps 20 hours, day 12 only 19


def test_an_inexact_daily_sum_is_refused():
    hours = month_hours("2021-03")[:24]
    hours[0] = replace(hours[0], volume=D("1e30"))
    hours[1] = replace(hours[1], volume=D("1e-40"), taker_buy_base=D(0))
    with pytest.raises(ValueError, match="exact"):
        daily_bars(hours)
