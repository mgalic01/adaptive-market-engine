"""Pure portfolio recovery controller; execution and dust classification stay outside.

Equal timestamps represent sequential events. Repeating the immediately previous
complete input is idempotent; distinct same-time events are processed in call order.
Callers must deduplicate event IDs upstream. Invalid input raises before mutation.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from enum import StrEnum

_ZERO = Decimal(0)
_ONE = Decimal(1)
_DAY_MS = 86_400_000


class RecoveryState(StrEnum):
    NORMAL = "Normal"
    CLOSING = "Closing"
    COOLDOWN = "Cooldown"
    RECOVERY25 = "Recovery25"
    RECOVERY50 = "Recovery50"
    TERMINAL = "Terminal"


@dataclass(frozen=True)
class RecoveryDecision:
    state: RecoveryState
    risk_fraction: Decimal
    close: bool
    reason: str
    lifetime_drawdown: Decimal
    max_drawdown: Decimal


class Recovery:
    """Track lifetime loss separately from each recoverable episode.

    Fractions are allowances, not orders. The allocator must apply them to normal
    admissible size and aggregate budgets. ``tradable_flat`` is a verified external
    assertion (including resolved pending reductions), not equity-based inference.
    """

    def __init__(self) -> None:
        self._state = RecoveryState.NORMAL
        self._peak = _ZERO
        self._max_drawdown = _ZERO
        self._episode_peak = _ZERO
        self._cooldown_since: int | None = None
        self._last: tuple[int, Decimal, bool, bool, bool] | None = None
        self._decision: RecoveryDecision | None = None
        self._terminal_reason = ""

    def update(
        self,
        timestamp_ms: int,
        equity: Decimal,
        tradable_flat: bool,
        qualified: bool,
        integrity_ok: bool,
    ) -> RecoveryDecision:
        """Process one mark, preserving peaks even during cooldown or failure."""
        if type(timestamp_ms) is not int or timestamp_ms < 0:
            raise ValueError("timestamp_ms must be a nonnegative integer")
        if not isinstance(equity, Decimal) or not equity.is_finite():
            raise ValueError("equity must be a finite Decimal")
        if any(type(flag) is not bool for flag in (tradable_flat, qualified, integrity_ok)):
            raise ValueError("state flags must be bool")
        if self._last is not None and timestamp_ms < self._last[0]:
            raise ValueError("timestamps must not move backwards")
        inputs = (timestamp_ms, equity, tradable_flat, qualified, integrity_ok)
        if inputs == self._last and self._decision is not None:
            return self._decision
        with localcontext() as context:
            context.prec = 60
            self._peak = max(self._peak, equity)
            drawdown = (_ONE - equity / self._peak) if self._peak > 0 else _ONE
            self._max_drawdown = max(self._max_drawdown, drawdown)
            if self._state != RecoveryState.TERMINAL and (not integrity_ok or equity <= 0):
                self._state = RecoveryState.TERMINAL
                self._terminal_reason = (
                    "integrity_failure" if not integrity_ok else "capital_exhausted"
                )
            reason = self._transition(timestamp_ms, equity, drawdown, tradable_flat, qualified)
            fraction = {
                RecoveryState.NORMAL: _ONE,
                RecoveryState.RECOVERY25: Decimal("0.25"),
                RecoveryState.RECOVERY50: Decimal("0.5"),
            }.get(self._state, _ZERO)
            decision = RecoveryDecision(
                self._state,
                fraction,
                self._state in (RecoveryState.CLOSING, RecoveryState.TERMINAL)
                and not tradable_flat,
                reason,
                drawdown,
                self._max_drawdown,
            )
        self._last = inputs
        self._decision = decision
        return decision

    def _transition(
        self, timestamp_ms: int, equity: Decimal, drawdown: Decimal, flat: bool, qualified: bool
    ) -> str:
        if self._state == RecoveryState.TERMINAL:
            return self._terminal_reason
        if self._state == RecoveryState.NORMAL:
            if drawdown < Decimal("0.30"):
                return "normal"
            return self._close(timestamp_ms, flat, "lifetime_stop")
        if self._state == RecoveryState.CLOSING:
            return self._close(timestamp_ms, flat, "awaiting_liquidation")
        if self._state == RecoveryState.COOLDOWN:
            if not flat:
                return self._close(timestamp_ms, False, "liquidation_incomplete")
            if self._cooldown_since is None or timestamp_ms - self._cooldown_since < _DAY_MS:
                return "cooldown"
            if not qualified:
                return "restart_unqualified"
            self._state = RecoveryState.RECOVERY25
            self._episode_peak = equity
            return "qualified_restart"
        self._episode_peak = max(self._episode_peak, equity)
        if _ONE - equity / self._episode_peak >= Decimal("0.03"):
            return self._close(timestamp_ms, flat, "episode_stop")
        if self._state == RecoveryState.RECOVERY50 and drawdown >= Decimal("0.15"):
            self._state = RecoveryState.RECOVERY25
            return "half_allowance_revoked"
        if qualified and drawdown < Decimal("0.10"):
            self._state = RecoveryState.NORMAL
            self._episode_peak = _ZERO
            return "normal_restored"
        if qualified and drawdown < Decimal("0.15"):
            self._state = RecoveryState.RECOVERY50
            return "half_restored"
        return "recovery"

    def _close(self, timestamp_ms: int, flat: bool, reason: str) -> str:
        self._state = RecoveryState.COOLDOWN if flat else RecoveryState.CLOSING
        self._cooldown_since = timestamp_ms if flat else None
        return reason
