"""Frozen minute-replay baselines (V0-V2 grids, comparator D); synthetic inputs only."""

import math
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from crypto_grid_bot.backtest import replay as minute_replay
from crypto_grid_bot.backtest.features import HOUR_MS, FeatureEngine, SeriesFeatures
from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.replay import RunConfig, replay
from crypto_grid_bot.combined import baseline_minute
from crypto_grid_bot.combined.baseline_minute import (
    MinuteJob,
    TrendJob,
    recorded_frames,
    replay_grid_baseline,
    replay_trend_baseline,
)
from crypto_grid_bot.combined.common_series import common_hourly_series
from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.models import MarketRules
from crypto_grid_bot.strategy.daily_sma import DailyCloses

PIN = "d" * 64
DAY = 24 * HOUR_MS
WARMUP_DAYS = 34
RESERVED = 1_735_689_600_000  # 2025-01-01T00:00Z
ORIGIN = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
T0 = ORIGIN + WARMUP_DAYS * DAY  # a UTC midnight after the feature warm-up
CONFIG = load_config(Path(__file__).resolve().parents[1] / "config" / "default.toml")


def candle(open_ms, o, h, low, c):
    o, h, low, c = (D(str(round(x, 6))) for x in (o, h, low, c))
    return Kline(open_ms, o, h, low, c, D(1000000), D(1000000) * c, D(500000))


def hourly(count):
    rows, previous = [], 1.0
    for index in range(count):
        close = 1.0 + 0.08 * math.sin(2 * math.pi * index / 24)
        high, low = max(previous, close) * 1.004, min(previous, close) * 0.996
        rows.append(candle(ORIGIN + index * HOUR_MS, previous, high, low, close))
        previous = close
    return rows


HOURS = hourly(WARMUP_DAYS * 24 + 96)  # features for four days after T0
SERIES = SeriesFeatures("TESTUSDT", HOURS)
ENGINE = FeatureEngine(
    SERIES,
    SERIES,
    [SeriesFeatures(f"B{i}USDT", HOURS, full=False) for i in range(5)],
    range_atr_multiple=2.0,
    levels=8,
    minimum_cost_multiple=3.0,
    round_trip_cost=0.0035,
)


def minutes(days=1, skip=(), first=T0):
    fair = float(ENGINE.at(T0).fair_value)
    rows = []
    for index in range(days * 24 * 60):
        if index in skip:
            continue
        price = fair * (1 + 0.01 * math.sin(index / 7.0))
        rows.append(
            candle(first + index * 60_000, price, price * 1.003, price * 0.997, price * 1.001)
        )
    return tuple(rows)


def run_config(symbol):
    rules = MarketRules(
        symbol=symbol, tick_size=D(".0001"), quantity_step=D(".1"), minimum_notional=D(5)
    )
    return RunConfig(symbol, "high_first", False, rules, D(100), D(".0005"))


def grid_jobs(skip=()):
    return {
        symbol: MinuteJob(CONFIG, run_config(symbol), minutes(skip=skip), ENGINE)
        for symbol in ("AAAUSDT", "BBBUSDT")
    }


def grid(skip=(), initial="2000", **options):
    return replay_grid_baseline(
        "matched_v0_grid_high_first",
        grid_jobs(skip),
        start_ms=T0,
        end_ms=T0 + DAY,
        initial=D(initial),
        source_refs=("synthetic:grid",),
        adapter_pin=PIN,
        **options,
    )


def test_the_recorder_changes_nothing_the_frozen_replay_computes():
    job = grid_jobs()["AAAUSDT"]
    plain = replay(job.config, job.run, job.minutes, job.features)
    with recorded_frames() as frames:
        observed = replay(job.config, job.run, job.minutes, job.features)
    assert asdict(observed[0]) == asdict(plain[0]) and observed[1] == plain[1]
    assert sorted(frames.hours) == list(range(T0, T0 + DAY, HOUR_MS))
    assert frames.last is not None and frames.last[1] == plain[0].final_equity
    assert vars(minute_replay)["PaperSimulator"].__name__ == "PaperSimulator"


def test_grid_portfolio_has_every_hourly_boundary_and_reconciles():
    evidence = grid()
    report = evidence.report
    boundaries = report.policy_evidence.boundaries
    assert [b.timestamp_ms for b in boundaries] == list(range(T0, T0 + DAY + HOUR_MS, HOUR_MS))
    assert report.equity_points[0].equity == D(2000)  # before any frame or cost
    assert report.reconciliation_residual == 0
    assert evidence.wallet_quantity_exact is True
    assert "minute_baseline_final_minute_close_is_window_end" in evidence.disclosures
    assert evidence.report.disclosures == evidence.disclosures
    assert "present_day_saved_exchange_filters_on_historical_data" in evidence.report.disclosures
    series = common_hourly_series(
        report.equity_points, report.policy_evidence, start_ms=T0, end_ms=T0 + DAY
    )
    assert series.points[-1].equity == report.final_equity


def test_a_missing_opening_minute_leaves_that_boundary_absent():
    evidence = grid(skip=(60,))  # the 01:00 minute
    stamps = {b.timestamp_ms for b in evidence.report.policy_evidence.boundaries}
    assert T0 + HOUR_MS not in stamps
    with pytest.raises(ValueError):
        common_hourly_series(
            evidence.report.equity_points,
            evidence.report.policy_evidence,
            start_ms=T0,
            end_ms=T0 + DAY,
        )


def test_capital_must_split_exactly_across_pairs():
    with pytest.raises(ValueError):
        replay_grid_baseline(
            "matched_v0_grid_high_first",
            {**grid_jobs(), "CCCUSDT": grid_jobs()["AAAUSDT"]},
            start_ms=T0,
            end_ms=T0 + DAY,
            initial=D(10000),
            source_refs=("s",),
            adapter_pin=PIN,
        )


def test_an_engine_failure_is_retained_and_incomplete(monkeypatch):
    from crypto_grid_bot.combined import baseline_minute

    def broken(*args, **kwargs):
        raise ValueError("synthetic engine failure")

    monkeypatch.setattr(baseline_minute, "replay", broken)
    evidence = grid()
    assert evidence.status == "engine_failure"
    assert not evidence.report.complete


def test_comparator_d_is_rebuilt_exactly_from_its_journal():
    fair = float(ENGINE.at(T0).fair_value)
    days = [T0 - 60 * DAY + d * DAY for d in range(61)]
    closes = DailyCloses((day, D(str(fair * (1 + 0.002 * i)))) for i, day in enumerate(days))
    jobs = {
        symbol: TrendJob(
            run_config(symbol), minutes(), closes, lambda ms: ENGINE.at(ms) is not None
        )
        for symbol in ("AAAUSDT", "BBBUSDT")
    }
    evidence = replay_trend_baseline(
        "matched_d_trend_high_first",
        jobs,
        start_ms=T0,
        end_ms=T0 + DAY,
        initial=D(2000),
        source_refs=("synthetic:d",),
        adapter_pin=PIN,
    )
    assert evidence.report.disclosures == evidence.disclosures
    assert "present_day_saved_exchange_filters_on_historical_data" in evidence.report.disclosures
    issues = [i for i in evidence.report.issues if "journal_parity" in i]
    assert not issues
    boundaries = evidence.report.policy_evidence.boundaries
    assert len(boundaries) == 25
    assert evidence.report.reconciliation_residual == 0


@pytest.fixture
def frozen_calls(monkeypatch):
    """Every call into a frozen replay; a refusal must come before the first one."""
    calls = []

    def spy(real):
        def call(*args, **kwargs):
            calls.append(real.__name__)
            return real(*args, **kwargs)

        return call

    for name in ("replay", "replay_trend"):
        monkeypatch.setattr(baseline_minute, name, spy(getattr(baseline_minute, name)))
    return calls


def trend_jobs(**changes):
    fair = float(ENGINE.at(T0).fair_value)
    days = [T0 - 60 * DAY + d * DAY for d in range(61)]
    closes = DailyCloses((day, D(str(fair * (1 + 0.002 * i)))) for i, day in enumerate(days))
    jobs = {
        symbol: TrendJob(
            run_config(symbol), minutes(), closes, lambda ms: ENGINE.at(ms) is not None
        )
        for symbol in ("AAAUSDT", "BBBUSDT")
    }
    return {symbol: replace(job, **changes) for symbol, job in jobs.items()}


def run_grid(jobs, start_ms=T0, end_ms=T0 + DAY):
    return replay_grid_baseline(
        "matched_v0_grid_high_first",
        jobs,
        start_ms=start_ms,
        end_ms=end_ms,
        initial=D(2000),
        source_refs=("synthetic:grid",),
        adapter_pin=PIN,
    )


def run_trend(jobs, start_ms=T0, end_ms=T0 + DAY):
    return replay_trend_baseline(
        "matched_d_trend_high_first",
        jobs,
        start_ms=start_ms,
        end_ms=end_ms,
        initial=D(2000),
        source_refs=("synthetic:d",),
        adapter_pin=PIN,
    )


# The frozen replay plays every minute it is given and has no pre-window minutes of its own:
# its warm-up is the hourly and daily history behind the feature engine, and its taker-flow
# window starts empty at the first played minute. So no minute outside the window is allowed.
STRAYS = [
    pytest.param(-DAY, 2, id="a_day_early"),
    pytest.param(-60_000, 1, id="one_minute_early"),
    pytest.param(0, 2, id="up_to_a_day_late"),
]


@pytest.mark.parametrize(("offset", "days"), STRAYS)
def test_a_grid_minute_outside_the_window_is_refused_before_the_frozen_replay(
    frozen_calls, offset, days
):
    stray = minutes(days=days, first=T0 + offset)
    jobs = {symbol: replace(job, minutes=stray) for symbol, job in grid_jobs().items()}
    with pytest.raises(ValueError, match="outside the registered window"):
        run_grid(jobs)
    assert frozen_calls == []


@pytest.mark.parametrize(("offset", "days"), STRAYS)
def test_a_trend_minute_outside_the_window_is_refused_before_the_frozen_replay(
    frozen_calls, offset, days
):
    with pytest.raises(ValueError, match="outside the registered window"):
        run_trend(trend_jobs(minutes=minutes(days=days, first=T0 + offset)))
    assert frozen_calls == []


def test_one_pair_with_a_stray_minute_refuses_the_whole_portfolio(frozen_calls):
    jobs = grid_jobs()
    jobs["BBBUSDT"] = replace(jobs["BBBUSDT"], minutes=minutes(days=2, first=T0 - DAY))
    with pytest.raises(ValueError, match="BBBUSDT"):
        run_grid(jobs)
    assert frozen_calls == []  # AAAUSDT, first in order, was not replayed either


def test_the_window_own_first_and_last_minutes_are_replayed_not_refused(frozen_calls):
    evidence = run_grid(grid_jobs())
    assert evidence.status is None
    assert frozen_calls == ["replay", "replay"]


def sealed_candle(open_ms=RESERVED):
    return candle(open_ms, 1, 1.01, 0.99, 1)


def sealed_engine(**changes):
    """A feature engine whose own history reaches the reserved boundary."""
    pair = SeriesFeatures("TESTUSDT", [*HOURS, sealed_candle()]) if "pair" in changes else SERIES
    return FeatureEngine(
        pair,
        SERIES,
        [SeriesFeatures(f"B{i}USDT", HOURS, full=False) for i in range(5)],
        range_atr_multiple=2.0,
        levels=8,
        minimum_cost_multiple=3.0,
        round_trip_cost=0.0035,
        daily_bars=[sealed_candle()] if "daily" in changes else None,
    )


def test_a_sealed_minute_is_refused_even_inside_the_window(frozen_calls):
    window = (RESERVED - 60_000, RESERVED + 60_000)
    stamps = minutes(days=1, first=RESERVED - 60_000)[:2]  # 23:59 and the sealed 00:00
    assert [bar.open_ms for bar in stamps] == [RESERVED - 60_000, RESERVED]
    jobs = {symbol: replace(job, minutes=stamps) for symbol, job in grid_jobs().items()}
    with pytest.raises(ValueError, match="reserved boundary"):
        run_grid(jobs, *window)
    with pytest.raises(ValueError, match="reserved boundary"):
        run_trend(trend_jobs(minutes=stamps), *window)
    assert frozen_calls == []


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"daily": [sealed_candle()]}, id="daily_bar"),
        pytest.param({"hourly": [sealed_candle()]}, id="hourly_bar"),
        pytest.param({"funding": [FundingRecord(RESERVED, 8, D("0.0001"))]}, id="funding"),
        pytest.param({"features": sealed_engine(pair=True)}, id="feature_hourly_candle"),
        pytest.param({"features": sealed_engine(daily=True)}, id="feature_daily_bar"),
    ],
)
def test_a_sealed_record_in_a_grid_input_is_refused_before_the_frozen_replay(frozen_calls, change):
    jobs = {symbol: replace(job, **change) for symbol, job in grid_jobs().items()}
    with pytest.raises(ValueError, match="reserved boundary"):
        run_grid(jobs)
    assert frozen_calls == []


def test_a_sealed_daily_close_in_comparator_d_is_refused_before_the_frozen_replay(frozen_calls):
    fair = float(ENGINE.at(T0).fair_value)
    closes = DailyCloses([(T0 - DAY, D(str(fair))), (RESERVED, D(str(fair)))])
    with pytest.raises(ValueError, match="reserved boundary"):
        run_trend(trend_jobs(closes=closes))
    assert frozen_calls == []


def test_both_minute_adapters_carry_a_research_capital_label():
    trend = replay_trend_baseline(
        "matched_d_trend_high_first",
        trend_jobs(),
        start_ms=T0,
        end_ms=T0 + DAY,
        initial=D(10000),
        source_refs=("synthetic:d",),
        adapter_pin=PIN,
        capital_label="research_10000_usdt",
    )
    gridded = grid(initial="10000", capital_label="research_10000_usdt")
    assert trend.report.capital_label == gridded.report.capital_label == "research_10000_usdt"
