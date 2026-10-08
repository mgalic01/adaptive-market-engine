"""Event-fed lifecycle attribution; callers preserve the actual event order."""

from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.trend.account import Fill, FillEvent, FundingEvent, JournalBatch, Position

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
        self._funding_clock = -1
        self._consumed: list[FillEvent | FundingEvent] = []

    @property
    def event_count(self) -> int:
        return len(self._consumed)

    def consume(
        self,
        events: tuple[FillEvent | FundingEvent, ...],
        exit_reasons: Mapping[int, Set[str]],
    ) -> None:
        """Consume an append-only journal; reason keys are absolute event indices.

        This API must not be mixed with manually feeding the same events. Missing
        exit attribution is an engine error, never inferred from a zero quantity.
        """
        start = len(self._consumed)
        if events[:start] != tuple(self._consumed):
            raise ValueError("account journal was truncated or changed")
        self.consume_batch(
            JournalBatch(start, events[start - 1] if start else None, events[start:]), exit_reasons
        )

    def consume_batch(self, batch: JournalBatch, exit_reasons: Mapping[int, Set[str]]) -> None:
        """Consume only new events, checking cursor and immutable boundary identity.

        Account journals append immutable entries; no historical prefix is copied
        or scanned on this path. Full snapshot validation remains in consume().
        """
        previous = self._consumed[-1] if self._consumed else None
        if batch.start != self.event_count or batch.previous is not previous:
            raise ValueError("account journal batch is discontinuous")
        for index, event in enumerate(batch.events, batch.start):
            if (
                isinstance(event, FillEvent)
                and event.after.quantity == ZERO
                and not any(reason in EXIT_PRIORITY for reason in exit_reasons.get(index, set()))
            ):
                raise ValueError("closing journal event needs an exit reason")
        for index, event in enumerate(batch.events, batch.start):
            if isinstance(event, FillEvent):
                self.fill(event.fill, event.before, event.after, exit_reasons.get(index, set()))
            else:
                self.fund(event)
            self._consumed.append(event)

    def observe(self, symbol: str, position: Position, price: Decimal) -> None:
        life = self.active[symbol]
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            value = life.realized + position.quantity * (price - position.average_entry)
            life.favourable = max(life.favourable, value)
            life.adverse = min(life.adverse, value)

    def fill(
        self, fill: Fill, before: Position, after: Position, reasons: Set[str] = frozenset()
    ) -> None:
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            if before.quantity + fill.quantity != after.quantity:
                raise ValueError("inconsistent fill quantity")
            if fill.quantity == ZERO or before.quantity * after.quantity < ZERO:
                raise ValueError("fill must not cross zero in one lifecycle event")
            if fill.reduce_only and (
                before.quantity * fill.quantity >= ZERO
                or abs(after.quantity) >= abs(before.quantity)
            ):
                raise ValueError("invalid reducing quantity")
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
        if type(event.timestamp_ms) is not int or event.timestamp_ms <= self._funding_clock:
            raise ValueError("funding groups must have strictly increasing timestamps")
        symbols = set()
        for payment in event.payments:
            if payment.symbol not in self.active or payment.symbol in symbols:
                raise ValueError("funding needs one payment per active lifecycle")
            if event.timestamp_ms < self.active[payment.symbol].start_ms:
                raise ValueError("funding predates lifecycle")
            if not payment.payment.is_finite():
                raise ValueError("nonfinite funding payment")
            symbols.add(payment.symbol)
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            for payment in event.payments:
                life = self.active[payment.symbol]
                if payment.payment > ZERO:
                    life.funding_paid += payment.payment
                else:
                    life.funding_received -= payment.payment
        self._funding_clock = event.timestamp_ms

    def censor(
        self,
        timestamp_ms: int,
        positions: Mapping[str, Position],
        prices: Mapping[str, Decimal],
        reason: str,
    ) -> None:
        if reason not in (
            "end_of_run",
            "liquidation",
            "no_tradable_position",
            "leverage_not_restored",
        ):
            raise ValueError("invalid censor reason")
        for symbol, life in self.active.items():
            if symbol not in positions or symbol not in prices:
                raise ValueError("missing terminal position or price")
            price = prices[symbol]
            if not isinstance(price, Decimal) or not price.is_finite() or price <= ZERO:
                raise ValueError("invalid terminal price")
            if type(timestamp_ms) is not int or timestamp_ms < life.start_ms:
                raise ValueError("invalid terminal timestamp")
            if positions[symbol].quantity == ZERO:
                raise ValueError("active lifecycle has flat terminal position")
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
