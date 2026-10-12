"""Literal equal-cash hold baseline (owner decision 2026-10-11).

The starting capital is split equally across the registered coins at the window's
first hour, bought once at that hour's opening quote with the run's adverse
slippage, tick rounding and fee, and held. A coin whose share cannot buy a legal
order (step, minimum quantity, minimum notional) stays in cash, and that is
disclosed. The frozen V3 hold hardcodes 10,000 USDT inside its purchase formula
and base costs, so it cannot serve the ~EUR100 or doubled-cost cells; this is the
owner-specified benchmark, not a change to any frozen strategy. Marks are the
hourly opening quotes (the boundary state) and the last bar's close (terminal).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from crypto_grid_bot.backtest.klines import Kline

from .baseline_records import BaselineEvidence, NativeMark, comparison_report, refuse_sealed
from .decisions import Costs
from .execution import VenueRules, _decimal, adverse_price
from .report import SAVED_FILTERS_DISCLOSURE, Contribution

HOUR = 3_600_000
HOLD = "matched_spot_hold"


@dataclass(frozen=True, slots=True)
class HoldMarket:
    hourly: Sequence[Kline]
    rules: VenueRules
    costs: Costs


def replay_hold_baseline(
    markets: Mapping[str, HoldMarket],
    *,
    start_ms: int,
    end_ms: int,
    initial: Decimal,
    cost_multiple: int,
    source_refs: tuple[str, ...],
    adapter_pin: str,
    skipped_hours: tuple[int, ...] = (),
    capital_label: str | None = None,
) -> BaselineEvidence:
    """Buy equal cash of every coin at the first opening quote and hold to the end.

    ``cost_multiple`` scales the registered fee and slippage rates (1 or 2). Every
    window hour needs a bar for every coin; a missing bar leaves that boundary absent
    and the comparison incomplete, never a pass, unless the registration skips it. An
    hourly bar at or after the reserved boundary is refused, never ignored.
    """
    if (
        not markets
        or type(cost_multiple) is not int
        or cost_multiple not in (1, 2)
        or not isinstance(initial, Decimal)
        or not initial.is_finite()
        or initial <= 0
    ):
        raise ValueError("coins, a cost multiple of 1 or 2 and positive capital required")
    for symbol in sorted(markets):
        refuse_sealed((row.open_ms for row in markets[symbol].hourly), f"{symbol} hourly")
    bars = {s: {row.open_ms: row for row in m.hourly} for s, m in markets.items()}
    symbols = sorted(markets)
    budget = Fraction(initial) / len(symbols)
    cash = Fraction(initial)
    held: dict[str, tuple[Fraction, Fraction, Fraction]] = {}  # quantity, price, fee
    disclosures = ["hold_marks_at_hourly_opening_quotes", SAVED_FILTERS_DISCLOSURE]
    issues: list[str] = []
    for symbol in symbols:
        first = bars[symbol].get(start_ms)
        if first is None:
            issues.append(f"hold_first_bar_missing:{symbol}")
            continue
        rules, costs = markets[symbol].rules, markets[symbol].costs
        fee = Fraction(costs.fee_rate) * cost_multiple
        slip = Fraction(costs.slippage_rate) * cost_multiple
        price = Fraction(adverse_price(_decimal(Fraction(first.open) * (1 + slip)), 1, rules))
        step = Fraction(rules.step)
        quantity = min(budget / (price * (1 + fee)), Fraction(rules.max_qty)) // step * step
        if (
            quantity <= 0
            or quantity < Fraction(rules.min_qty)
            or quantity * price < Fraction(rules.min_notional)
        ):
            disclosures.append(f"hold_share_below_exchange_minimum_kept_in_cash:{symbol}")
            continue
        cost = quantity * price * fee
        cash -= quantity * price + cost
        held[symbol] = (quantity, price, cost)
    marks: list[NativeMark] = []

    def value(prices: Mapping[str, Fraction]) -> tuple[Decimal, Decimal]:
        inventory = sum((held[s][0] * prices[s] for s in held), Fraction(0))
        return _decimal(cash + inventory), _decimal(inventory)

    marks.append(NativeMark(start_ms, "before_purchase", initial, Decimal(0), Decimal(0)))
    for hour in range(start_ms, end_ms, HOUR):
        if any(hour not in bars[s] for s in symbols):
            continue  # absent boundary: the comparison stays incomplete
        equity, spot = value({s: Fraction(bars[s][hour].open) for s in symbols})
        marks.append(NativeMark(hour, "open", equity, spot, Decimal(0)))
    last = end_ms - HOUR
    if all(last in bars[s] for s in symbols):
        equity, spot = value({s: Fraction(bars[s][last].close) for s in symbols})
        marks.append(NativeMark(end_ms, "terminal", equity, spot, Decimal(0)))
        closes = {s: Fraction(bars[s][last].close) for s in symbols}
    else:
        closes = {}
        issues.append("hold_terminal_bar_missing")
    contributions = [
        Contribution(
            f"{HOLD}:{symbol}",
            "matched_spot_hold",
            symbol,
            "long",
            None,
            _decimal(quantity * (closes[symbol] - price)),
            _decimal(fee),
            Decimal(0),
            _decimal(quantity * price),
            None,
            start_ms,
            "open_marked",
            source_refs=source_refs,
        )
        for symbol, (quantity, price, fee) in held.items()
        if symbol in closes
    ]
    report = comparison_report(
        HOLD,
        marks,
        contributions,
        initial=initial,
        start_ms=start_ms,
        end_ms=end_ms,
        source_refs=source_refs,
        adapter_pin=adapter_pin,
        producer_issues=tuple(issues),
        skipped_hours=skipped_hours,
        disclosures=tuple(disclosures),
        capital_label=capital_label,
    )
    return BaselineEvidence(
        HOLD,
        "hold-native",
        tuple(marks),
        report,
        None if not issues else issues[0],
        0,
        report.reconciliation_residual or Decimal(0),
        False,
        True,
        report.disclosures,
    )
