from unittest import TestCase

from crypto_grid_bot.strategy.grid import GridBuilder, GridNotViable


class GridBuilderTests(TestCase):
    def setUp(self) -> None:
        self.builder = GridBuilder(
            minimum_levels=6,
            maximum_levels=8,
            minimum_cost_multiple=3,
            range_atr_multiple=2,
        )

    def test_builds_affordable_geometric_grid(self) -> None:
        plan = self.builder.build(
            symbol="NIGHTUSDT",
            fair_value=0.023,
            atr=0.0015,
            capital=100,
            min_notional=5,
            round_trip_cost_pct=0.2,
            capital_utilization=0.8,
        )
        self.assertEqual(8, len(plan.levels))
        self.assertGreater(plan.estimated_spacing_pct, 0.6)

    def test_rejects_unaffordable_grid(self) -> None:
        with self.assertRaises(GridNotViable):
            self.builder.build(
                symbol="BTCUSDT",
                fair_value=80_000,
                atr=2_000,
                capital=20,
                min_notional=5,
                round_trip_cost_pct=0.2,
                capital_utilization=0.8,
            )

    def test_rejects_invalid_inputs_and_uncovered_costs(self) -> None:
        inputs = dict(
            symbol="TESTUSDT",
            fair_value=0.023,
            atr=0.0015,
            capital=100,
            min_notional=5,
            round_trip_cost_pct=0.2,
            capital_utilization=0.8,
        )
        for key in ["fair_value", "atr", "capital", "min_notional", "round_trip_cost_pct"]:
            for bad in [float("nan"), float("inf"), -1, 0]:
                with self.subTest(key=key, value=bad), self.assertRaises(GridNotViable):
                    self.builder.build(**(inputs | {key: bad}))
        with self.assertRaises(GridNotViable):
            self.builder.build(**(inputs | {"round_trip_cost_pct": 20}))
