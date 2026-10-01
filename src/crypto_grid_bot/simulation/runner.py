"""Persistent, single-symbol offline strategy-to-fill loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from crypto_grid_bot.config import BotConfig
from crypto_grid_bot.domain import (
    CandidateMetrics,
    MarketRegime,
    MarketSignals,
    PortfolioSnapshot,
    RegimeAssessment,
    RiskAction,
    RiskDecision,
)
from crypto_grid_bot.portfolio.profit_vault import ProfitVault, ProfitVaultState
from crypto_grid_bot.risk.engine import RiskEngine
from crypto_grid_bot.simulation.execution import (
    Reduction,
    exit_state,
    exitable,
    liquidate,
    match,
    place,
    reduce_unreserved,
    unpaired_inventory,
)
from crypto_grid_bot.simulation.inventory_cap import capped_quantity
from crypto_grid_bot.simulation.models import (
    ONE,
    ZERO,
    Account,
    D,
    LimitOrder,
    MarketRules,
    Quote,
    floor_step,
    nonnegative,
    seconds_between,
    timestamp,
)
from crypto_grid_bot.simulation.store import StateStore, encode
from crypto_grid_bot.simulation.trend_switch import (
    DOWN_DEADLINE_SECONDS,
    UNAVAILABLE,
    UP,
    TrendSignal,
    effective_state,
    starts_down_sequence,
)
from crypto_grid_bot.strategy.grid import GridBuilder, GridNotViable
from crypto_grid_bot.strategy.opportunity import OpportunityScorer
from crypto_grid_bot.strategy.regime import RegimeClassifier, thresholds_from_config

DEFAULT_CAPITAL = D("100")
# 5 (2026-09-27, engine "exit-residue-v1"): a residue the exchange filters forbid
# selling no longer blocks settlement or a new grid, and a validation halt holding
# inventory arms liquidation. A schema-4 database was written under the old lifecycle,
# so reopening it here would mix two semantics in one event history; the identity
# mismatch refuses it instead.
# 6 (2026-09-28, engine "drawdown-recovery-v1", spec v1 amendment 1): a soft-drawdown
# episode rebases ``risk_high`` after a cool-off; a ``drawdown`` halt restarts by itself
# after a cool-off; a manual resume admits a residue below the exchange minimum; the
# account carries the halt's start and category, the episode and the C1(b) reference.
# Schema 1-5 databases are refused: their halts were final and their state lacks these
# fields.
SCHEMA = 6
# The four halt categories (spec v1 amendment 1); only ``drawdown`` restarts by itself.
DRAWDOWN, EMERGENCY, EXHAUSTION, INTEGRITY = "drawdown", "emergency", "exhaustion", "integrity"
RESTART_PAUSE = "automatic restart after drawdown halt: awaiting confirmed eligible data"


class TransientFrame(ValueError):
    """Unusable observation: cancel entries and wait for confirmed fresh recovery."""


@dataclass(frozen=True)
class SimulationPolicy:
    recovery_frames: int = 2
    # Continuity between fresh observations, independent of per-frame delivery age.
    maximum_frame_gap_seconds: int = 180
    # Observed outside-range time (valid frames only) before exiting a grid to cash.
    outside_range_seconds: int = 21600
    # After a range exit, allow a new grid centred on current fair value once this
    # cooldown has passed and eligibility is reconfirmed. False = wait in cash until
    # price re-enters the old band (an explicit, documented terminal-until-return state).
    recenter_after_exit: bool = True
    recenter_cooldown_seconds: int = 86400
    # Experiment variant B (spec v1, section 3 B): committed exposure may not exceed this
    # fraction of prospective active equity when a buy is created. None = off (V0).
    inventory_cap: Decimal | None = None
    # Experiment variant A (spec v1, section 3 A): the daily SMA50/SMA200 trend switch.
    # False = off (V0). The daily state arrives on each Frame as ``trend``.
    trend_switch: bool = False
    # Experiment variant E (spec v1, section 3 E): volume-confirmed range exit.
    # When True, a 6h outside-range timer that triggers on low volume is extended to 12h.
    # The threshold (2 × median 720h volume × 6) and measured volume arrive on each Frame.
    # False = off (V0). Not eligible for selection until Codex reviews implementation.
    volume_exit: bool = False
    # Experiment variant F (spec v1, section 3 F): order-flow entry block.
    # When True, new buys are blocked when taker-buy share < 0.40 over the last 15 completed
    # 1m bars; unblocked when share >= 0.45. Starts blocked (fails closed).
    # False = off (V0). Not eligible for selection until Codex reviews implementation.
    flow_block_entry: bool = False
    # Spec v1 amendment 1 (owner decision 2026-09-27): the soft-drawdown cool-off before
    # ``risk_high`` may be rebased, and the hard-drawdown cool-off H before a ``drawdown``
    # halt restarts. Both are part of the account identity and fixed for all v1 runs.
    soft_cooloff_seconds: int = 86400
    hard_cooloff_seconds: int = 86400

    def __post_init__(self) -> None:
        if type(self.recovery_frames) is not int or not 2 <= self.recovery_frames <= 100:
            raise ValueError("recovery requires 2-100 distinct eligible frames")
        if type(self.outside_range_seconds) is not int or self.outside_range_seconds <= 0:
            raise ValueError("outside-range timeout must be a positive integer")
        if type(self.recenter_after_exit) is not bool:
            raise ValueError("recenter_after_exit must be a boolean")
        if type(self.recenter_cooldown_seconds) is not int or self.recenter_cooldown_seconds <= 0:
            raise ValueError("recentering cooldown must be a positive integer")
        if (
            type(self.maximum_frame_gap_seconds) is not int
            or not 1 <= self.maximum_frame_gap_seconds <= 3600
        ):
            raise ValueError("maximum frame gap must be 1-3600 seconds")
        if self.inventory_cap is not None:
            nonnegative(self.inventory_cap)
            if not ZERO < self.inventory_cap < ONE:
                raise ValueError("inventory cap must be above zero and below one")
        if type(self.trend_switch) is not bool:
            raise ValueError("trend_switch must be a boolean")
        if type(self.volume_exit) is not bool:
            raise ValueError("volume_exit must be a boolean")
        if type(self.flow_block_entry) is not bool:
            raise ValueError("flow_block_entry must be a boolean")
        for name in ("soft_cooloff_seconds", "hard_cooloff_seconds"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def identity(self) -> dict[str, Any]:
        """Persisted form; omits unset variants so existing paper identities still match."""
        value = asdict(self)
        if self.inventory_cap is None:
            del value["inventory_cap"]
        if not self.trend_switch:
            del value["trend_switch"]
        if not self.volume_exit:
            del value["volume_exit"]
        if not self.flow_block_entry:
            del value["flow_block_entry"]
        return value


@dataclass(frozen=True)
class Frame:
    quote: Quote
    signals: MarketSignals
    candidate: CandidateMetrics
    fair_value: Decimal
    atr: Decimal
    allow_new_grid: bool = True
    # Historical replay only: frames sharing an epoch replay one bar (see match()).
    epoch: str | None = None
    # Variant A only: the daily trend state for this observation (see trend_switch.py).
    trend: TrendSignal | None = None
    # V2: nearest resistance above current price from structure.py; None when unavailable.
    fta_resistance: float | None = None
    # Variant E (spec v1, §3 E): volume-confirmed range exit inputs. Both are None/zero
    # when variant E is off or the reference is unavailable (falls back to V0 behaviour).
    # e_threshold: 2 × median(last 720 completed 1h base volumes) × 6, frozen at t0.
    # e_bar_volume: accumulated 1m base volume in [floor_min(t0), floor_min(t0+6h)).
    e_threshold: Decimal | None = None
    e_bar_volume: Decimal = ZERO
    # Variant F (spec v1, §3 F): order-flow entry block. None when F is off.
    # share = taker-buy base ÷ total base over the last 15 completed consecutive 1m bars.
    # None when unavailable (missing bar or zero aggregate volume).
    f_share: float | None = None

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["signals"]["observed_at"] = self.signals.observed_at.isoformat()
        if value["epoch"] is None:
            del value["epoch"]  # Keeps journals written before this field byte-identical.
        if value["trend"] is None:
            del value["trend"]  # Likewise for journals without variant A.
        if value["fta_resistance"] is None:
            del value["fta_resistance"]  # Omit from journals when structure unavailable.
        if value["e_threshold"] is None:
            del value["e_threshold"]
        if not value["e_bar_volume"]:
            del value["e_bar_volume"]
        if value["f_share"] is None:
            del value["f_share"]
        return value


class PaperSimulator:
    def __init__(
        self,
        path: Path,
        config: BotConfig,
        rules: MarketRules,
        initial_cash: Decimal = DEFAULT_CAPITAL,
        policy: SimulationPolicy | None = None,
    ) -> None:
        if config.mode != "paper":
            raise ValueError("only paper mode is supported")
        self.config, self.rules = config, rules
        self.policy = policy or SimulationPolicy()
        # Replay measurement hook: sees (active equity, risk high-water mark, C1(b)
        # measurement reference, decision) at every risk evaluation the engine performs.
        # A tentative evaluation for a rebase or a restart is not one. It observes only
        # and must not change the account.
        self.risk_observer: Callable[[Decimal, Decimal, Decimal, RiskDecision], None] | None = None
        identity = encode(
            {
                "schema": SCHEMA,
                "policy": self.policy.identity(),
                "config": asdict(config),
                "rules": rules.identity(),
                "initial_cash": initial_cash,
            }
        )
        self.store = StateStore(path, Account.start(initial_cash), rules, identity)
        self.risk = RiskEngine(
            daily_loss_pause_pct=config.daily_loss_pause_pct,
            soft_drawdown_pct=config.soft_drawdown_pct,
            hard_drawdown_pct=config.hard_drawdown_pct,
            maximum_data_age_seconds=config.maximum_data_age_seconds,
        )
        self.classifier = RegimeClassifier(thresholds_from_config(config))
        self.scorer = OpportunityScorer(
            minimum_score=config.minimum_opportunity_score,
            maximum_news_risk=config.maximum_news_risk,
            maximum_spread_pct=config.maximum_spread_pct,
            minimum_depth_multiple=config.minimum_depth_multiple,
        )
        self.builder = GridBuilder(
            minimum_levels=config.minimum_levels,
            maximum_levels=config.maximum_levels,
            minimum_cost_multiple=config.minimum_grid_cost_multiple,
            range_atr_multiple=config.range_atr_multiple,
        )
        self.vault = ProfitVault(
            reserve_fraction=D(str(config.reserve_fraction)),
            minimum_transfer_quote=D(str(config.minimum_transfer_quote)),
        )

    def close(self) -> None:
        self.store.close()

    def process(self, frame: Frame) -> dict[str, Any]:
        return self.store.transact(
            frame.quote.event_id, frame.payload(), lambda account: self._step(account, frame)
        )

    def step(self, account: Account, frame: Frame) -> dict[str, Any]:
        """Advance an in-memory account by one frame, without the event journal.

        Historical replay only: the same decision logic, Decimal context and final
        invariant check as ``process``, but nothing is persisted or deduplicated.
        """
        with localcontext() as context:
            context.prec = 50
            report = self._step(account, frame)
            account.validate(self.rules)
        return report

    @staticmethod
    def _cancel_buys(account: Account) -> list[str]:
        cancelled = [key for key, order in account.orders.items() if order.side == "buy"]
        for key in cancelled:
            del account.orders[key]
        return cancelled

    def _f_cancel_buys(self, account: Account, quote: Quote, report: dict) -> list[str]:
        """Variant F: cancel all resting buys and handle partial fills.

        For each cancelled buy, the already-filled quantity (quantity - remaining)
        needs a resting sell at order.target. If the notional is below minimum,
        accumulate in account.flow_fragments[target] until it reaches minimum_notional,
        then place a single sell.

        Returns the list of cancelled order IDs (same as _cancel_buys).
        """
        rules = self.rules
        # Snapshot buy orders before modifying.
        buys = {key: order for key, order in account.orders.items() if order.side == "buy"}
        if not buys:
            return []
        cancelled: list[str] = []
        for key, order in buys.items():
            del account.orders[key]
            cancelled.append(key)
            filled = order.quantity - order.remaining
            if filled <= ZERO or order.target is None:
                continue
            # Return the reserved quote for the remaining unfilled portion back to cash.
            # This is handled automatically by the account: deleting the order removes
            # the reservation, so cash is freed implicitly. Only handle the filled qty.
            # Place a sell for the filled quantity (possibly accumulating fragments).
            target = order.target
            accum = account.flow_fragments.get(target, ZERO) + filled
            notional = target * floor_step(accum, rules.quantity_step)
            if notional >= rules.minimum_notional:
                qty = floor_step(accum, rules.quantity_step)
                sell_id = f"{quote.event_id}/f_frag/{key}"
                sell = LimitOrder(sell_id, "sell", target, qty, qty, reentry=order.price)
                place(account, sell, rules)
                remainder = accum - qty
                if remainder > ZERO:
                    account.flow_fragments[target] = remainder
                else:
                    account.flow_fragments.pop(target, None)
            else:
                account.flow_fragments[target] = accum
        if cancelled:
            report.setdefault("cancelled", [])
            report["cancelled"] = sorted(set(report["cancelled"]) | set(cancelled))
        return cancelled

    @staticmethod
    def _halt(
        account: Account,
        reason: str,
        *,
        category: str,
        observed: str,
        exit_requested: bool = False,
    ) -> None:
        """Halt, or keep halted. The start, category and reason are captured once, on the
        transition from not halted to halted, and no later call changes them (spec v1
        amendment 1: an ``integrity`` or ``emergency`` halt past 12% is never
        re-categorised as ``drawdown``, and an invalid frame during a ``drawdown`` halt
        does not make it ``integrity``). Later calls may still clear orders and arm the
        exit. A halt of any category ends an open soft-drawdown episode."""
        account.orders.clear()
        if not account.halt:
            account.halt = reason
            account.halt_since = observed
            account.halt_category = category
            account.episode_since, account.episode_count = "", 0
        account.pause = ""
        account.recovery_count = 0
        account.liquidating = account.liquidating or exit_requested

    @staticmethod
    def _halt_time(account: Account, quote: Quote) -> str:
        """The halt start for an invalid frame: its own time if parseable, else the last
        valid observation. Empty only when neither exists."""
        try:
            timestamp(quote.observed_at)
        except (TypeError, ValueError):
            return account.last_observed
        return quote.observed_at

    def _resolved(self, account: Account, quote: Quote) -> bool:
        """True when no position is left that the account could still trade out of.

        Either flat, or holding only a residue the market filters forbid selling: the
        engine has no way to reduce that residue, so no recovery step may wait for it.

        Deliberately scoped differently from ``unpaired_inventory``: this asks "is
        anything sellable held", so it counts the filled part of a resting buy, while the
        drain and the end-of-run verdict ask "what does this exit owe" and exclude it.
        The range-exit and settlement callers are gated on an empty order book
        (``liquidate``'s precondition, and ``_settle``'s own check). The harvest gate is
        not: a partly filled buy may still rest there, and then ``exitable`` counts its
        filled part while ``unpaired_inventory`` does not. That disagreement is the
        point. This is the stricter test, so a harvest never sells inventory a resting
        buy's child sell will pair, and it is never True while ``exit_state`` is
        ``incomplete``. Keeping them distinct is what stops a partly filled buy being
        drained out from under its own child sell.
        """
        return not account.reserved_base() and not exitable(account, quote, self.rules)

    def _pause(self, account: Account, reason: str) -> None:
        self._cancel_buys(account)
        account.pause = reason
        account.recovery_count = 0
        account.draining = True

    def _risk_action(self, account: Account, quote: Quote, emergency: bool) -> RiskAction:
        equity = account.equity(quote, self.rules)
        result = self.risk.evaluate(
            PortfolioSnapshot(
                float(equity),
                float(account.day_start),
                float(account.risk_high),
                0,
                emergency=emergency,
            )
        )
        if self.risk_observer is not None:
            self.risk_observer(equity, account.risk_high, account.measure_high, result)
        if result.action == RiskAction.EXIT:
            # The engine checks the emergency flag before the drawdown, so a frame with
            # both is an emergency halt (spec v1 amendment 1).
            self._halt(
                account,
                "; ".join(result.reasons),
                category=EMERGENCY if emergency else DRAWDOWN,
                observed=quote.observed_at,
                exit_requested=True,
            )
        elif result.action != RiskAction.ALLOW and not account.halt:
            self._pause(account, "; ".join(result.reasons))
            if result.action == RiskAction.REDUCE and not account.episode_since:
                # The first REDUCE outside an episode starts one (amendment 1, soft
                # drawdown, item 1); its cool-off runs from this observation.
                account.episode_since, account.episode_count = quote.observed_at, 0
        return result.action

    def _tentative_allow(self, account: Account, quote: Quote, emergency: bool) -> bool:
        """Would the risk engine ALLOW with ``risk_high`` rebased to this frame's active
        equity? By construction this tests the daily loss, the emergency flag and the
        input checks, and nothing about drawdown (amendment 1). Not an engine evaluation:
        the observer does not see it and the account is untouched."""
        equity = account.equity(quote, self.rules)
        result = self.risk.evaluate(
            PortfolioSnapshot(
                float(equity), float(account.day_start), float(equity), 0, emergency=emergency
            )
        )
        return result.action == RiskAction.ALLOW

    def _rebase(
        self, account: Account, frame: Frame, eligible: bool, report: dict[str, Any]
    ) -> None:
        """Soft drawdown, option C (amendment 1): on each valid frame of an open episode,
        before any other state change, count the confirmations and commit the rebase once
        the cool-off has passed. Runs first in the step, after the mark."""
        if not account.episode_since or account.halt:
            return
        quote = frame.quote
        confirmed = eligible and self._tentative_allow(account, quote, frame.signals.emergency)
        account.episode_count = account.episode_count + 1 if confirmed else 0
        if (
            confirmed
            and account.episode_count >= self.policy.recovery_frames
            and seconds_between(account.episode_since, quote.observed_at)
            >= self.policy.soft_cooloff_seconds
        ):
            report["rebase"] = {
                "episode_since": account.episode_since,
                "old_reference": account.risk_high,
                "new_reference": account.last_equity,
            }
            account.risk_high = account.last_equity
            account.episode_since, account.episode_count = "", 0

    def _restart(
        self, account: Account, frame: Frame, eligible: bool, report: dict[str, Any]
    ) -> bool:
        """Hard drawdown, automatic restart (amendment 1). Evaluated on a halted frame after
        this frame's liquidation attempt. Only a ``drawdown`` halt restarts; it changes
        exactly the fields a manual ``resume()`` changes, and never the daily baseline,
        the C1 references, the reserves or the vault."""
        quote = frame.quote
        if account.halt_category != DRAWDOWN or not account.halt_since or account.orders:
            return False
        if (
            seconds_between(account.halt_since, quote.observed_at)
            < self.policy.hard_cooloff_seconds
        ):
            return False
        # "Flat" is PR #122's liquidation-complete: nothing the market would still accept.
        # A residue below the exchange minimum stays held and marked.
        if exit_state(account, quote, self.rules)[0] == "incomplete" or not eligible:
            return False
        try:
            account.validate(self.rules)
        except ValueError:
            return False
        if not self._tentative_allow(account, quote, frame.signals.emergency):
            return False
        reference = account.equity(quote, self.rules)
        report["restart"] = {
            "halt_since": account.halt_since,
            "category": account.halt_category,
            "halt": account.halt,
            "old_reference": account.risk_high,
            "new_reference": reference,
        }
        account.halt, account.liquidating = "", False
        account.halt_since, account.halt_category = "", ""
        account.range_exit, account.range_exit_since = False, ""
        account.grid_lower = account.grid_upper = ZERO
        account.outside_seconds, account.outside_last = ZERO, ""
        account.down_since = ""  # a flat account has ended any variant A sequence
        account.risk_high = reference
        self._pause(account, RESTART_PAUSE)
        return True

    def _validate_frame(self, account: Account, frame: Frame) -> None:
        quote = frame.quote
        quote.validate(self.rules)
        observed, received = timestamp(quote.observed_at), timestamp(quote.received_at)
        age = (received - observed).total_seconds()
        signal_age = (received - timestamp(frame.signals.observed_at.isoformat())).total_seconds()
        if not 0 <= age <= self.config.maximum_data_age_seconds:
            raise TransientFrame("stale or future-dated quote")
        if not 0 <= signal_age <= self.config.maximum_data_age_seconds:
            raise TransientFrame("stale or future-dated strategy inputs")
        if account.last_observed and observed <= timestamp(account.last_observed):
            raise TransientFrame("out-of-order quote")
        if account.last_received and received < timestamp(account.last_received):
            raise TransientFrame("receive clock moved backwards")
        actual_spread_pct = (quote.ask - quote.bid) / quote.ask * 100
        if actual_spread_pct > D(str(self.config.maximum_spread_pct)):
            raise TransientFrame("observed spread exceeds the eligibility limit")
        nonnegative(frame.fair_value)
        nonnegative(frame.atr)
        if frame.fair_value == ZERO or frame.atr == ZERO:
            raise ValueError("fair value and ATR must be positive")
        if frame.candidate.symbol != self.rules.symbol:
            raise ValueError("candidate does not match configured market")
        if self.policy.trend_switch and frame.trend is not None:
            # A daily bar that had not closed at this observation is lookahead: fail closed.
            frame.trend.validate(quote.observed_at)

    def _track_range(self, account: Account, quote: Quote, frame: Frame) -> None:
        """Accumulate observed outside-range time; call before updating last_observed."""
        if not account.grid_lower or account.range_exit:
            return
        observed = quote.observed_at
        if account.grid_lower <= quote.bid <= account.grid_upper:
            account.outside_seconds, account.outside_last = ZERO, ""
            account.e_extended = False
            return
        # Count only intervals bracketed by two consecutive valid outside observations
        # within the continuity limit. Gaps do not prove time outside the range, but they
        # do not erase time already observed; only a valid inside frame resets the clock.
        if account.outside_last and account.outside_last == account.last_observed:
            elapsed = seconds_between(account.outside_last, observed)
            if elapsed <= self.policy.maximum_frame_gap_seconds:
                account.outside_seconds += elapsed
        account.outside_last = observed
        if account.outside_seconds >= self.policy.outside_range_seconds:
            # Variant E: at the 6h trigger, check volume before committing to exit.
            if (
                self.policy.volume_exit
                and not account.e_extended
                and frame.e_threshold is not None
                and frame.e_bar_volume < frame.e_threshold
            ):
                # Volume is below threshold and extension not yet used: extend to 12h.
                # The outside_seconds clock keeps running; exit fires when it reaches 2×.
                account.e_extended = True
                return
            # V0 path, or E with extension already used, or E with volume ≥ threshold,
            # or E extension has now run out (outside_seconds ≥ 2 × outside_range_seconds).
            if (
                self.policy.volume_exit
                and account.e_extended
                and account.outside_seconds < self.policy.outside_range_seconds * 2
            ):
                # Still within the 12h window — wait.
                return
            account.orders.clear()
            account.range_exit = True
            account.range_exit_since = observed
            account.outside_seconds, account.outside_last = ZERO, ""
            account.e_extended = False
            self._pause(account, "outside-range timeout: exit to cash")

    @staticmethod
    def _record_exit(report: dict[str, Any], result: Reduction, reason: str) -> None:
        """Journal an exit attempt, including a refusal that sold nothing.

        A refused exit used to leave no trace at all, so an account that could make no
        progress looked identical to one with nothing left to sell.
        """
        report["fills"].extend(asdict(fill) for fill in result.fills)
        if result.fills:
            report["exit_reason"] = reason
        # Always recorded, so a frame that attempted an exit and was not refused is
        # distinguishable from one that attempted none: a rejected or halting frame
        # returns before this and carries no key at all.
        report["exit_blocked"] = result.blocked if result.blocked in ("depth", "dust") else ""
        report["exit_blocked_notional"] = result.outstanding_notional

    @staticmethod
    def _mark(account: Account, quote: Quote, rules: MarketRules) -> None:
        account.last_equity = account.equity(quote, rules)
        account.risk_high = max(account.risk_high, account.last_equity)
        account.measure_high = max(account.measure_high, account.last_equity)

    def _step(self, account: Account, frame: Frame) -> dict[str, Any]:
        quote = frame.quote
        report: dict[str, Any] = {
            "event_id": quote.event_id,
            "fills": [],
            "opened": [],
            "cancelled": [],
            "decision": "hold",
            "allocation": None,
        }
        previous_orders = set(account.orders)
        capped: list[dict[str, Any]] = []
        restarted = False
        try:
            self._validate_frame(account, frame)
            regime = self.classifier.classify(frame.signals)
            score = self.scorer.score(frame.candidate, regime)
        except TransientFrame as exc:
            # Unusable data pauses the outside-range clock but never erases time already
            # observed outside; otherwise a flapping feed could postpone the exit forever.
            if not account.halt:
                self._pause(account, str(exc))
            account.episode_count = 0  # a TransientFrame breaks the confirmations
            report.update(
                decision="halt" if account.halt else "pause",
                reason=account.halt or account.pause,
                cancelled=sorted(previous_orders - account.orders.keys()),
            )
            return report  # No marking, fills, liquidation or recovery on unusable data.
        except ValueError as exc:
            # A validation halt cancels the resting sells that were the inventory's only
            # exit, so held inventory must be armed for liquidation. Nothing is traded on
            # this invalid frame: the return below precedes the liquidation branch, so the
            # exit runs on the next frame that validates.
            self._halt(
                account,
                str(exc),
                category=INTEGRITY,
                observed=self._halt_time(account, quote),
                exit_requested=account.inventory != ZERO,
            )
            report.update(decision="halt", reason=str(exc), cancelled=sorted(previous_orders))
            return report

        observed = timestamp(quote.observed_at)
        day = observed.date().isoformat()
        if account.day != day:
            account.day, account.day_start = day, account.last_equity
        # _track_range uses account.last_observed for continuity detection: call it before
        # last_observed is updated to the current quote's time, so the check
        # ``outside_last == last_observed`` correctly identifies consecutive observations.
        self._track_range(account, quote, frame)
        # A gap or a new ineligible frame breaks the recovery streak.
        if (
            account.last_observed
            and (observed - timestamp(account.last_observed)).total_seconds()
            > self.policy.maximum_frame_gap_seconds
        ):
            account.recovery_count = account.episode_count = 0
        account.last_observed, account.last_received = quote.observed_at, quote.received_at
        self._mark(account, quote, self.rules)
        # regime.reasons contains per-signal diagnostic strings. They are intentionally
        # not written to the report: in a full backtest replay the volume of per-frame
        # reason strings would dominate the output and add no measurable value to results
        # analysis. For live diagnostics, log regime.reasons at the call site instead.
        report.update(regime=regime.regime.value, opportunity_score=score.score)
        self._rebase(account, frame, score.eligible, report)
        action = self._risk_action(account, quote, frame.signals.emergency)
        trend = self._apply_trend(account, frame) if self.policy.trend_switch else None
        if account.halt:
            if account.liquidating:
                self._record_exit(report, liquidate(account, quote, self.rules), "liquidation")
            # Preconditions read after the liquidation attempt, so a restart can happen
            # on the frame that completes it. Its settlement and any new grid follow on
            # the next frame, exactly as after a manual resume.
            restarted = self._restart(account, frame, score.eligible, report)
            if account.halt:
                report.update(decision="halt", reason=account.halt)
        elif account.range_exit:
            self._record_exit(report, liquidate(account, quote, self.rules), "range_exit")
            back_inside = account.grid_lower <= quote.bid <= account.grid_upper
            cooled = (
                self.policy.recenter_after_exit
                and seconds_between(account.range_exit_since, quote.observed_at)
                >= self.policy.recenter_cooldown_seconds
            )
            self._pause(
                account,
                "outside-range timeout: waiting in cash for range recovery"
                + (
                    " or recentering after cooldown"
                    if self.policy.recenter_after_exit
                    else " (recentering disabled)"
                ),
            )
            # _resolved counts the whole unreserved inventory; safe here because
            # liquidate() above required an empty order book.
            if (
                self._resolved(account, quote)
                and action == RiskAction.ALLOW
                and score.eligible
                and (back_inside or cooled)
            ):
                # Leave the exit only after liquidation; the normal recovery confirmations
                # still apply and the next grid is built around the current fair value.
                account.range_exit, account.range_exit_since = False, ""
                account.grid_lower = account.grid_upper = ZERO
                report["range_exit_cleared"] = "returned inside" if back_inside else "recenter"
        else:
            if not score.eligible:
                self._pause(account, "; ".join(score.reasons))
            elif account.pause and action == RiskAction.ALLOW:
                account.recovery_count += 1
                if account.recovery_count >= self.policy.recovery_frames:
                    account.pause = ""
                    account.recovery_count = 0
            # Variant A deadline (spec v1, section 3 A): T0 + 24 h, not reset by further
            # Down days. The remaining sells are cancelled BEFORE this observation's
            # matching, so a quote that would have filled them cannot (Codex, PR #114);
            # what is left is then exited under the bid-size limit, retried at each later
            # valid observation.
            trend_due = bool(account.down_since) and (
                seconds_between(account.down_since, quote.observed_at) >= DOWN_DEADLINE_SECONDS
            )
            if trend_due:
                account.orders.clear()
            # Variant F: when flow_block is active, cancel all resting buys and handle
            # partial fills (fragment accumulation) before matching. This ensures no buys
            # are filled during a blocked frame and no new reentry buys are placed.
            if self.policy.flow_block_entry and account.flow_block:
                self._f_cancel_buys(account, quote, report)
            report["fills"] = [
                asdict(fill)
                for fill in match(
                    account,
                    quote,
                    self.rules,
                    # A running variant A Down sequence places no new buy (reentries too).
                    # Variant F: also suppress reentry buys when flow_block is active.
                    recycle=not account.pause
                    and not account.draining
                    and frame.allow_new_grid
                    and not account.down_since
                    and not (self.policy.flow_block_entry and account.flow_block),
                    epoch=frame.epoch,
                    reentry_quantity=(
                        None
                        if self.policy.inventory_cap is None
                        else lambda order_id, price, quantity: self._cap(
                            account, quote, capped, order_id, price, quantity
                        )
                    ),
                )
            ]
            # Unpaired inventory: neither reserved by a resting sell nor the filled part
            # of a buy still resting, whose own sell will pair it once it fills. Cancelled
            # partial buys leave it, and so does a residue a harvest tolerated. Exit it
            # using only remaining bid capacity, never inventory reserved by a sell, and
            # never the part of a resting buy that has already filled.
            unpaired = unpaired_inventory(account)
            if unpaired > ZERO:
                consumed = sum(
                    (D(fill["quantity"]) for fill in report["fills"] if fill["side"] == "sell"),
                    ZERO,
                )
                self._record_exit(
                    report,
                    reduce_unreserved(
                        account, quote, self.rules, consumed=consumed, maximum=unpaired
                    ),
                    # Same-step labelling (spec v1, section 3 A): drain outranks trend_exit.
                    "drain" if account.draining or not trend_due else "trend_exit",
                )

        # Recheck risk after any fills, but never reuse this event's liquidity for an exit.
        if report["fills"]:
            self._risk_action(account, quote, frame.signals.emergency)
        # Buys may still rest here, so _resolved (whole unreserved inventory) is the
        # stricter gate: a partly filled buy's inventory blocks the harvest until its own
        # child sell has paired it. See _resolved.
        if not account.halt and not restarted and self._resolved(account, quote):
            # A flat account is a safe harvest point even with unused deeper buys.
            # Do this only after sells, draining, or when all orders are already gone.
            sold = any(fill["side"] == "sell" for fill in report["fills"])
            if sold or account.draining or not account.orders:
                self._cancel_buys(account)
                if account.cash - account.pending <= ZERO:
                    # Arm the exit for any residue, as the other halt sites do, so the
                    # stuck inventory is reported from the next frame rather than only
                    # once the risk engine re-halts a frame later.
                    self._halt(
                        account,
                        "active capital exhausted",
                        category=EXHAUSTION,
                        observed=quote.observed_at,
                        exit_requested=account.inventory != ZERO,
                    )
                else:
                    report["allocation"] = self._settle(account, quote)
                    account.draining = False
                    if (
                        not account.pause
                        and not account.range_exit
                        and frame.allow_new_grid
                        and trend is not None
                        and (trend != UP or account.down_since)
                    ):
                        # Variant A: a new grid needs Up and no running Down sequence.
                        report.update(
                            decision="cash",
                            reason=f"trend switch: {trend}"
                            + ("; Down sequence running" if account.down_since else ""),
                        )
                    elif (
                        not account.pause
                        and not account.range_exit
                        and frame.allow_new_grid
                        # Variant F: block new grid when flow_block is active.
                        and not (self.policy.flow_block_entry and account.flow_block)
                    ):
                        try:
                            report["opened"] = self._open_grid(account, frame, capped, regime)
                            report["decision"] = "open_grid"
                        except GridNotViable as exc:
                            report.update(decision="cash", reason=str(exc))
                    elif self.policy.flow_block_entry and account.flow_block:
                        report.update(decision="cash", reason="flow_block: buy side blocked")
        if account.halt:
            report.update(decision="halt", reason=account.halt)
        elif account.pause:
            report.update(decision="pause", reason=account.pause)
        if self.policy.inventory_cap is not None:
            report["capped"] = capped
        if trend is not None:
            # The sequence ends once nothing sellable is left: flat, or holding only a
            # residue the market filters forbid selling (PR #122's rule; waiting for
            # inventory == 0 looped forever on such a residue, Bob's F1). Only a later
            # observation can then open a grid, and only in the Up state.
            if account.down_since and not account.orders and self._resolved(account, quote):
                report["down_sequence_ended"] = account.down_since
                account.down_since = ""
                if not account.range_exit:
                    # The grid this sequence ended left no orders behind; its bounds and
                    # outside-range clock are obsolete and would otherwise time an empty
                    # account out into a range exit (Codex, PR #114). A genuine V0 range
                    # exit in progress is untouched.
                    account.grid_lower = account.grid_upper = ZERO
                    account.outside_seconds, account.outside_last = ZERO, ""
            report["trend"] = {
                "state": trend,
                "day": frame.trend.day if frame.trend is not None else None,
                "down_since": account.down_since or None,
            }
        report["cancelled"] = sorted(
            previous_orders - account.orders.keys() - {fill["order_id"] for fill in report["fills"]}
        )
        self._mark(account, quote, self.rules)
        report.update(
            active_equity=account.last_equity,
            pending_reserve=account.pending,
            secured_reserve=account.secured,
            cash=account.cash,
            inventory=account.inventory,
            fees=account.fees,
            open_orders=len(account.orders),
            total_equity=account.last_equity + account.pending + account.secured,
            recovery_count=account.recovery_count,
            draining=account.draining,
            halt_category=account.halt_category,
            episode_since=account.episode_since or None,
            risk_high=account.risk_high,
            measure_high=account.measure_high,
            range_exit=account.range_exit,
            outside_seconds=account.outside_seconds,
            unreserved_inventory=account.inventory - account.reserved_base(),
        )
        return report

    def resume(self, frame: Frame, *, event_id: str, reason: str) -> dict[str, Any]:
        """Audited paper-only control; never erase losses or place/fill orders."""
        if not event_id.strip() or not reason.strip():
            raise ValueError("resume requires a unique event ID and an operator reason")

        def operation(account: Account) -> dict[str, Any]:
            self._validate_frame(account, frame)
            account.validate(self.rules)
            if not account.halt or account.orders:
                raise ValueError("resume requires a halted, reconciled flat paper account")
            if exit_state(account, frame.quote, self.rules)[0] == "incomplete":
                # Liquidation-complete, PR #122's criterion (spec v1 amendment 1): a
                # remainder below the exchange minimum is admitted, stays held and marked,
                # and is drained or settled as after any resume; inventory the market
                # would still accept is not. The risk check below is what keeps the final
                # halts final: a held residue marked to the bid can move the measured
                # drawdown by at most one minimum notional against risk_high.
                raise ValueError(
                    "resume requires a flat paper account: "
                    f"{account.inventory} base units are still held, so the exit is "
                    "incomplete; the halt stands until the liquidation completes"
                )
            regime = self.classifier.classify(frame.signals)
            if not self.scorer.score(frame.candidate, regime).eligible:
                raise ValueError("resume eligibility checks failed")
            day = timestamp(frame.quote.observed_at).date().isoformat()
            if account.day != day:
                account.day, account.day_start = day, account.last_equity
            if self._risk_action(account, frame.quote, frame.signals.emergency) != RiskAction.ALLOW:
                raise ValueError(
                    "resume blocked by current risk limits; baselines are preserved. A flat "
                    "account's equity cannot move, so its drawdown against risk_high is "
                    "frozen: a capital-exhaustion halt is final for this account and no "
                    "repeated resume can clear it; a hard-drawdown halt cannot be resumed by "
                    "hand and restarts automatically once its cool-off has passed (spec v1 "
                    "amendment 1). An emergency halt resumes once the emergency signal has "
                    "cleared and every other limit passes"
                )
            previous_halt = account.halt
            account.halt = ""
            account.halt_since, account.halt_category = "", ""
            account.episode_since, account.episode_count = "", 0
            account.liquidating = False
            # Flat with no orders: no grid remains, so clear its bounds and range timers.
            account.range_exit, account.range_exit_since = False, ""
            account.grid_lower = account.grid_upper = ZERO
            account.outside_seconds, account.outside_last = ZERO, ""
            account.down_since = ""  # a flat account has ended any variant A sequence
            self._pause(account, "operator resume: awaiting confirmed eligible data")
            account.last_observed = frame.quote.observed_at
            account.last_received = frame.quote.received_at
            self._mark(account, frame.quote, self.rules)
            return {
                "decision": "resume_pending",
                "previous_halt": previous_halt,
                "operator_reason": reason,
                "fills": [],
                "opened": [],
            }

        return self.store.transact(
            "control/resume/" + event_id, {"frame": frame.payload(), "reason": reason}, operation
        )

    def _apply_trend(self, account: Account, frame: Frame) -> str:
        """Variant A at a valid observation: return the gating state.

        A Down classification that became effective since the last applied signal
        starts a Down sequence (T0 = this observation) unless one is running. Resting
        buys are cancelled at once; resting sells stay. Only a usable signal acts: a
        stale or missing one gates as Unavailable and must neither start a sequence nor
        advance ``trend_day`` (Bob's F2 and C2 on PR #114).
        """
        signal, observed = frame.trend, frame.quote.observed_at
        state = effective_state(signal, observed)
        if signal is not None and state != UNAVAILABLE:
            if starts_down_sequence(signal, account.trend_day) and not account.down_since:
                account.down_since = observed
                self._cancel_buys(account)
            account.trend_day = max(account.trend_day, signal.day)
        return state

    def _settle(self, account: Account, quote: Quote) -> dict[str, Any]:
        # An unsellable residue is left out of the allocation base, which understates
        # profit; it is never counted as settled cash.
        # No orders is checked first, so _resolved here sees the whole inventory.
        if account.orders or not self._resolved(account, quote):
            raise ValueError("profit settlement requires no orders and no sellable inventory")
        active_before = account.cash - account.pending
        if active_before <= ZERO:
            raise ValueError("cannot settle an exhausted active account")
        # A held residue is excluded from the allocation base but IS in day_start,
        # risk_high and every later active-equity reading, so it must sit on both sides
        # of the rescaling ratio. Leaving it out of both depresses the baselines and can
        # move a later drawdown or daily-loss reading across its threshold. Marked exactly
        # as Account.equity marks it, since that is what populated those baselines: the
        # unrounded liquidation price, not the tick-floored price an order would use.
        marked_residue = (
            account.inventory
            * quote.bid
            * (ONE - self.rules.slippage_rate)
            * (ONE - self.rules.taker_fee)
        )
        account.settlement_count += 1
        state = ProfitVaultState(
            account.reserve_high,
            account.pending,
            account.secured,
            dict(account.confirmed_transfers),
        )
        allocation = self.vault.allocate(
            state, account.cash, positions_flat=True, orders_reconciled=True
        )
        account.pending, account.reserve_high = state.pending_reserve, state.active_high_water_mark
        # Proportional adjustment preserves returns even when reserve exceeds the
        # original capital; subtracting could make a baseline zero or negative.
        factor = (allocation.active_capital_after_allocation + marked_residue) / (
            active_before + marked_residue
        )
        account.day_start *= factor
        # The C1(b) reference is scaled in the same statement as risk_high, by the same
        # factor, and nowhere else (amendment 1).
        account.risk_high *= factor
        account.measure_high *= factor
        if allocation.transfer_due:
            self.vault.confirm_transfer(
                state, allocation.transfer_due, f"simulated-checkpoint/{account.settlement_count}"
            )
            account.cash -= allocation.transfer_due
            account.pending, account.secured = state.pending_reserve, state.secured_reserve
        account.confirmed_transfers = state.confirmed_transfers
        return asdict(allocation)

    def _cap(
        self,
        account: Account,
        quote: Quote,
        capped: list[dict[str, Any]],
        order_id: str,
        price: Decimal,
        quantity: Decimal,
    ) -> Decimal:
        """Variant B check for one new buy; records any resize or skip."""
        cap = self.policy.inventory_cap
        if cap is None:
            return quantity
        allowed = capped_quantity(account, quote, self.rules, cap, price, quantity)
        if allowed != quantity:
            capped.append(
                {
                    "order_id": order_id,
                    "price": price,
                    "requested": quantity,
                    "placed": allowed,
                    "action": "resized" if allowed else "skipped",
                }
            )
        return allowed

    def _open_grid(
        self,
        account: Account,
        frame: Frame,
        capped: list[dict[str, Any]],
        regime: RegimeAssessment | None = None,
    ) -> list[str]:
        rules, quote = self.rules, frame.quote
        spread = (quote.ask - quote.bid) / quote.ask
        cost = 2 * (rules.fee_rate + rules.slippage_rate) + spread
        budget = account.available_quote(rules) * D("0.8")
        # FTA resistance cap only applies in a ranging market. In trending markets
        # (BULL/BEAR) resistance zones cluster everywhere and the cap compresses all
        # sell levels to one price, preventing cycle completion. See backtest comparison
        # 2026-09-30 §8.4 for the diagnosis.
        fta = (
            frame.fta_resistance if regime is None or regime.regime == MarketRegime.RANGE else None
        )
        plan = self.builder.build(
            symbol=rules.symbol,
            fair_value=float(frame.fair_value),
            atr=float(frame.atr),
            capital=float(budget),
            min_notional=float(rules.minimum_notional * (ONE + rules.fee_rate)),
            round_trip_cost_pct=float(cost * 100),
            capital_utilization=1,
            fta_resistance=fta,
        )
        levels = tuple(floor_step(D(str(level)), rules.tick_size) for level in plan.levels)
        pairs = [
            (low, high)
            for low, high in zip(levels, levels[1:], strict=False)
            if low < min(quote.bid, frame.fair_value)
        ]
        if not pairs or len(set(levels)) != len(levels):
            raise GridNotViable("no distinct, passive buy levels after tick rounding")
        per_order = budget / len(pairs)
        orders: list[LimitOrder] = []
        for index, (low, high) in enumerate(pairs):
            quantity = floor_step(per_order / (low * (ONE + rules.fee_rate)), rules.quantity_step)
            if low * quantity < rules.minimum_notional:
                raise GridNotViable("rounded quantity cannot satisfy minimum notional")
            if (high - low) / low < cost * D(str(self.config.minimum_grid_cost_multiple)):
                raise GridNotViable("rounded spacing cannot cover conservative costs")
            orders.append(
                LimitOrder(
                    f"{quote.event_id}/buy/{index}",
                    "buy",
                    low,
                    quantity,
                    quantity,
                    target=high,
                    epoch=frame.epoch,
                )
            )
        if self.policy.inventory_cap is None:
            for order in orders:
                place(account, order, rules)
        else:
            orders = self._place_capped(account, quote, orders, capped)
        account.grid_lower, account.grid_upper = levels[0], levels[-1]
        account.outside_seconds, account.outside_last = ZERO, ""
        account.cycles += 1
        return [order.order_id for order in orders]

    def _place_capped(
        self,
        account: Account,
        quote: Quote,
        orders: list[LimitOrder],
        capped: list[dict[str, Any]],
    ) -> list[LimitOrder]:
        """Place buys from the highest price down. The first that does not fit whole is
        resized (or skipped below the minimum notional), and every lower level is skipped.
        """
        placed: list[LimitOrder] = []
        descending = sorted(orders, key=lambda order: order.price, reverse=True)
        for index, order in enumerate(descending):
            requested = order.quantity
            quantity = self._cap(account, quote, capped, order.order_id, order.price, requested)
            if quantity:
                order.quantity = order.remaining = quantity
                place(account, order, self.rules)
                placed.append(order)
            if quantity != requested:
                capped.extend(
                    {
                        "order_id": lower.order_id,
                        "price": lower.price,
                        "requested": lower.quantity,
                        "placed": ZERO,
                        "action": "skipped",
                    }
                    for lower in descending[index + 1 :]
                )
                break
        if not placed:
            raise GridNotViable("inventory cap leaves room for no buy level")
        return placed
