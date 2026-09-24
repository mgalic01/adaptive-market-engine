"""Persistent, single-symbol offline strategy-to-fill loop."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from crypto_grid_bot.config import BotConfig
from crypto_grid_bot.domain import CandidateMetrics, MarketSignals, PortfolioSnapshot, RiskAction
from crypto_grid_bot.portfolio.profit_vault import ProfitVault, ProfitVaultState
from crypto_grid_bot.risk.engine import RiskEngine
from crypto_grid_bot.simulation.execution import liquidate, match, place, reduce_unreserved
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
from crypto_grid_bot.strategy.grid import GridBuilder, GridNotViable
from crypto_grid_bot.strategy.opportunity import OpportunityScorer
from crypto_grid_bot.strategy.regime import RegimeClassifier, thresholds_from_config

DEFAULT_CAPITAL = D("100")
SCHEMA = 3


class TransientFrame(ValueError):
    """Unusable observation: cancel entries and wait for confirmed fresh recovery."""


@dataclass(frozen=True)
class SimulationPolicy:
    recovery_frames: int = 2
    # Observed outside-range time (valid frames only) before exiting a grid to cash.
    outside_range_seconds: int = 21600
    # After a range exit, allow a new grid centred on current fair value once this
    # cooldown has passed and eligibility is reconfirmed. False = wait in cash until
    # price re-enters the old band (an explicit, documented terminal-until-return state).
    recenter_after_exit: bool = True
    recenter_cooldown_seconds: int = 86400

    def __post_init__(self) -> None:
        if type(self.recovery_frames) is not int or not 2 <= self.recovery_frames <= 100:
            raise ValueError("recovery requires 2-100 distinct eligible frames")
        if type(self.outside_range_seconds) is not int or self.outside_range_seconds <= 0:
            raise ValueError("outside-range timeout must be a positive integer")
        if type(self.recenter_after_exit) is not bool:
            raise ValueError("recenter_after_exit must be a boolean")
        if type(self.recenter_cooldown_seconds) is not int or self.recenter_cooldown_seconds <= 0:
            raise ValueError("recentering cooldown must be a positive integer")


@dataclass(frozen=True)
class Frame:
    quote: Quote
    signals: MarketSignals
    candidate: CandidateMetrics
    fair_value: Decimal
    atr: Decimal
    allow_new_grid: bool = True

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["signals"]["observed_at"] = self.signals.observed_at.isoformat()
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
        identity = encode(
            {
                "schema": SCHEMA,
                "policy": asdict(self.policy),
                "config": asdict(config),
                "rules": asdict(rules),
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

    @staticmethod
    def _cancel_buys(account: Account) -> list[str]:
        cancelled = [key for key, order in account.orders.items() if order.side == "buy"]
        for key in cancelled:
            del account.orders[key]
        return cancelled

    @staticmethod
    def _halt(account: Account, reason: str, *, exit_requested: bool = False) -> None:
        account.orders.clear()
        account.halt = reason
        account.pause = ""
        account.recovery_count = 0
        account.liquidating = account.liquidating or exit_requested

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
        if result.action == RiskAction.EXIT:
            self._halt(account, "; ".join(result.reasons), exit_requested=True)
        elif result.action != RiskAction.ALLOW and not account.halt:
            self._pause(account, "; ".join(result.reasons))
        return result.action

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

    def _track_range(self, account: Account, quote: Quote) -> None:
        """Accumulate observed outside-range time; call before updating last_observed."""
        if not account.grid_lower or account.range_exit:
            return
        observed = quote.observed_at
        if account.grid_lower <= quote.bid <= account.grid_upper:
            account.outside_seconds, account.outside_last = ZERO, ""
            return
        # Count only intervals bracketed by two consecutive valid outside observations
        # within the freshness limit. Gaps do not prove time outside the range, but they
        # do not erase time already observed; only a valid inside frame resets the clock.
        if account.outside_last and account.outside_last == account.last_observed:
            elapsed = seconds_between(account.outside_last, observed)
            if elapsed <= self.config.maximum_data_age_seconds:
                account.outside_seconds += elapsed
        account.outside_last = observed
        if account.outside_seconds >= self.policy.outside_range_seconds:
            account.orders.clear()
            account.range_exit = True
            account.range_exit_since = observed
            account.outside_seconds, account.outside_last = ZERO, ""
            self._pause(account, "outside-range timeout: exit to cash")

    @staticmethod
    def _mark(account: Account, quote: Quote, rules: MarketRules) -> None:
        account.last_equity = account.equity(quote, rules)
        account.risk_high = max(account.risk_high, account.last_equity)

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
        try:
            self._validate_frame(account, frame)
            regime = self.classifier.classify(frame.signals)
            score = self.scorer.score(frame.candidate, regime)
        except TransientFrame as exc:
            # Unusable data pauses the outside-range clock but never erases time already
            # observed outside; otherwise a flapping feed could postpone the exit forever.
            if not account.halt:
                self._pause(account, str(exc))
            report.update(
                decision="halt" if account.halt else "pause",
                reason=account.halt or account.pause,
                cancelled=sorted(previous_orders - account.orders.keys()),
            )
            return report  # No marking, fills, liquidation or recovery on unusable data.
        except ValueError as exc:
            self._halt(account, str(exc))
            report.update(decision="halt", reason=str(exc), cancelled=sorted(previous_orders))
            return report

        observed = timestamp(quote.observed_at)
        day = observed.date().isoformat()
        if account.day != day:
            account.day, account.day_start = day, account.last_equity
        self._track_range(account, quote)
        # A gap or a new ineligible frame breaks the recovery streak.
        if (
            account.last_observed
            and (observed - timestamp(account.last_observed)).total_seconds()
            > self.config.maximum_data_age_seconds
        ):
            account.recovery_count = 0
        account.last_observed, account.last_received = quote.observed_at, quote.received_at
        self._mark(account, quote, self.rules)
        report.update(regime=regime.regime.value, opportunity_score=score.score)
        action = self._risk_action(account, quote, frame.signals.emergency)
        if account.halt:
            if account.liquidating:
                report["fills"] = [asdict(fill) for fill in liquidate(account, quote, self.rules)]
            report.update(decision="halt", reason=account.halt)
        elif account.range_exit:
            report["fills"] = [asdict(fill) for fill in liquidate(account, quote, self.rules)]
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
            if (
                account.inventory == ZERO
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
            report["fills"] = [
                asdict(fill)
                for fill in match(
                    account,
                    quote,
                    self.rules,
                    recycle=not account.pause and not account.draining and frame.allow_new_grid,
                )
            ]
            # Cancelled partial buys can leave unpaired inventory. Exit it using only
            # remaining bid capacity, never inventory reserved by an existing sell.
            if account.draining:
                consumed = sum(
                    (D(fill["quantity"]) for fill in report["fills"] if fill["side"] == "sell"),
                    ZERO,
                )
                report["fills"].extend(
                    asdict(fill)
                    for fill in reduce_unreserved(
                        account,
                        quote,
                        self.rules,
                        consumed=consumed,
                    )
                )

        # Recheck risk after any fills, but never reuse this event's liquidity for an exit.
        if report["fills"]:
            self._risk_action(account, quote, frame.signals.emergency)
        if not account.halt and account.inventory == ZERO:
            # A flat account is a safe harvest point even with unused deeper buys.
            # Do this only after sells, draining, or when all orders are already gone.
            sold = any(fill["side"] == "sell" for fill in report["fills"])
            if sold or account.draining or not account.orders:
                self._cancel_buys(account)
                if account.cash - account.pending <= ZERO:
                    self._halt(account, "active capital exhausted")
                else:
                    report["allocation"] = self._settle(account)
                    account.draining = False
                    if not account.pause and not account.range_exit and frame.allow_new_grid:
                        try:
                            report["opened"] = self._open_grid(account, frame)
                            report["decision"] = "open_grid"
                        except GridNotViable as exc:
                            report.update(decision="cash", reason=str(exc))
        if account.halt:
            report.update(decision="halt", reason=account.halt)
        elif account.pause:
            report.update(decision="pause", reason=account.pause)
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
            if not account.halt or account.orders or account.inventory != ZERO:
                raise ValueError("resume requires a halted, reconciled flat paper account")
            regime = self.classifier.classify(frame.signals)
            if not self.scorer.score(frame.candidate, regime).eligible:
                raise ValueError("resume eligibility checks failed")
            day = timestamp(frame.quote.observed_at).date().isoformat()
            if account.day != day:
                account.day, account.day_start = day, account.last_equity
            if self._risk_action(account, frame.quote, frame.signals.emergency) != RiskAction.ALLOW:
                raise ValueError("resume blocked by current risk limits; baselines are preserved")
            previous_halt = account.halt
            account.halt = ""
            account.liquidating = False
            # Flat with no orders: no grid remains, so clear its bounds and range timers.
            account.range_exit, account.range_exit_since = False, ""
            account.grid_lower = account.grid_upper = ZERO
            account.outside_seconds, account.outside_last = ZERO, ""
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

    def _settle(self, account: Account) -> dict[str, Any]:
        if account.orders or account.inventory != ZERO:
            raise ValueError("profit settlement requires flat inventory and no orders")
        active_before = account.cash - account.pending
        if active_before <= ZERO:
            raise ValueError("cannot settle an exhausted active account")
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
        factor = allocation.active_capital_after_allocation / active_before
        account.day_start *= factor
        account.risk_high *= factor
        if allocation.transfer_due:
            self.vault.confirm_transfer(
                state, allocation.transfer_due, f"simulated-checkpoint/{account.settlement_count}"
            )
            account.cash -= allocation.transfer_due
            account.pending, account.secured = state.pending_reserve, state.secured_reserve
        account.confirmed_transfers = state.confirmed_transfers
        return asdict(allocation)

    def _open_grid(self, account: Account, frame: Frame) -> list[str]:
        rules, quote = self.rules, frame.quote
        spread = (quote.ask - quote.bid) / quote.ask
        cost = 2 * (rules.fee_rate + rules.slippage_rate) + spread
        budget = account.available_quote(rules) * D("0.8")
        plan = self.builder.build(
            symbol=rules.symbol,
            fair_value=float(frame.fair_value),
            atr=float(frame.atr),
            capital=float(budget),
            min_notional=float(rules.minimum_notional * (ONE + rules.fee_rate)),
            round_trip_cost_pct=float(cost * 100),
            capital_utilization=1,
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
                    f"{quote.event_id}/buy/{index}", "buy", low, quantity, quantity, target=high
                )
            )
        for order in orders:
            place(account, order, rules)
        account.grid_lower, account.grid_upper = levels[0], levels[-1]
        account.outside_seconds, account.outside_last = ZERO, ""
        account.cycles += 1
        return [order.order_id for order in orders]
