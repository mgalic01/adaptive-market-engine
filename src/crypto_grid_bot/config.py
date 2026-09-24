"""Configuration loading with fail-closed validation."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Raised when a configuration violates a safety invariant."""


@dataclass(frozen=True, slots=True)
class BotConfig:
    mode: str
    top_n: int
    include_assets: tuple[str, ...]
    maximum_active_grids: int
    minimum_confidence: float
    bull_threshold: float
    bear_threshold: float
    range_score_limit: float
    range_adx_limit: float
    minimum_input_quality: float
    range_dispersion_limit: float
    minimum_opportunity_score: float
    maximum_news_risk: float
    maximum_spread_pct: float
    minimum_depth_multiple: float
    minimum_levels: int
    maximum_levels: int
    minimum_grid_cost_multiple: float
    range_atr_multiple: float
    daily_loss_pause_pct: float
    soft_drawdown_pct: float
    hard_drawdown_pct: float
    maximum_data_age_seconds: int
    reserve_fraction: float
    minimum_transfer_quote: float
    rotation_improvement: float
    rotation_confirmation_cycles: int
    rotation_cost_multiple: float
    rotation_cooldown_hours: int


def _table(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ConfigurationError(f"Missing [{name}] configuration section")
    return value


def load_config(path: str | Path) -> BotConfig:
    config_path = Path(path)
    with config_path.open("rb") as config_file:
        try:
            raw = tomllib.load(config_file)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigurationError(f"Invalid TOML: {exc}") from exc

    _validate_schema(raw)

    bot = _table(raw, "bot")
    universe = _table(raw, "universe")
    regime = _table(raw, "regime")
    opportunity = _table(raw, "opportunity")
    grid = _table(raw, "grid")
    rotation = _table(raw, "rotation")
    risk = _table(raw, "risk")
    vault = _table(raw, "profit_vault")

    config = BotConfig(
        mode=str(bot["mode"]),
        top_n=int(universe["top_n"]),
        include_assets=tuple(str(asset).upper() for asset in universe["include_assets"]),
        maximum_active_grids=int(universe["maximum_active_grids"]),
        minimum_confidence=float(regime["minimum_confidence"]),
        bull_threshold=float(regime["bull_threshold"]),
        bear_threshold=float(regime["bear_threshold"]),
        range_score_limit=float(regime["range_score_limit"]),
        range_adx_limit=float(regime["range_adx_limit"]),
        minimum_input_quality=float(regime["minimum_input_quality"]),
        range_dispersion_limit=float(regime["range_dispersion_limit"]),
        minimum_opportunity_score=float(opportunity["minimum_score"]),
        maximum_news_risk=float(opportunity["maximum_news_risk"]),
        maximum_spread_pct=float(opportunity["maximum_spread_pct"]),
        minimum_depth_multiple=float(opportunity["minimum_depth_multiple"]),
        minimum_levels=int(grid["minimum_levels"]),
        maximum_levels=int(grid["maximum_levels"]),
        minimum_grid_cost_multiple=float(grid["minimum_cost_multiple"]),
        range_atr_multiple=float(grid["range_atr_multiple"]),
        daily_loss_pause_pct=float(risk["daily_loss_pause_pct"]),
        soft_drawdown_pct=float(risk["soft_drawdown_pct"]),
        hard_drawdown_pct=float(risk["hard_drawdown_pct"]),
        maximum_data_age_seconds=int(risk["maximum_data_age_seconds"]),
        reserve_fraction=float(vault["reserve_fraction"]),
        minimum_transfer_quote=float(vault["minimum_transfer_quote"]),
        rotation_improvement=float(rotation["minimum_relative_improvement"]),
        rotation_confirmation_cycles=int(rotation["confirmation_cycles"]),
        rotation_cost_multiple=float(rotation["minimum_cost_multiple"]),
        rotation_cooldown_hours=int(rotation["cooldown_hours"]),
    )
    _validate(config)
    return config


def _validate(config: BotConfig) -> None:
    if config.mode != "paper":
        raise ConfigurationError("This version supports paper mode only")
    if config.top_n != 100 or "NIGHT" not in config.include_assets:
        raise ConfigurationError("Universe must contain the top 100 plus NIGHT")
    if not 0.5 <= config.minimum_confidence < 1.0:
        raise ConfigurationError("minimum_confidence must be at least 0.5 and below 1.0")
    if not 0.0 < config.minimum_input_quality <= 1.0:
        raise ConfigurationError("minimum_input_quality must be above 0 and at most 1")
    if not 0.0 < config.range_dispersion_limit <= 1.0:
        raise ConfigurationError("range_dispersion_limit must be above 0 and at most 1")
    if config.reserve_fraction != 0.5:
        raise ConfigurationError("reserve_fraction must remain exactly 0.5")
    if not 0.0 < config.daily_loss_pause_pct < config.soft_drawdown_pct:
        raise ConfigurationError("daily loss limit must be below soft drawdown")
    if not config.soft_drawdown_pct < config.hard_drawdown_pct < 1.0:
        raise ConfigurationError("soft drawdown must be below hard drawdown")
    if config.minimum_levels < 2 or config.maximum_levels < config.minimum_levels:
        raise ConfigurationError("grid level bounds are invalid")
    if not 1 <= config.maximum_active_grids <= 5:
        raise ConfigurationError("maximum_active_grids must be between 1 and 5")
    if not -1 <= config.bear_threshold < 0 < config.bull_threshold <= 1:
        raise ConfigurationError("invalid bull/bear thresholds")
    if not 0 <= config.range_score_limit < min(config.bull_threshold, -config.bear_threshold):
        raise ConfigurationError("range threshold must not overlap bull/bear thresholds")
    if not 0 < config.range_adx_limit <= 100:
        raise ConfigurationError("invalid range ADX threshold")
    if not 0 < config.minimum_opportunity_score <= 1 or not 0 <= config.maximum_news_risk <= 1:
        raise ConfigurationError("invalid opportunity thresholds")
    if config.minimum_grid_cost_multiple < 1 or config.rotation_cost_multiple < 1:
        raise ConfigurationError("cost multiples must be at least one")
    for name in (
        "maximum_spread_pct",
        "minimum_depth_multiple",
        "range_atr_multiple",
        "maximum_data_age_seconds",
        "minimum_transfer_quote",
        "rotation_improvement",
        "rotation_confirmation_cycles",
        "rotation_cooldown_hours",
    ):
        if getattr(config, name) <= 0:
            raise ConfigurationError(f"{name} must be positive")


def _validate_schema(raw: dict[str, Any]) -> None:
    """Reject misspelled, unused, missing, non-finite, and mistyped settings."""
    schema: dict[str, dict[str, type]] = {
        "bot": {"mode": str},
        "universe": {"top_n": int, "include_assets": list, "maximum_active_grids": int},
        "regime": {
            "bull_threshold": float,
            "bear_threshold": float,
            "range_score_limit": float,
            "range_adx_limit": float,
            "minimum_confidence": float,
            "minimum_input_quality": float,
            "range_dispersion_limit": float,
        },
        "opportunity": {
            "minimum_score": float,
            "maximum_news_risk": float,
            "maximum_spread_pct": float,
            "minimum_depth_multiple": float,
        },
        "grid": {
            "minimum_levels": int,
            "maximum_levels": int,
            "minimum_cost_multiple": float,
            "range_atr_multiple": float,
        },
        "rotation": {
            "minimum_relative_improvement": float,
            "confirmation_cycles": int,
            "minimum_cost_multiple": float,
            "cooldown_hours": int,
        },
        "risk": {
            "daily_loss_pause_pct": float,
            "soft_drawdown_pct": float,
            "hard_drawdown_pct": float,
            "maximum_data_age_seconds": int,
        },
        "profit_vault": {"reserve_fraction": float, "minimum_transfer_quote": float},
    }
    if set(raw) != set(schema):
        raise ConfigurationError("configuration contains missing or unknown sections")
    for section, fields in schema.items():
        values = _table(raw, section)
        if set(values) != set(fields):
            raise ConfigurationError(f"[{section}] contains missing or unknown options")
        for key, expected in fields.items():
            value = values[key]
            valid = type(value) in (int, float) if expected is float else type(value) is expected
            if not valid:
                raise ConfigurationError(f"{section}.{key} has an invalid type")
            if expected in (int, float) and not isfinite(value):
                raise ConfigurationError(f"{section}.{key} must be finite")
        if section == "universe" and (
            not values["include_assets"]
            or any(
                not isinstance(asset, str) or not asset.strip()
                for asset in values["include_assets"]
            )
        ):
            raise ConfigurationError("include_assets must be a non-empty list of asset names")
