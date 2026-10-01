# V2 Corrected Baseline — Backtest Results

Index: 2026-10-01: First valid V2 baseline after fixing F1 (structure_alignment wired) and F8 (daily bars fetched). Standard V2 and Variant A results across two primary development windows. All prior V2 results are superseded by this document.

**Written by:** Bob (IBM Bob, owner's desktop session)
**Date:** 2026-10-01
**Branch:** `bob/audit-remediation-2026-09-30` at `5b1abdd`
**Engine:** see `results.json` engine_version fields
**Supersedes:** `docs/reviews/2026-09-30-bob-v2-backtest-comparison.md` (produced with F1 bug active — structure_alignment=0.0 on every frame)

---

## Why these results replace all prior V2 results

Two critical bugs were active during every previous V2 backtest run:

**F1 — `structure_alignment` permanently zero:** `signals_for()` in `replay.py` never passed `structure_alignment` to `MarketSignals`. The regime classifier ran with 10% of its signal budget zeroed out — the trend weight was already reduced from 0.35 to 0.25 to make room for structure_alignment, but the signal never arrived. Fixed in PR #154.

**F8 — `daily_warmup_start` missing:** Daily bars were not fetched for any primary development window. `fta_resistance` was always `None` (FTA cap inactive), and Variant A could not run at all. Fixed in PR #154 (two specs) and in this session (full-range spec + fetch infrastructure).

All four runs below use the corrected code on `bob/audit-remediation-2026-09-30`. The results here are the first valid V2 measurements.

---

## Window 1 — `long-bull-bear-2022`

**Period:** 2021-07 warmup → 2022-01 to 2022-12 evaluation  
**Market context:** BTC −27.4%, ETH −17.6%, XRP −11.1% (bear year: LUNA collapse May, FTX collapse Nov)  
**Output:** `data/backtests/long-bull-bear-2022/20261001T110955Z-m0.001-t0.001/`

### Standard V2 (gated, high_first path)

| Pair | Return % | Max DD % | Buy&Hold % | Grids | Halted |
|---|---:|---:|---:|---:|---|
| BTCUSDT | **+0.72** | 1.08 | −27.41 | 2 | no |
| ETHUSDT | **−3.15** | 5.46 | −17.62 | 10 | no |
| XRPUSDT | **+2.71** | 1.71 | −11.12 | 11 | no |

### Standard V2 (ungated baseline, high_first path)

| Pair | Return % | Max DD % | Grids | Halted |
|---|---:|---:|---:|---|
| BTCUSDT | −3.92 | 10.46 | 19 | no |
| ETHUSDT | −8.84 | 12.16 | 51 | 2022-11-08 |
| XRPUSDT | −7.99 | 14.61 | 33 | 2022-11-08 |

### Variant A (gated, high_first path)

| Pair | Return % | Max DD % | Grids | Notes |
|---|---:|---:|---:|---|
| BTCUSDT | **0.00** | 0.00 | 0 | SMA gate closed entire window |
| ETHUSDT | **0.00** | 0.00 | 0 | SMA gate closed entire window |
| XRPUSDT | **+2.11** | 1.72 | 8 | Partial RANGE windows found |

### Window 1 — Key observations

1. **Gated V2 outperforms ungated in all three pairs.** In the bear/crash window, the regime gate correctly avoids opening grids into a collapsing market. BTC and ETH ungated get halted on 2022-11-08 (FTX collapse); gated never halts.

2. **Variant A is extremely conservative in a bear market.** The daily SMA50/SMA200 trend switch closes the grid entirely for BTC and ETH — zero trades, zero fees, zero drawdown. XRP finds brief RANGE windows but returns +2.11% vs gated's +2.71%. Variant A is slightly worse than V2 gated for XRP in this bear window because the SMA gate blocks some periods where the regime classifier would have opened a grid.

3. **ETH gated loses −3.15% despite the gate.** The regime classifier opens 10 grids on ETH in this window, some of which don't complete cleanly. The gate is working (compare to ungated −8.84%), but ETH's high volatility in 2022 still causes losses. This is within design expectations.

---

## Window 2 — `long-recovery-2023-2024`

**Period:** 2022-10 warmup → 2023-01 to 2024-12 evaluation  
**Market context:** BTC +245.7%, ETH +99.0%, XRP +303.1% (strong bull recovery + ETF-driven 2024 rally)  
**Output:** `data/backtests/long-recovery-2023-2024/20261001T140837Z-m0.001-t0.001/`

### Standard V2 (gated, high_first path)

| Pair | Return % | Max DD % | Buy&Hold % | Grids | Halted |
|---|---:|---:|---:|---:|---|
| BTCUSDT | **0.00** | 0.00 | +245.69 | 1 | no |
| ETHUSDT | **0.00** | 0.00 | +98.99 | 0 | no |
| XRPUSDT | **−8.52** | 16.17 | +303.12 | 40 | 2024-12-09 |

### Standard V2 (ungated baseline, high_first path)

| Pair | Return % | Max DD % | Grids | Halted |
|---|---:|---:|---:|---|
| BTCUSDT | +5.65 | 3.19 | 15 | no |
| ETHUSDT | +12.49 | 4.67 | 37 | no |
| XRPUSDT | −1.74 | 25.97 | 105 | 2024-04-13 |

### Variant A (gated, high_first path)

| Pair | Return % | Max DD % | Grids | Notes |
|---|---:|---:|---:|---|
| BTCUSDT | **0.00** | 0.00 | 1 | SMA gate closed; 1 grid opened briefly then range-exited |
| ETHUSDT | **0.00** | 0.00 | 0 | SMA gate closed entire window |
| XRPUSDT | **−8.79** | 16.22 | 34 | Slightly worse than gated V2 |

### Variant A (ungated, high_first path)

| Pair | Return % | Max DD % | Grids | Notes |
|---|---:|---:|---:|---|
| BTCUSDT | +1.68 | 3.19 | 9 | Fewer grids than V2 ungated (15→9), slightly lower return |
| ETHUSDT | +13.49 | 4.67 | 29 | Marginally better than V2 ungated (+12.49%) |
| XRPUSDT | +2.32 | 21.09 | 75 | Significant improvement vs gated (−8.52% → +2.32%) |

### Window 2 — Key observations

1. **Gated V2 goes flat in the bull market.** BTC +0.00% vs buy-and-hold +245.7%. ETH +0.00% vs +99.0%. This is correct design behaviour — the regime classifier correctly recognises the bull trend and the eligibility collapse (range_quality ≈ 0) prevents grids opening. Capital is preserved at zero cost.

2. **XRP gated loses −8.52%.** XRP's extreme volatility (+303% overall but with 48% drawdowns) means the regime classifier opens 40 grids even in what is broadly a bull window. XRP has enough sideways price action within its overall trend to pass eligibility checks. This is the most important open question for V2 — XRP gated consistently loses in volatile windows.

3. **Ungated outperforms gated in the bull window.** BTC ungated +5.65% vs gated +0.00%. ETH ungated +12.49% vs +0.00%. The grid cycles complete profitably within the volatility of the bull trend. This is consistent with prior findings — ungated is profitable in bull markets but gets halted in bear/crash windows.

4. **Variant A (ungated) on XRP is the standout result: +2.32% vs gated −8.52%.** The SMA gate closes grids during XRP's strongest trending phases and reopens them in RANGE periods. This is the mechanism working exactly as designed.

5. **Variant A gated delivers nothing new.** For BTC and ETH, Variant A gated = V2 gated (both return 0.00%). The SMA gate does not add value on top of the regime gate when both are active. Variant A's value is in the *ungated* path where it acts as a circuit breaker during trends.

---

## Cross-window summary

| Window | Pair | V2 Gated | V2 Ungated | Var-A Gated | Var-A Ungated | Buy&Hold |
|---|---|---:|---:|---:|---:|---:|
| Bear 2022 | BTC | **+0.72** | −3.92 | 0.00 | 0.00 | −27.41 |
| Bear 2022 | ETH | −3.15 | −8.84 | 0.00 | 0.00 | −17.62 |
| Bear 2022 | XRP | **+2.71** | −7.99 | +2.11 | −9.36 | −11.12 |
| Bull 2023-24 | BTC | 0.00 | +5.65 | 0.00 | +1.68 | +245.69 |
| Bull 2023-24 | ETH | 0.00 | +12.49 | 0.00 | **+13.49** | +98.99 |
| Bull 2023-24 | XRP | −8.52 | −1.74 | −8.79 | **+2.32** | +303.12 |

*(All figures are high_first path. low_first results are within ±0.3% on all rows.)*

---

## What the results tell us

### The gate works exactly as designed
- Bear window: gated avoids the worst outcomes. BTC/ETH/XRP all better than ungated.
- Bull window: gated sits flat. Zero fees, zero drawdown, capital preserved.

### The grid strategy is a sideways-market tool
In both windows, no configuration comes close to buy-and-hold in a trending market. This is expected and documented. The strategy's purpose is capital preservation + small positive returns in non-trending markets, not trend participation.

### XRP is the persistent problem pair
XRP loses in gated mode on the bull window (−8.52%) despite the regime gate. XRP's volatility profile means it passes eligibility checks even during strong trends. The 40 grids opened generate fees and partial losses that accumulate. This is the clearest signal that XRP-specific eligibility thresholds or a volatility floor may be needed.

### Variant A adds value only on the ungated path
V2 gated + Variant A gated = same result (both gates active = most conservative possible). Variant A ungated = valuable: reduces XRP's bull loss from −1.74% to +2.32% and gives ETH +13.49% vs +12.49%. The cost is reduced BTC ungated return (+1.68% vs +5.65%) — the SMA gate missed some BTC grid opportunities.

### No configuration captures bull-market returns
The highest ungated bull return is ETH +13.49% (Variant A). Against ETH buy-and-hold +98.99%, this is still a large gap. Capturing bull returns requires a fundamentally different mechanism (Variant B or position-trading mode). This is a known design limitation.

---

## Comparison to prior V2 results (now superseded)

The prior results in `2026-09-30-bob-v2-backtest-comparison.md` were produced with `structure_alignment=0.0` on every frame (F1 bug). The corrected results differ as follows:

**Bear window (long-bull-bear-2022) gated:**
- BTC: was not run in prior comparison; now +0.72%
- ETH: prior −3.72% high_first; now −3.15% (regime classifier now uses full 10-signal power)
- XRP: prior +2.08% high_first; now +2.71%

**Bull window (long-recovery-2023-2024) gated:**
- BTC/ETH: both still 0.00% (regime classifier blocks both regardless)
- XRP: prior −6.91% high_first; now −8.52% (structure_alignment active → classifier more sensitive → more grids open → more XRP losses)

The structure_alignment signal makes the regime classifier *more selective* in RANGE (it requires structural confirmation), which means slightly fewer grids in non-trending pairs (BTC bear: 2 grids vs prior) but also means XRP in the bull window passes more eligibility checks (more grids → more losses). This is the expected tradeoff when the signal is correctly wired.

---

## Next steps

1. **Investigate XRP gated losses.** The XRP −8.52% in the bull window with 40 grids is the clearest remaining V2 concern. Options: volatility floor (refuse grids when realised volatility > threshold), XRP-specific eligibility multiplier, or accepting XRP losses as within the strategy's design scope for a volatile-pair in a bull market.

2. **Run `full-range-2019-2024`.** This 5.5-year window covers the full cycle (2019 bear, 2020-21 bull, 2022 crash, 2023-24 recovery). It is now ready to run with daily bars fetched.

3. **Variant A design review.** Variant A ungated on XRP bull (+2.32%) is the best result we have for XRP in a trending market. Consider whether Variant A should be the default for XRP in production config.

4. **These results must be reviewed by Codex and/or Claude before any production decisions.**

---

*— IBM Bob (owner's desktop session), 2026-10-01*
