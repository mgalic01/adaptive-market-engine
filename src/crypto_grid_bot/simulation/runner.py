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
from crypto_grid_bot.simulation.execution import liquidate, match, place
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
    timestamp,
)
from crypto_grid_bot.simulation.store import StateStore, encode
from crypto_grid_bot.strategy.grid import GridBuilder, GridNotViable
from crypto_grid_bot.strategy.opportunity import OpportunityScorer
from crypto_grid_bot.strategy.regime import RegimeClassifier, RegimeThresholds

DEFAULT_CAPITAL = D("100")


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
    ) -> None:
        if config.mode != "paper":
            raise ValueError("only paper mode is supported")
        self.config, self.rules = config, rules
        identity = encode(
            {
                "schema": 1,
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
        self.classifier = RegimeClassifier(
            RegimeThresholds(
                bull=config.bull_threshold,
                bear=config.bear_threshold,
                range_score_limit=config.range_score_limit,
                range_adx_limit=config.range_adx_limit,
                minimum_confidence=config.minimum_confidence,
            )
        )
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
            reserve_fraction=D("0.5"), minimum_transfer_quote=D(str(config.minimum_transfer_quote))
        )

    def close(self) -> None:
        self.store.close()

    def process(self, frame: Frame) -> dict[str, Any]:
        return self.store.transact(
            frame.quote.event_id, frame.payload(), lambda account: self._step(account, frame)
        )

    @staticmethod
    def _halt(account: Account, reason: str, *, exit_requested: bool = False) -> None:
        account.orders.clear()
        account.halt = reason
        account.liquidating = account.liquidating or exit_requested

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
        if result.action != RiskAction.ALLOW:
            self._halt(
                account, "; ".join(result.reasons), exit_requested=result.action == RiskAction.EXIT
            )
        return result.action

    def _step(self, account: Account, frame: Frame) -> dict[str, Any]:
        quote = frame.quote
        report: dict[str, Any] = {
            "event_id": quote.event_id,
            "fills": [],
            "opened": [],
            "decision": "hold",
            "allocation": None,
        }
        try:
            quote.validate(self.rules)
            observed, received = timestamp(quote.observed_at), timestamp(quote.received_at)
            age = (received - observed).total_seconds()
            signal_age = (
                received - timestamp(frame.signals.observed_at.isoformat())
            ).total_seconds()
            if not 0 <= age <= self.config.maximum_data_age_seconds:
                raise ValueError("stale or future-dated quote")
            if not 0 <= signal_age <= self.config.maximum_data_age_seconds:
                raise ValueError("stale or future-dated strategy inputs")
            if account.last_observed and observed <= timestamp(account.last_observed):
                raise ValueError("out-of-order quote")
            if account.last_received and received < timestamp(account.last_received):
                raise ValueError("receive clock moved backwards")
            actual_spread_pct = (quote.ask - quote.bid) / quote.ask * 100
            if actual_spread_pct > D(str(self.config.maximum_spread_pct)):
                raise ValueError("observed spread exceeds the eligibility limit")
            nonnegative(frame.fair_value)
            nonnegative(frame.atr)
            if frame.candidate.symbol != self.rules.symbol:
                raise ValueError("candidate does not match configured market")
            regime = self.classifier.classify(frame.signals)
            score = self.scorer.score(frame.candidate, regime)
        except ValueError as exc:
            report["cancelled"] = list(account.orders)
            self._halt(account, str(exc))
            report.update(decision="halt", reason=str(exc))
            return report

        day = observed.date().isoformat()
        if account.day != day:
            # Previous close is the baseline, so an overnight gap is not erased.
            account.day, account.day_start = day, account.last_equity
        account.last_observed, account.last_received = quote.observed_at, quote.received_at
        account.risk_high = max(account.risk_high, account.equity(quote, self.rules))
        report.update(regime=regime.regime.value, opportunity_score=score.score)
        previous_orders = list(account.orders)
        action = self._risk_action(account, quote, frame.signals.emergency)
        if account.halt:
            report["cancelled"] = previous_orders
            if account.liquidating:
                report["fills"] = [asdict(fill) for fill in liquidate(account, quote, self.rules)]
            report.update(decision="halt", reason=account.halt)
        elif not score.eligible:
            # Reject risky conditions before matching old grid entries.
            report["cancelled"] = list(account.orders)
            self._halt(account, "; ".join(score.reasons))
            report.update(decision="halt", reason=account.halt)
        elif action == RiskAction.ALLOW:
            report["fills"] = [asdict(fill) for fill in match(account, quote, self.rules)]
            action = self._risk_action(account, quote, frame.signals.emergency)
            if action != RiskAction.ALLOW:
                # Liquidity used by fills cannot be reused for an exit in this event.
                report.update(decision="halt", reason=account.halt)
            else:
                if not account.orders and account.inventory == ZERO:
                    report["allocation"] = self._settle(account)
                    if frame.allow_new_grid:
                        try:
                            report["opened"] = self._open_grid(account, frame)
                            report["decision"] = "open_grid"
                        except GridNotViable as exc:
                            report.update(decision="cash", reason=str(exc))
        account.last_equity = account.equity(quote, self.rules)
        account.risk_high = max(account.risk_high, account.last_equity)
        report.update(
            active_equity=account.last_equity,
            pending_reserve=account.pending,
            secured_reserve=account.secured,
            cash=account.cash,
            inventory=account.inventory,
            fees=account.fees,
            open_orders=len(account.orders),
            total_equity=account.last_equity + account.pending + account.secured,
        )
        return report

    def _settle(self, account: Account) -> dict[str, Any]:
        state = ProfitVaultState(account.reserve_high, account.pending, account.secured)
        allocation = self.vault.allocate(
            state, account.cash, positions_flat=True, orders_reconciled=True
        )
        active_before = account.cash - account.pending
        account.pending, account.reserve_high = state.pending_reserve, state.active_high_water_mark
        # Proportional adjustment preserves returns even when reserve exceeds the
        # original capital; subtracting could make a baseline zero or negative.
        factor = allocation.active_capital_after_allocation / active_before
        account.day_start *= factor
        account.risk_high *= factor
        if allocation.transfer_due:
            self.vault.confirm_transfer(state, allocation.transfer_due, "simulated-checkpoint")
            account.cash -= allocation.transfer_due
            account.pending, account.secured = state.pending_reserve, state.secured_reserve
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
            (low, high) for low, high in zip(levels, levels[1:], strict=False) if low < quote.bid
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
        account.cycles += 1
        return [order.order_id for order in orders]
