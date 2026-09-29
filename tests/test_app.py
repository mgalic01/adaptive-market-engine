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


def parse(flags):
    return app._parse_args(["--config", CONFIG, *flags.split()])


class ModeOptionTests(unittest.TestCase):
    def test_documented_invocations_parse_with_their_defaults(self):
        # README, docs/MARKET_DATA.md, docs/PAPER_SIMULATION.md and the CI workflow.
        parse("--self-check")
        self.assertEqual(Path("x.db"), parse("--paper-demo --database x.db").database)
        capture = parse("--capture-market --symbol ADAUSDC --database m.db")
        self.assertEqual(
            (["ADAUSDC"], 1, 60), (capture.symbol, capture.samples, capture.poll_seconds)
        )
        capture = parse(
            "--capture-market --symbol ADAUSDC --database m.db --samples 60 --poll-seconds 120"
        )
        self.assertEqual((60, 120), (capture.samples, capture.poll_seconds))
        stream = parse("--stream-prices --symbol ADAUSDC --symbol BTCUSDC")
        self.assertEqual((["ADAUSDC", "BTCUSDC"], 60), (stream.symbol, stream.seconds))
        self.assertEqual(900, parse("--stream-prices --symbol ADAUSDC --seconds 900").seconds)
        resume = parse(
            "--resume-paper --database p.db --resume-frame f.json --event-id e-1 --reason ok"
        )
        self.assertEqual(("e-1", "ok"), (resume.event_id, resume.reason))

    def test_an_option_the_mode_ignores_is_rejected(self):
        cases = [
            ("--self-check --database x.db --samples 50", "--database, --samples"),
            ("--capture-market --symbol ADAUSDC --seconds 900", "--seconds"),
            # Even the stream's default value is refused: capture would still ignore it.
            ("--capture-market --symbol ADAUSDC --seconds 60", "--seconds"),
            ("--stream-prices --symbol ADAUSDC --database x.db", "--database"),
            ("--stream-prices --symbol ADAUSDC --poll-seconds 60", "--poll-seconds"),
            ("--paper-demo --database x.db --reason why", "--reason"),
            ("--resume-paper --database x.db --symbol ADAUSDC", "--symbol"),
        ]
        for flags, named in cases:
            stderr = io.StringIO()
            with (
                self.subTest(flags=flags),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as caught,
            ):
                parse(flags)
            self.assertEqual(2, caught.exception.code)
            self.assertIn(f"does not use {named}", stderr.getvalue())


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
