"""Frozen stationary bootstrap diagnostic; no data loading or strategy selection."""

import random
from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from crypto_grid_bot.trend.metrics import sharpe


class RandomDraws(Protocol):
    def randrange(self, stop: int, /) -> int: ...
    def random(self) -> float: ...


def resample_indices(length: int, rng: RandomDraws) -> tuple[int, ...]:
    """Section 8 exact draw order, geometric blocks of mean 20, circular wrap."""
    if type(length) is not int or length < 1:
        raise ValueError("positive integer series length required")
    index = rng.randrange(length)
    result = [index]
    for _ in range(length - 1):
        index = rng.randrange(length) if rng.random() < 1 / 20 else (index + 1) % length
        result.append(index)
    return tuple(result)


def sharpe_interval(returns: Sequence[Decimal]) -> tuple[Decimal, Decimal] | None:
    """95% nearest-rank interval from 10,000 freshly seeded stationary resamples.

    This is a diagnostic, not a probability of profitability or liquidation.
    Each call resets its generator, making series-processing order irrelevant.
    """
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in returns):
        raise ValueError("finite Decimal returns required")
    if len(returns) < 60:
        return None
    # Frozen statistical resampling seed; never used for secrets or security.
    rng = random.Random(20261008)  # nosec B311
    scores = []
    for _ in range(10000):
        indices = resample_indices(len(returns), rng)
        scores.append(sharpe([returns[index] for index in indices]))
    scores.sort()
    return scores[249], scores[9749]
