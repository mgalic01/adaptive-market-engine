"""Event-fed lifecycle attribution; callers preserve the actual event order."""

from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.trend.account import Fill, FundingEvent, Position

ZERO = Decimal(0)
EXIT_PRIORITY = (
    "excluded_month",
    "flip",
    "pick_change",
    "signal_zero",
    "sizing",
    "delevering",
    "minimum_quantity",
)


@dataclass
class Lifecycle:
    symbol: str
    side: str
    start_ms: int
    fills: list[Fill] = field(default_factory=list)
    realized: Decimal = ZERO
    fees: Decimal = ZERO
    funding_paid: Decimal = ZERO
    funding_received: Decimal = ZERO
    unrealized: Decimal = ZERO
    favourable: Decimal = ZERO
    adverse: Decimal = ZERO
    end_ms: int | None = None
    exit_reason: str | None = None
    censored: bool = False

    @property
    def net(self) -> Decimal:
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            return (
                self.realized
                + self.unrealized
                - self.fees
                - self.funding_paid
                + self.funding_received
            )

    @property
    def given_back(self) -> Decimal:
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            return self.favourable - (self.realized + self.unrealized)

    @property
    def duration_ms(self) -> int | None:
        return None if self.end_ms is None else self.end_ms - self.start_ms


class LifecycleLedger:
    def __init__(self) -> None:
        self.active: dict[str, Lifecycle] = {}
        self.completed: list[Lifecycle] = []

    def observe(self, symbol: str, position: Position, price: Decimal) -> None:
        life = self.active[symbol]
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            value = life.realized + position.quantity * (price - position.average_entry)
            life.favourable = max(life.favourable, value)
            life.adverse = min(life.adverse, value)

    def fill(
        self, fill: Fill, before: Position, after: Position, reasons: Set[str] = frozenset()
    ) -> None:
        reason = next((reason for reason in EXIT_PRIORITY if reason in reasons), None)
        if after.quantity == ZERO and reason is None:
            raise ValueError("closing fill needs an exit reason")
        if before.quantity == ZERO:
            if fill.symbol in self.active:
                raise ValueError("duplicate lifecycle entry")
            self.active[fill.symbol] = Lifecycle(
                fill.symbol, "long" if after.quantity > 0 else "short", fill.timestamp_ms
            )
        else:
            self.observe(fill.symbol, before, fill.price)
        life = self.active[fill.symbol]
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            life.realized += fill.realized
            life.fees += fill.fee
        life.fills.append(fill)
        if fill.reduce_only:
            self.observe(fill.symbol, after, fill.price)
        if after.quantity == ZERO:
            life.end_ms = fill.timestamp_ms
            life.exit_reason = reason
            self.completed.append(self.active.pop(fill.symbol))

    def fund(self, event: FundingEvent) -> None:
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            for payment in event.payments:
                life = self.active[payment.symbol]
                if payment.payment > ZERO:
                    life.funding_paid += payment.payment
                else:
                    life.funding_received -= payment.payment

    def censor(
        self,
        timestamp_ms: int,
        positions: Mapping[str, Position],
        prices: Mapping[str, Decimal],
        reason: str,
    ) -> None:
        if reason not in ("end_of_run", "liquidation"):
            raise ValueError("invalid censor reason")
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            for symbol in sorted(self.active):
                life = self.active[symbol]
                held = positions[symbol]
                self.observe(symbol, held, prices[symbol])
                life.unrealized = held.quantity * (prices[symbol] - held.average_entry)
                life.end_ms = timestamp_ms
                life.exit_reason = reason
                life.censored = True
                self.completed.append(life)
        self.active.clear()
