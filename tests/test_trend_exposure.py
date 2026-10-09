"""Frozen post-fill exposure diagnostics on synthetic account marks."""

from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.account import FuturesAccount
from crypto_grid_bot.trend.execution import HourResult
from crypto_grid_bot.trend.orders import OrderIntent

T = 1577836800000


def mark(long=0, short=0):
    account = FuturesAccount()
    if long:
        account.fill("BTCUSDT", OrderIntent(D(long), False), D(100), T)
    if short:
        account.fill("ETHUSDT", OrderIntent(-D(short), False), D(100), T)
    return account.mark({"BTCUSDT": D(100), "ETHUSDT": D(100)})


def hour(*marks):
    return HourResult(tuple(marks), (), (), None)


def test_account_mark_retains_signed_notional_for_mixed_and_flat_books():
    mixed = mark(10, 6)
    assert mixed.gross_notional == 1600
    assert mixed.net_notional == 400
    assert mark(0, 6).net_notional == -600
    assert mark().net_notional == 0


def test_exposure_uses_post_delevering_but_not_later_funding_or_extremes():
    from decimal import localcontext

    from crypto_grid_bot.trend.exposure import exposure_diagnostics

    flat, before, after, later = mark(), mark(150), mark(70), mark(20)
    hours = [
        hour(("post_fill", flat)),
        hour(
            ("open", before),
            ("post_fill", before),
            ("post_fill_delevered", after),
            ("funding", later),
            ("favourable", mark(300)),
            ("adverse", later),
        ),
    ]
    result = exposure_diagnostics(hours)
    assert result.observed_hours == result.sampled_hours == 2
    assert result.invested_fraction == D(".5")
    with localcontext() as context:
        context.prec = 60
        assert result.mean_gross_exposure == after.gross_notional / after.equity / 2
        assert result.mean_net_exposure == after.net_notional / after.equity / 2
    assert result.minimum_margin_ratio == before.margin_ratio


def test_early_terminal_hour_is_explicitly_unsampled_not_fabricated_flat():
    from crypto_grid_bot.trend.exposure import exposure_diagnostics

    result = exposure_diagnostics([hour(("open", mark(10)))])
    assert result.observed_hours == 1
    assert result.sampled_hours == 0
    assert result.invested_fraction is None
    assert result.mean_gross_exposure is None
    assert result.mean_net_exposure is None


def test_legacy_missing_net_evidence_and_nonpositive_equity_are_not_reported_as_zero():
    from dataclasses import replace

    from crypto_grid_bot.trend.exposure import exposure_diagnostics

    value = mark(10)
    with pytest.raises(ValueError, match="net"):
        exposure_diagnostics([hour(("post_fill", replace(value, net_notional=None)))])
    result = exposure_diagnostics([hour(("post_fill", replace(value, equity=D(0))))])
    assert result.undefined_equity_hours == 1
    assert result.invested_fraction == 1
    assert result.mean_gross_exposure is None
    assert result.mean_net_exposure is None
