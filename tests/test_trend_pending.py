"""Deferred daily decisions at midnight and missing-hour boundaries."""

from decimal import Decimal as D

import pytest

T = 1609459200000
H = 3600000


def test_deferred_pick_close_keeps_cause_across_replacement_but_not_after_dispatch():
    from crypto_grid_bot.trend.pending import PendingDecisions

    q = PendingDecisions()
    q.advance(T, {"BTCUSDT": D(0)}, set(), {"BTCUSDT": frozenset({"pick_change"})})
    q.advance(T + 24 * H, {"BTCUSDT": D(0)}, set(), {"BTCUSDT": frozenset({"signal_zero"})})
    ready = q.advance(T + 25 * H, {}, {"BTCUSDT"}).ready
    assert ready[0][1].exit_reasons == frozenset({"pick_change", "signal_zero"})
    q.advance(T + 48 * H, {"BTCUSDT": D(0)}, set())
    assert q.advance(T + 49 * H, {}, {"BTCUSDT"}).ready[0][1].exit_reasons == frozenset()


def test_cancelled_close_does_not_attribute_later_nonzero_target_to_old_pick():
    from crypto_grid_bot.trend.pending import PendingDecisions

    q = PendingDecisions()
    q.advance(T, {"BTCUSDT": D(0)}, set(), {"BTCUSDT": frozenset({"pick_change"})})
    q.advance(T + 24 * H, {"BTCUSDT": D(".1")}, set())
    assert q.advance(T + 25 * H, {}, {"BTCUSDT"}).ready[0][1].exit_reasons == frozenset()


def test_midnight_replaces_pending_before_zero_hour_fill():
    from crypto_grid_bot.trend.pending import PendingDecisions

    q = PendingDecisions()
    assert q.advance(T, {"BTCUSDT": D(".1")}, set()).ready == ()
    result = q.advance(T + 24 * H, {"BTCUSDT": D("-.2")}, {"BTCUSDT"})
    assert result.ready == ()
    assert result.cancelled[0][1].weight == D(".1")
    ready = q.advance(T + 25 * H, {}, {"BTCUSDT"}).ready
    assert ready[0][1].weight == D("-.2")
    assert ready[0][1].decision_ms == T + 24 * H


def test_no_bar_day_keeps_old_decision_and_can_fill_at_midnight():
    from crypto_grid_bot.trend.pending import PendingDecisions

    q = PendingDecisions()
    q.advance(T, {"BTCUSDT": D(".1")}, set())
    result = q.advance(T + 24 * H, {}, {"BTCUSDT"})
    assert not result.cancelled
    assert result.ready[0][1].decision_ms == T
    assert not q.advance(T + 25 * H, {}, {"BTCUSDT"}).ready


def test_each_coin_waits_for_its_own_first_unmasked_hour():
    from crypto_grid_bot.trend.pending import PendingDecisions

    q = PendingDecisions()
    q.advance(T, {"ETHUSDT": D(".2"), "BTCUSDT": D(0)}, set())
    assert [s for s, _ in q.advance(T + H, {}, {"ETHUSDT"}).ready] == ["ETHUSDT"]
    assert [s for s, _ in q.advance(T + 2 * H, {}, {"BTCUSDT"}).ready] == ["BTCUSDT"]


def test_bad_decision_batch_does_not_cancel_or_advance():
    from crypto_grid_bot.trend.pending import PendingDecisions

    q = PendingDecisions()
    q.advance(T, {"BTCUSDT": D(".1")}, set())
    with pytest.raises(ValueError):
        q.advance(T + 24 * H, {"BTCUSDT": D("NaN")}, set())
    assert q.advance(T + H, {}, {"BTCUSDT"}).ready[0][1].weight == D(".1")


def test_duplicate_hour_and_nonmidnight_decisions_are_rejected():
    from crypto_grid_bot.trend.pending import PendingDecisions

    q = PendingDecisions()
    q.advance(T, {}, set())
    with pytest.raises(ValueError):
        q.advance(T, {}, set())
    with pytest.raises(ValueError):
        q.advance(T + H, {"BTCUSDT": D(0)}, set())
