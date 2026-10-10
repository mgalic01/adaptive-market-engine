"""Serialized shared reservations. The engine supplies one authoritative account view.

An acknowledged fill transfers reserved exposure into that view atomically under
the engine's event lock. This component never sends orders or infers acknowledgments.
"""

from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from fractions import Fraction
from threading import Lock

from crypto_grid_bot.market_data.parsing import symbol_name

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class Exposure:
    symbol: str
    owner: str
    notional: Decimal
    stop_risk: Decimal
    correlation_group: str


@dataclass(frozen=True, slots=True)
class PortfolioView:
    equity: Decimal
    free_cash: Decimal
    exposures: tuple[Exposure, ...]
    risk_fraction: Decimal
    correlation_groups: tuple[tuple[str, str], ...] = ()
    futures_backing: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Intent:
    intent_id: str
    symbol: str
    owner: str
    venue: str
    side: int
    price: Decimal
    stop: Decimal
    requested_quantity: Decimal
    fee_rate: Decimal
    slippage_rate: Decimal
    step: Decimal
    min_quantity: Decimal
    max_quantity: Decimal
    min_notional: Decimal
    correlation_group: str
    funding_rate: Decimal | None = None
    funding_age_ms: int | None = None
    funding_interval_ms: int | None = None
    funding_admission: bool = True
    maintenance_rate: Decimal = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Admission:
    intent_id: str
    accepted: bool
    reason: str
    quantity: Decimal = ZERO
    cash: Decimal = ZERO
    risk: Decimal = ZERO
    notional: Decimal = ZERO


def _number(value: Decimal, positive: bool = False) -> None:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < 0
        or value > Decimal("1e36")
        or (positive and value == 0)
    ):
        raise ValueError("finite nonnegative bounded Decimal required")


def _validate(intent: Intent, view: PortfolioView) -> None:
    symbol_name(intent.symbol)
    if view.futures_backing is not None:
        _number(view.futures_backing)
    for value in (intent.price, intent.stop, intent.step, intent.max_quantity):
        _number(value, True)
    for value in (
        view.equity,
        view.free_cash,
        view.risk_fraction,
        intent.requested_quantity,
        intent.fee_rate,
        intent.slippage_rate,
        intent.min_quantity,
        intent.min_notional,
        intent.maintenance_rate,
    ):
        _number(value)
    if (
        not intent.intent_id
        or not intent.correlation_group
        or intent.owner not in {"spot_trend", "spot_grid", "futures_trend"}
        or intent.venue not in {"spot", "futures"}
        or type(intent.side) is not int
        or intent.side not in {-1, 1}
        or type(intent.funding_admission) is not bool
        or view.risk_fraction not in {ZERO, Decimal("0.25"), Decimal("0.5"), Decimal(1)}
        or intent.min_quantity > intent.max_quantity
        or intent.step > intent.max_quantity
        or intent.fee_rate >= 1
        or intent.slippage_rate >= 1
    ):
        raise ValueError("invalid admission contract")
    if (intent.venue == "spot" and (intent.side != 1 or intent.owner == "futures_trend")) or (
        intent.venue == "futures" and intent.owner != "futures_trend"
    ):
        raise ValueError("invalid strategy ownership")
    if (intent.price - intent.stop) * intent.side <= 0:
        raise ValueError("stop must protect the proposed direction")
    if not isinstance(view.exposures, tuple):
        raise ValueError("immutable exposure snapshot required")
    if not isinstance(view.correlation_groups, tuple) or any(
        not isinstance(pair, tuple)
        or len(pair) != 2
        or not all(isinstance(item, str) and item for item in pair)
        for pair in view.correlation_groups
    ):
        raise ValueError("immutable correlation mapping required")
    groups = dict(view.correlation_groups)
    if len(groups) != len(view.correlation_groups):
        raise ValueError("duplicate correlation mapping")
    if intent.correlation_group != groups.get(intent.symbol, "unknown"):
        raise ValueError("intent correlation group differs from authoritative view")
    symbols = set()
    for exposure in view.exposures:
        symbol_name(exposure.symbol)
        _number(exposure.notional)
        _number(exposure.stop_risk)
        if exposure.symbol in symbols or not exposure.correlation_group or not exposure.owner:
            raise ValueError("duplicate or invalid asset ownership")
        if exposure.correlation_group != groups.get(exposure.symbol, "unknown"):
            raise ValueError("exposure correlation group differs from authoritative view")
        symbols.add(exposure.symbol)


class PortfolioRisk:
    def __init__(self) -> None:
        self._lock = Lock()
        self._seen: dict[str, tuple[Intent, Admission]] = {}
        self._pending: dict[str, tuple[Intent, Admission]] = {}

    @property
    def reservations(self) -> tuple[Admission, ...]:
        with self._lock:
            return tuple(answer for _, answer in self._pending.values())

    def acknowledge_remaining(
        self, intent_id: str, remaining: Decimal, *, acknowledged: bool
    ) -> None:
        """Engine has booked all filled quantity; release only its acknowledged share."""
        _number(remaining)
        if acknowledged is not True:
            raise ValueError("acknowledgement required")
        with self._lock, localcontext() as context:
            context.prec = 60
            if intent_id not in self._pending:
                raise ValueError("unknown pending intent")
            intent, previous = self._pending[intent_id]
            if remaining > previous.quantity:
                raise ValueError("remaining quantity cannot grow")
            if not remaining:
                del self._pending[intent_id]
            else:
                scale = remaining / previous.quantity
                self._pending[intent_id] = (
                    intent,
                    replace(
                        previous,
                        quantity=remaining,
                        cash=previous.cash * scale,
                        risk=previous.risk * scale,
                        notional=previous.notional * scale,
                    ),
                )

    def reserve(self, intent: Intent, view: PortfolioView) -> Admission:
        _validate(intent, view)
        with self._lock, localcontext() as context:
            context.prec = 60
            if intent.intent_id in self._seen:
                old_intent, old_answer = self._seen[intent.intent_id]
                if intent != old_intent:
                    raise ValueError("conflicting intent ID")
                return old_answer
            answer = self._admit(intent, view)
            self._seen[intent.intent_id] = (intent, answer)
            if answer.accepted:
                self._pending[intent.intent_id] = (intent, answer)
            return answer

    def release(self, intent_id: str, *, acknowledged: bool) -> None:
        """Only after cancellation or atomic transfer of all fills into account view."""
        if acknowledged is not True:
            raise ValueError("acknowledgement required")
        with self._lock:
            if intent_id not in self._seen:
                raise ValueError("unknown intent")
            self._pending.pop(intent_id, None)

    def _admit(self, intent: Intent, view: PortfolioView) -> Admission:
        def no(reason: str) -> Admission:
            return Admission(intent.intent_id, False, reason)

        if not view.equity or not view.risk_fraction:
            return no("risk_halted")
        pending = tuple(self._pending.values())
        if any(e.symbol == intent.symbol for e in view.exposures) or any(
            i.symbol == intent.symbol for i, _ in pending
        ):
            return no("asset_owned")
        distance = abs(intent.price - intent.stop)
        # Bounds run from the quote to the adverse execution price. Entry and
        # stop-exit fees use their own prices, especially for short buybacks.
        entry = intent.price * (1 + intent.side * intent.slippage_rate)
        stop_exit = intent.stop * (1 - intent.side * intent.slippage_rate)
        fees = (entry + stop_exit) * intent.fee_rate
        entry_slippage = intent.price * intent.slippage_rate
        exit_slippage = intent.stop * intent.slippage_rate
        unit_risk = distance + entry_slippage + exit_slippage + fees
        unit_notional = max(intent.price, entry)
        minimum_price = min(intent.price, entry)
        collateral_fraction = Decimal(1) if intent.venue == "spot" else Decimal("0.5")
        unit_cash = unit_notional * collateral_fraction + fees + exit_slippage
        if intent.venue == "futures":
            # Spot principal already includes its adverse entry price; futures
            # must also retain cash for the entry execution loss against the mark.
            unit_cash += entry_slippage
        if intent.venue == "futures":
            if (
                not isinstance(intent.funding_rate, Decimal)
                or not intent.funding_rate.is_finite()
                or type(intent.funding_age_ms) is not int
                or not 0 <= intent.funding_age_ms <= 28_800_000
                or intent.funding_interval_ms != 28_800_000
            ):
                return no("funding_unavailable")
            if intent.maintenance_rate <= 0 or Decimal("0.5") < 4 * intent.maintenance_rate:
                return no("margin_buffer")
            if (
                intent.funding_admission
                and max(ZERO, intent.funding_rate * intent.side) * 3 * intent.price
                > Decimal("0.25") * unit_risk
            ):
                return no("adverse_funding")
        cash = view.free_cash - sum((a.cash for _, a in pending), ZERO)
        used_risk = sum((e.stop_risk for e in view.exposures), ZERO)
        used_risk += sum((a.risk for _, a in pending), ZERO)
        used_gross = sum((e.notional for e in view.exposures), ZERO)
        used_gross += sum((a.notional for _, a in pending), ZERO)
        group = sum(
            (e.notional for e in view.exposures if e.correlation_group == intent.correlation_group),
            ZERO,
        )
        groups = dict(view.correlation_groups)
        group += sum(
            (
                a.notional
                for i, a in pending
                if groups.get(i.symbol, "unknown") == intent.correlation_group
            ),
            ZERO,
        )
        fraction = view.risk_fraction
        normal = min(
            intent.requested_quantity,
            view.equity * Decimal("0.005") / unit_risk,
            view.equity * Decimal("0.20") / unit_notional,
            view.free_cash / unit_cash,
            intent.max_quantity,
        )
        # Shared futures backing includes free cash and futures collateral/P&L,
        # never spot inventory. With no explicit snapshot use only free cash.
        backing = view.free_cash if view.futures_backing is None else view.futures_backing
        backing -= sum((a.cash for i, a in pending if i.venue == "spot"), ZERO)
        held = tuple(e for e in view.exposures if e.owner == "futures_trend")
        gross = sum((e.notional for e in held), ZERO)
        stress = sum((e.stop_risk for e in held), ZERO)
        gross += sum((a.notional for i, a in pending if i.venue == "futures"), ZERO)
        pending_risk = sum((a.risk for i, a in pending if i.venue == "futures"), ZERO)
        stress += pending_risk
        rate = intent.maintenance_rate if intent.venue == "futures" else Decimal("0.01")
        if intent.venue == "futures":
            # gross+stop risk bounds short notional growth at stressed exits, and
            # conservatively overstates it for longs. Existing risks are not reset.
            stop_capacity = (backing - stress - 3 * rate * (gross + stress)) / (
                unit_risk + 3 * rate * max(unit_notional, stop_exit)
            )
            entry_capacity = (backing - pending_risk - 4 * rate * gross) / (
                entry * intent.fee_rate + entry_slippage + 4 * rate * unit_notional
            )
            normal = min(normal, stop_capacity, entry_capacity)
        elif held or any(i.venue == "futures" for i, _ in pending):
            # Spot spending removes eligible backing too. Preserve both buffers
            # for already held/reserved futures regardless of admission order.
            stop_capacity = (backing - stress - 3 * rate * (gross + stress)) / unit_cash
            entry_capacity = (backing - pending_risk - 4 * rate * gross) / unit_cash
            normal = min(normal, stop_capacity, entry_capacity)

        quantity = min(
            normal * fraction,
            cash / unit_cash,
            (view.equity * Decimal("0.03") * fraction - used_risk) / unit_risk,
            (view.equity * Decimal("1.6") * fraction - used_gross) / unit_notional,
            (view.equity * Decimal("0.8") * fraction - group) / unit_notional,
        )
        if quantity <= 0:
            return no("portfolio_capacity")
        quantity = Decimal(Fraction(quantity) // Fraction(intent.step)) * intent.step
        if (
            quantity == 0
            or quantity < intent.min_quantity
            or quantity * minimum_price < intent.min_notional
        ):
            return no("below_minimum")
        return Admission(
            intent.intent_id,
            True,
            "approved",
            quantity,
            quantity * unit_cash,
            quantity * unit_risk,
            quantity * unit_notional,
        )
