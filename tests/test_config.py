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
            ("range_score_limit = 0.25", "range_score_limit = 0"),
            ("range_adx_limit = 22.0", "range_adx_limit = 100"),
            ("maximum_news_risk = 0.30", "maximum_news_risk = 2"),
            ("minimum_levels = 6", "minimum_levels = 9"),
            ("confirmation_cycles = 2", "confirmation_cycles = 0"),
            ('include_assets = ["NIGHT"]', 'include_assets = "NIGHT"'),
            ("top_n = 100", "top_n = 10"),
            ("minimum_score = 0.70", "minimum_socre = 0.70"),
            ("minimum_score = 0.70", ""),
            ("minimum_confidence = 0.70", "minimum_confidence = 1.0"),
            ("minimum_input_quality = 0.70", "minimum_input_quality = 0"),
            ("minimum_input_quality = 0.70", "minimum_input_quality = 1.5"),
            ("range_dispersion_limit = 0.50", "range_dispersion_limit = 0"),
            ("range_dispersion_limit = 0.50", ""),
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

    def test_regime_quality_floor_and_dispersion_limit_are_loaded(self) -> None:
        config = load_config(DEFAULT)
        self.assertEqual(0.70, config.minimum_input_quality)
        self.assertEqual(0.50, config.range_dispersion_limit)

    def test_include_assets_entries_are_asset_names_listed_once(self) -> None:
        cases = {
            '["NIGHT", "AD A"]': "'AD A' is not an asset name",
            '["NIGHT", "BTC/USDT"]': "'BTC/USDT' is not an asset name",
            '["NIGHT", ""]': "non-empty list of asset names",
            '["NIGHT", "ÄDA"]': "is not an asset name",
            '["NIGHT", "ﬀ"]': "is not an asset name",  # upper-cases to ASCII "FF"
            '["NIGHT", "NIGHT"]': "lists NIGHT more than once",
            '["NIGHT", "BTC", " btc "]': "lists BTC more than once",
        }
        source = DEFAULT.read_text()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "test.toml"
            for assets, error in cases.items():
                with self.subTest(assets=assets):
                    path.write_text(source.replace('["NIGHT"]', assets), encoding="utf-8")
                    with self.assertRaisesRegex(ConfigurationError, error):
                        load_config(path)

    def test_include_assets_are_trimmed_and_upper_cased(self) -> None:
        self.assertEqual(("NIGHT",), load_config(DEFAULT).include_assets)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "test.toml"
            path.write_text(DEFAULT.read_text().replace('["NIGHT"]', '[" night ", "1000sats"]'))
            self.assertEqual(("NIGHT", "1000SATS"), load_config(path).include_assets)
