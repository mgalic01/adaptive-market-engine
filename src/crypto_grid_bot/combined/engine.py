"""Serialized wallet/reservation/recovery kernel; no market fetching or live orders.

The replay adapter supplies qualified intents and explicit settled executions. It
owns OHLC sequencing and source identities. This kernel never invents an execution
to satisfy a close obligation. Funding is booked before reductions, then increases.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Context, Decimal, localcontext
from threading import RLock

from crypto_grid_bot.combined.account import (
    AccountSnapshot,
    CombinedAccount,
    FillEvent,
    FundingEvent,
    PositionSnapshot,
)
from crypto_grid_bot.combined.execution import VenueRules, executable_reduction, futures_margin
from crypto_grid_bot.combined.recovery import Recovery, RecoveryDecision
from crypto_grid_bot.combined.risk import Admission, Exposure, Intent, PortfolioRisk, PortfolioView
from crypto_grid_bot.combined.routing import Qualification


@dataclass(frozen=True, slots=True)
class Quote:
    price: Decimal
    timestamp_ms: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.price, Decimal)
            or not self.price.is_finite()
            or not 0 < self.price <= Decimal("1e36")
            or type(self.timestamp_ms) is not int
            or self.timestamp_ms < 0
        ):
            raise ValueError("invalid quote")


@dataclass(frozen=True, slots=True)
class EngineSnapshot:
    timestamp_ms: int
    account: AccountSnapshot
    recovery: RecoveryDecision
    close_required: tuple[str, ...]
    reasons: tuple[str, ...]
    liquidation: bool
    available_cash: Decimal


class PortfolioEngine:
    """One account and one event lock, including acknowledged reservation transfers."""

    def __init__(self, initial_cash: Decimal, *, automatic_recovery: bool = True) -> None:
        if type(automatic_recovery) is not bool:
            raise ValueError("automatic_recovery must be Boolean")
        self._automatic_recovery = automatic_recovery
        self._account = CombinedAccount(initial_cash)
        self._risk = PortfolioRisk()
        self._recovery = Recovery()
        self._lock = RLock()
        self._clock = -1
        self._quotes: dict[str, Quote] = {}
        self._orders: dict[str, tuple[Intent, Decimal]] = {}
        self._known_orders: dict[str, tuple[Intent, Decimal]] = {}
        self._stops: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
        self._close: set[str] = set()
        self._close_reasons: dict[str, set[str]] = {}
        self._liquidation = False
        self._integrity_failure = False
        self._batches: dict[str, tuple[object, EngineSnapshot]] = {}
        self._fills: dict[str, FillEvent] = {}
        self._recovery.update(0, initial_cash, True, False, True)

    @property
    def reservations(self) -> tuple[Admission, ...]:
        return self._risk.reservations

    def cancel(self, intent_id: str) -> None:
        """Acknowledged local-simulator cancellation, never a live cancellation request."""
        with self._lock:
            self._risk.release(intent_id, acknowledged=True)
            self._orders.pop(intent_id, None)

    def _protective_owner(self, symbol: str, owner: str, side: int) -> PositionSnapshot | None:
        if type(side) is not int or side not in {-1, 1}:
            raise ValueError("held side must be exactly +1 or -1")
        position = next((p for p in self._account.snapshot().positions if p.symbol == symbol), None)
        pending = [i for i, _ in self._orders.values() if i.symbol == symbol]
        if position is None and not pending:
            raise ValueError("asset has no held or pending owner")
        if (
            position is not None
            and (position.owner != owner or (1 if position.quantity > 0 else -1) != side)
        ) or any(i.owner != owner or i.side != side for i in pending):
            raise ValueError("protective request differs from asset owner or held side")
        return position

    def request_close(self, symbol: str, owner: str, side: int, *, reason: str) -> None:
        """Persist a close obligation and cancel this asset's simulator increases.

        Caller supplies the owning strategy and HELD side, not the exit side.
        Repeated requests are idempotent while owned. Missing prices and partial
        fills cannot clear the obligation; verified dust stays valued and owned.
        Only settled reductions change inventory. A pending-only request cancels
        its order; any subsequent actual late fill is still booked and closed.
        """
        with self._lock:
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("nonempty protective close reason required")
            position = self._protective_owner(symbol, owner, side)
            for key, (intent, _) in tuple(self._orders.items()):
                if intent.symbol == symbol:
                    self.cancel(key)
            if position is not None:
                self._close.add(symbol)
                self._close_reasons.setdefault(symbol, set()).add(reason)

    def tighten_stop(self, symbol: str, owner: str, side: int, stop: Decimal) -> None:
        """Accept an externally computed completed-information stop, never widen it.

        Replay verifies ATR/activation and old-stop OHLC ordering before calling.
        It first observes the current completed close. A stop through that fresh
        mark requests a close at the next available execution, never a fictional fill.
        """
        with self._lock:
            if (
                not isinstance(stop, Decimal)
                or not stop.is_finite()
                or not 0 < stop <= Decimal("1e36")
            ):
                raise ValueError("finite positive bounded stop required")
            position = self._protective_owner(symbol, owner, side)
            if position is None:
                raise ValueError("stop tightening requires held inventory")
            prior, fee, slip = self._stops[symbol]
            if (stop < prior) if side == 1 else (stop > prior):
                raise ValueError("protective stop cannot widen")
            self._stops[symbol] = (stop, fee, slip)
            quote = self._quotes.get(symbol)
            if (
                quote is not None
                and self._fresh(symbol, self._clock)
                and ((quote.price <= stop) if side == 1 else (quote.price >= stop))
            ):
                self.request_close(symbol, owner, side, reason="tightened_stop_crossed")

    def _prices(self, now: int, quotes: Mapping[str, Quote]) -> dict[str, Decimal]:
        if type(now) is not int or not 0 <= now < 1_735_689_600_000 or now < self._clock:
            raise ValueError("chronological development timestamp required")
        for symbol, quote in quotes.items():
            if not isinstance(quote, Quote) or quote.timestamp_ms > now:
                raise ValueError("future or malformed quote")
            prior = self._quotes.get(symbol)
            if prior is not None and quote.timestamp_ms < prior.timestamp_ms:
                raise ValueError("quote timestamp moved backwards")
        self._quotes.update(quotes)
        self._clock = now
        return {symbol: quote.price for symbol, quote in self._quotes.items()}

    def _fresh(self, symbol: str, now: int) -> bool:
        quote = self._quotes.get(symbol)
        return quote is not None and 0 <= now - quote.timestamp_ms <= 3_600_000

    def _view(
        self, account: AccountSnapshot, fraction: Decimal, groups: tuple[tuple[str, str], ...]
    ) -> PortfolioView:
        mapping = dict(groups)
        exposures = []
        for position in account.positions:
            stop, fee, slip = self._stops[position.symbol]
            side = 1 if position.quantity > 0 else -1
            exit_price = stop * (1 - side * slip)
            unit_risk = max(Decimal(0), side * (position.mark - exit_price)) + exit_price * fee
            exposures.append(
                Exposure(
                    position.symbol,
                    position.owner,
                    abs(position.quantity) * position.mark,
                    abs(position.quantity) * unit_risk,
                    mapping.get(position.symbol, "unknown"),
                )
            )
        return PortfolioView(
            account.equity,
            max(Decimal(0), account.free_cash - self._exit_reserve(account)),
            tuple(exposures),
            fraction,
            groups,
            max(Decimal(0), futures_margin(account.free_cash, account.positions).backing),
        )

    def _exit_reserve(self, account: AccountSnapshot) -> Decimal:
        reserve = Decimal(0)
        for position in account.positions:
            stop, fee, slip = self._stops[position.symbol]
            side = 1 if position.quantity > 0 else -1
            reserve += abs(position.quantity) * (stop * slip + stop * (1 - side * slip) * fee)
        return reserve

    def observe(
        self,
        timestamp_ms: int,
        quotes: Mapping[str, Quote],
        rules: Mapping[str, VenueRules],
        *,
        qualified: bool = False,
    ) -> EngineSnapshot:
        with self._lock, localcontext(Context(prec=60)):
            prices = self._prices(timestamp_ms, quotes)
            account = self._account.snapshot(prices)
            reasons: list[str] = []
            flat = not self._orders
            for position in account.positions:
                if not self._fresh(position.symbol, timestamp_ms) or position.symbol not in rules:
                    flat = False
                    self._close.add(position.symbol)
                    reasons.append("stale_position_or_missing_filters")
                elif executable_reduction(
                    abs(position.quantity), position.mark, rules[position.symbol]
                ).quantity:
                    flat = False
            margin = futures_margin(account.free_cash, account.positions)
            if margin.maintenance > 0 and margin.backing <= margin.maintenance:
                self._liquidation = True
                reasons.append("simulated_liquidation")
            if margin.maintenance > 0 and margin.backing < 3 * margin.maintenance:
                self._close.update(p.symbol for p in account.positions if p.venue == "futures")
                reasons.append("margin_reduction")
            recovery = self._recovery.update(
                timestamp_ms,
                account.equity,
                flat,
                qualified and self._automatic_recovery,
                account.integrity_ok and not self._liquidation and not self._integrity_failure,
            )
            if recovery.close or recovery.risk_fraction == 0:
                for key in tuple(self._orders):
                    self.cancel(key)
            if recovery.close:
                self._close.update(p.symbol for p in account.positions)
                reasons.append(recovery.reason)
            held = {p.symbol for p in account.positions}
            self._close.intersection_update(held)
            self._close_reasons = {
                symbol: why for symbol, why in self._close_reasons.items() if symbol in held
            }
            reasons.extend(
                sorted({why for values in self._close_reasons.values() for why in values})
            )
            if self._integrity_failure:
                reasons.append("execution_integrity_failure")
            return EngineSnapshot(
                timestamp_ms,
                account,
                recovery,
                tuple(sorted(self._close)),
                tuple(dict.fromkeys(reasons)),
                self._liquidation,
                max(
                    Decimal(0),
                    account.free_cash
                    - self._exit_reserve(account)
                    - sum((a.cash for a in self.reservations), Decimal(0)),
                ),
            )

    def preview(
        self,
        intent: Intent,
        qualification: Qualification,
        quotes: Mapping[str, Quote],
        rules: Mapping[str, VenueRules],
        groups: tuple[tuple[str, str], ...] = (),
        *,
        candidate_quote: Quote | None = None,
        candidate_rules: VenueRules | None = None,
    ) -> Admission:
        """Check normal admissible size without reservation or recovery promotion.

        This is not pure: fresh observations still update protective/recovery state
        and can cancel unsafe pending orders. It never spends cash or qualifies a
        restart. Submit repeats these checks under the same engine event lock.
        Explicit candidate quote/filters are venue-specific and never overwrite
        the authoritative held-position marks/filters supplied in the mappings.
        """
        with self._lock, localcontext(Context(prec=60)):
            now = qualification.decision_ms
            if intent.intent_id in self._known_orders:
                if self._known_orders[intent.intent_id][0] != intent:
                    raise ValueError("conflicting intent ID")
                return Admission(intent.intent_id, False, "intent_already_processed")
            if (
                qualification.symbol != intent.symbol
                or qualification.owner != intent.owner
                or qualification.side != intent.side
                or qualification.risk_multiplier != intent.risk_multiplier
            ):
                raise ValueError("qualification and intent differ")
            state = self.observe(now, quotes, rules)

            def refuse(reason: str) -> Admission:
                return Admission(intent.intent_id, False, reason)

            if not qualification.allowed or qualification.reasons:
                return refuse("unqualified")
            if candidate_quote is not None and any(
                p.symbol == intent.symbol for p in state.account.positions
            ):
                return refuse("asset_owned")
            quote = (
                candidate_quote if candidate_quote is not None else self._quotes.get(intent.symbol)
            )
            if (
                not isinstance(quote, Quote) or not 0 <= now - quote.timestamp_ms <= 3_600_000
            ) or any(not self._fresh(p.symbol, now) for p in state.account.positions):
                return refuse("stale_or_missing_quote")
            rule = candidate_rules if candidate_rules is not None else rules.get(intent.symbol)
            if rule is None:
                return refuse("filters_unavailable")
            if not isinstance(rule, VenueRules):
                raise ValueError("invalid candidate venue rules")
            if (
                intent.price != quote.price
                or intent.step != rule.step
                or intent.min_quantity != rule.min_qty
                or intent.max_quantity != rule.max_qty
                or intent.min_notional != rule.min_notional
            ):
                raise ValueError("intent differs from quote or venue rules")
            if (
                any(
                    p.symbol in self._close
                    and (
                        not self._fresh(p.symbol, now)
                        or p.symbol not in rules
                        or executable_reduction(abs(p.quantity), p.mark, rules[p.symbol]).quantity
                        > 0
                    )
                    for p in state.account.positions
                )
                or not state.account.integrity_ok
                or self._liquidation
                or self._integrity_failure
            ):
                return refuse("protective_reduction_pending")
            return self._risk.preview(intent, self._view(state.account, Decimal(1), groups))

    def submit(
        self,
        intent: Intent,
        qualification: Qualification,
        quotes: Mapping[str, Quote],
        rules: Mapping[str, VenueRules],
        groups: tuple[tuple[str, str], ...] = (),
        *,
        candidate_quote: Quote | None = None,
        candidate_rules: VenueRules | None = None,
    ) -> Admission:
        with self._lock, localcontext(Context(prec=60)):
            normal = self.preview(
                intent,
                qualification,
                quotes,
                rules,
                groups,
                candidate_quote=candidate_quote,
                candidate_rules=candidate_rules,
            )
            if not normal.accepted:
                return normal
            state = self.observe(qualification.decision_ms, quotes, rules, qualified=True)
            answer = self._risk.reserve(
                intent, self._view(state.account, state.recovery.risk_fraction, groups)
            )
            if answer.accepted and intent.intent_id not in self._orders:
                self._orders[intent.intent_id] = (intent, answer.quantity)
                self._known_orders[intent.intent_id] = (intent, answer.quantity)
            return answer

    def settle(
        self,
        batch_id: str,
        timestamp_ms: int,
        quotes: Mapping[str, Quote],
        rules: Mapping[str, VenueRules],
        *,
        funding: tuple[FundingEvent, ...] = (),
        reductions: tuple[FillEvent, ...] = (),
        increases: tuple[tuple[str, FillEvent], ...] = (),
    ) -> EngineSnapshot:
        with self._lock:
            try:
                return self._settle(
                    batch_id,
                    timestamp_ms,
                    quotes,
                    rules,
                    funding=funding,
                    reductions=reductions,
                    increases=increases,
                )
            except (ValueError, ArithmeticError):
                self._integrity_failure = True
                for key in tuple(self._orders):
                    self.cancel(key)
                raise

    def _settle(
        self,
        batch_id: str,
        timestamp_ms: int,
        quotes: Mapping[str, Quote],
        rules: Mapping[str, VenueRules],
        *,
        funding: tuple[FundingEvent, ...],
        reductions: tuple[FillEvent, ...],
        increases: tuple[tuple[str, FillEvent], ...],
    ) -> EngineSnapshot:
        with self._lock, localcontext(Context(prec=60)):
            identity = (
                timestamp_ms,
                tuple(sorted(quotes.items())),
                tuple(sorted(rules.items())),
                funding,
                reductions,
                increases,
            )
            if batch_id in self._batches:
                old, result = self._batches[batch_id]
                if old != identity:
                    raise ValueError("conflicting duplicate settlement")
                return result
            all_events: tuple[FundingEvent | FillEvent, ...] = (
                *funding,
                *reductions,
                *(e for _, e in increases),
            )
            if not batch_id or any(e.timestamp_ms != timestamp_ms for e in all_events):
                raise ValueError("settlement identity/time mismatch")
            self.observe(timestamp_ms, quotes, rules)
            for payment in funding:
                self._account.apply(payment)
                self.observe(timestamp_ms, quotes, rules)
            for event in reductions:
                if event.event_id in self._fills:
                    if self._fills[event.event_id] != event:
                        raise ValueError("conflicting fill ID")
                    continue
                before = next(
                    (p for p in self._account.snapshot().positions if p.symbol == event.symbol),
                    None,
                )
                if before is None or before.quantity * event.side >= 0:
                    raise ValueError("reduction must reduce held inventory")
                self._account.apply(event)
                self._fills[event.event_id] = event
                self.observe(timestamp_ms, quotes, rules)
            breached = False
            for key, event in increases:
                if event.event_id in self._fills:
                    if self._fills[event.event_id] != event:
                        raise ValueError("conflicting fill ID")
                    continue
                if key not in self._known_orders:
                    raise ValueError("fill has no recorded admission")
                intent, remaining = self._known_orders[key]
                was_pending = key in self._orders
                if (event.symbol, event.owner, event.venue, event.side) != (
                    intent.symbol,
                    intent.owner,
                    intent.venue,
                    intent.side,
                ) or event.quantity > remaining:
                    raise ValueError("fill differs from pending order")
                already_held = any(
                    p.symbol == event.symbol for p in self._account.snapshot().positions
                )
                self._account.apply(event)
                stop = intent.stop
                if already_held:
                    prior_stop = self._stops[event.symbol][0]
                    stop = max(stop, prior_stop) if intent.side == 1 else min(stop, prior_stop)
                self._stops[event.symbol] = (stop, intent.fee_rate, intent.slippage_rate)
                remaining -= event.quantity
                self._known_orders[key] = (intent, remaining)
                if was_pending:
                    self._risk.acknowledge_remaining(key, remaining, acknowledged=True)
                if remaining and was_pending:
                    self._orders[key] = (intent, remaining)
                else:
                    self._orders.pop(key, None)
                self._fills[event.event_id] = event
                adverse = intent.price * (1 + intent.side * intent.slippage_rate)
                if (
                    not was_pending
                    or intent.side * (event.price - adverse) > 0
                    or event.fee > event.quantity * event.price * intent.fee_rate
                ):
                    self._close.add(event.symbol)
                    breached = True
                self.observe(timestamp_ms, quotes, rules)
            result = self.observe(timestamp_ms, quotes, rules)
            if breached:
                result = replace(result, reasons=(*result.reasons, "post_fill_risk_breach"))
            self._batches[batch_id] = (identity, result)
            return result
