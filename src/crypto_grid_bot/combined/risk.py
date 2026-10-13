"""Serialized shared reservations. The engine supplies one authoritative account view.

An acknowledged fill transfers reserved exposure into that view atomically under
the engine's event lock. This component never sends orders or infers acknowledgments.
"""

from dataclasses import dataclass, replace
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from threading import Lock

from crypto_grid_bot.market_data.parsing import symbol_name

ZERO = Decimal(0)

# The owner-approved size limits, each a share of equity, as exact Fractions so no Decimal
# context can move them. Source: docs/superpowers/specs/2026-10-10-v3-1-design.md, Package D.
# tests/test_combined_risk_limits.py pins every value.
# Spec 2026-10-10-v3-1-design.md, Package D: initial risk per asset 0.5% of equity.
ASSET_RISK_LIMIT = Fraction(1, 200)
# Spec 2026-10-10-v3-1-design.md, Package D: aggregate open+reserved stop risk <= 3%.
AGGREGATE_RISK_LIMIT = Fraction(3, 100)
# Spec 2026-10-10-v3-1-design.md, Package D: asset notional <= 20% of equity.
ASSET_NOTIONAL_LIMIT = Fraction(1, 5)
# Spec 2026-10-10-v3-1-design.md, Package D: portfolio gross <= 1.6x (absolute cap 2x).
GROSS_LIMIT = Fraction(8, 5)
# Spec 2026-10-10-v3-1-design.md, Package D: correlated group gross cap 80% of equity.
GROUP_GROSS_LIMIT = Fraction(4, 5)


def planned_price(price: Decimal, side: int, slip: Decimal, tick: Decimal) -> Decimal:
    """Planned adverse execution using an explicit tick, not a gap-price guarantee.

    The engine always supplies a verified venue tick. Fraction arithmetic keeps
    slippage and tick rounding independent of the caller's Decimal context.
    """
    value = Fraction(price) * (1 + side * Fraction(slip))
    unit = Fraction(tick)
    value = (-((-value) // unit) if side == 1 else value // unit) * unit
    precision = len(str(abs(value.numerator))) + 4 * len(str(value.denominator)) + 10
    with localcontext(Context(prec=precision)):
        return Decimal(value.numerator) / Decimal(value.denominator)


@dataclass(frozen=True, slots=True)
class Exposure:
    """Held exposure. ``stop_risk`` is the loss from entry to the current stop (owner
    decision 2026-10-11): it feeds the 0.5%/3% risk limits. ``mark_risk`` is the loss
    from the current mark to the stop: margin stress, where unrealized profit counts.
    """

    symbol: str
    owner: str
    notional: Decimal
    stop_risk: Decimal
    correlation_group: str
    risk_multiplier: Decimal = Decimal(1)
    mark_risk: Decimal | None = None


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
    tick: Decimal
    funding_rate: Decimal | None = None
    funding_age_ms: int | None = None
    funding_interval_ms: int | None = None
    funding_admission: bool = True
    maintenance_rate: Decimal = Decimal("0.01")
    risk_multiplier: Decimal = Decimal(1)


@dataclass(frozen=True, slots=True)
class Admission:
    """An approval, or a refusal with every independent reason; ``reason`` is the first."""

    intent_id: str
    accepted: bool
    reason: str
    quantity: Decimal = ZERO
    cash: Decimal = ZERO
    risk: Decimal = ZERO
    notional: Decimal = ZERO
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.accepted and not self.reasons:
            object.__setattr__(self, "reasons", (self.reason,))
        if (
            not isinstance(self.reasons, tuple)
            or any(not isinstance(reason, str) or not reason for reason in self.reasons)
            or (self.accepted and self.reasons)
            or (not self.accepted and self.reasons[0] != self.reason)
        ):
            raise ValueError("an approval has no reasons; a refusal's first reason leads them")


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
    _number(intent.tick, True)
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
        intent.risk_multiplier,
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
        or intent.risk_multiplier not in {Decimal("0.5"), Decimal(1)}
    ):
        raise ValueError("invalid admission contract")
    if (intent.venue == "spot" and (intent.side != 1 or intent.owner == "futures_trend")) or (
        intent.venue == "futures" and intent.owner != "futures_trend"
    ):
        raise ValueError("invalid strategy ownership")
    if (Fraction(intent.price) - Fraction(intent.stop)) * intent.side <= 0:
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
        _number(exposure.risk_multiplier)
        if exposure.risk_multiplier not in {Decimal("0.5"), Decimal(1)}:
            raise ValueError("invalid exposure risk multiplier")
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

    @property
    def pending(self) -> tuple[tuple[Intent, Admission], ...]:
        """Remaining reservations with the intents they belong to."""
        with self._lock:
            return tuple(self._pending.values())

    def acknowledge_remaining(
        self, intent_id: str, remaining: Decimal, *, acknowledged: bool
    ) -> None:
        """Engine has booked all filled quantity; release only its acknowledged share."""
        _number(remaining)
        if acknowledged is not True:
            raise ValueError("acknowledgement required")
        with self._lock, localcontext(Context(prec=60)):
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

    def preview(self, intent: Intent, view: PortfolioView) -> Admission:
        """Read-only eligibility check; no ID or capacity is reserved."""
        _validate(intent, view)
        with self._lock, localcontext(Context(prec=60)):
            return self._admit(intent, view)

    def reserve(self, intent: Intent, view: PortfolioView) -> Admission:
        _validate(intent, view)
        with self._lock, localcontext(Context(prec=60)):
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
        """Every independent refusal reason, in check order; ``reason`` is the first.

        A halt or an invalid margin rate leaves no meaningful size, and an invalid
        execution price leaves nothing to price, so the size limits are then skipped
        instead of reported as consequences.
        """
        reasons: list[str] = []

        def no() -> Admission:
            return Admission(intent.intent_id, False, reasons[0], reasons=tuple(reasons))

        sizing = True
        if not view.equity or not view.risk_fraction:
            reasons.append("risk_halted")
            sizing = False
        pending = tuple(self._pending.values())
        if any(e.symbol == intent.symbol for e in view.exposures) or any(
            i.symbol == intent.symbol for i, _ in pending
        ):
            reasons.append("asset_owned")
        distance = abs(intent.price - intent.stop)
        # Bounds run from the quote to the adverse execution price. Entry and
        # stop-exit fees use their own prices, especially for short buybacks.
        entry = planned_price(intent.price, intent.side, intent.slippage_rate, intent.tick)
        stop_exit = planned_price(intent.stop, -intent.side, intent.slippage_rate, intent.tick)
        if min(entry, stop_exit) <= 0:
            reasons.append("invalid_execution_price")
            return no()
        fees = (entry + stop_exit) * intent.fee_rate
        entry_slippage = intent.side * (entry - intent.price)
        exit_slippage = intent.side * (intent.stop - stop_exit)
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
            funding = intent.funding_rate
            if (
                not isinstance(funding, Decimal)
                or not funding.is_finite()
                or type(intent.funding_age_ms) is not int
                or not 0 <= intent.funding_age_ms <= 28_800_000
                or intent.funding_interval_ms != 28_800_000
            ):
                reasons.append("funding_unavailable")
                funding = None
            if intent.maintenance_rate <= 0 or Decimal("0.5") < 4 * intent.maintenance_rate:
                reasons.append("margin_buffer")
                sizing = False
            if (
                funding is not None
                and intent.funding_admission
                and max(ZERO, funding * intent.side) * 3 * intent.price
                > Decimal("0.25") * unit_risk
            ):
                reasons.append("adverse_funding")
        if not sizing:
            return no()
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
            view.free_cash / unit_cash,
            intent.max_quantity,
        )
        # Shared futures backing includes free cash and futures collateral/P&L,
        # never spot inventory. With no explicit snapshot use only free cash.
        backing = view.free_cash if view.futures_backing is None else view.futures_backing
        backing -= sum((a.cash for i, a in pending if i.venue == "spot"), ZERO)
        held = tuple(e for e in view.exposures if e.owner == "futures_trend")
        gross = sum((e.notional for e in held), ZERO)
        stress = sum((e.stop_risk if e.mark_risk is None else e.mark_risk for e in held), ZERO)
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

        # Entry fees and adverse execution against the current mark reduce equity.
        # Only remaining reservations are charged here: settled costs are already
        # in view.equity. Exit costs stay in stop risk/cash, not this equity debit.
        unit_loss = Fraction(entry) * Fraction(intent.fee_rate) + Fraction(entry_slippage)
        equity = Fraction(view.equity)
        notionals: dict[str, Fraction] = {}
        risks: dict[str, Fraction] = {}
        multipliers: dict[str, Fraction] = {}
        group_totals: dict[str, Fraction] = {}
        for exposure in view.exposures:
            notionals[exposure.symbol] = Fraction(exposure.notional)
            risks[exposure.symbol] = Fraction(exposure.stop_risk)
            multipliers[exposure.symbol] = Fraction(exposure.risk_multiplier)
        for held_intent, answer in pending:
            held_entry = planned_price(
                held_intent.price, held_intent.side, held_intent.slippage_rate, held_intent.tick
            )
            equity -= Fraction(answer.quantity) * (
                Fraction(held_entry) * Fraction(held_intent.fee_rate)
                + held_intent.side * (Fraction(held_entry) - Fraction(held_intent.price))
            )
            symbol = held_intent.symbol
            notionals[symbol] = notionals.get(symbol, Fraction(0)) + Fraction(answer.notional)
            risks[symbol] = risks.get(symbol, Fraction(0)) + Fraction(answer.risk)
            multipliers[symbol] = min(
                multipliers.get(symbol, Fraction(held_intent.risk_multiplier)),
                Fraction(held_intent.risk_multiplier),
            )
        for symbol, notional in notionals.items():
            name = groups.get(symbol, "unknown")
            group_totals[name] = group_totals.get(name, Fraction(0)) + notional

        def capacity(
            coefficient: Fraction, used: Fraction, unit: Fraction, capital: Fraction = equity
        ) -> Fraction:
            # used + q*unit <= coefficient * (capital - q*unit_loss).
            cap = coefficient * Fraction(fraction)
            return (cap * capital - used) / (unit + cap * unit_loss)

        def own_limits(capital: Fraction) -> Fraction:
            """The candidate's own asset risk and asset notional limits."""
            return min(
                capacity(
                    ASSET_RISK_LIMIT * Fraction(intent.risk_multiplier),
                    Fraction(0),
                    Fraction(unit_risk),
                    capital,
                ),
                capacity(ASSET_NOTIONAL_LIMIT, Fraction(0), Fraction(unit_notional), capital),
            )

        def executable(bound: Fraction) -> Decimal | None:
            """The step-floored size, or None when it misses a venue minimum."""
            quantity = Decimal(bound // Fraction(intent.step)) * intent.step
            if (
                quantity <= 0
                or quantity < intent.min_quantity
                or quantity * minimum_price < intent.min_notional
            ):
                return None
            return quantity

        quantity_bound = min(
            Fraction(normal) * Fraction(fraction),
            Fraction(cash) / Fraction(unit_cash),
            own_limits(equity),
            capacity(AGGREGATE_RISK_LIMIT, Fraction(used_risk), Fraction(unit_risk)),
            capacity(GROSS_LIMIT, Fraction(used_gross), Fraction(unit_notional)),
            capacity(GROUP_GROSS_LIMIT, Fraction(group), Fraction(unit_notional)),
        )
        # The candidate's costs also shrink limits on every other held/reserved
        # asset and correlation group. No priority rule can silently resize them.
        if unit_loss:
            for symbol in notionals:
                quantity_bound = min(
                    quantity_bound,
                    capacity(ASSET_NOTIONAL_LIMIT, notionals[symbol], Fraction(0)),
                    capacity(ASSET_RISK_LIMIT * multipliers[symbol], risks[symbol], Fraction(0)),
                )
            for name, notional in group_totals.items():
                if name != intent.correlation_group:
                    quantity_bound = min(
                        quantity_bound, capacity(GROUP_GROSS_LIMIT, notional, Fraction(0))
                    )

        def size_refusal() -> str:
            if intent.venue == "spot":
                # Owner decision 2026-10-11: ``below_minimum``, the only spot refusal that
                # permits a futures fallback, means the size allowed by the size limits,
                # own asset limits and recovery allowance misses the venue minimum before
                # any committed cash or capacity (free cash, futures backing, reservations,
                # aggregate risk, gross, group, other assets' headroom). A size those
                # commitments cut short is refused for that cause instead.
                uncommitted = min(
                    Fraction(min(intent.requested_quantity, intent.max_quantity))
                    * Fraction(fraction),
                    own_limits(Fraction(view.equity)),
                )
                if executable(uncommitted) is None:
                    return "below_minimum"
                if quantity_bound > 0:
                    return "spot_capacity_committed"
            return "portfolio_capacity" if quantity_bound <= 0 else "below_minimum"

        quantity = executable(quantity_bound)
        if quantity is None:
            reasons.append(size_refusal())
        if reasons or quantity is None:
            return no()
        return Admission(
            intent.intent_id,
            True,
            "approved",
            quantity,
            quantity * unit_cash,
            quantity * unit_risk,
            quantity * unit_notional,
        )
