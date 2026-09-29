"""Command-line parsing and output of the app entry point; no network or database."""

import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from crypto_grid_bot import app
from crypto_grid_bot.market_data.stream import StreamStopped

CONFIG = str(Path(__file__).resolve().parents[1] / "config" / "default.toml")


class StreamOutputTests(unittest.TestCase):
    def test_a_ban_mid_run_prints_the_collected_summary_and_fails(self):
        summary = {
            "orders_authorized": False,
            "symbols": {"ADAUSDC": {"ticks": 2}},
            "stopped_reason": "HTTP 429 on connect; stream stopped",
        }
        stopped = StreamStopped("HTTP 429 on connect; stream stopped", summary)
        stdout = io.StringIO()
        with (
            patch.object(app, "run_stream", side_effect=stopped),
            contextlib.redirect_stdout(stdout),
        ):
            code = app.main(["--config", CONFIG, "--stream-prices", "--symbol", "ADAUSDC"])
        self.assertEqual(2, code)
        printed = json.loads(stdout.getvalue())
        self.assertEqual("stopped", printed["status"])
        self.assertEqual("HTTP 429 on connect; stream stopped", printed["reason"])
        self.assertEqual({"ADAUSDC": {"ticks": 2}}, printed["symbols"])
        self.assertFalse(printed["orders_authorized"])


if __name__ == "__main__":
    unittest.main()
