"""Hysteresis policy that prevents wasteful opportunity chasing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite


@dataclass(slots=True)
class RotationState:
    challenger_symbol: str | None = None
    consecutive_wins: int = 0
    last_rotation_at: datetime | None = None
    last_observed_at: datetime | None = None


class RotationPolicy:
    def __init__(
        self,
        *,
        minimum_relative_improvement: float,
        confirmation_cycles: int,
        minimum_cost_multiple: float,
        cooldown_hours: int,
    ) -> None:
        if (
            not isfinite(minimum_relative_improvement)
            or minimum_relative_improvement <= 0
            or confirmation_cycles < 1
            or not isfinite(minimum_cost_multiple)
            or minimum_cost_multiple < 1
            or cooldown_hours <= 0
        ):
            raise ValueError("invalid rotation thresholds")
        self._minimum_relative_improvement = minimum_relative_improvement
        self._confirmation_cycles = confirmation_cycles
        self._minimum_cost_multiple = minimum_cost_multiple
        self._cooldown = timedelta(hours=cooldown_hours)

    def should_rotate(
        self,
        *,
        state: RotationState,
        incumbent_symbol: str,
        incumbent_score: float,
        challenger_symbol: str,
        challenger_score: float,
        expected_improvement_quote: float,
        switching_cost_quote: float,
        now: datetime,
    ) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("rotation timestamps must be timezone-aware")
        if (
            any(
                not isfinite(x) or x < 0
                for x in (
                    incumbent_score,
                    challenger_score,
                    expected_improvement_quote,
                    switching_cost_quote,
                )
            )
            or max(incumbent_score, challenger_score) > 1
        ):
            self._reset_challenger(state)
            return False
        if state.last_observed_at is not None and now <= state.last_observed_at:
            return False
        state.last_observed_at = now
        if challenger_symbol == incumbent_symbol:
            self._reset_challenger(state)
            return False
        if state.last_rotation_at and now - state.last_rotation_at < self._cooldown:
            self._reset_challenger(state)
            return False
        baseline = max(incumbent_score, 1e-9)
        relative_improvement = (challenger_score - incumbent_score) / baseline
        cost_pass = expected_improvement_quote > switching_cost_quote * self._minimum_cost_multiple
        if relative_improvement < self._minimum_relative_improvement or not cost_pass:
            self._reset_challenger(state)
            return False

        if state.challenger_symbol == challenger_symbol:
            state.consecutive_wins += 1
        else:
            state.challenger_symbol = challenger_symbol
            state.consecutive_wins = 1
        return state.consecutive_wins >= self._confirmation_cycles

    def confirm_rotation(self, state: RotationState, now: datetime) -> None:
        """Start cooldown after a completed rotation, not merely a recommendation."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("rotation timestamps must be timezone-aware")
        if state.consecutive_wins < self._confirmation_cycles:
            raise ValueError("there is no confirmed rotation recommendation")
        if state.last_observed_at is not None and now < state.last_observed_at:
            raise ValueError("completion predates the recommendation")
        state.last_rotation_at = now
        self._reset_challenger(state)

    @staticmethod
    def _reset_challenger(state: RotationState) -> None:
        state.challenger_symbol = None
        state.consecutive_wins = 0
