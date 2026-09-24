"""Explicit recovery command for an existing paper account; no exchange access."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crypto_grid_bot.config import BotConfig
from crypto_grid_bot.domain import CandidateMetrics, MarketSignals
from crypto_grid_bot.simulation.models import MarketRules, Quote, decimal, timestamp
from crypto_grid_bot.simulation.runner import SCHEMA, Frame, PaperSimulator, SimulationPolicy


def decode_frame(payload: dict[str, Any]) -> Frame:
    quote = dict(payload["quote"])
    for key in ("bid", "ask", "bid_size", "ask_size"):
        quote[key] = decimal(quote[key])
    signals = dict(payload["signals"])
    signals["observed_at"] = timestamp(signals["observed_at"])
    return Frame(
        Quote(**quote),
        MarketSignals(**signals),
        CandidateMetrics(**payload["candidate"]),
        decimal(payload["fair_value"]),
        decimal(payload["atr"]),
    )


def resume_paper(
    database: Path,
    config: BotConfig,
    frame_path: Path,
    *,
    event_id: str,
    reason: str,
) -> dict[str, Any]:
    with frame_path.open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("resume frame exceeds 64 KiB")
    frame = decode_frame(json.loads(raw))
    # The engine supports deterministic historical replay. The operator CLI additionally
    # requires a genuinely current observation rather than a backdated received_at.
    now = datetime.now(UTC)
    for when in (frame.quote.observed_at, frame.quote.received_at):
        if not 0 <= (now - timestamp(when)).total_seconds() <= config.maximum_data_age_seconds:
            raise ValueError("resume requires a current fresh frame")
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT identity FROM state WHERE id=1").fetchone()
        if row is None:
            raise ValueError("missing paper account identity")
        identity = json.loads(row[0])
    finally:
        connection.close()
    if identity["schema"] != SCHEMA:
        raise ValueError(f"resume supports only paper schema {SCHEMA}; no implicit migration")
    rules = dict(identity["rules"])
    for key in (
        "tick_size",
        "quantity_step",
        "minimum_notional",
        "fee_rate",
        "slippage_rate",
        "participation",
    ):
        rules[key] = decimal(rules[key])
    simulator = PaperSimulator(
        database,
        config,
        MarketRules(**rules),
        decimal(identity["initial_cash"]),
        SimulationPolicy(**identity["policy"]),
    )
    try:
        return simulator.resume(frame, event_id=event_id, reason=reason)
    finally:
        simulator.close()
