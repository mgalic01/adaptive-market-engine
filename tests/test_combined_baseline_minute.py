"""Frozen minute-replay baselines (V0-V2 grids, comparator D); synthetic inputs only."""

import math
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from crypto_grid_bot.backtest import replay as minute_replay
from crypto_grid_bot.backtest.features import HOUR_MS, FeatureEngine, SeriesFeatures
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.replay import RunConfig, replay
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


HOURS = hourly(WARMUP_DAYS * 24 + 48)
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


def minutes(days=1, skip=()):
    fair = float(ENGINE.at(T0).fair_value)
    rows = []
    for index in range(days * 24 * 60):
        if index in skip:
            continue
        price = fair * (1 + 0.01 * math.sin(index / 7.0))
        rows.append(candle(T0 + index * 60_000, price, price * 1.003, price * 0.997, price * 1.001))
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


def grid(skip=(), initial="2000"):
    return replay_grid_baseline(
        "matched_v0_grid_high_first",
        grid_jobs(skip),
        start_ms=T0,
        end_ms=T0 + DAY,
        initial=D(initial),
        source_refs=("synthetic:grid",),
        adapter_pin=PIN,
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
    issues = [i for i in evidence.report.issues if "journal_parity" in i]
    assert not issues
    boundaries = evidence.report.policy_evidence.boundaries
    assert len(boundaries) == 25
    assert evidence.report.reconciliation_residual == 0
