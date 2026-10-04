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
        # Standard args used by FTA tests.  fair_value=1.0, atr=0.1 → lower=0.8, upper=1.2
        self._std = dict(
            symbol="TESTUSDT",
            fair_value=1.0,
            atr=0.1,
            capital=80,
            min_notional=5,
            round_trip_cost_pct=0.2,
        )

    def test_builds_affordable_geometric_grid(self) -> None:
        plan = self.builder.build(
            symbol="NIGHTUSDT",
            fair_value=0.023,
            atr=0.0015,
            capital=80,
            min_notional=5,
            round_trip_cost_pct=0.2,
        )
        self.assertEqual(8, len(plan.levels))
        self.assertGreater(plan.estimated_spacing_pct, 0.6)

    def test_rejects_unaffordable_grid(self) -> None:
        with self.assertRaises(GridNotViable):
            self.builder.build(
                symbol="BTCUSDT",
                fair_value=80_000,
                atr=2_000,
                capital=16,
                min_notional=5,
                round_trip_cost_pct=0.2,
            )

    def test_rejects_invalid_inputs_and_uncovered_costs(self) -> None:
        inputs = dict(
            symbol="TESTUSDT",
            fair_value=0.023,
            atr=0.0015,
            capital=80,
            min_notional=5,
            round_trip_cost_pct=0.2,
        )
        for key in ["fair_value", "atr", "capital", "min_notional", "round_trip_cost_pct"]:
            for bad in [float("nan"), float("inf"), -1, 0]:
                with self.subTest(key=key, value=bad), self.assertRaises(GridNotViable):
                    self.builder.build(**(inputs | {key: bad}))
        with self.assertRaises(GridNotViable):
            self.builder.build(**(inputs | {"round_trip_cost_pct": 20}))

    # ------------------------------------------------------------------
    # FTA resistance cap tests
    # ------------------------------------------------------------------

    def test_fta_none_leaves_levels_unchanged(self) -> None:
        """No fta_resistance → identical plan to passing no argument at all."""
        plan_default = self.builder.build(**self._std)
        plan_none = self.builder.build(**self._std, fta_resistance=None)
        self.assertEqual(plan_default.levels, plan_none.levels)
        self.assertIsNone(plan_none.fta_resistance_used)

    def test_fta_within_grid_caps_top_levels(self) -> None:
        """fta_resistance inside the grid → levels above resistance are capped."""
        # lower=0.8, upper=1.2; place FTA at 1.1 (inside the grid)
        fta = 1.1
        plan = self.builder.build(**self._std, fta_resistance=fta)
        cap = fta * 0.999
        # Every level must be <= cap
        for lvl in plan.levels:
            self.assertLessEqual(lvl, cap + 1e-12, msg=f"level {lvl} exceeds cap {cap}")
        # Levels that were originally below fta should be unchanged
        plan_no_fta = self.builder.build(**self._std)
        for orig, capped in zip(plan_no_fta.levels, plan.levels, strict=False):
            if orig < fta:
                self.assertAlmostEqual(
                    orig, capped, places=12, msg="levels below FTA must not be altered"
                )
        # fta_resistance_used must be recorded
        self.assertEqual(plan.fta_resistance_used, fta)

    def test_fta_above_grid_upper_has_no_effect(self) -> None:
        """fta_resistance above the grid's upper bound → no cap applied."""
        # upper = 1.2; FTA at 1.5 is outside the grid
        plan_no_fta = self.builder.build(**self._std)
        plan_fta = self.builder.build(**self._std, fta_resistance=1.5)
        self.assertEqual(plan_no_fta.levels, plan_fta.levels)
        self.assertIsNone(plan_fta.fta_resistance_used)

    def test_fta_below_or_equal_lower_has_no_effect(self) -> None:
        """fta_resistance at or below the grid's lower bound → no cap applied."""
        plan_no_fta = self.builder.build(**self._std)
        for fta in [0.8, 0.5]:  # lower=0.8
            with self.subTest(fta=fta):
                plan_fta = self.builder.build(**self._std, fta_resistance=fta)
                self.assertEqual(plan_no_fta.levels, plan_fta.levels)
                self.assertIsNone(plan_fta.fta_resistance_used)

    def test_fta_exactly_at_upper_bound_applies_cap(self) -> None:
        """fta_resistance == upper is inside the grid (boundary inclusive) → cap applied."""
        # upper = 1.2
        fta = 1.2
        plan = self.builder.build(**self._std, fta_resistance=fta)
        cap = fta * 0.999
        for lvl in plan.levels:
            self.assertLessEqual(lvl, cap + 1e-12)
        self.assertEqual(plan.fta_resistance_used, fta)
