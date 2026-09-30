# V2 master strategy proposal: multi-timeframe, multi-mode trading architecture

Index: 2026-09-30 owner direction consolidated. Fast grid (minutes–5h), slow grid (1–2 days), position hold (bear accumulation). Full market perception layer. 4-year cycle awareness. All owner direction from 2026-09-30 session. Owner decisions required before implementation.

- **Recorded by:** Bob (IBM Bob, owner's desktop session), 2026-09-30
- **Status:** Master proposal consolidating all owner direction from this session.
  Supersedes the individual proposals in `2026-09-30-owner-position-trading-proposal.md`
  and `2026-09-30-owner-live-market-data-proposal.md` — those remain as supporting
  detail. This document is the single reference for Claude and Codex.
- **Not a spec amendment. Not registered trials. Owner decisions required (§7).**

---

## 1. What the data told us (the honest diagnosis)

From four backtest windows across 2022–2024:

**Where we lose money:**
- Opening grids into the beginning of a trend move (regime classifier too slow — 6h ATR lag)
- Opportunity score bar set too high: bot passes on 93% of setups, sits in cash
- More grids in a trending market = more losses (ungated XRP: 22 grids, −3.61% vs gated 7 grids, +4.67%)
- No participation in bull markets: BTC/ETH earn 0% while buy-and-hold earns 245%/99%
- Single-speed bot treating XRP and BTC identically (they are completely different)

**Where we make money:**
- Short windows of sideways oscillation within a larger trend — all 14 XRP cycles in week 38/2022 completed in one week of genuine ranging
- Altcoins (XRP, SOL) oscillate faster and deeper → grid cycling works better than on BTC/ETH
- Gated strategy avoids all catastrophic halts (ungated ETH −18%, halted; gated ETH −2%)
- Low grid count + high cycle completion rate > high grid count + low completion rate

**The core problem in one sentence:**
The bot is a single-speed, single-timeframe instrument. It treats XRP the same as BTC and a bear market the same as a range market. It needs to know which animal it's dealing with and respond differently.

---

## 2. The three-mode architecture

The owner confirmed three distinct operating modes, running simultaneously with separate capital allocations:

### Mode A — Fast grid (minutes to 5 hours max)

**Target pairs:** high-volatility alts — XRP, SOL, DOGE, LINK, ADA class
**What it catches:** the red candles within an uptrend, the green candles within a downtrend. Price oscillates rapidly on these pairs — cycles complete in hours, not days.
**Grid parameters:**
- ATR window: 1h–4h (tight, reacts to recent volatility)
- Grid spacing: tight (0.3–0.8% between levels)
- Grid range: ±1.5–2× ATR
- Max hold time per grid: 4–5 hours. If grid hasn't cycled, exit and reassess.
- Capital per grid: small (10–20% of altcoin allocation per position)
**Entry condition:** genuine short-term oscillation confirmed by:
  - 1h regime: RANGE or TRANSITION with low ADX (< 20)
  - Taker buy pressure neutral (0.40–0.60) — neither buyers nor sellers dominating
  - RSI(14) on 1h bars: 35–65 (not overbought, not oversold — sideways zone)
  - Structure: price between identified support and resistance zones
**Exit condition:** range exit (price leaves the band), OR 5-hour time limit, OR daily loss limit

---

### Mode B — Slow grid (1 day to ~2 days max)

**Target pairs:** BTC, ETH — lower volatility, slower oscillation
**What it catches:** multi-day consolidation zones within larger trends. BTC regularly oscillates ±5–8% over 1–3 days even within strong trends.
**Grid parameters:**
- ATR window: 24h–48h
- Grid spacing: wider (0.8–2.0% between levels)
- Grid range: ±2–3× ATR
- Max hold time per grid: 2 days. If grid hasn't cycled, exit.
- Capital per grid: moderate (20–30% of BTC/ETH allocation)
**Entry condition:**
  - 1h regime: RANGE confirmed for at least 4 consecutive hours
  - 1d trend: not actively BEAR (SMA50 > SMA200 or flat)
  - Structure: FTA resistance at least 3× ATR above current price (room to oscillate)
  - ADX(14) on daily bars: < 25 (no strong directional trend)
**Exit condition:** range exit, OR 2-day time limit, OR drawdown limit

---

### Mode C — Position hold (bear market accumulation)

**Target pairs:** BTC primarily, ETH secondarily
**What it catches:** the cycle bottom — buying in the accumulation zone and holding through the bull market. NOT 100% of capital, NOT all trades. A portion of capital reserved for this.
**Capital allocation:** 20–30% of total portfolio maximum. Never more.
**Entry condition (all must be true):**
  - 4-year cycle phase: ACCUMULATION or late BEAR (see §3)
  - Daily RSI(14) < 40 (price depressed, not extended)
  - Weekly structure: higher low forming after a major swing low (structure confirms bottom)
  - Fear & Greed Index < 30 (extreme fear = historically good buy zone)
  - Funding rate negative or near zero (shorts are in control = squeeze potential)
  - Buy-and-hold drawdown from ATH > 60% (deep enough into the bear)
**Hold rules:**
  - Do NOT sell on regime flipping to BULL — that is when to hold hardest
  - Do NOT sell on normal volatility drawdowns (20–30% within the hold is expected)
  - Only exit on: distribution signal (see below) OR structure breakdown (close below entry support on 2 consecutive daily bars)
**Exit condition (the "85–90% of the cycle" target):**
  - 4-year cycle elapsed ≥ 80%
  - Daily RSI(14) > 75 (overbought on major timeframe)
  - Weekly structure: bearish swing high confirmed (lower high forming)
  - Fear & Greed Index > 80 (extreme greed = historically good sell zone)
  - Sell in 3 tranches: 33% at 80% cycle elapsed, 33% at 85%, 33% at first structure breakdown
**Emergency exit:** 2 consecutive daily closes below entry support zone → exit immediately

---

## 3. Full market perception layer (before every trade)

Every trade decision — grid open, position entry, position exit — must pass through a full market assessment. Not just the regime classifier. The following signals must all be computed and available:

### 3.1 Signals already built (do not rebuild)
| Signal | Where | Notes |
|--------|--------|-------|
| Regime (RANGE/BULL/BEAR/TRANSITION) | `strategy/regime.py` | 6-signal weighted classifier |
| Structure (swing zones, FTA, alignment) | `strategy/structure.py` | Hourly + daily timeframes |
| ADX(14) | `backtest/features.py` | Trend strength |
| ATR(14) | `backtest/features.py` | Volatility sizing |
| SMA20, SMA50 | `backtest/features.py` | Trend direction |
| 24h momentum | `backtest/features.py` | Short-term direction |
| Breadth (basket above SMA50) | `backtest/features.py` | Market-wide participation |
| Taker buy volume | `backtest/replay.py` | Already in klines, not yet in Inputs |

### 3.2 Signals to add (backtest + live)
| Signal | What it tells you | Data source | Priority |
|--------|------------------|-------------|----------|
| **Buy/sell pressure** (taker volume ratio) | Are buyers or sellers dominating right now? | Kline `taker_buy_base` — already in archive | **#1 — highest priority** |
| **RSI(14)** | Overbought/oversold on the entry timeframe | Computed from OHLC — no new data | **#2** |
| **Bollinger Band position** | Is price in a squeeze (range forming) or expansion (trend starting)? | Computed from OHLC — no new data | **#3** |
| **VWAP deviation** | Is price above or below where volume traded? | Computed from kline volume — no new data | **#4** |
| **Fear & Greed Index** | Is the crowd panicking or euphoric? | `api.alternative.me/fng/` — free, daily, historical back to 2018 | **#5** |
| **Funding rate** | Are futures traders long-heavy or short-heavy? | Binance futures public API — partially built | **#6** |
| **Open interest** | Is momentum building or fading? | Binance futures public API — no auth needed | **#7** |
| **4-year cycle phase** | Where are we in the macro cycle? | Hardcoded halving dates + elapsed time | **#8** |

### 3.3 Multi-timeframe confirmation gate
Before any grid opens (Mode A or B), require agreement across two timeframes:
- **1h timeframe** must show RANGE regime
- **4h timeframe** must not show BULL or BEAR (for Mode A)
- **1d timeframe** must not show BEAR (for Mode B)

This eliminates false RANGE detections where the hourly looks calm but the daily is in a downtrend. This was the ETH June 2022 mistake — hourly said RANGE, daily was already BEAR.

---

## 4. The 4-year cycle layer

Bitcoin follows a consistent macro cycle anchored to the halving (every ~210,000 blocks, ~4 years):

| Phase | Timing | Bot behaviour |
|-------|--------|--------------|
| **Bear / capitulation** | 6–18 months post-ATH | Grids closed. Monitor for accumulation signal. |
| **Accumulation** | 12–24 months post-ATH | Start Mode C entries in tranches. Run Mode A on alts. |
| **Early bull** | 6–12 months pre-halving | Hold Mode C positions. Run Mode A + B for income. |
| **Parabolic bull** | 6–18 months post-halving | Hold Mode C. Tighten stops. Begin tranche exits at 80–85% elapsed. |
| **Distribution / top** | 85–90% of cycle | Exit Mode C in tranches. Raise all entry thresholds. Prepare cash. |

**Current position (2026-09-30):**
- 4th halving: 2024-04-20
- Estimated 4th cycle peak: ~Oct–Nov 2025 (17 months post-halving, consistent with history)
- Today: ~11 months post-estimated-peak
- Historical bear duration: 12–13 months
- **Current phase: late bear / entering accumulation**
- **Bot action now: preparing Mode C entry conditions. Watching for accumulation signals.**

**Cycle phase is a prior, not a trigger.** The calendar says "we are probably near the bottom." The market structure, RSI, Fear & Greed, and funding rate give the actual entry signal. Never enter on calendar alone.

---

## 5. Capital allocation across the three modes

The owner confirmed: position hold is NOT 100% of capital, NOT all trades. Here is the proposed split:

| Mode | Allocation | Description |
|------|-----------|-------------|
| **Mode A (fast grid)** | 40% of total | Cycling on volatile alts. Daily income layer. |
| **Mode B (slow grid)** | 30% of total | Weekly cycling on BTC/ETH. Slower income layer. |
| **Mode C (position hold)** | 20% of total | Long-term accumulation. Only during bear/accumulation phase. |
| **Reserve (cash)** | 10% of total | Emergency buffer. Never deployed. |

When NOT in the accumulation phase (i.e. during parabolic bull or distribution):
- Mode C allocation moves to Mode A: 60% fast grid, 30% slow grid, 10% reserve
- Mode C positions are being exited, not entered

---

## 6. What is NOT changing

- **Paper only** — no live orders until the forward test passes (minimum 30 days paper across one regime change)
- **Reserved window stays closed** — no data from 2025-01 onwards used in any backtest
- **One variable at a time** — each new signal is backtested in isolation before combining
- **No tuning on reserved data** — parameters are set on development windows only

---

## 7. Build order for Claude and Codex

This is the priority-ordered implementation plan. Do not skip steps. Do not combine multiple changes in one PR unless they are trivially linked.

| Step | What | Owner approval needed? | Complexity | Expected impact |
|------|------|----------------------|-----------|-----------------|
| **1** | Wire `taker_buy_base` ratio → `Inputs.buy_pressure` | Yes (LD-1) | Low | Buy/sell pressure in every decision |
| **2** | Add RSI(14) to `SeriesFeatures` and `Inputs` | Yes | Low | Overbought/oversold filter |
| **3** | Fix FTA cap to RANGE-only (see §8.4 of backtest comparison doc) | No — bug fix | Trivial | Fix V2 ungated −4.5% regression |
| **4** | Fetch daily bars for both new specs; run Variant A backtest | No — existing code | Low | Single most important unmeasured test |
| **5** | Add Bollinger Band width to `SeriesFeatures` | Yes | Low | Squeeze detection |
| **6** | Fear & Greed Index historical fetch + backtest signal | Yes (LD-3) | Low | Macro sentiment confirmation |
| **7** | Funding rate + open interest wiring (already partially built) | Yes (LD-4) | Low | Futures sentiment |
| **8** | `CyclePhase` enum + `HalvingCalendar` (4-year cycle signal) | Yes (P2-D1) | Low | Macro positioning layer |
| **9** | Multi-timeframe confirmation gate (1h + 4h + 1d must agree) | Yes | Medium | Eliminate false RANGE detections |
| **10** | Mode A fast grid (tight ATR, 5h time limit) | Yes (P3-D1) | Medium | Altcoin day-trading layer |
| **11** | Mode B slow grid (wider ATR, 2d time limit) | Yes | Medium | BTC/ETH swing layer |
| **12** | Mode C position hold (accumulation entry + tranche exit) | Yes (P3-D1 through P3-D5) | High | Macro cycle participation |
| **13** | Capital allocation manager (splits capital across A/B/C) | Yes | Medium | Coordinates the three modes |
| **14** | Live kline stream (reduce 59-minute lag) | Yes (LD-2) | Medium | Live trading only |
| **15** | Monitoring dashboard | No | Medium | Observability |

**Steps 1–4 can start immediately** once the owner gives go. They are isolated changes with no cross-dependencies and high confidence of improvement.

---

## 8. Owner decisions required before implementation

Mark each with your decision. Claude and Codex will not implement anything without a confirmed owner decision on the relevant items.

### Market perception signals
- [ ] **LD-1:** Add `buy_pressure` (taker volume ratio) to `Inputs`. Affects all future backtest reproducibility.
- [ ] **LD-2:** Add RSI(14) to `SeriesFeatures`. Same note.
- [ ] **LD-3:** Approve Fear & Greed Index as a signal. Third-party API (alternative.me). Accept it as a signal source?
- [ ] **LD-4:** Approve funding rate + open interest signals from Binance futures public API.
- [ ] **LD-5:** Multi-timeframe gate (1h + 4h + 1d must agree before any grid opens). Accept this as the new entry requirement?

### 4-year cycle
- [ ] **P2-D1:** Confirm halving dates are correct and accept them as the cycle anchor.
- [ ] **P2-D2:** Accept the cycle phase → bot behaviour mapping in §4 above.
- [ ] **P2-D3:** Confirm: calendar is a prior only. Structure + indicators give the actual signal.

### Three-mode architecture
- [ ] **P3-D1:** Approve Mode A (fast grid, minutes–5h, alts), Mode B (slow grid, 1–2 days, BTC/ETH), Mode C (position hold, 20% capital) as the target architecture.
- [ ] **P3-D2:** Confirm capital split: 40% Mode A / 30% Mode B / 20% Mode C / 10% reserve. Or adjust.
- [ ] **P3-D3:** Mode C: confirm 3-tranche exit at 80/85/first-breakdown. Or single exit?
- [ ] **P3-D4:** Mode C: confirm emergency exit rule (2 daily closes below entry support → exit immediately).
- [ ] **P3-D5:** Mode C: confirm 20% capital maximum for position hold. Never more.

### Process
- [ ] **PR-D1:** Confirm build order in §7. Any steps to reprioritise or remove?
- [ ] **PR-D2:** Confirm: steps 1–4 can start immediately without waiting for full architecture sign-off.

---

## 9. Cross-references

| Document | What it contains |
|----------|-----------------|
| `2026-09-30-bob-v2-backtest-comparison.md` | Full backtest results across 4 windows + strategic analysis (§8) |
| `2026-09-30-owner-position-trading-proposal.md` | Position trading detail, 4-year cycle table, P2/P3 decisions |
| `2026-09-30-owner-live-market-data-proposal.md` | Live data infrastructure, what exists vs what to build |
| `2026-09-29-owner-v2-backlog.md` | Earlier S1–S8 research items (still valid, now integrated into this proposal) |
| `src/crypto_grid_bot/strategy/regime.py` | Current regime classifier (6 signals, weights) |
| `src/crypto_grid_bot/strategy/structure.py` | Market structure perception (already built) |
| `src/crypto_grid_bot/simulation/trend_switch.py` | Variant A daily SMA filter (already built, not yet backtested) |
| `src/crypto_grid_bot/market_data/stream.py` | Live WebSocket price stream (already built) |
| `src/crypto_grid_bot/market_data/client.py` | REST client with depth endpoint on allowlist (already built) |

— IBM Bob (owner's desktop session)

---

## 10. What has been built so far (complete history)

### 10.1 Foundation (merged to `main`, fully stable)

Everything below `344f9ae` on `main` is the stable V0 foundation. Key capabilities:

| What | Where | Status |
|------|-------|--------|
| Paper simulation engine | `simulation/runner.py` | ✅ Merged, tested |
| Geometric grid builder | `strategy/grid.py` | ✅ Merged, tested |
| Regime classifier (5 signals: trend, breadth, momentum, vol_health, liq_health) | `strategy/regime.py` | ✅ Merged, tested |
| Opportunity scorer | `strategy/opportunity.py` | ✅ Merged, tested |
| Historical replay engine (backtest) | `backtest/replay.py` | ✅ Merged, tested |
| Binance kline archive fetcher (1m, 1h, 1d) | `backtest/dataset.py` | ✅ Merged, tested |
| Archive integrity checker | `backtest/dataset.py` | ✅ Merged, tested |
| Live WebSocket price stream (bid/ask) | `market_data/stream.py` | ✅ Merged, tested |
| Live REST client (klines, depth, exchange info) | `market_data/client.py` | ✅ Merged, tested |
| Variant A daily SMA50/SMA200 trend switch | `simulation/trend_switch.py` | ✅ Merged, **not yet backtested** |
| Variant B inventory cap | `simulation/runner.py` | ✅ Merged, not yet measured |
| Soft/hard drawdown recovery (spec v1 amendment 1) | `simulation/runner.py` | ✅ Merged |
| Funding rate signal (G) | `backtest/funding.py` | ✅ Merged, partial |
| Test suite | `tests/` | ✅ 773 passed, 4 skipped |

### 10.2 V2 work in progress (on `bob/v2-integrated`, PR #151)

All commits on top of `main` at `344f9ae`:

| Commit | What was built | Tests |
|--------|---------------|-------|
| `c2055b5` | `structure.py` — swing detection, support/resistance zones, FTA, multi-timeframe alignment | 55 new tests |
| `c220c4d` | `GridBuilder.build()` — optional FTA resistance cap (sell just below resistance) | 5 new tests |
| `86a11ab` | `structure_alignment` added to `MarketSignals`, `Inputs`, `RegimeClassifier` (weight 0.10; `trend` reduced 0.35→0.25) | Existing tests updated |
| `11a158b` | V2 backlog docs (S3 min sample size, S8 scientific loop metrics) | Docs only |
| `67fd563` | Full V2 wiring: `_KlineView`, `fta_resistance` in `Inputs`/`Frame`, `hourly_candles`/`daily_bars` in `FeatureEngine`, `jobs.py`, `replay.py` | 773 passed |
| `0edcc1f` | Variant A flag (`--variant-a`) wired into backtest CLI and `run_job` | Tests updated |
| `9d18c68` | Performance fix 1: `_structure_cache` — only recomputes structure when hourly candle index `p` changes (was O(n²)) | Existing tests |
| `7e24568` | Performance fix 2: cap hourly window to 500 bars (prevents O(n) growth per cache miss) | Existing tests |
| `9abb1f3` | `scripts/run_nopool.py` — sequential runner (no `ProcessPoolExecutor`); `backtest.yml` updated | Workflow |
| `9d7bd99` | V2 vs V0 backtest comparison report across 4 windows | Docs |
| `cde876c` | Strategic analysis appendix (§8): root cause diagnosis + concrete proposals | Docs |
| `8bed5be` | Owner proposal: position trading mode + 4-year cycle | Docs |
| `a47797b` | Cycle position corrected: late bear/accumulation as of 2026-09-30 | Docs |
| `4b88127` | Owner proposal: live market data layer | Docs |
| `9f35e12` | **This document** — master strategy proposal | Docs |

### 10.3 Backtest results summary (development windows only)

Four runs completed on GitHub Actions, 2026-09-30:

| Window | Period | BTC gated | ETH gated | XRP gated | Key finding |
|--------|--------|-----------|-----------|-----------|-------------|
| long-bull-bear-2022 | 2022-06→2023-02 | 0.00% | −2.10% | **+4.67%** | Gate saves capital; XRP profits in range pockets |
| long-recovery-2023-2024 | 2023-10→2024-12 | 0.00% | 0.00% | −6.91% | Bot sits out entire bull market — primary gap |
| practice-2022 | 2022-06→2023-01 | +0.72% | n/a | +2.71% | SOL: 500 grids in crash — eligibility needs review |
| verify-2024h1 | 2024-01→2024-06 | 0.00% | n/a | n/a | ADA gated −0.73% vs ungated −15.46% (halted) |

---

## 11. Open PRs — merge order for Claude and Codex

**Rule:** never merge to `main` without Claude review + owner go. Never merge out of order — later PRs depend on earlier ones being on `main` first.

### Current open PRs (6 total)

```
#146 → #147 → (#148 + #150 in either order) → #149 → #151
```

| PR | Title | What it contains | Depends on | Status |
|----|-------|-----------------|-----------|--------|
| **#146** | Owner direction: regime-adaptive grid spacing | Docs only — records owner direction on tight/wide spacing per regime. No code. | Nothing | Merge first — docs only, no conflicts |
| **#147** | Market structure perception | `structure.py` — swing detection, S/R zones, FTA, MTF alignment. 55 tests. | #146 (docs context) | Merge second |
| **#148** | FTA-aware sell targets | `GridBuilder.build()` FTA cap. 5 tests. | #147 (`structure.py` provides the concept; `grid.py` itself is independent) | Merge with or after #147 |
| **#150** | Structure alignment signal | `structure_alignment` in `MarketSignals`, `Inputs`, `RegimeClassifier`. | #147 (uses `structure.py` concept) | Merge with or after #147 |
| **#149** | Bob task: backtest comparison | Task file for V0 vs FTA vs structure_alignment comparison. Docs only. | #147, #148, #150 all merged first | Merge after #148 + #150 |
| **#151** | V2 integrated (this branch) | Everything above cherry-picked + wiring + performance fixes + new dataset specs + backtest results + all proposals from today | All of #146–#150 merged | Merge last — this is the integration branch |

### Why this order

- **#146 first:** pure docs, no conflicts with anything, provides context for reviewers of #147
- **#147 second:** `structure.py` is the foundation. #148 and #150 both depend on its concepts (though not its import directly). Must be on `main` before either can be cleanly reviewed.
- **#148 and #150 in either order:** independent of each other. #148 touches `grid.py`; #150 touches `domain.py` and `regime.py`. No file overlap.
- **#149 after #148 + #150:** the task file runs the comparison — it requires all features to be on `main` first.
- **#151 last:** this integration branch cherry-picked everything from the above PRs. Once #146–#150 are all merged, #151's cherry-picks become redundant and only the V2-specific additions (new specs, performance fixes, today's proposals) are new. Claude/Codex should review what's unique to #151 at that point.

### Note on #151 vs individual PRs

PR #151 (`bob/v2-integrated`) already contains all code from #147, #148, and #150 as cherry-picks — it is the only branch where everything actually runs together and has been backtested. If Claude/Codex want to verify the integration works, they should review #151. If they want to merge cleanly, they should merge #146 → #150 first, then #151 will only add the V2-specific work on top.

### After all PRs merge

Once `main` has all 6 PRs merged, the next immediate tasks (from §7 build order) are:
1. Fix FTA cap to RANGE-only (trivial bug fix, no owner decision needed)
2. Fetch daily bars → run Variant A backtest (owner decision PR-D2 needed)
3. Add `buy_pressure` signal (owner decision LD-1 needed)
