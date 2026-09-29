"""Command-line entry point for safe configuration and strategy self-checks."""

from __future__ import annotations

import argparse
from pathlib import Path

from crypto_grid_bot.config import load_config
from crypto_grid_bot.domain import MarketSignals
from crypto_grid_bot.market_data.client import FeedError
from crypto_grid_bot.market_data.command import run_capture
from crypto_grid_bot.market_data.parsing import DataError
from crypto_grid_bot.market_data.stream import StreamStopped, run_stream
from crypto_grid_bot.simulation.control import resume_paper
from crypto_grid_bot.simulation.demo import run_demo
from crypto_grid_bot.simulation.store import encode
from crypto_grid_bot.strategy.regime import RegimeClassifier, thresholds_from_config

# The options each mode reads. Any other option given with a mode is an error, not
# silently ignored; unset options are None until the defaults below are applied.
MODE_OPTIONS = {
    "self_check": (),
    "paper_demo": ("database",),
    "resume_paper": ("database", "resume_frame", "event_id", "reason"),
    "capture_market": ("database", "symbol", "samples", "poll_seconds"),
    "stream_prices": ("symbol", "seconds"),
}
DEFAULTS = {"seconds": 60, "samples": 1, "poll_seconds": 60}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adaptive crypto grid bot")
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--paper-demo", action="store_true")
    mode.add_argument("--resume-paper", action="store_true")
    parser.add_argument("--resume-frame", type=Path)
    parser.add_argument("--event-id")
    parser.add_argument("--reason")
    mode.add_argument("--capture-market", action="store_true")
    mode.add_argument("--stream-prices", action="store_true")
    parser.add_argument(
        "--symbol",
        action="append",
        help="explicit Binance spot symbol, e.g. ADAUSDC; repeat for --stream-prices",
    )
    parser.add_argument("--seconds", type=int, help="--stream-prices duration (default 60)")
    parser.add_argument("--samples", type=int, help="--capture-market samples (default 1)")
    parser.add_argument("--poll-seconds", type=int, help="--capture-market interval (default 60)")
    parser.add_argument("--database", type=Path)
    return parser


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = _parser()
    args = parser.parse_args(argv)
    mode = next(name for name in MODE_OPTIONS if getattr(args, name))
    options = {name for names in MODE_OPTIONS.values() for name in names}
    ignored = sorted(
        f"--{name.replace('_', '-')}"
        for name in options - set(MODE_OPTIONS[mode])
        if getattr(args, name) is not None
    )
    if ignored:
        parser.error(f"--{mode.replace('_', '-')} does not use {', '.join(ignored)}")
    for name, value in DEFAULTS.items():
        if getattr(args, name) is None:
            setattr(args, name, value)
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = load_config(args.config)
    if args.resume_paper:
        if not all((args.database, args.resume_frame, args.event_id, args.reason)):
            raise SystemExit(
                "--resume-paper requires --database, --resume-frame, --event-id, --reason"
            )
        print(
            encode(
                resume_paper(
                    args.database,
                    config,
                    args.resume_frame,
                    event_id=args.event_id,
                    reason=args.reason,
                )
            )
        )
        return 0
    if args.capture_market:
        if args.database is None or not args.symbol or len(args.symbol) != 1:
            raise SystemExit("--capture-market requires --database PATH and one --symbol SYMBOL")
        return run_capture(args.database, args.symbol[0], args.samples, args.poll_seconds)
    if args.stream_prices:
        if not args.symbol:
            raise SystemExit("--stream-prices requires at least one --symbol SYMBOL")
        try:
            print(encode(run_stream(args.symbol, args.seconds)))
        except StreamStopped as exc:
            print(encode({"status": "stopped", "reason": str(exc), **exc.summary}))
            return 2
        except (DataError, FeedError) as exc:
            print(encode({"status": "stopped", "reason": str(exc), "orders_authorized": False}))
            return 2
        return 0
    if args.paper_demo:
        if args.database is None:
            raise SystemExit("--paper-demo requires --database PATH; no live execution exists")
        print(encode(run_demo(args.database, config)))
        return 0

    classifier = RegimeClassifier(thresholds_from_config(config))
    assessment = classifier.classify(
        MarketSignals(
            trend=0.05,
            breadth=0.02,
            momentum=-0.03,
            volatility_health=0.04,
            liquidity_health=0.02,
            adx=15.0,
        )
    )
    print("configuration: valid")
    print(f"mode: {config.mode}")
    print(f"universe: top {config.top_n} plus {', '.join(config.include_assets)}")
    print(f"sample regime: {assessment.regime} ({assessment.confidence:.0%} confidence)")
    print("live trading: unavailable by design")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
