from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from crypto_grid_bot.config import ConfigurationError, load_config

DEFAULT = Path(__file__).resolve().parents[1] / "config" / "default.toml"


class ConfigTests(TestCase):
    def test_default_is_paper_with_one_slot(self) -> None:
        config = load_config(DEFAULT)
        self.assertEqual("paper", config.mode)
        self.assertEqual(1, config.maximum_active_grids)
        self.assertEqual(0.5, config.reserve_fraction)

    def test_invalid_configs_are_rejected(self) -> None:
        replacements = [
            ('mode = "paper"', 'mode = "live"'),
            ("maximum_active_grids = 1", "maximum_active_grids = 6"),
            ("maximum_active_grids = 1", "maximum_active_grids = 1.5"),
            ("maximum_active_grids = 1", "maximum_active_grids = true"),
            ("reserve_fraction = 0.50", "reserve_fraction = 0.40"),
            ("minimum_transfer_quote = 10.0", "minimum_transfer_quote = nan"),
            ("minimum_transfer_quote = 10.0", "minimum_transfer_quote = -1"),
            ("maximum_data_age_seconds = 30", "maximum_data_age_seconds = 0"),
            ("maximum_spread_pct = 0.15", "maximum_spread_pct = inf"),
            ("bull_threshold = 0.35", "bull_threshold = -0.2"),
            ("range_score_limit = 0.25", "range_score_limit = 0.9"),
            ("maximum_news_risk = 0.30", "maximum_news_risk = 2"),
            ("minimum_levels = 6", "minimum_levels = 9"),
            ("confirmation_cycles = 2", "confirmation_cycles = 0"),
            ('include_assets = ["NIGHT"]', 'include_assets = "NIGHT"'),
            ("top_n = 100", "top_n = 10"),
            ("minimum_score = 0.70", "minimum_socre = 0.70"),
            ("minimum_score = 0.70", ""),
        ]
        source = DEFAULT.read_text()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "test.toml"
            for old, new in replacements:
                with self.subTest(setting=new):
                    self.assertIn(old, source)
                    path.write_text(source.replace(old, new))
                    with self.assertRaises(ConfigurationError):
                        load_config(path)

    def test_regime_thresholds_are_loaded(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "test.toml"
            path.write_text(
                DEFAULT.read_text().replace("bull_threshold = 0.35", "bull_threshold = 0.45")
            )
            self.assertEqual(0.45, load_config(path).bull_threshold)
