"""Market structure perception: swing points, support/resistance zones, and
multi-timeframe structural state.

**What this module does:**
Given a sequence of OHLC candles (any timeframe), it:

1. Detects *swing highs* and *swing lows* — bars that are locally extreme over a
   symmetric look-back/look-forward window of ``n`` bars on each side.
2. Clusters nearby swing points into *structural zones* — price levels where the market
   has previously reversed, weighted by recency and test-count.
3. Classifies the *structural trend* on this timeframe — bullish (higher highs and
   higher lows), bearish (lower highs and lower lows), or ranging.
4. Identifies the *first trouble area* (FTA) above and below the current price — the
   nearest resistance zone above and the nearest support zone below.

**Design principles (for reviewers):**
- Pure functions and immutable dataclasses only. No I/O, no randomness, no state.
- Decimal arithmetic is NOT used here: these are structural heuristics, not accounting.
  float is sufficient and consistent with the rest of ``features.py``.
- Every public function is deterministic: the same candles always produce the same result.
- No look-ahead: swing detection requires ``n`` bars *after* the candidate bar, so the
  last ``n`` bars of any sequence are never classified (they are too recent to confirm).
- Thresholds are explicit parameters, never magic numbers inside logic.

**Mathematical decisions (see agent report for full derivation):**
- Swing detection: a bar at index ``i`` is a swing high iff
  ``high[i] > max(high[i-n:i])`` and ``high[i] > max(high[i+1:i+n+1])``.
  Strict inequality on both sides; ties are not swings.
- Zone clustering: two swing points merge into one zone if their prices differ by less
  than ``merge_atr`` × ATR. The zone's price is the mean of its members.
- Zone strength: (mean of linear recency weights) × (1 + log2(test_count)); see
  ``cluster_into_zones``. The mean weight depends only on the member count, so in
  effect strength grows with the number of tests alone. No decision reads it yet.
- Structural trend: computed from the last ``min_swings`` confirmed swing highs and lows
  separately. Bullish iff the last two swing lows are ascending AND the last two swing
  highs are ascending. Bearish iff both are descending. Ranging otherwise.
- Multi-timeframe alignment score: mean of per-timeframe scores where BULL=+1,
  BEAR=-1, RANGE=0, UNKNOWN=0. Weighted by timeframe importance.

**References:**
- Luka Hranjec Jeri's analysis, 2026-09-29 (relayed by owner): FTA concept
- Owner conversation, 2026-09-29: requirement for multi-timeframe structure
- docs/reviews/2026-09-29-owner-market-structure-perception.md: design rationale
- docs/reviews/2026-09-29-bob-market-structure-implementation.md: full agent report
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

# ---------------------------------------------------------------------------
# Protocols — any OHLC object satisfying these can be passed in
# ---------------------------------------------------------------------------


class OHLCBar(Protocol):
    """Minimal OHLC interface. ``open_ms`` is the bar's UTC open timestamp in ms."""

    @property
    def open_ms(self) -> int: ...

    @property
    def high(self) -> float: ...

    @property
    def low(self) -> float: ...

    @property
    def close(self) -> float: ...


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class StructuralTrend(StrEnum):
    BULLISH = "bullish"  # higher highs AND higher lows
    BEARISH = "bearish"  # lower highs AND lower lows
    RANGING = "ranging"  # mixed / oscillating
    UNKNOWN = "unknown"  # not enough confirmed swing points yet


# ---------------------------------------------------------------------------
# Immutable result objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SwingPoint:
    """A confirmed structural pivot.

    ``index`` is the position in the original candle sequence.
    ``open_ms`` is the bar's UTC open timestamp (ms).
    ``price`` is the high (for swing highs) or the low (for swing lows).
    ``is_high`` is True for swing highs, False for swing lows.
    """

    index: int
    open_ms: int
    price: float
    is_high: bool


@dataclass(frozen=True, slots=True)
class StructureZone:
    """A support or resistance zone derived from one or more swing points.

    ``price`` is the mean price of all contributing swing points.
    ``is_resistance`` is True for resistance (from swing highs), False for support
    (from swing lows).
    ``strength`` is >= 1.0; higher means more tests or more recent.
    ``test_count`` is the number of swing points that contributed.
    ``latest_open_ms`` is the most recent contributing bar's open timestamp.
    """

    price: float
    is_resistance: bool
    strength: float
    test_count: int
    latest_open_ms: int


@dataclass(frozen=True, slots=True)
class StructureLevel:
    """The nearest resistance above and support below the current price.

    Either field may be None if no zone exists on that side within
    ``max_distance_atr`` × ATR of the current price.
    """

    resistance: StructureZone | None  # nearest zone above current price
    support: StructureZone | None  # nearest zone below current price


@dataclass(frozen=True, slots=True)
class TimeframeStructure:
    """Full structural picture for one timeframe.

    ``trend`` is the structural trend.
    ``zones`` is all detected zones, sorted by price ascending.
    ``fta`` is the nearest actionable levels around the current price.
    ``swing_highs`` and ``swing_lows`` are the confirmed swing points, most recent last.
    ``atr`` is the ATR of the last ``atr_period`` candles (used for zone clustering).
    """

    trend: StructuralTrend
    zones: tuple[StructureZone, ...]
    fta: StructureLevel
    swing_highs: tuple[SwingPoint, ...]
    swing_lows: tuple[SwingPoint, ...]
    atr: float


@dataclass(frozen=True, slots=True)
class MultiTimeframeStructure:
    """Aligned structural view across up to three timeframes.

    Fields are None when the timeframe's data was not supplied or was too short.
    ``alignment`` is a score in [-1, +1]: +1 means all timeframes bullish,
    -1 means all bearish, 0 means mixed or all ranging/unknown.
    """

    hourly: TimeframeStructure | None
    daily: TimeframeStructure | None
    weekly: TimeframeStructure | None
    alignment: float  # [-1, +1]


# ---------------------------------------------------------------------------
# Thresholds — all parameters explicit, no magic numbers in logic
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StructureParams:
    """All tunable parameters for structure detection.

    ``swing_n``: bars on each side required to confirm a swing point (default 3).
        Higher = fewer but stronger swings.
    ``merge_atr``: two swing points within this many ATRs merge into one zone (default 0.5).
    ``max_distance_atr``: FTA search radius in ATRs (default 5.0).
    ``min_swings``: minimum confirmed swing points needed on each side to classify trend
        (default 2 — need at least two highs and two lows).
    ``atr_period``: number of bars for ATR calculation (default 14).
    ``zone_recency_weight``: weight given to the most recent swing vs the oldest when
        computing zone strength. The oldest gets (1 - zone_recency_weight) (default 0.5).
    """

    swing_n: int = 3
    merge_atr: float = 0.5
    max_distance_atr: float = 5.0
    min_swings: int = 2
    atr_period: int = 14
    zone_recency_weight: float = 0.5

    def __post_init__(self) -> None:
        if self.swing_n < 1:
            raise ValueError("swing_n must be at least 1")
        if self.merge_atr <= 0:
            raise ValueError("merge_atr must be positive")
        if self.max_distance_atr <= 0:
            raise ValueError("max_distance_atr must be positive")
        if self.min_swings < 2:
            raise ValueError("min_swings must be at least 2")
        if self.atr_period < 1:
            raise ValueError("atr_period must be at least 1")
        if not 0.0 <= self.zone_recency_weight <= 1.0:
            raise ValueError("zone_recency_weight must be in [0, 1]")


# ---------------------------------------------------------------------------
# Core calculations
# ---------------------------------------------------------------------------


def _true_range(bars: Sequence[OHLCBar], i: int) -> float:
    """True range of bar i. Uses previous close if available, else high-low."""
    if i == 0:
        return bars[i].high - bars[i].low
    prev_close = bars[i - 1].close
    return max(
        bars[i].high - bars[i].low,
        abs(bars[i].high - prev_close),
        abs(bars[i].low - prev_close),
    )


def compute_atr(bars: Sequence[OHLCBar], period: int) -> float:
    """Average True Range of the last ``period`` bars: the simple mean of their true
    ranges (not Wilder smoothing, unlike the ADX in features.py).

    Returns 0.0 if fewer than ``period`` bars are available.
    """
    n = len(bars)
    if n < period:
        return 0.0
    total = sum(_true_range(bars, i) for i in range(n - period, n))
    return total / period


def detect_swing_highs(bars: Sequence[OHLCBar], n: int) -> list[SwingPoint]:
    """Confirmed swing highs in ``bars``.

    Bar i is a swing high iff:
      bars[i].high > bars[j].high  for all j in [i-n, i-1]   (left side)
      bars[i].high > bars[j].high  for all j in [i+1, i+n]   (right side)

    The first n and last n bars are never candidates (insufficient context).
    Strict inequality: ties do not produce a swing.
    """
    result: list[SwingPoint] = []
    highs = [b.high for b in bars]
    length = len(highs)
    for i in range(n, length - n):
        candidate = highs[i]
        if all(candidate > highs[j] for j in range(i - n, i)) and all(
            candidate > highs[j] for j in range(i + 1, i + n + 1)
        ):
            result.append(
                SwingPoint(
                    index=i,
                    open_ms=bars[i].open_ms,
                    price=candidate,
                    is_high=True,
                )
            )
    return result


def detect_swing_lows(bars: Sequence[OHLCBar], n: int) -> list[SwingPoint]:
    """Confirmed swing lows in ``bars``.

    Bar i is a swing low iff:
      bars[i].low < bars[j].low  for all j in [i-n, i-1]
      bars[i].low < bars[j].low  for all j in [i+1, i+n]
    """
    result: list[SwingPoint] = []
    lows = [b.low for b in bars]
    length = len(lows)
    for i in range(n, length - n):
        candidate = lows[i]
        if all(candidate < lows[j] for j in range(i - n, i)) and all(
            candidate < lows[j] for j in range(i + 1, i + n + 1)
        ):
            result.append(
                SwingPoint(
                    index=i,
                    open_ms=bars[i].open_ms,
                    price=candidate,
                    is_high=False,
                )
            )
    return result


def cluster_into_zones(
    swings: list[SwingPoint],
    atr: float,
    merge_atr: float,
    is_resistance: bool,
    recency_weight: float,
) -> list[StructureZone]:
    """Group nearby swing points into structural zones.

    Two swings merge if their prices differ by less than ``merge_atr × atr``.
    Zone price = mean of member prices.
    Zone strength formula:
      Each member i (0=oldest, N-1=most recent, by open time) gets a linear weight:
        w_i = (1 - recency_weight) + recency_weight × (i / (N - 1))   [N > 1]
        w_i = 1.0   [N == 1]
      strength = sum(w_i) / N × (1 + log2(N))   [more tests = stronger zone]
    The sum of the weights is the same whatever the members' times, so strength is
    (1 - recency_weight / 2) × (1 + log2(N)) for N > 1: it does not reward a recent test.

    If atr == 0 (degenerate data), merge threshold is 0 and no merging occurs.
    Returns zones sorted by price ascending.
    """
    if not swings:
        return []

    # Sort by price so we can do a single-pass merge
    sorted_swings = sorted(swings, key=lambda s: s.price)
    threshold = merge_atr * atr  # 0 when atr==0 -> no merging

    groups: list[list[SwingPoint]] = []
    current_group: list[SwingPoint] = [sorted_swings[0]]

    for swing in sorted_swings[1:]:
        if threshold > 0 and (swing.price - current_group[0].price) < threshold:
            current_group.append(swing)
        else:
            groups.append(current_group)
            current_group = [swing]
    groups.append(current_group)

    zones: list[StructureZone] = []
    for group in groups:
        n = len(group)
        zone_price = sum(s.price for s in group) / n
        # w_i belongs to the i-th member by open time; only the sum is used, and it is
        # the same in any order, so the members need not be sorted.
        if n == 1:
            weights = [1.0]
        else:
            weights = [(1.0 - recency_weight) + recency_weight * (i / (n - 1)) for i in range(n)]
        strength = (sum(weights) / n) * (1.0 + math.log2(n))
        latest = max(s.open_ms for s in group)
        zones.append(
            StructureZone(
                price=zone_price,
                is_resistance=is_resistance,
                strength=strength,
                test_count=n,
                latest_open_ms=latest,
            )
        )

    zones.sort(key=lambda z: z.price)
    return zones


def classify_structural_trend(
    highs: list[SwingPoint],
    lows: list[SwingPoint],
    min_swings: int,
) -> StructuralTrend:
    """Structural trend from the sequence of confirmed swing highs and lows.

    Requires at least ``min_swings`` confirmed highs AND ``min_swings`` confirmed lows.

    Logic (uses only the last ``min_swings`` of each):
    - Take last N swing highs (HH = higher highs if ascending, LH = lower highs if descending)
    - Take last N swing lows  (HL = higher lows if ascending, LL = lower lows if descending)
    - BULLISH  iff last N highs are strictly ascending AND last N lows are strictly ascending
    - BEARISH  iff last N highs are strictly descending AND last N lows are strictly descending
    - RANGING  otherwise (mixed signals)
    - UNKNOWN  if not enough swings
    """
    if len(highs) < min_swings or len(lows) < min_swings:
        return StructuralTrend.UNKNOWN

    last_highs = [s.price for s in highs[-min_swings:]]
    last_lows = [s.price for s in lows[-min_swings:]]

    highs_ascending = all(b > a for a, b in zip(last_highs, last_highs[1:], strict=False))
    highs_descending = all(b < a for a, b in zip(last_highs, last_highs[1:], strict=False))
    lows_ascending = all(b > a for a, b in zip(last_lows, last_lows[1:], strict=False))
    lows_descending = all(b < a for a, b in zip(last_lows, last_lows[1:], strict=False))

    if highs_ascending and lows_ascending:
        return StructuralTrend.BULLISH
    if highs_descending and lows_descending:
        return StructuralTrend.BEARISH
    return StructuralTrend.RANGING


def find_fta(
    current_price: float,
    resistance_zones: list[StructureZone],
    support_zones: list[StructureZone],
    atr: float,
    max_distance_atr: float,
) -> StructureLevel:
    """Nearest resistance above and support below ``current_price``.

    Search radius: ``max_distance_atr × atr``. If no zone found within that radius,
    the field is None. Zones are sorted by price; we want the closest one on each side.
    """
    max_dist = max_distance_atr * atr

    resistance = None
    for zone in resistance_zones:
        if zone.price > current_price:
            if max_dist == 0 or (zone.price - current_price) <= max_dist:
                resistance = zone
            break  # zones are sorted ascending; first above is closest

    support = None
    for zone in reversed(support_zones):
        if zone.price < current_price:
            if max_dist == 0 or (current_price - zone.price) <= max_dist:
                support = zone
            break  # zones sorted ascending; last below is closest

    return StructureLevel(resistance=resistance, support=support)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def analyse_timeframe(
    bars: Sequence[OHLCBar],
    current_price: float,
    params: StructureParams | None = None,
) -> TimeframeStructure | None:
    """Full structure analysis for one timeframe.

    Returns None if bars is empty or too short to compute ATR.
    ``current_price`` is used only for FTA search (point-in-time; not from bars).
    """
    if params is None:
        params = StructureParams()

    if not bars or len(bars) < params.atr_period + params.swing_n * 2:
        return None

    atr = compute_atr(bars, params.atr_period)

    swing_highs = detect_swing_highs(bars, params.swing_n)
    swing_lows = detect_swing_lows(bars, params.swing_n)

    resistance_zones = cluster_into_zones(
        swing_highs,
        atr,
        params.merge_atr,
        is_resistance=True,
        recency_weight=params.zone_recency_weight,
    )
    support_zones = cluster_into_zones(
        swing_lows,
        atr,
        params.merge_atr,
        is_resistance=False,
        recency_weight=params.zone_recency_weight,
    )

    all_zones = sorted(resistance_zones + support_zones, key=lambda z: z.price)

    trend = classify_structural_trend(swing_highs, swing_lows, params.min_swings)

    fta = find_fta(current_price, resistance_zones, support_zones, atr, params.max_distance_atr)

    return TimeframeStructure(
        trend=trend,
        zones=tuple(all_zones),
        fta=fta,
        swing_highs=tuple(swing_highs),
        swing_lows=tuple(swing_lows),
        atr=atr,
    )


def analyse_multi_timeframe(
    hourly_bars: Sequence[OHLCBar] | None,
    daily_bars: Sequence[OHLCBar] | None,
    weekly_bars: Sequence[OHLCBar] | None,
    current_price: float,
    params: StructureParams | None = None,
) -> MultiTimeframeStructure:
    """Aligned structure across hourly, daily and weekly timeframes.

    Any timeframe can be None or empty — it is skipped and its field is None.
    ``alignment`` weights: weekly 0.5, daily 0.35, hourly 0.15.
    These reflect that higher timeframes are more authoritative for structural direction.
    """
    if params is None:
        params = StructureParams()

    hourly = analyse_timeframe(hourly_bars, current_price, params) if hourly_bars else None
    daily = analyse_timeframe(daily_bars, current_price, params) if daily_bars else None
    weekly = analyse_timeframe(weekly_bars, current_price, params) if weekly_bars else None

    # Alignment score: BULL=+1, BEAR=-1, RANGING/UNKNOWN=0
    def score(tf: TimeframeStructure | None) -> float | None:
        if tf is None:
            return None
        if tf.trend == StructuralTrend.BULLISH:
            return 1.0
        if tf.trend == StructuralTrend.BEARISH:
            return -1.0
        return 0.0

    weights = [(score(hourly), 0.15), (score(daily), 0.35), (score(weekly), 0.50)]
    active = [(s, w) for s, w in weights if s is not None]
    if active:
        total_weight = sum(w for _, w in active)
        alignment = sum(s * w for s, w in active) / total_weight
    else:
        alignment = 0.0

    return MultiTimeframeStructure(
        hourly=hourly,
        daily=daily,
        weekly=weekly,
        alignment=alignment,
    )
