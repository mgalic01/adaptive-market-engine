"""Reported-only V3 exposure on retained hourly execution marks."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.trend.execution import HourResult


@dataclass(frozen=True, slots=True)
class ExposureDiagnostics:
    observed_hours: int
    sampled_hours: int
    undefined_equity_hours: int
    invested_fraction: Decimal | None
    mean_gross_exposure: Decimal | None
    mean_net_exposure: Decimal | None
    minimum_margin_ratio: Decimal | None


def exposure_diagnostics(hours: Sequence[HourResult]) -> ExposureDiagnostics:
    """Use step 4 after any delevering, before funding or intrabar extremes.

    An early-liquidated hour may never reach step 4. Coverage counts expose that
    omission rather than inventing a flat observation. Any nonpositive sampled
    equity makes both mean exposure ratios undefined, not silently censored.
    Callers separately establish hourly continuity, provenance and account audits.
    """
    checks = {"open", "post_fill", "post_fill_delevered", "funding", "funding_delevered", "adverse"}
    sampled = invested = undefined = 0
    gross_sum = net_sum = Decimal(0)
    minimum = None
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        for hour in hours:
            selected = None
            seen: set[str] = set()
            for kind, mark in hour.marks:
                if kind not in checks | {"favourable"}:
                    raise ValueError("unknown exposure mark kind")
                if (
                    not mark.equity.is_finite()
                    or not mark.gross_notional.is_finite()
                    or mark.gross_notional < 0
                ):
                    raise ValueError("invalid account mark for exposure")
                if kind in checks and mark.gross_notional:
                    ratio = mark.equity / mark.gross_notional
                    minimum = ratio if minimum is None else min(minimum, ratio)
                if kind in {"post_fill", "post_fill_delevered"}:
                    if kind in seen or (kind == "post_fill_delevered" and "post_fill" not in seen):
                        raise ValueError("invalid post-fill mark order")
                    if kind == "post_fill" and seen:
                        raise ValueError("invalid post-fill mark order")
                    seen.add(kind)
                    selected = mark
            if selected is None:
                continue
            net = selected.net_notional
            if net is None or not net.is_finite() or abs(net) > selected.gross_notional:
                raise ValueError("missing or invalid net notional evidence")
            sampled += 1
            invested += int(selected.gross_notional > 0)
            if selected.equity <= 0:
                undefined += 1
            else:
                gross_sum += selected.gross_notional / selected.equity
                net_sum += net / selected.equity
        return ExposureDiagnostics(
            len(hours),
            sampled,
            undefined,
            Decimal(invested) / sampled if sampled else None,
            gross_sum / sampled if sampled and not undefined else None,
            net_sum / sampled if sampled and not undefined else None,
            minimum,
        )
