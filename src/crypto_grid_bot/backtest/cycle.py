"""Bitcoin halving cycle context for experiment variant H (spec v1 §3 H).

Computes the phase ``m`` (whole calendar months since the most recent halving at or
before an observation), determines which H band applies, and decides whether H2 or H3
is active given the pair's SMA200 and ATH.

The halving timestamps are historical facts fixed in the spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

# Halving timestamps fixed in spec v1 §3 H (UTC).
_HALVINGS: tuple[datetime, ...] = (
    datetime(2016, 7, 9, 16, 46, 13, tzinfo=UTC),
    datetime(2020, 5, 11, 19, 23, 43, tzinfo=UTC),
    datetime(2024, 4, 20, 0, 9, 27, tzinfo=UTC),
)

# Phase bands (half-open).
_H2_LO, _H2_HI = 18, 30  # [18, 30)
_H3_LO, _H3_HI = 30, 48  # [30, 48)

# H2 threshold: C > 1.60 × SMA200 → no new grid + 2h outside-range threshold.
H2_PRICE_MULTIPLE = Decimal("1.60")
# H2 outside-range threshold in seconds (2 hours).
H2_OUTSIDE_RANGE_SECONDS = 7_200
# H3 threshold: C < 0.50 × ATH → opportunity score minimum lowered by 0.10.
H3_PRICE_MULTIPLE = Decimal("0.50")
H3_SCORE_RELAXATION = 0.10


def _halving_before(obs: datetime) -> datetime:
    """The most recent halving at or before ``obs``."""
    result = _HALVINGS[0]
    for h in _HALVINGS:
        if h <= obs:
            result = h
    return result


def phase_m(obs: datetime) -> int:
    """Whole calendar months since the most recent halving at or before ``obs``.

    Formula: (year - year_h) * 12 + (month - month_h), minus 1 if the observation's
    day-of-month and time of day are earlier than the halving's.
    """
    h = _halving_before(obs)
    m = (obs.year - h.year) * 12 + (obs.month - h.month)
    # Subtract 1 if the observation has not yet passed the anniversary instant
    # (day-of-month earlier, or same day but earlier time).
    if obs.day < h.day or (obs.day == h.day and obs.time() < h.time()):
        m -= 1
    return m


@dataclass(frozen=True)
class CycleSignal:
    """H2/H3 state for one observation."""

    phase: int
    # H2: True when m in [18, 30) and C > 1.60 × SMA200.
    h2_active: bool
    # H3: True when m in [30, 48) and C < 0.50 × ATH; False when ATH unavailable.
    h3_active: bool
    # Whether the pair's ATH is available (daily data back to the halving).
    ath_available: bool


def cycle_signal(
    obs_ms: int,
    close: Decimal,
    sma200: Decimal | None,
    ath: Decimal | None,
) -> CycleSignal:
    """Compute the H2/H3 signal at observation time ``obs_ms`` (Unix milliseconds).

    ``sma200`` is the pair's SMA200 computed from completed daily bars before ``obs_ms``.
    None when fewer than 200 completed bars are available.
    ``ath`` is the highest completed daily close since the most recent halving, or None
    when daily data does not reach back to the halving (H3 then never activates).
    """
    obs = datetime.fromtimestamp(obs_ms / 1000, UTC)
    m = phase_m(obs)
    ath_available = ath is not None
    h2 = False
    h3 = False
    if _H2_LO <= m < _H2_HI and sma200 is not None and sma200 > 0:
        h2 = close > H2_PRICE_MULTIPLE * sma200
    if _H3_LO <= m < _H3_HI and ath is not None and ath > 0:
        h3 = close < H3_PRICE_MULTIPLE * ath
    return CycleSignal(m, h2, h3, ath_available)


def compute_sma200(daily_bars: list, obs_ms: int) -> Decimal | None:
    """SMA200 from the 200 most recently completed daily bars before ``obs_ms``.

    ``daily_bars`` is a list of Kline objects sorted ascending by open_ms. Returns None
    when fewer than 200 completed daily bars precede ``obs_ms``.
    """
    completed = [k for k in daily_bars if k.open_ms < obs_ms]
    if len(completed) < 200:
        return None
    last_200 = completed[-200:]
    return sum((k.close for k in last_200), Decimal(0)) / 200


def compute_ath(daily_bars: list, obs_ms: int) -> Decimal | None:
    """Highest completed daily close since the most recent halving at or before ``obs_ms``.

    Returns None when daily data does not reach back to the halving (i.e. the first
    bar's open_ms is after the halving's timestamp in milliseconds).
    """
    obs = datetime.fromtimestamp(obs_ms / 1000, UTC)
    h = _halving_before(obs)
    h_ms = int(h.timestamp() * 1000)
    completed = [k for k in daily_bars if k.open_ms < obs_ms]
    since_halving = [k for k in completed if k.open_ms >= h_ms]
    if not completed or completed[0].open_ms > h_ms:
        return None  # data doesn't reach back to the halving
    if not since_halving:
        return None
    return max(k.close for k in since_halving)
