"""Frozen V3 selection helpers; no data access or experiment dispatch."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from crypto_grid_bot.backtest.window import development_month

RULES = tuple(f"R{i}{suffix}" for suffix in ("", "L") for i in range(1, 7))


@dataclass(frozen=True, slots=True)
class Window:
    train_start: str
    train_end_exclusive: str
    test_start: str
    test_end_exclusive: str


def windows(first_portfolio_month: str) -> tuple[Window, ...]:
    """Calendar boundaries only; the validated manifest supplies the start month.

    The final exclusive boundary is January 2025, not permission to read it.
    """
    development_month(first_portfolio_month)
    year, month = map(int, first_portfolio_month.split("-"))
    earliest = year * 12 + month - 1 + 18
    first_test = ((earliest + 2) // 3) * 3
    end = 2025 * 12
    if first_test >= end:
        raise ValueError("no development test quarter remains after training")

    def name(index: int) -> str:
        year, zero_month = divmod(index, 12)
        return f"{year:04d}-{zero_month + 1:02d}"

    return tuple(
        Window(name(start - 18), name(start), name(start), name(start + 3))
        for start in range(first_test, end, 3)
    )


def choose_rule(scores: Mapping[str, Decimal | None]) -> str | None:
    """None means strategy-invalid, never an engine error or missing result.

    Every candidate must be supplied. All invalid means a flat test quarter;
    otherwise the highest training Sharpe wins, including when all are negative.
    """
    if set(scores) != set(RULES):
        raise ValueError("training must report every frozen candidate exactly once")
    best: str | None = None
    best_score: Decimal | None = None
    for rule in RULES:
        score = scores[rule]
        if score is None:
            continue
        if not isinstance(score, Decimal) or not score.is_finite():
            raise ValueError("invalid training score is an engine error")
        if best_score is None or score > best_score:
            best, best_score = rule, score
    return best
