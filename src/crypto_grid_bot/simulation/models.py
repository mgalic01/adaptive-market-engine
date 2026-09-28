"""Exact balances and explicit assumptions for the single-market simulator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Any

D = Decimal
ZERO = D("0")
ONE = D("1")


def decimal(value: str) -> Decimal:
    number = D(value)
    if not number.is_finite() or abs(number) > D("1e18"):
        raise ValueError("number must be finite and bounded")
    return number


def nonnegative(value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or not ZERO <= value <= D("1e18"):
        raise ValueError("amount must be a finite, bounded, non-negative Decimal")


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamps must include timezone information")
    return result.astimezone(UTC)


def seconds_between(start: str, end: str) -> Decimal:
    """Exact elapsed seconds between two ISO timestamps (negative if reversed)."""
    delta = timestamp(end) - timestamp(start)
    return D(delta.days * 86400 + delta.seconds) + D(delta.microseconds) / D(1_000_000)


@dataclass(frozen=True)
class MarketRules:
    symbol: str = "DEMOUSDT"
    tick_size: Decimal = D("0.00001")
    quantity_step: Decimal = D("1")
    minimum_notional: Decimal = D("5")
    # Maker fee: charged when a resting limit order fills.
    fee_rate: Decimal = D("0.001")
    slippage_rate: Decimal = D("0.0005")
    participation: Decimal = D("0.10")
    # Taker fee for marketable exits and liquidation; None means equal to fee_rate.
    taker_fee_rate: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.upper():
            raise ValueError("a non-empty uppercase symbol is required")
        for value in (self.tick_size, self.quantity_step, self.minimum_notional):
            nonnegative(value)
            if value == ZERO:
                raise ValueError("market filters must be positive")
        for value in (self.fee_rate, self.slippage_rate, self.taker_fee):
            nonnegative(value)
            if value >= D("0.1"):
                raise ValueError("fee and slippage rates must be below 10%")
        nonnegative(self.participation)
        if not ZERO < self.participation <= ONE:
            raise ValueError("participation must be between zero and one")

    @property
    def taker_fee(self) -> Decimal:
        return self.fee_rate if self.taker_fee_rate is None else self.taker_fee_rate

    def identity(self) -> dict[str, Any]:
        """Persisted form; omits an unset taker fee so older identities still match."""
        value = asdict(self)
        if self.taker_fee_rate is None:
            del value["taker_fee_rate"]
        return value


@dataclass(frozen=True)
class Quote:
    event_id: str
    symbol: str
    observed_at: str
    received_at: str
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal

    def validate(self, rules: MarketRules) -> None:
        if not self.event_id.strip() or self.symbol != rules.symbol:
            raise ValueError("invalid event ID or unexpected market")
        for value in (self.bid, self.ask, self.bid_size, self.ask_size):
            nonnegative(value)
        if not ZERO < self.bid <= self.ask:
            raise ValueError("quote must have positive uncrossed prices")
        timestamp(self.observed_at)
        timestamp(self.received_at)


@dataclass
class LimitOrder:
    order_id: str
    side: str
    price: Decimal
    quantity: Decimal
    remaining: Decimal
    target: Decimal | None = None
    reentry: Decimal | None = None
    # Replay bar label: an order cannot fill during the bar (epoch) that created it.
    epoch: str | None = None


@dataclass(frozen=True)
class Fill:
    order_id: str
    side: str
    price: Decimal
    quantity: Decimal
    fee: Decimal


# Spec v1 amendment 1: the four halt categories, set where a halt is raised, never
# inferred from its text. Only ``drawdown`` restarts automatically.
HALT_CATEGORIES = ("", "drawdown", "emergency", "exhaustion", "integrity")


@dataclass
class Account:
    initial_cash: Decimal
    cash: Decimal
    reserve_high: Decimal
    risk_high: Decimal
    day_start: Decimal
    inventory: Decimal = ZERO
    pending: Decimal = ZERO
    secured: Decimal = ZERO
    fees: Decimal = ZERO
    last_equity: Decimal = ZERO
    day: str = ""
    last_observed: str = ""
    last_received: str = ""
    halt: str = ""
    liquidating: bool = False
    pause: str = ""
    recovery_count: int = 0
    draining: bool = False
    range_exit: bool = False
    range_exit_since: str = ""
    outside_seconds: Decimal = ZERO
    outside_last: str = ""
    grid_lower: Decimal = ZERO
    grid_upper: Decimal = ZERO
    settlement_count: int = 0
    confirmed_transfers: dict[str, Decimal] = field(default_factory=dict)
    cycles: int = 0
    fill_count: int = 0
    orders: dict[str, LimitOrder] = field(default_factory=dict)
    # Variant A (spec v1, section 3 A) only; empty and omitted from saved state when off.
    # The latest daily-bar day whose trend signal this account has applied.
    trend_day: str = ""
    # T0 of the running Down sequence (its effective observation); empty when none runs.
    down_since: str = ""
    # Spec v1 amendment 1 (drawdown recovery), schema 6.
    # The C1(b) measurement reference: starts with the initial active capital, rises at
    # every mark and is scaled at every settlement exactly as ``risk_high`` is, but a
    # rebase or an automatic restart never changes it. Equal to ``risk_high`` in any run
    # without one.
    measure_high: Decimal = ZERO
    # The halt instance: its start (``observed_at``) and category, captured once on the
    # transition from not halted to halted and never changed by later halt calls.
    halt_since: str = ""
    halt_category: str = ""
    # The open soft-drawdown episode: its start, and its consecutive confirmations.
    episode_since: str = ""
    episode_count: int = 0

    @classmethod
    def start(cls, cash: Decimal) -> Account:
        nonnegative(cash)
        if cash <= ZERO:
            raise ValueError("initial capital must be positive")
        return cls(cash, cash, cash, cash, cash, last_equity=cash, measure_high=cash)

    def reserved_quote(self, rules: MarketRules) -> Decimal:
        return sum(
            (
                order.price * order.remaining * (ONE + rules.fee_rate)
                for order in self.orders.values()
                if order.side == "buy"
            ),
            ZERO,
        )

    def reserved_base(self) -> Decimal:
        return sum(
            (order.remaining for order in self.orders.values() if order.side == "sell"), ZERO
        )

    def available_quote(self, rules: MarketRules) -> Decimal:
        return self.cash - self.pending - self.reserved_quote(rules)

    def equity(self, quote: Quote, rules: MarketRules) -> Decimal:
        liquidation_price = quote.bid * (ONE - rules.slippage_rate)
        return (
            self.cash - self.pending + self.inventory * liquidation_price * (ONE - rules.taker_fee)
        )

    def validate(self, rules: MarketRules) -> None:
        for name in (
            "initial_cash",
            "cash",
            "inventory",
            "pending",
            "secured",
            "fees",
            "reserve_high",
            "risk_high",
            "day_start",
            "last_equity",
            "grid_lower",
            "grid_upper",
            "outside_seconds",
            "measure_high",
        ):
            nonnegative(getattr(self, name))
        if (
            min(
                self.initial_cash,
                self.reserve_high,
                self.risk_high,
                self.day_start,
                self.measure_high,
            )
            <= ZERO
        ):
            raise ValueError("account baselines must be positive")
        if self.halt_category not in HALT_CATEGORIES or bool(self.halt) != bool(self.halt_category):
            raise ValueError("halt category does not match the halt")
        if self.halt_since and not self.halt:
            raise ValueError("halt start without a halt")
        if self.episode_since and self.halt:
            raise ValueError("a drawdown episode cannot stay open during a halt")
        if self.episode_count and not self.episode_since:
            raise ValueError("episode confirmations without an open episode")
        if self.grid_lower > self.grid_upper:
            raise ValueError("saved grid bounds are inverted")
        held_by_buys = sum(
            (
                order.quantity - order.remaining
                for order in self.orders.values()
                if order.side == "buy"
            ),
            ZERO,
        )
        if self.inventory - self.reserved_base() < held_by_buys:
            # Otherwise unpaired_inventory goes negative and the exit classifier would
            # report nothing owed while a sell reservation exceeds what is held.
            raise ValueError("resting orders claim more inventory than the account holds")
        if any(
            type(flag) is not bool for flag in (self.liquidating, self.draining, self.range_exit)
        ):
            raise ValueError("invalid saved lifecycle flag")
        if self.range_exit != bool(self.range_exit_since):
            raise ValueError("range-exit timestamp does not match the lifecycle flag")
        if self.outside_seconds and not self.outside_last:
            raise ValueError("outside-range time has no last observation")
        for counter in (
            self.recovery_count,
            self.settlement_count,
            self.cycles,
            self.fill_count,
            self.episode_count,
        ):
            if type(counter) is not int or counter < 0:
                raise ValueError("invalid saved counter")
        for transfer_id, amount in self.confirmed_transfers.items():
            nonnegative(amount)
            if not transfer_id.strip() or amount == ZERO:
                raise ValueError("invalid simulated transfer journal")
        with localcontext() as context:
            context.prec = 80
            if sum(self.confirmed_transfers.values(), ZERO) != self.secured:
                raise ValueError("simulated transfer journal does not reconcile to secured reserve")
        for when in (
            self.outside_last,
            self.range_exit_since,
            self.last_observed,
            self.last_received,
            self.down_since,
            self.halt_since,
            self.episode_since,
        ):
            if when:
                timestamp(when)
        if type(self.trend_day) is not str or type(self.down_since) is not str:
            raise ValueError("invalid saved trend-switch state")
        if self.trend_day:
            date.fromisoformat(self.trend_day)
        for key, order in self.orders.items():
            if key != order.order_id or order.side not in ("buy", "sell"):
                raise ValueError("invalid saved order identity")
            for value in (order.price, order.quantity, order.remaining):
                nonnegative(value)
            if not ZERO < order.remaining <= order.quantity or order.price == ZERO:
                raise ValueError("invalid order balance")
            if order.price % rules.tick_size or order.quantity % rules.quantity_step:
                raise ValueError("order violates market precision")
            if order.remaining % rules.quantity_step:
                raise ValueError("remaining quantity violates precision")
            if order.epoch is not None and (type(order.epoch) is not str or not order.epoch):
                raise ValueError("invalid order epoch")
            if order.target is not None:
                nonnegative(order.target)
                if (
                    order.side != "buy"
                    or order.target <= order.price
                    or order.target % rules.tick_size
                ):
                    raise ValueError("invalid saved sell target")
            if order.reentry is not None:
                nonnegative(order.reentry)
                if (
                    order.side != "sell"
                    or not ZERO < order.reentry < order.price
                    or order.reentry % rules.tick_size
                ):
                    raise ValueError("invalid saved reentry level")
        if self.available_quote(rules) < ZERO or self.inventory < self.reserved_base():
            raise ValueError("account is oversubscribed or reserve is being spent")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for order in data["orders"].values():
            if order["epoch"] is None:
                # Replay-only field: omitted when unused so saved paper state keeps the
                # schema 4 layout that earlier versions read.
                del order["epoch"]
        for key in ("trend_day", "down_since"):
            if not data[key]:
                del data[key]  # Variant A only: V0 saved state keeps its exact layout.
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Account:
        data = dict(data)
        for key in (
            "initial_cash",
            "cash",
            "reserve_high",
            "risk_high",
            "day_start",
            "inventory",
            "pending",
            "secured",
            "fees",
            "last_equity",
            "grid_lower",
            "grid_upper",
            "outside_seconds",
            "measure_high",
        ):
            data[key] = decimal(data[key])
        orders: dict[str, LimitOrder] = {}
        for key, raw in data["orders"].items():
            raw = dict(raw)
            for name in ("price", "quantity", "remaining"):
                raw[name] = decimal(raw[name])
            if raw["target"] is not None:
                raw["target"] = decimal(raw["target"])
            if raw["reentry"] is not None:
                raw["reentry"] = decimal(raw["reentry"])
            orders[key] = LimitOrder(**raw)
        data["confirmed_transfers"] = {
            key: decimal(value) for key, value in data["confirmed_transfers"].items()
        }
        data["orders"] = orders
        return cls(**data)
