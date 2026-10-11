"""Serialized wallet/reservation/recovery kernel; no market fetching or live orders.

The replay adapter supplies qualified intents and explicit settled executions. It
owns OHLC sequencing and source identities. This kernel never invents an execution
to satisfy a close obligation. Funding is booked before reductions, then increases.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from threading import RLock

from crypto_grid_bot.combined.account import (
    AccountSnapshot,
    CombinedAccount,
    FillEvent,
    FundingEvent,
    PositionSnapshot,
)
from crypto_grid_bot.combined.execution import (
    Reduction,
    VenueRules,
    _decimal,
    executable_reduction,
    futures_margin,
)
from crypto_grid_bot.combined.recovery import Recovery, RecoveryDecision
from crypto_grid_bot.combined.risk import (
    Admission,
    Exposure,
    Intent,
    PortfolioRisk,
    PortfolioView,
    planned_price,
)
from crypto_grid_bot.combined.routing import Qualification

_STARTED = object()  # An attempt that began but never recorded its result.


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
    unresolved_execution: tuple[str, ...] = ()
    # Held symbols whose mark is stale or filters missing at THIS observation. The
    # close reason persists while held; this field describes only the current mark.
    stale: tuple[str, ...] = ()
    # Persisting close and cut-back reasons of each held symbol, for exit attribution.
    close_reasons: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # Cut-back obligations: (symbol, absolute quantity to keep at most).
    reduce_to: tuple[tuple[str, Decimal], ...] = ()


@dataclass(frozen=True, slots=True)
class SettlementObservation:
    phase: str
    event_id: str
    snapshot: EngineSnapshot


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
        self._admissions: dict[str, Admission] = {}
        self._risk_multipliers: dict[str, Decimal] = {}
        self._correlation_groups: tuple[tuple[str, str], ...] = ()
        self._finality: dict[str, tuple[str, ...]] = {}
        self._releases: dict[str, tuple[tuple[Decimal, tuple[str, ...]], ...]] = {}
        self._ticks: dict[str, Decimal] = {}
        self._stops: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
        self._close: set[str] = set()
        self._close_reasons: dict[str, set[str]] = {}
        self._trims: dict[str, Decimal] = {}
        self._trim_reasons: dict[str, set[str]] = {}
        self._order_close_reasons: dict[str, set[str]] = {}
        self._liquidation = False
        self._integrity_failure = False
        self._batches: dict[str, tuple[object, EngineSnapshot]] = {}
        self._batch_observations: dict[str, tuple[SettlementObservation, ...]] = {}
        # Duplicate executions must preserve their role and original admission.
        self._fills: dict[str, tuple[str, str | None, FillEvent]] = {}
        self._funding_events: dict[str, FundingEvent] = {}
        # Whole-frame attempts span several settlement batches; one registry per account.
        self._attempts: dict[str, tuple[object, object]] = {}
        self._recovery.update(0, initial_cash, True, False, True)

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Serialize one whole replay frame against every other caller of this account."""
        with self._lock:
            yield

    def retained_attempt(self, attempt_id: str, identity: object) -> object | None:
        """Return an identical completed frame's retained result, never a retry.

        None means no attempt with this ID exists. A conflicting identity, or an
        attempt that started without recording its result (an interrupted frame),
        raises. The registry lives on the account, so a new adapter cannot reset it.
        """
        with self._lock:
            if not isinstance(attempt_id, str) or not attempt_id.strip():
                raise ValueError("attempt identity required")
            if attempt_id not in self._attempts:
                return None
            prior, result = self._attempts[attempt_id]
            if prior != identity or result is _STARTED:
                raise ValueError("conflicting or unfinished attempt")
            return result

    def begin_attempt(self, attempt_id: str, identity: object) -> None:
        """Register a multi-batch frame once per account before its first mutation."""
        with self._lock:
            if self.retained_attempt(attempt_id, identity) is not None or (
                attempt_id in self._attempts
            ):
                raise ValueError("attempt already registered")
            self._attempts[attempt_id] = (identity, _STARTED)

    def finish_attempt(self, attempt_id: str, result: object) -> None:
        """Retain the result, including failures, of a started attempt exactly once."""
        with self._lock:
            entry = self._attempts.get(attempt_id)
            if entry is None or entry[1] is not _STARTED or result is None:
                raise ValueError("started attempt and a result required")
            self._attempts[attempt_id] = (entry[0], result)

    def close_dust(self, rules: Mapping[str, VenueRules]) -> tuple[str, ...]:
        """Held close obligations that no legal reduction can execute at fresh marks.

        Stale marks, missing filters and pending or unreconciled orders are never
        dust. The inventory stays valued and owned, and its obligation is retained.
        """
        with self._lock, localcontext(Context(prec=60)):
            account = self._account.snapshot({s: q.price for s, q in self._quotes.items()})
            return tuple(
                sorted(
                    p.symbol
                    for p in account.positions
                    if p.symbol in self._close
                    and self._fresh(p.symbol, self._clock)
                    and isinstance(rules.get(p.symbol), VenueRules)
                    and not self._reduction(p, rules[p.symbol]).quantity
                    and not self._unresolved_canceled_fill(p.symbol)
                    and all(intent.symbol != p.symbol for intent, _ in self._orders.values())
                )
            )

    @property
    def reservations(self) -> tuple[Admission, ...]:
        return self._risk.reservations

    @property
    def clock(self) -> int:
        """Last accepted observation time; adapters may reject overlapping intervals."""
        with self._lock:
            return self._clock

    def held_execution_terms(
        self,
    ) -> tuple[tuple[PositionSnapshot, Decimal, Decimal, Decimal], ...]:
        """Immutable current inventory and its authoritative stop, fee and slippage."""
        with self._lock:
            account = self._account.snapshot({s: q.price for s, q in self._quotes.items()})
            return tuple((p, *self._stops[p.symbol]) for p in account.positions)

    def settlement_observations(self, batch_id: str) -> tuple[SettlementObservation, ...]:
        """Retained event marks, including a successfully observed prefix after failure.

        This is evidence only. No replay, sampling choice or rollback is performed.
        Duplicate completed batches return the original trace unchanged.
        """
        with self._lock:
            return self._batch_observations.get(batch_id, ())

    def booked_fill(self, event_id: str) -> FillEvent | None:
        """Execution evidence even when a subsequent settlement mark failed."""
        with self._lock:
            recorded = self._fills.get(event_id)
            return recorded[2] if recorded is not None else None

    def booked_funding(self, event_id: str) -> FundingEvent | None:
        """Retain a booked payment even if its following valuation fails."""
        with self._lock:
            return self._funding_events.get(event_id)

    def cancel(self, intent_id: str) -> None:
        """Cancel increases locally; this does not attest that all fills are reconciled."""
        with self._lock:
            self._risk.release(intent_id, acknowledged=True)
            self._orders.pop(intent_id, None)

    def acknowledge_finality(self, intent_id: str, *, source_refs: tuple[str, ...]) -> None:
        """Attest all fills reconciled and zero remaining executable quantity.

        The replay adapter must establish this from its execution evidence. A cancel
        request/ack alone is insufficient. Provenance and original remaining capacity
        are retained; a later novel fill contradicts finality and fails integrity.
        """
        with self._lock:
            if (
                intent_id not in self._known_orders
                or intent_id in self._orders
                or not isinstance(source_refs, tuple)
                or not source_refs
                or any(not isinstance(ref, str) or not ref.strip() for ref in source_refs)
            ):
                raise ValueError("canceled recorded admission and finality evidence required")
            if intent_id in self._finality and self._finality[intent_id] != source_refs:
                raise ValueError("conflicting finality evidence")
            self._finality[intent_id] = source_refs

    def release_unallocated(
        self, intent_id: str, remaining: Decimal, *, source_refs: tuple[str, ...]
    ) -> None:
        """Acknowledge that only ``remaining`` of a pending order can still fill.

        A grid basket's rounded children never use all of its admitted quantity;
        the unplaced share is released instead of staying reserved. Remaining can
        only shrink, zero releases the order, and the provenance is retained.
        """
        with self._lock:
            if (
                intent_id not in self._orders
                or not isinstance(remaining, Decimal)
                or not remaining.is_finite()
                or remaining < 0
                or not isinstance(source_refs, tuple)
                or not source_refs
                or any(not isinstance(ref, str) or not ref.strip() for ref in source_refs)
            ):
                raise ValueError("pending admission, remaining quantity and evidence required")
            intent, current = self._orders[intent_id]
            if remaining > current:
                raise ValueError("remaining quantity cannot grow")
            self._risk.acknowledge_remaining(intent_id, remaining, acknowledged=True)
            self._known_orders[intent_id] = (intent, remaining)
            if remaining:
                self._orders[intent_id] = (intent, remaining)
            else:
                self._orders.pop(intent_id)
            self._releases[intent_id] = (
                *self._releases.get(intent_id, ()),
                (remaining, source_refs),
            )

    @property
    def release_evidence(
        self,
    ) -> tuple[tuple[str, tuple[tuple[Decimal, tuple[str, ...]], ...]], ...]:
        with self._lock:
            return tuple(sorted(self._releases.items()))

    @property
    def canceled_unreconciled(self) -> tuple[str, ...]:
        """Canceled orders whose remaining quantity still lacks finality evidence."""
        with self._lock:
            return tuple(
                sorted(
                    key
                    for key, (_, remaining) in self._known_orders.items()
                    if remaining > 0 and key not in self._orders and key not in self._finality
                )
            )

    @property
    def finality_evidence(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        with self._lock:
            return tuple(sorted(self._finality.items()))

    def _require_close(self, symbol: str, reason: str) -> None:
        """Caller holds the event lock; cancel increases but retain late-fill identity."""
        portfolio_protection = reason in {
            "stale_position_or_missing_filters",
            "margin_reduction",
            "post_fill_risk_breach",
            "portfolio_cap_reduction",
        }
        for key, (intent, _) in tuple(self._orders.items()):
            if portfolio_protection or intent.symbol == symbol:
                self._order_close_reasons.setdefault(key, set()).add(reason)
                self.cancel(key)
        self._close.add(symbol)
        self._close_reasons.setdefault(symbol, set()).add(reason)

    def _protective_owner(self, symbol: str, owner: str, side: int) -> PositionSnapshot | None:
        if type(side) is not int or side not in {-1, 1}:
            raise ValueError("held side must be exactly +1 or -1")
        position = next((p for p in self._account.snapshot().positions if p.symbol == symbol), None)
        pending = [
            i
            for key, (i, remaining) in self._known_orders.items()
            if i.symbol == symbol and remaining > 0 and key not in self._finality
        ]
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
        its order; its disposition remains attached to that admission so subsequent
        actual late fills are booked and closed with the original reason.
        """
        with self._lock:
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("nonempty protective close reason required")
            position = self._protective_owner(symbol, owner, side)
            for key, (intent, remaining) in tuple(self._known_orders.items()):
                if intent.symbol == symbol and remaining > 0 and key not in self._finality:
                    self._order_close_reasons.setdefault(key, set()).add(reason)
                    if key in self._orders:
                        self.cancel(key)
            if position is not None:
                self._require_close(symbol, reason)

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
            exit_price = planned_price(stop, -side, slip, self._ticks[position.symbol])
            unit_risk = max(Decimal(0), side * (position.mark - exit_price)) + exit_price * fee
            # Owner decision 2026-10-11: the risk limits measure the loss from each
            # lot's entry price to the current stop, so a favorable move never raises it.
            entry_risk = sum(
                (
                    abs(lot.quantity) * max(Decimal(0), side * (lot.entry_price - exit_price))
                    for lot in position.lots
                ),
                abs(position.quantity) * exit_price * fee,
            )
            exposures.append(
                Exposure(
                    position.symbol,
                    position.owner,
                    abs(position.quantity) * position.mark,
                    entry_risk,
                    mapping.get(position.symbol, "unknown"),
                    self._risk_multipliers[position.symbol],
                    abs(position.quantity) * unit_risk,
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

    def _cap_reductions(
        self, account: AccountSnapshot, fraction: Decimal
    ) -> tuple[set[str], dict[str, Fraction]]:
        """Check current limits; return assets to cancel and keep fractions to cut back to.

        Owner decision 2026-10-11: the 0.5% asset and 3% aggregate risk limits measure
        each holding's loss from entry to its current stop; a breached limit cuts the
        holdings back to it instead of closing them. Breach detection counts unfilled
        potential (canceled remainders until finality), whose increases are canceled;
        keep fractions then use held exposure only. Aggregate and correlation-group
        breaches cut every affected holding by one common fraction, so no unregistered
        priority among assets decides. Groups are the last admitted causal snapshot.
        """
        view = self._view(account, fraction, self._correlation_groups)
        held_gross = {e.symbol: Fraction(e.notional) for e in view.exposures}
        held_risk = {e.symbol: Fraction(e.stop_risk) for e in view.exposures}
        gross, risk = dict(held_gross), dict(held_risk)
        pending: set[str] = set()
        for key, (intent, remaining) in self._known_orders.items():
            if not remaining or key in self._finality:
                continue
            admission = self._admissions[key]
            scale = Fraction(remaining) / Fraction(admission.quantity)
            symbol = intent.symbol
            gross[symbol] = gross.get(symbol, Fraction(0)) + Fraction(admission.notional) * scale
            risk[symbol] = risk.get(symbol, Fraction(0)) + Fraction(admission.risk) * scale
            pending.add(symbol)
        capital = max(Fraction(0), Fraction(view.equity)) * Fraction(view.risk_fraction)
        mapping = dict(self._correlation_groups)

        def asset_cap(symbol: str) -> Fraction:
            return capital * Fraction(self._risk_multipliers[symbol]) / 200

        def groups_of(values: dict[str, Fraction]) -> dict[str, Fraction]:
            totals: dict[str, Fraction] = {}
            for symbol, value in values.items():
                name = mapping.get(symbol, "unknown")
                totals[name] = totals.get(name, Fraction(0)) + value
            return totals

        breached = {s for s in gross if gross[s] > capital / 5 or risk[s] > asset_cap(s)}
        aggregate = (
            sum(risk.values(), Fraction(0)) > capital * Fraction(3, 100)
            or sum(gross.values(), Fraction(0)) > capital * Fraction(8, 5)
            or any(value > capital * Fraction(4, 5) for value in groups_of(gross).values())
        )
        if not breached and not aggregate:
            return set(), {}
        cancel = (set(gross) if aggregate else breached) & pending
        # Holdings already required to close go to zero; they never size others' cuts.
        held_gross = {s: v for s, v in held_gross.items() if s not in self._close}
        held_risk = {s: v for s, v in held_risk.items() if s not in self._close}
        total_risk = sum(held_risk.values(), Fraction(0))
        total_gross = sum(held_gross.values(), Fraction(0))
        group_gross = groups_of(held_gross)
        keep: dict[str, Fraction] = {}
        for symbol in held_gross:
            factor = Fraction(1)
            limits = (
                (held_gross[symbol], capital / 5),
                (held_risk[symbol], asset_cap(symbol)),
                (total_risk, capital * Fraction(3, 100)),
                (total_gross, capital * Fraction(8, 5)),
                (group_gross[mapping.get(symbol, "unknown")], capital * Fraction(4, 5)),
            )
            for used, limit in limits:
                if used > limit:
                    factor = min(factor, limit / used)
            if factor < 1:
                keep[symbol] = factor
        return cancel, keep

    def _apply_caps(
        self,
        account: AccountSnapshot,
        rules: Mapping[str, VenueRules],
        cancel: set[str],
        keep: dict[str, Fraction],
        reason: str,
    ) -> None:
        """Caller holds the lock. Cancel increases, then record cut-back obligations.

        A target rounds down to the venue step; zero becomes a full close. Targets only
        tighten until a reduction satisfies them, so a transient breach is not erased.
        """
        for key, (intent, _) in tuple(self._orders.items()):
            if intent.symbol in cancel:
                self._order_close_reasons.setdefault(key, set()).add(reason)
                self.cancel(key)
        for position in account.positions:
            factor = keep.get(position.symbol)
            if factor is None:
                continue
            target = Fraction(abs(position.quantity)) * factor
            rule = rules.get(position.symbol)
            if isinstance(rule, VenueRules):
                target = (target // Fraction(rule.step)) * Fraction(rule.step)
            if target <= 0:
                self._require_close(position.symbol, reason)
                continue
            amount = _decimal(target)
            prior = self._trims.get(position.symbol)
            self._trims[position.symbol] = amount if prior is None else min(prior, amount)
            self._trim_reasons.setdefault(position.symbol, set()).add(reason)

    def _exit_reasons(self, symbol: str) -> set[str]:
        closing = self._close_reasons.get(symbol, set()) if symbol in self._close else set()
        return closing | self._trim_reasons.get(symbol, set())

    def _exit_reserve(self, account: AccountSnapshot) -> Decimal:
        reserve = Decimal(0)
        for position in account.positions:
            stop, fee, slip = self._stops[position.symbol]
            side = 1 if position.quantity > 0 else -1
            exit_price = planned_price(stop, -side, slip, self._ticks[position.symbol])
            reserve += abs(position.quantity) * (side * (stop - exit_price) + exit_price * fee)
        return reserve

    def _unresolved_canceled_fill(self, symbol: str | None = None) -> bool:
        """Caller holds the lock; cancellation alone cannot prove execution finality."""
        return any(
            (symbol is None or known.symbol == symbol)
            and remaining > 0
            and key not in self._orders
            and key not in self._finality
            for key, (known, remaining) in self._known_orders.items()
        )

    def _reduction(self, position: PositionSnapshot, rules: VenueRules) -> Reduction:
        """Use held execution costs, never a new candidate's slippage profile."""
        return executable_reduction(
            abs(position.quantity),
            position.mark,
            rules,
            side=-1 if position.quantity > 0 else 1,
            slippage=self._stops[position.symbol][2],
        )

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
            stale: list[str] = []
            flat = not self._orders and not self._unresolved_canceled_fill()
            for position in account.positions:
                if position.symbol in rules:
                    self._ticks[position.symbol] = rules[position.symbol].tick
                if not self._fresh(position.symbol, timestamp_ms) or position.symbol not in rules:
                    flat = False
                    self._require_close(position.symbol, "stale_position_or_missing_filters")
                    reasons.append("stale_position_or_missing_filters")
                    stale.append(position.symbol)
                elif self._reduction(position, rules[position.symbol]).quantity:
                    flat = False
            margin = futures_margin(account.free_cash, account.positions)
            if margin.maintenance > 0 and margin.backing <= margin.maintenance:
                self._liquidation = True
                reasons.append("simulated_liquidation")
            if margin.maintenance > 0 and margin.backing < 3 * margin.maintenance:
                for position in account.positions:
                    if position.venue == "futures":
                        self._require_close(position.symbol, "margin_reduction")
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
                for position in account.positions:
                    self._require_close(position.symbol, recovery.reason)
                reasons.append(recovery.reason)
            # Routine cap management applies to every causal valuation/account event.
            # Keep it distinct from failed execution so replay can settle reductions.
            cancel, keep = self._cap_reductions(account, recovery.risk_fraction)
            self._apply_caps(account, rules, cancel, keep, "portfolio_cap_reduction")
            held = {p.symbol: abs(p.quantity) for p in account.positions}
            self._close.intersection_update(held)
            self._close_reasons = {
                symbol: why for symbol, why in self._close_reasons.items() if symbol in held
            }
            self._trims = {
                symbol: target
                for symbol, target in self._trims.items()
                if symbol in held and held[symbol] > target
            }
            self._trim_reasons = {
                symbol: why for symbol, why in self._trim_reasons.items() if symbol in self._trims
            }
            persisting = (*self._close_reasons.values(), *self._trim_reasons.values())
            reasons.extend(sorted({why for values in persisting for why in values}))
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
                tuple(
                    sorted(
                        key
                        for key, (_, remaining) in self._known_orders.items()
                        if remaining > 0 and key not in self._finality
                    )
                ),
                tuple(sorted(stale)),
                tuple(
                    (symbol, tuple(sorted(self._exit_reasons(symbol))))
                    for symbol in sorted(self._close | set(self._trims))
                ),
                tuple(sorted(self._trims.items())),
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
            if self._unresolved_canceled_fill():
                return refuse("canceled_fill_finality_pending")

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
                or intent.tick != rule.tick
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
                        or self._reduction(p, rules[p.symbol]).quantity > 0
                    )
                    for p in state.account.positions
                )
                or not state.account.integrity_ok
                or self._liquidation
                or self._integrity_failure
            ):
                return refuse("protective_reduction_pending")
            return self._risk.preview(
                replace(intent, tick=rule.tick), self._view(state.account, Decimal(1), groups)
            )

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
            rule = candidate_rules if candidate_rules is not None else rules[intent.symbol]
            answer = self._risk.reserve(
                replace(intent, tick=rule.tick),
                self._view(state.account, state.recovery.risk_fraction, groups),
            )
            if answer.accepted and intent.intent_id not in self._orders:
                self._ticks[intent.symbol] = rule.tick
                self._orders[intent.intent_id] = (intent, answer.quantity)
                self._known_orders[intent.intent_id] = (intent, answer.quantity)
                self._admissions[intent.intent_id] = answer
                self._risk_multipliers[intent.symbol] = intent.risk_multiplier
                self._correlation_groups = groups
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
            except (ValueError, ArithmeticError, TypeError, AttributeError):
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
            if batch_id in self._batch_observations:
                raise ValueError("failed settlement cannot be retried")

            def mark(phase: str, event_id: str) -> EngineSnapshot:
                snapshot = self.observe(timestamp_ms, quotes, rules)
                self._batch_observations[batch_id] = (
                    *self._batch_observations[batch_id],
                    SettlementObservation(phase, event_id, snapshot),
                )
                return snapshot

            self._batch_observations[batch_id] = ()
            mark("before", batch_id)
            for payment in funding:
                self._account.apply(payment)
                self._funding_events[payment.event_id] = payment
                mark("funding", payment.event_id)
            for event in reductions:
                reduction_identity = ("reduction", None, event)
                if event.event_id in self._fills:
                    if self._fills[event.event_id] != reduction_identity:
                        raise ValueError("conflicting fill ID")
                    continue
                before = next(
                    (p for p in self._account.snapshot().positions if p.symbol == event.symbol),
                    None,
                )
                if before is None or before.quantity * event.side >= 0:
                    raise ValueError("reduction must reduce held inventory")
                self._account.apply(event)
                self._fills[event.event_id] = reduction_identity
                mark("reduction", event.event_id)
            for key, event in increases:
                increase_identity = ("increase", key, event)
                if event.event_id in self._fills:
                    if self._fills[event.event_id] != increase_identity:
                        raise ValueError("conflicting fill ID")
                    continue
                if key not in self._known_orders:
                    raise ValueError("fill has no recorded admission")
                if key in self._finality:
                    raise ValueError("novel fill contradicts acknowledged finality")
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
                self._fills[event.event_id] = increase_identity
                for reason in self._order_close_reasons.get(key, ()):
                    self._require_close(event.symbol, reason)
                adverse = planned_price(
                    intent.price, intent.side, intent.slippage_rate, intent.tick
                )
                if (
                    not was_pending
                    or intent.side * (event.price - adverse) > 0
                    or event.fee > event.quantity * event.price * intent.fee_rate
                ):
                    self._require_close(event.symbol, "post_fill_risk_breach")
                state = mark("increase", event.event_id)
                cancel, keep = self._cap_reductions(state.account, state.recovery.risk_fraction)
                self._apply_caps(state.account, rules, cancel, keep, "post_fill_risk_breach")
            result = mark("settled", batch_id)
            self._batches[batch_id] = (identity, result)
            return result
