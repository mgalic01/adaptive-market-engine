"""Synthetic price replay for software testing, never a performance backtest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from crypto_grid_bot.config import BotConfig
from crypto_grid_bot.domain import CandidateMetrics, MarketSignals
from crypto_grid_bot.simulation.models import D, MarketRules, Quote
from crypto_grid_bot.simulation.runner import Frame, PaperSimulator


def demo_frames(cycles: int = 30) -> list[Frame]:
    if not 1 <= cycles <= 1000:
        raise ValueError("demo cycles must be between 1 and 1000")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    frames: list[Frame] = []
    for cycle in range(cycles):
        for phase, bid, ask, size in [
            ("start", "0.02300", "0.02301", "100000"),
            ("partial", "0.02196", "0.02197", "2000"),
            ("buy", "0.02196", "0.02197", "100000"),
            ("sell", "0.02320", "0.02321", "100000"),
        ]:
            when = start + timedelta(seconds=len(frames))
            quote = Quote(
                f"demo/{cycle}/{phase}",
                "DEMOUSDT",
                when.isoformat(),
                when.isoformat(),
                D(bid),
                D(ask),
                D(size),
                D(size),
            )
            signals = MarketSignals(0.02, -0.01, 0.01, 0.02, 0.01, 14, observed_at=when)
            metrics = CandidateMetrics(
                "DEMOUSDT",
                0.95,
                0.95,
                0.95,
                0.95,
                1,
                0,
                float((D(ask) - D(bid)) / D(ask) * 100),
                100,
            )
            frames.append(
                Frame(
                    quote,
                    signals,
                    metrics,
                    D("0.023"),
                    D("0.0005"),
                    allow_new_grid=phase == "start",
                )
            )
    return frames


def run_demo(path: Path, config: BotConfig) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    simulator = PaperSimulator(path, config, MarketRules())
    try:
        for frame in demo_frames():
            simulator.process(frame)
        account = simulator.store.read()
        return {
            "mode": "synthetic paper replay; not a backtest or forecast",
            "initial_quote_units": account.initial_cash,
            "cash": account.cash,
            "inventory": account.inventory,
            "pending_reserve": account.pending,
            "secured_reserve": account.secured,
            "fees": account.fees,
            "cycles": account.cycles,
            "fills": account.fill_count,
            "halt_reason": account.halt or None,
            "live_trading": "unavailable",
        }
    finally:
        simulator.close()
