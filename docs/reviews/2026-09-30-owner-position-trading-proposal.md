# Owner proposal: full market intelligence layer and position trading mode

Index: 2026-09-30 owner direction. Buy-and-hold in bull cycles, sell at structure resistance. 4-year Bitcoin cycle awareness. Full market assessment before every trade. Not yet a registered trial — owner decisions required before implementation.

- **Recorded by:** Bob (IBM Bob, owner's desktop session), 2026-09-30
- **Status:** Proposal. Owner direction confirmed in conversation 2026-09-30. Requires owner sign-off on each section before Claude/Codex implement anything.

---

## The owner's direction (verbatim intent)

> "The bot needs to do a real assessment of the market every time it wishes to make a trade. How do you know what you will do if you do not know market structure, do not see what the pressure is — buy or sell — and a bunch of other things. You didn't even take the 4-year cycle into consideration. If you did you would know what approximate situation is and would be able to buy in the beginning and sell at let's say 85–90% of that bull cycle."

This describes three missing capabilities:

1. **Full market assessment before every trade** — not just regime classification, but a complete picture: structure, pressure (buy vs sell dominance), order flow, volatility state, cycle position.
2. **4-year Bitcoin halving cycle awareness** — knowing roughly where in the macro cycle we are changes everything: buy in accumulation, sell in late bull, stay out of the worst of the bear.
3. **Position trading mode** — buy once at a structurally significant low, hold through the bull, sell near the top. The current grid strategy does none of this.

---

## Proposal P1: Full pre-trade market assessment

### What the bot currently does
Before every grid open, the bot checks:
- Regime (RANGE/BULL/BEAR/TRANSITION) from 6 weighted signals
- Opportunity score (range quality, liquidity, drawdown history)
- Risk check (drawdown limits)

That's it. It does not assess buy/sell pressure, order flow, volume profile, or macro context.

### What needs to be added

**P1a — Buy/sell pressure signal**

*What it is:* the ratio of aggressive buying (market buys) to aggressive selling (market sells) over the last N candles. Binance 1-minute klines already contain `taker_buy_base_asset_volume` and `taker_buy_quote_asset_volume` — the share of volume initiated by buyers. The complement is seller-initiated. This is already available in the archive; no new data source needed.

*Implementation:* add a `buy_pressure` field to `Inputs` in `features.py`:
```python
# Ratio of taker-buy volume to total volume over last 24 bars (0=all sells, 1=all buys)
buy_pressure: float = 0.5
```
When `buy_pressure > 0.6`, buyers dominate → price more likely to rise → grid buys fill quickly.
When `buy_pressure < 0.4`, sellers dominate → price more likely to fall → dangerous to open grid buys.

*Decision rule:* require `buy_pressure > 0.45` before opening any long grid. In a bear market, `buy_pressure < 0.4` for 3+ consecutive hours is a veto signal.

*Data already in archives:* yes. `Kline.taker_buy_base` is already loaded by the replay engine.

**P1b — Volume profile / VWAP deviation**

*What it is:* is current price above or below where most volume traded? VWAP (Volume-Weighted Average Price) is the fairest measure of this. Price above VWAP = buyers in control. Price below VWAP = sellers in control.

*Implementation:* add to `SeriesFeatures`:
```python
# Deviation of current price from 24h VWAP; positive = price above fair value
vwap_deviation: list[float | None]
```

*Decision rule:* prefer opening grid buys when price is near or below VWAP (value zone). Avoid buying when price is significantly above VWAP (extended).

**P1c — RSI(14) as overbought/oversold filter**

Already proposed in S6 of the backlog. In context of position trading: RSI below 30 is a confirmed oversold level — historically one of the best buy signals. RSI above 70 is overbought — sell pressure incoming. Wire as an entry filter: `rsi < 40` required for new long grid opens; `rsi > 65` vetoes new buys.

**P1d — Multi-timeframe confirmation gate**

The current regime runs on hourly bars. Before any trade, require agreement across two timeframes:
- **1h regime** must be RANGE or confirming structure
- **1d trend** (already available via `trend_switch.py`) must not be actively BEAR

A trade is only opened when both timeframes agree. This eliminates the majority of false RANGE classifications that currently cause grid openings into the early stages of a trend move.

---

## Proposal P2: 4-year Bitcoin halving cycle awareness

### The concept

Bitcoin has historically followed a consistent 4-year cycle driven by the halving (block reward cut in half every ~210,000 blocks, approximately every 4 years):

| Phase | Approximate timing | Price behaviour | Bot action |
|-------|-------------------|-----------------|------------|
| **Accumulation** | 12–18 months after previous ATH | Sideways to slowly rising, low volatility | **BUY and accumulate** — best entry zone |
| **Early bull** | 6–12 months before halving | Rising, higher highs/lows | **Hold and run grids** for income |
| **Parabolic bull** | 6–18 months after halving | Rapid price appreciation | **Hold, tighten stops, sell in tranches** |
| **Distribution / top** | 85–90% through the cycle | RSI 80+, extreme volume, news frenzy | **SELL** — this is the owner's target |
| **Bear market** | 18–24 months after ATH | Falling, lower highs/lows, capitulation | **Stay out or short** |

### The known halving dates and cycle peaks

| Halving | Date | Price at halving | Cycle peak (approx) | Peak price (approx) |
|---------|------|-----------------|--------------------|--------------------|
| 1st | 2012-11-28 | ~$12 | 2013-12 | ~$1,100 |
| 2nd | 2016-07-09 | ~$650 | 2017-12 | ~$19,700 |
| 3rd | 2020-05-11 | ~$8,600 | 2021-11 | ~$69,000 |
| 4th | 2024-04-20 | ~$64,000 | 2025-Q4 est. | unknown (reserved window) |

**The 4th halving occurred on 2024-04-20.** Based on the historical pattern (17–18 months post-halving), the cycle peak is estimated around **October–November 2025** — this is in the reserved window and the bot makes no price prediction about it.

### Current position in the cycle (as of 2026-09-30)

Today is **30 September 2026.** Working through the timeline:

- 4th halving: 2024-04-20
- Estimated cycle peak: ~Oct–Nov 2025 (17 months post-halving, consistent with prior cycles)
- Time since estimated peak: **~11 months**
- Prior bear market durations post-ATH: 13 months (2018), 12 months (2022)
- Expected bottom range: **Oct 2026 – Apr 2027**

**The owner is correct: as of today we are nearing the end of the bear market / entering the accumulation zone.** This is historically the best time to begin accumulating — not the bull, not the parabolic phase. The bot sitting in cash right now is actually appropriate for capital preservation, but it should be preparing to accumulate, not waiting indefinitely.

This is the exact scenario the position trading mode (P3) is designed for.

### What the cycle tells us about the development data

Our backtest windows now make complete sense through this lens:

- **2022-06 to 2023-02 (bear window):** post-3rd-ATH bear market, 7–15 months after the Nov 2021 peak. Capitulation phase. The gated strategy correctly sat out.
- **2023-10 to 2024-12 (recovery/bull window):** late bear → accumulation → early bull leading into the 4th halving (April 2024). **This is the buy zone.** The gated strategy sat in cash earning 0%. This is the primary missed opportunity — accumulation phase entries should have been triggered.
- **2024-04-20 to 2024-12 (end of development data):** early post-halving bull. Hold phase. Bot should have been holding positions accumulated in 2023.
- **2025 onwards (reserved window):** estimated parabolic bull and distribution phase. Not used in development.
- **Today, Sept 2026:** post-peak bear, approaching bottom. **Accumulation mode should be activating.**

### P2a: Cycle phase signal

*What it is:* a hardcoded but updatable cycle phase input. Based on the halving date and elapsed time, the bot knows roughly which phase it is in. This is not a prediction — it is a prior that shifts the bot's aggression level.

*Implementation:* add a `CyclePhase` enum and a `HalvingCalendar` to the strategy layer:

```python
class CyclePhase(StrEnum):
    ACCUMULATION = "accumulation"  # 12-24 months post-ATH
    EARLY_BULL = "early_bull"  # 6-12 months pre-halving
    LATE_BULL = "late_bull"  # 6-18 months post-halving
    DISTRIBUTION = "distribution"  # RSI/structure signals approaching top
    BEAR = "bear"  # Post-ATH decline


HALVINGS_MS = [
    1354147200000,  # 2012-11-28
    1468022400000,  # 2016-07-09
    1589155200000,  # 2020-05-11
    1713571200000,  # 2024-04-20
]
```

*Decision rules by phase:*
- `ACCUMULATION`: allow grid buys aggressively. This is the buy zone. Lower minimum opportunity score threshold by 20%.
- `EARLY_BULL`: hold existing positions. Allow grids but tighten sell targets (use FTA). Shift from income to capital appreciation mode.
- `LATE_BULL`: hold. Run trailing sell targets. Tighten stops. Begin selling in tranches at each major resistance zone.
- `DISTRIBUTION`: raise all entry thresholds. Only open grids with very tight range criteria. Prioritise exiting inventory.
- `BEAR`: no new long grids. Grid on short side only (if exchange supports it) or stay in cash.

*What the owner specifically requested:* "sell at 85–90% of the bull cycle." This means:
- Define cycle length as ~12–18 months post-halving
- At 85% elapsed (roughly 10-15 months post-halving), begin distributing
- Use structure + RSI + VWAP as confirmation that the top is near

*Important:* cycle timing is approximate. The bot cannot predict the exact top. The sell signal must come from **structure + indicators**, not calendar alone. The calendar gives the prior; the market gives the trigger.

---

## Proposal P3: Position trading mode (buy-and-hold + structured exit)

### What it is

A new operating mode, separate from the grid, that runs alongside it:

1. **Entry condition:** all of the following must be true:
   - Cycle phase is ACCUMULATION or EARLY_BULL
   - Daily regime is not BEAR
   - RSI(14) on daily bars < 45 (price not extended)
   - Buy pressure > 0.50 on hourly bars
   - Price is at or near a major support zone (structure.py swing low or FTA support)
   - 4-year cycle confirms we are in the buy zone (< 40% through the cycle)

2. **Position size:** a fixed fraction of capital, separate from the grid capital. Suggested: 30–50% of total capital as a position hold, rest for grid income.

3. **Hold rules:**
   - Do NOT sell just because the regime flips to BULL. That is the time to hold most tightly.
   - Do NOT sell on normal volatility. Only exit on structure breakdown (price closes below the major support that triggered the entry) or on the distribution signal (see below).

4. **Exit condition (the "85–90% of the cycle" the owner described):**
   - Cycle phase elapsed: ≥ 80% of the estimated cycle length
   - RSI(14) on daily bars > 75 (overbought on the major timeframe)
   - Price has broken above and is now below a major resistance zone (structure reversal)
   - Weekly structure shows a bearish swing high (lower high forming)
   - Optional: sell in 3 tranches at 80%, 85%, 90% elapsed to reduce timing risk

5. **Emergency exit:**
   - Price closes below the original entry support zone on 2 consecutive daily bars → exit immediately regardless of cycle phase.

### Why this is fundamentally different from the grid

| | Grid (current) | Position trading (proposed) |
|---|---|---|
| Timeframe | Minutes to hours | Weeks to months |
| Profit source | Oscillation | Appreciation |
| Best market | Sideways/range | Trending/bull |
| Risk | Getting run over by trend | Holding through bear |
| Capital allocation | 100% cycling | 30-50% held, rest for grids |
| Exit trigger | Range exit / drawdown | Structure + cycle |

They are **complementary, not competing.** In the bull phase:
- 40-50% of capital is in the position trade, appreciating
- 50-60% is in grids on altcoins, harvesting oscillation income

In the bear phase:
- Position trade has been exited (at the distribution signal)
- Grids are closed (regime veto)
- Capital sits in stablecoin earning nothing, but losing nothing

---

## Owner decisions required

Before any code is written, the owner must answer:

**P1 — Full market assessment:**
- [ ] **P1-D1:** Approve adding `buy_pressure` (taker volume ratio) to `Inputs`. This is a data change affecting all future backtest reproducibility.
- [ ] **P1-D2:** Approve VWAP addition to `SeriesFeatures`. Same reproducibility note.
- [ ] **P1-D3:** Set the `buy_pressure` entry floor (suggested 0.45 — is this right or adjust?).
- [ ] **P1-D4:** Approve multi-timeframe gate (1h + 1d must agree before grid opens).

**P2 — 4-year cycle:**
- [ ] **P2-D1:** Confirm the hardcoded halving dates are correct and accept them as the cycle anchor.
- [ ] **P2-D2:** Approve the cycle phase → aggression mapping above, or amend.
- [ ] **P2-D3:** Accept that cycle phase is a prior only — structure + indicators are the actual triggers. (No calendar-only trading.)
- [ ] **P2-D4:** Confirm reserved window rule: no cycle-phase logic may reference data after 2024-12 during development.

**P3 — Position trading mode:**
- [ ] **P3-D1:** Approve position trading as a new mode alongside the grid (not replacing it).
- [ ] **P3-D2:** Set capital split: what fraction goes to the position hold vs grid cycling?
- [ ] **P3-D3:** Confirm exit strategy: sell in tranches at 80/85/90% of cycle, or a single exit?
- [ ] **P3-D4:** Confirm the emergency exit rule (2 consecutive daily closes below entry support).
- [ ] **P3-D5:** Should this be a new formal variant in `EXPERIMENT_SPEC_V1.md`, or a new strategy tracked separately?

---

## Relationship to existing work

| Existing item | How this proposal extends it |
|---------------|------------------------------|
| `structure.py` (PR #147) | Used directly for entry support zones and exit resistance detection |
| `fta_resistance` (PR #148) | Sell targets in both grid and position mode |
| `trend_switch.py` (Variant A) | Daily SMA signal is an input to the multi-timeframe gate (P1d) |
| `structure_alignment` (PR #150) | One of the confirmation signals for position entry |
| S2 in v2 backlog | This proposal supersedes S2's open questions with a concrete implementation plan |
| S6 in v2 backlog | RSI and VWAP additions are now mandatory, not optional |

---

## What this is NOT

- This is **not a prediction** that BTC will reach any specific price.
- This is **not a recommendation to open live positions** — paper trading and backtest validation must come first.
- This is **not a spec amendment** — it becomes one only after owner decisions above are answered and Claude/Codex review the implementation plan.
- The **reserved window stays closed** until formal C7 testing regardless of cycle signals.

— IBM Bob (owner's desktop session)
