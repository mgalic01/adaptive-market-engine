"""Command-line entry point for safe configuration and strategy self-checks."""

from __future__ import annotations

import argparse
from pathlib import Path

from crypto_grid_bot.config import load_config
from crypto_grid_bot.domain import MarketSignals
from crypto_grid_bot.market_data.command import run_capture
from crypto_grid_bot.simulation.control import resume_paper
from crypto_grid_bot.simulation.demo import run_demo
from crypto_grid_bot.simulation.store import encode
from crypto_grid_bot.strategy.regime import RegimeClassifier, RegimeThresholds


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
    parser.add_argument("--symbol", help="explicit Binance spot symbol, e.g. ADAUSDC")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--database", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
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
        if args.database is None or args.symbol is None:
            raise SystemExit("--capture-market requires --database PATH and --symbol SYMBOL")
        return run_capture(args.database, args.symbol, args.samples, args.poll_seconds)
    if args.paper_demo:
        if args.database is None:
            raise SystemExit("--paper-demo requires --database PATH; no live execution exists")
        print(encode(run_demo(args.database, config)))
        return 0

    classifier = RegimeClassifier(
        RegimeThresholds(
            bull=config.bull_threshold,
            bear=config.bear_threshold,
            range_score_limit=config.range_score_limit,
            range_adx_limit=config.range_adx_limit,
            minimum_confidence=config.minimum_confidence,
        )
    )
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
