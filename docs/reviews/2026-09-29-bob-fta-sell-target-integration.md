# FTA-aware sell targets: cap grid levels below nearest resistance

**Date:** 2026-09-29
**Branch:** bob/fta-sell-target
**Author:** IBM Bob (owner's desktop session)
**Related:** PR #146 (owner direction: regime-adaptive spacing),
             PR #147 (structure.py — swing detection, zone clustering, find_fta)

---

## What was changed

Two files:

1. **`src/crypto_grid_bot/domain.py`** — `GridPlan` gained one new optional field:
   ```python
   fta_resistance_used: float | None = None
   ```
   When `None`, no FTA override was applied. When set, it records the exact
   resistance price that was used to cap the top of the grid.

2. **`src/crypto_grid_bot/strategy/grid.py`** — `GridBuilder.build()` gained one new
   optional keyword argument:
   ```python
   fta_resistance: float | None = None
   ```
   Default `None` preserves the existing behaviour exactly.

---

## Design decision: what the FTA cap does

A plain geometric grid places sell targets at evenly-spaced levels computed from
`lower * ratio^index`.  The top-most sell target may land inside or above a known
resistance zone — a price level where sellers historically cluster and fills are
harder to obtain.

Luka Hranjec Jeri's FTA concept (relayed by owner, 2026-09-29): place the sell
target just *below* the nearest resistance, not at or above it.  Exiting before
the wall, not into it.

**The cap rule:**

```
if lower < fta_resistance <= upper:
    cap = fta_resistance * 0.999
    levels = [min(level, cap) for level in levels]
```

- **Condition `lower < fta_resistance <= upper`**: the FTA must be strictly inside
  the grid for the cap to apply.  If the resistance is above the grid's upper
  bound it is irrelevant (price would have to leave the grid to reach it).  If
  it is at or below the lower bound it is behind us — also irrelevant.  The
  boundary-inclusive check on the upper side (`<= upper`) handles the exact-match
  edge case: if a resistance zone sits exactly at the grid's geometric upper
  bound, capping is still correct.

- **Cap value `fta_resistance * 0.999`**: a 0.1% buffer below the resistance
  price.  Rationale:
  - Small enough not to meaningfully reduce profit (0.1% on the top level).
  - Large enough to avoid placing an order at the exact resistance price, where
    thin liquidity and stop-order clusters increase the chance of a partial fill
    or a fill at a worse price than expected.
  - Consistent with the project's existing fee model (round-trip costs are on
    the order of 0.28%, so 0.1% is well below the minimum cost multiple).

- **Only top levels are affected**: levels already below `fta_resistance` are
  untouched — `min(lvl, cap)` is an identity for any `lvl < cap`.

---

## Separation of concerns

`grid.py` does **not** import `structure.py`.  The caller is responsible for
running `find_fta()` from `structure.py` and passing the resistance price in as
a plain `float`.  This keeps `GridBuilder` a pure geometry module with no
knowledge of candles, swing points, or zones.

---

## 0.999 buffer: explicit derivation

Let `P` be the FTA resistance price and `f = 0.001` (0.1%).

```
cap = P × (1 - f) = P × 0.999
```

A fill at `cap` earns `cap - buy_price` gross.  The fill is `f × P` below the
resistance wall.  For `P = 1.0` and a buy level of `0.90` this means the sell
target moves from `1.000` to `0.999` — a reduction in the cycle profit of 0.1
percentage points on a ~10% spacing.  The change is negligible.

The choice `f = 0.001` is not derived from data.  It is a sensible default
based on the project's fee scale.  If backtesting shows that a larger or smaller
buffer improves fill rates, this constant should be promoted to a `GridBuilder`
constructor parameter.

---

## What callers need to do

To enable FTA-aware targets:

1. Call `find_fta(current_price, resistance_zones, support_zones, atr,
   max_distance_atr)` from `structure.py` (PR #147).
2. If `fta.resistance` is not `None`, pass `fta_resistance=fta.resistance.price`
   to `GridBuilder.build()`.
3. Check `plan.fta_resistance_used` to confirm the cap was applied (it is `None`
   if the resistance fell outside the grid).

---

## Tests added (`tests/test_grid.py`)

Five new test methods cover all branches of the cap logic:

| Test | What it checks |
|---|---|
| `test_fta_none_leaves_levels_unchanged` | `fta_resistance=None` → identical levels, `fta_resistance_used=None` |
| `test_fta_within_grid_caps_top_levels` | FTA inside grid → all levels ≤ cap, levels below FTA unchanged, `fta_resistance_used` recorded |
| `test_fta_above_grid_upper_has_no_effect` | FTA above upper bound → no change, `fta_resistance_used=None` |
| `test_fta_below_or_equal_lower_has_no_effect` | FTA at or below lower bound → no change, `fta_resistance_used=None` |
| `test_fta_exactly_at_upper_bound_applies_cap` | FTA == upper (boundary inclusive) → cap applied |

Full suite result: 731 passed (+ 2 pre-existing failures in `test_documented_hosts.py`
unrelated to this change), 4 skipped, 0 new failures.

---

## Open items for future work

- Promote the `0.999` buffer to a `GridBuilder` constructor parameter once
  backtest data is available to tune it.
- Wire `fta_resistance` into the runner / engine so the FTA is recomputed on
  each grid rebuild (hourly or after a trend-state change).
- Measure whether FTA capping reduces cycle count (fewer fills at the top of
  the range) and whether it improves profit-per-fill enough to compensate.
- Consider applying a symmetric FTA *support* floor to buy targets (not
  implemented here — the buy-side analogue would cap buy levels just above
  the nearest support zone).

— IBM Bob (owner's desktop session)
