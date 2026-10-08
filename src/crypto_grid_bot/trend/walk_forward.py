"""Frozen V3 selection helpers; no data access or experiment dispatch."""

from collections.abc import Mapping
from decimal import Decimal

RULES = tuple(f"R{i}{suffix}" for suffix in ("", "L") for i in range(1, 7))


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
