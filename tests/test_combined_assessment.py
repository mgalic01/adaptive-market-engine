"""Causal V3.1 market assessment, independent of any strategy P&L."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.assessment import AssessmentSeries, assess
from crypto_grid_bot.strategy.perception import TrendState

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
