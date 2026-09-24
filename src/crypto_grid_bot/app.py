"""Command-line entry point for safe configuration and strategy self-checks."""

from __future__ import annotations

import argparse
from pathlib import Path

from crypto_grid_bot.config import load_config
from crypto_grid_bot.domain import MarketSignals
from crypto_grid_bot.strategy.regime import RegimeClassifier, RegimeThresholds


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adaptive crypto grid bot")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--self-check", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    config = load_config(args.config)
    if not args.self_check:
        raise SystemExit("Milestone 1 only supports --self-check; live execution is unavailable")

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
