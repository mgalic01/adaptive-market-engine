# Bob report: market structure perception layer — implementation record

Index: 2026-09-29: Implementation of `src/crypto_grid_bot/strategy/structure.py`.
Market structure perception: swing detection, support/resistance zones, multi-timeframe
structural trend. Written by Bob (owner's desktop IBM Bob session). For agent review.

Script: `src/crypto_grid_bot/strategy/structure.py`
Tests: `tests/test_structure.py`
Test result: **731 passed, 4 skipped, 0 failures** (full suite, Python 3.14.7)
Design docs: `docs/reviews/2026-09-29-owner-market-structure-perception.md`,
             `docs/reviews/2026-09-29-owner-regime-adaptive-grid-spacing.md`

- **Author:** Bob (owner's desktop IBM Bob session), 2026-09-29.
- **Requested by:** owner, 2026-09-29 (conversation recorded in
  `docs/reviews/2026-09-29-owner-market-structure-perception.md`).
- **Status:** implementation complete, tests passing, PR open. Not yet integrated into
  `FeatureEngine` or `Inputs` — that is a separate step requiring a spec amendment.
- **Reserved window:** no market data is fetched or read. Pure computation only.

---

## 1. What was built

A new module `src/crypto_grid_bot/strategy/structure.py` with the following public API:

| Function / Class | Purpose |
|---|---|
| `compute_atr(bars, period)` | Average True Range of the last `period` bars |
| `detect_swing_highs(bars, n)` | Confirmed swing highs: bar i is a high iff strictly highest in [i-n, i+n] |
| `detect_swing_lows(bars, n)` | Confirmed swing lows: bar i is a low iff strictly lowest in [i-n, i+n] |
| `cluster_into_zones(swings, atr, ...)` | Group nearby swing points into structural zones |
| `classify_structural_trend(highs, lows, min_swings)` | BULLISH / BEARISH / RANGING / UNKNOWN from swing sequences |
| `find_fta(price, resistance_zones, support_zones, atr, max_distance_atr)` | Nearest resistance above and support below |
| `analyse_timeframe(bars, current_price, params)` | Full structure analysis for one timeframe |
| `analyse_multi_timeframe(hourly, daily, weekly, price, params)` | Aligned structural view across up to three timeframes |

All functions are pure (no I/O, no state, no randomness). All results are immutable
frozen dataclasses. The `OHLCBar` protocol means any object with `open_ms`, `high`,
`low`, `close` works — including the existing `Kline` from `backtest/klines.py`.

---

## 2. Mathematical decisions and derivations

### 2.1 Swing point detection

**Definition:**  
Bar `i` is a swing high iff `high[i] > high[j]` for all `j` in `[i-n, i-1]` AND all
`j` in `[i+1, i+n]`. Strict inequality on both sides.

**Why strict inequality:**  
Ties mean two bars share the same high. Neither is structurally more significant, so
neither should be labelled a swing. Strict inequality avoids arbitrary tie-breaking.

**Why `n` bars on each side:**  
`n` is the confirmation window. A larger `n` finds fewer but more significant swings
(major turning points). A smaller `n` finds more swings (noise-sensitive). Default `n=3`
is a commonly-used value in technical analysis literature.

**No-look-ahead guarantee:**  
The last `n` bars are never candidates. The function only classifies bars `[n, len-n)`.
In a live context, you would only pass bars that have closed — the last `n` live bars
would not yet be confirmed as swings.

### 2.2 ATR calculation

**Formula:**  
True range of bar `i`:  
`TR(i) = max(high[i] - low[i], |high[i] - prev_close|, |low[i] - prev_close|)`  
For bar 0 (no previous close): `TR(0) = high[0] - low[0]`  
ATR = simple mean of TR over the last `period` bars.

**Why simple mean, not Wilder smoothing:**  
`features.py` uses Wilder smoothing for the running ADX/ATR. Here ATR is used as a
distance unit for zone clustering and FTA search radius — a simple mean of the tail is
sufficient and produces the same order of magnitude. The difference is immaterial for
the intended use.

**Zero ATR:**  
If all `period` bars have identical OHLC (flat price), ATR = 0. This is handled
explicitly: when ATR = 0, the zone merge threshold is 0 (no merging), and the FTA
radius check is bypassed (all zones included). This avoids division-by-zero and
ensures degenerate data doesn't cause silent failures.

### 2.3 Zone clustering

**Merge condition:**  
Two swing points `p1` and `p2` merge into one zone iff:  
`|p1.price - p2.price| < merge_atr × ATR`

**Implementation:**  
Swings are sorted by price. A single pass groups consecutive swings within the
threshold. This is O(N log N) total (dominated by sort). Groups are non-overlapping
and contiguous in price space.

**Zone price:**  
Mean of all member prices. Alternatives considered: median (more robust to outliers),
most-tested price (requires tie-breaking). Mean is simplest and sufficient.

**Zone strength formula:**  
Each member `i` in a group of `N` (sorted by `open_ms`, oldest=0) gets a linear
recency weight:

```
w_i = (1 - recency_weight) + recency_weight × (i / (N - 1))   [N > 1]
w_i = 1.0                                                       [N == 1]
```

With `recency_weight = 0.5`: oldest member gets weight 0.5, newest gets 1.0.

Zone strength:
```
strength = (mean(w_i)) × (1 + log2(N))
```

The `log2(N)` factor makes a zone with 4 tests stronger than one with 2 tests by a
factor of `(1 + log2(4)) / (1 + log2(2)) = 3/2 = 1.5×`. This reflects that a level
tested more times is more significant, but with diminishing returns.

**Verification for N=1:** `strength = 1.0 × (1 + 0) = 1.0` ✓  
**Verification for N=2 with recency_weight=0.5:** mean weight = (0.5 + 1.0)/2 = 0.75;  
`strength = 0.75 × (1 + 1) = 1.5` ✓

### 2.4 Structural trend classification

**Rules (applied to last `min_swings` confirmed highs and lows):**

| Condition | Trend |
|---|---|
| last N highs strictly ascending AND last N lows strictly ascending | BULLISH |
| last N highs strictly descending AND last N lows strictly descending | BEARISH |
| fewer than `min_swings` of either | UNKNOWN |
| all other cases | RANGING |

**Why only the last N:**  
Market structure can change. Using all historical swings would make the classifier
slow to respond to reversals. Using only the last `min_swings` (default 2) means a
single higher high + higher low is enough to signal bullish structure — quick but
noise-sensitive. For more stability, increase `min_swings`.

**Why strict in both highs AND lows:**  
A market is only structurally bullish if buyers are making progress on both fronts —
each peak is higher AND each trough is higher. A market that makes higher highs but
lower lows is potentially a broadening top (increasing volatility, not a trend).

### 2.5 First Trouble Area (FTA)

**Definition:**  
The FTA resistance is the nearest `StructureZone` with `price > current_price` within
`max_distance_atr × ATR` of the current price. Zones are pre-sorted ascending;
the first one above current_price is the nearest.

**Why "just below resistance":**  
Professional traders (and Luka's analysis) place sell targets just below the nearest
resistance rather than at a fixed % above entry. Price approaching a resistance zone
is likely to slow, stall, or reverse — placing the target inside the zone risks
not filling. The bot would use `resistance.price × (1 - small_buffer)` as the sell
target, where `small_buffer` is one tick size.

**FTA search radius:**  
`max_distance_atr × ATR` (default 5× ATR). Zones further than this are not the "first"
trouble — they are too far to be relevant for the current grid level. If no zone
is within radius, the field is None and the caller falls back to geometric spacing.

**Zero ATR bypass:**  
When ATR = 0, max_dist = 0 and the radius check is skipped. All zones above/below
are considered. This ensures degenerate data doesn't silently drop zones.

### 2.6 Multi-timeframe alignment score

**Formula:**  
```
score(tf) = +1.0 if tf.trend == BULLISH
score(tf) = -1.0 if tf.trend == BEARISH
score(tf) =  0.0 if RANGING or UNKNOWN

alignment = sum(score(tf) × weight(tf)) / sum(weight(tf))
            (only over timeframes where data is available)
```

**Weights:** weekly=0.50, daily=0.35, hourly=0.15.

**Rationale for weights:**  
Higher timeframes are more authoritative for structural direction. A weekly bullish
structure that a daily pullback is testing is a correction, not a reversal. The
50/35/15 split assigns majority weight to the weekly trend while still letting daily
and hourly provide meaningful input. These weights are a starting point — they should
be validated empirically.

**Result range:** [-1, +1].  
+1: all available timeframes bullish.  
-1: all bearish.  
0: mixed, or all ranging/unknown, or no data.  
When only one timeframe is available, alignment equals its score (±1 or 0).

---

## 3. What this does NOT do (scope boundaries)

- **Not integrated into `FeatureEngine` or `Inputs`** — the `Inputs` dataclass would
  need new fields (`structure_alignment`, `nearest_resistance`, `nearest_support`).
  That is a spec amendment and requires Claude/Codex review before touching `features.py`.
- **Not a sell-target override** — the grid builder still uses geometric spacing. Using
  FTA as a sell target requires changes to `strategy/grid.py` and `simulation/runner.py`.
  Those are code changes with strategy implications, not documentation changes.
- **Not live market data** — this module is pure computation on whatever bars are passed
  in. Fetching live hourly/weekly bars is a separate concern for the market data layer.
- **Not backtested** — this is an implementation of the structural analysis logic. Whether
  FTA-aware sell targets improve P&L requires a measured backtest comparison, which is
  the natural next step (a Bob task).

---

## 4. Integration path for Claude/Codex

When ready to integrate this into the live strategy:

**Step 1 — Add to `Inputs` dataclass (`backtest/features.py`):**
```python
structure_alignment: float = 0.0  # [-1, +1], from MultiTimeframeStructure
nearest_resistance: float | None = None  # price of nearest FTA resistance, or None
nearest_support: float | None = None  # price of nearest FTA support, or None
```

**Step 2 — Feed into `FeatureEngine.at()`:**
Pass `hourly_bars`, `daily_bars`, `weekly_bars` into `analyse_multi_timeframe()` and
read `.alignment` and `.daily.fta` (or whichever timeframe is used for grid targets).

**Step 3 — Modify `GridBuilder` to accept an optional FTA resistance:**
If `fta_resistance` is provided and lies within the grid's upper half, place the sell
target at `fta_resistance × (1 - tick_size)` instead of the geometric level.

**Step 4 — Add `structure_alignment` as a new signal in `RegimeClassifier`:**
It can be treated like the `trend` signal (already -1 to +1) and given a weight.

**Step 5 — Write a Bob task to measure the impact** on the backtest datasets, compare
FTA-aware sell targets vs geometric targets across V0 and variant A.

---

## 5. Files changed

| File | Change |
|---|---|
| `src/crypto_grid_bot/strategy/structure.py` | New module (348 lines) |
| `tests/test_structure.py` | New test file (55 tests, all passing) |
| `docs/reviews/2026-09-29-owner-market-structure-perception.md` | Owner requirement record |
| `docs/reviews/2026-09-29-owner-regime-adaptive-grid-spacing.md` | Owner direction record (PR #146) |

No existing files were modified.

— IBM Bob (owner's desktop session)
