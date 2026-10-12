"""Literal equal-cash hold baseline; synthetic inputs only."""

from dataclasses import replace
from decimal import Decimal as D

import combined_market_fixtures as fx
import pytest

from crypto_grid_bot.combined.baseline_hold import HoldMarket, replay_hold_baseline

PIN = "c" * 64


def markets(rules=fx.RULES):
    return {
        symbol: HoldMarket(fx.market(symbol, path, 3).spot.hourly, rules, fx.COSTS)
        for symbol, path in (("BTCUSDT", fx.uptrend), ("ETHUSDT", fx.downtrend))
    }


def hold(cash="10000", cost=1, rules=fx.RULES):
    return replay_hold_baseline(
        markets(rules),
        start_ms=fx.START,
        end_ms=fx.START + 3 * fx.DAY,
        initial=D(cash),
        cost_multiple=cost,
        source_refs=("synthetic:hold",),
        adapter_pin=PIN,
    )


def test_equal_cash_hold_reconciles_exactly_and_is_complete():
    evidence = hold()
    report = evidence.report
    assert report.complete, report.issues
    assert report.reconciliation_residual == 0
    assert report.equity_points[0].equity == D(10000)  # before the purchase costs
    assert {c.asset for c in report.contributions} == {"BTCUSDT", "ETHUSDT"}
    assert all(c.status == "open_marked" for c in report.contributions)
    # Equal cash: each coin's purchase is within its share, and both are bought.
    assert all(c.turnover + c.fees <= D(5000) for c in report.contributions)
    first_open = {s: m.hourly[0] for s, m in markets().items()}
    btc = next(c for c in report.contributions if c.asset == "BTCUSDT")
    assert btc.entry_ms == fx.START and btc.turnover > 0
    assert first_open["BTCUSDT"].open_ms <= fx.START


def test_a_share_below_the_exchange_minimum_stays_in_cash_and_is_disclosed():
    evidence = hold(cash="108.5", rules=replace(fx.RULES, min_notional=D(60)))
    assert {c.asset for c in evidence.report.contributions} == set()
    assert any("kept_in_cash" in note for note in evidence.disclosures)
    assert evidence.report.final_equity == D("108.5")


def test_doubled_cost_doubles_fee_and_slippage():
    base, doubled = hold(cost=1), hold(cost=2)
    assert doubled.report.fees > base.report.fees
    assert doubled.report.final_equity < base.report.final_equity


def test_a_missing_midnight_bar_is_complete_only_when_registered_as_skipped():
    midnight = fx.START + fx.DAY
    gapped = {
        symbol: replace(market, hourly=tuple(b for b in market.hourly if b.open_ms != midnight))
        for symbol, market in markets().items()
    }

    def run(skipped):
        return replay_hold_baseline(
            gapped,
            start_ms=fx.START,
            end_ms=fx.START + 3 * fx.DAY,
            initial=D(10000),
            cost_multiple=1,
            source_refs=("synthetic:hold",),
            adapter_pin=PIN,
            skipped_hours=skipped,
        )

    skipped = run((midnight,))
    assert skipped.report.complete, skipped.report.issues
    assert midnight not in {p.timestamp_ms for p in skipped.report.equity_points}
    sharpe = next(m for m in skipped.report.metrics if m.name == "sharpe")
    assert sharpe.value is not None and "2020-12-23" in sharpe.definition
    unskipped = run(())
    assert not unskipped.report.complete
    assert "metric_unavailable:sharpe:incomplete_or_unmatched_daily_samples" in (
        unskipped.report.issues
    )


def test_invalid_cost_multiple_is_refused():
    with pytest.raises(ValueError):
        hold(cost=3)
