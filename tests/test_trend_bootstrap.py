"""Frozen resampling conventions, using synthetic returns only."""

from decimal import Decimal as D

import pytest


def test_short_history_has_no_interval_but_bad_values_still_fail():
    from crypto_grid_bot.trend.bootstrap import sharpe_interval

    assert sharpe_interval([D(0)] * 59) is None
    with pytest.raises(ValueError):
        sharpe_interval([D("NaN")])


def test_constant_returns_have_zero_interval():
    from crypto_grid_bot.trend.bootstrap import sharpe_interval

    assert sharpe_interval([D(".01")] * 60) == (D(0), D(0))


def test_exact_resample_count_ranks_and_fresh_seed(monkeypatch):
    from crypto_grid_bot.trend import bootstrap

    paths = []

    def score(rows):
        paths.append(tuple(rows))
        return D(len(paths) - 1)

    monkeypatch.setattr(bootstrap, "sharpe", score)
    source = [D(i) / 100 for i in range(60)]
    assert bootstrap.sharpe_interval(source) == (D(249), D(9749))
    assert len(paths) == 10000
    assert all(len(path) == 60 for path in paths)
    first = paths[0]
    paths.clear()
    bootstrap.sharpe_interval(source)
    assert paths[0] == first


def test_circular_block_and_restart_draw_order():
    from crypto_grid_bot.trend.bootstrap import resample_indices

    class Draws:
        def __init__(self):
            self.calls = []
            self.starts = iter([3, 1])
            self.uniforms = iter([0.5, 0.01, 0.5])

        def randrange(self, n):
            self.calls.append(("index", n))
            return next(self.starts)

        def random(self):
            self.calls.append(("uniform",))
            return next(self.uniforms)

    rng = Draws()
    assert resample_indices(4, rng) == (3, 0, 1, 2)
    assert rng.calls == [("index", 4), ("uniform",), ("uniform",), ("index", 4), ("uniform",)]
