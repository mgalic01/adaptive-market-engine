"""Recompute frozen picks from complete supplied training score records."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Context, Decimal, localcontext

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.trend.orchestration import INVALID, TrainingScore
from crypto_grid_bot.trend.walk_forward import RULES, choose_rule, windows


@dataclass(frozen=True, slots=True)
class QuarterSelection:
    test_month: str
    picked_rule: str | None
    training: tuple[TrainingScore, ...]
    monthly_coin_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class SelectionReport:
    quarters: tuple[QuarterSelection, ...]
    long_only_quarters: int
    flat_quarters: int
    long_only_share: Decimal


def selection_report(
    training: Sequence[TrainingScore],
    picks: Mapping[int, str | None],
    first_months: Mapping[str, str],
    exclusions: Mapping[str, frozenset[str]] | None = None,
) -> SelectionReport:
    """Audit score/menu consistency, not the provenance of training scores.

    Counts are monthly portfolio membership after exclusions, not signal-ready
    or actively held coins. Long-only share includes flat quarters in its
    denominator. Training artifacts must independently authenticate the scores.
    """
    if "BTCUSDT" not in first_months:
        raise ValueError("BTCUSDT portfolio start required")
    for month in first_months.values():
        development_month(month)
    exclusions = exclusions or {}
    if not set(exclusions) <= set(first_months):
        raise ValueError("unknown exclusion symbol")
    for months in exclusions.values():
        for month in months:
            development_month(month)
    calendar = windows(first_months["BTCUSDT"])
    expected_months = {w.test_start for w in calendar}
    expected_stamps = {month_bounds_ms(m)[0] for m in expected_months}
    if set(picks) != expected_stamps:
        raise ValueError("picks must cover every frozen test quarter")
    indexed: dict[tuple[str, str], TrainingScore] = {}
    run_ids: set[str] = set()
    for score in training:
        key = (score.test_month, score.rule)
        if score.test_month not in expected_months or score.rule not in RULES or key in indexed:
            raise ValueError("unexpected or duplicate training score")
        if not score.run_id.strip() or score.run_id in run_ids:
            raise ValueError("unique training run identities required")
        if score.invalid_reason is None:
            if not isinstance(score.sharpe, Decimal) or not score.sharpe.is_finite():
                raise ValueError("valid training run requires finite Sharpe")
        elif score.invalid_reason not in INVALID or score.sharpe is not None:
            raise ValueError("strategy-invalid training requires known reason and no score")
        indexed[key] = score
        run_ids.add(score.run_id)
    if len(indexed) != len(calendar) * len(RULES):
        raise ValueError("every training quarter requires all twelve rules")
    quarters = []
    for window in calendar:
        rows = tuple(indexed[window.test_start, rule] for rule in RULES)
        chosen = choose_rule({row.rule: row.sharpe for row in rows})
        if picks[month_bounds_ms(window.test_start)[0]] != chosen:
            raise ValueError("recorded pick disagrees with frozen selection")
        year, first_number = map(int, window.test_start.split("-"))
        quarter_months = tuple(f"{year:04d}-{m:02d}" for m in range(first_number, first_number + 3))
        counts = tuple(
            (
                m,
                sum(
                    first <= m and m not in exclusions.get(s, ())
                    for s, first in first_months.items()
                ),
            )
            for m in quarter_months
        )
        quarters.append(QuarterSelection(window.test_start, chosen, rows, counts))
    long_only = sum(q.picked_rule is not None and q.picked_rule.endswith("L") for q in quarters)
    with localcontext(Context(prec=60)):
        share = Decimal(long_only) / len(quarters)
    return SelectionReport(
        tuple(quarters), long_only, sum(q.picked_rule is None for q in quarters), share
    )
