from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext

import pytest

from crypto_grid_bot.combined.recovery import Recovery, RecoveryState

D = Decimal
DAY = 86_400_000


def enter_recovery() -> Recovery:
    recovery = Recovery()
    recovery.update(0, D(100), True, True, True)
    recovery.update(1, D(70), False, True, True)
    recovery.update(2, D(70), True, True, True)
    result = recovery.update(DAY + 2, D(70), True, True, True)
    assert result.state == RecoveryState.RECOVERY25
    return recovery


def test_lifetime_peak_not_initial_balance_controls_trigger() -> None:
    recovery = Recovery()
    recovery.update(0, D(100), True, True, True)
    recovery.update(1, D(200), False, True, True)
    assert recovery.update(2, D("140.0001"), False, True, True).close is False
    result = recovery.update(3, D(140), False, True, True)
    assert result.state == RecoveryState.CLOSING
    assert result.close and result.risk_fraction == 0
    assert result.lifetime_drawdown == D(".30")


def test_cooldown_requires_completed_liquidation_and_qualification() -> None:
    recovery = Recovery()
    recovery.update(0, D(100), True, True, True)
    recovery.update(1, D(70), False, True, True)
    assert recovery.update(DAY, D(69), False, True, True).close
    assert recovery.update(DAY + 1, D(69), True, True, True).state == RecoveryState.COOLDOWN
    assert recovery.update(2 * DAY, D(69), True, True, True).risk_fraction == 0
    assert recovery.update(2 * DAY + 1, D(69), True, False, True).risk_fraction == 0
    result = recovery.update(2 * DAY + 2, D(69), True, True, True)
    assert result.risk_fraction == D(".25")
    assert result.max_drawdown == D(".31")


def test_first_restart_is_quarter_even_when_equity_recovers_during_cooldown() -> None:
    recovery = Recovery()
    recovery.update(0, D(100), True, True, True)
    recovery.update(1, D(70), True, True, True)
    result = recovery.update(DAY + 1, D(110), True, True, True)
    assert result.state == RecoveryState.RECOVERY25
    assert result.lifetime_drawdown == 0
    assert result.max_drawdown == D(".3")
    assert recovery.update(DAY + 1, D(110), True, True, True) == result
    assert recovery.update(DAY + 2, D(110), True, True, True).state == RecoveryState.NORMAL


def test_episode_stop_uses_all_marks_and_exact_boundary_without_lifetime_reset() -> None:
    recovery = enter_recovery()
    recovery.update(DAY + 3, D(71), False, False, True)
    assert not recovery.update(DAY + 4, D("68.8701"), False, False, True).close
    result = recovery.update(DAY + 5, D("68.87"), False, True, True)
    assert result.close
    assert result.lifetime_drawdown == D(".3113")
    recovery.update(DAY + 6, D("68.8"), True, True, True)
    result = recovery.update(2 * DAY + 6, D("68.8"), True, True, True)
    assert result.risk_fraction == D(".25")
    assert result.max_drawdown == D(".312")


def test_upgrades_are_strict_and_require_qualification() -> None:
    recovery = enter_recovery()
    assert recovery.update(DAY + 3, D(85), False, True, True).risk_fraction == D(".25")
    assert recovery.update(DAY + 4, D(86), False, False, True).risk_fraction == D(".25")
    assert recovery.update(DAY + 5, D(86), False, True, True).risk_fraction == D(".5")
    assert recovery.update(DAY + 6, D(90), False, True, True).risk_fraction == D(".5")
    assert recovery.update(DAY + 7, D(91), False, False, True).risk_fraction == D(".5")
    result = recovery.update(DAY + 8, D(91), False, True, True)
    assert result.state == RecoveryState.NORMAL
    assert result.max_drawdown == D(".3")


def test_lost_flat_confirmation_restarts_cooldown() -> None:
    recovery = Recovery()
    recovery.update(0, D(100), True, True, True)
    recovery.update(1, D(70), True, True, True)
    assert recovery.update(DAY, D(70), False, True, True).close
    recovery.update(DAY + 1, D(70), True, True, True)
    assert recovery.update(DAY + 2, D(70), True, True, True).risk_fraction == 0
    assert recovery.update(2 * DAY + 1, D(70), True, True, True).risk_fraction == D(".25")


@pytest.mark.parametrize("equity,integrity", [(D(0), True), (D(-1), True), (D(70), False)])
def test_terminal_failure_while_closing_never_auto_recovers(
    equity: Decimal, integrity: bool
) -> None:
    recovery = Recovery()
    recovery.update(0, D(100), True, True, True)
    recovery.update(1, D(70), False, True, True)
    result = recovery.update(2, equity, False, True, integrity)
    assert result.state == RecoveryState.TERMINAL and result.close
    result = recovery.update(3 * DAY, D(200), True, True, True)
    assert result.state == RecoveryState.TERMINAL
    assert result.risk_fraction == 0 and not result.close


@pytest.mark.parametrize("equity", [D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity"), 100])
def test_invalid_equity_rejected_without_mutating_clock(equity: Decimal) -> None:
    recovery = Recovery()
    recovery.update(2, D(100), True, True, True)
    with pytest.raises((ValueError, TypeError)):
        recovery.update(10, equity, True, True, True)
    assert recovery.update(3, D(70), False, True, True).close


def test_clock_policy_rejects_backwards_but_orders_distinct_same_timestamp_events() -> None:
    recovery = Recovery()
    recovery.update(2, D(100), True, True, True)
    for invalid in (1, -1, True, 2.5):
        with pytest.raises((ValueError, TypeError)):
            recovery.update(invalid, D(100), True, True, True)
    assert recovery.update(2, D(70), False, True, True).close
    assert recovery.update(2, D(70), True, True, True).state == RecoveryState.COOLDOWN


def test_result_immutable_and_arithmetic_independent_of_callers_precision() -> None:
    recovery = Recovery()
    recovery.update(0, D(100), True, True, True)
    with localcontext() as context:
        context.prec = 2
        result = recovery.update(1, D("69.99999"), False, True, True)
    assert result.max_drawdown == D(".3000001")
    with pytest.raises(FrozenInstanceError):
        result.close = False  # type: ignore[misc]


def test_half_allowance_falls_back_at_fifteen_percent_without_waiting_for_qualification() -> None:
    recovery = enter_recovery()
    assert recovery.update(DAY + 3, D(86), False, True, True).risk_fraction == D(".5")
    result = recovery.update(DAY + 4, D(85), False, False, True)
    assert result.state == RecoveryState.RECOVERY25
    assert result.risk_fraction == D(".25")
    assert not result.close
