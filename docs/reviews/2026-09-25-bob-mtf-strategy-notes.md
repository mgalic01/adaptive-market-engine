# Bob: Multi-timeframe trend diagnosis proposal & strategy evolution notes

- **Author:** Bob (IBM)
- **Date:** 2026-09-25
- **Branch:** `bob/funding-cadence`
- **Context:** Strategic review with the repository owner following the V0 diagnostic findings and funding cadence survey completion.
- **Audience:** Claude, Codex, and Owner

---

## 1. Background & Owner Strategic Questions

Following the completion of the 60-month funding cadence report (PR #19), the owner raised key strategic questions regarding the profitability, trend adaptation, and multi-timeframe decision-making of the bot:

1. **V0 Baseline Flaw vs. Future Viability:**
   - In the reported practice-window gated runs at 0% maker / 0.09% taker fees, resting sells realised +11.5 to +19.0 USDT and forced exits realised −9.6 to −22.3 USDT at average cost ([diagnostic](../backtests/fee-levels-2026-09.md)). Exits offset part or all of those gains, depending on the run. Exit reasons were not separated, so the data does not establish a specific cause or paired-cycle profit.
   - V0 is the unchanged control strategy. Variants A–H are hypotheses to evaluate, not demonstrated remedies or evidence that V0 was deliberately designed to fail.

2. **Trend Adaptation:**
   - The owner confirmed the priority of having the bot diagnose the trend and dynamically adapt its behavior rather than running as a static naive grid.

3. **Multi-Timeframe (MTF) Decision Making:**
   - The owner requested explicit multi-timeframe integration across 1-hour, 24-hour/daily, weekly, and monthly time horizons.

---

## 2. Multi-Timeframe (MTF) Architecture Proposal (Variant I / Spec v2 Candidate)

To formalize the owner's request without disrupting the draft Spec v1 matrix, we propose framing this multi-timeframe structure as **Variant I (Multi-Timeframe Trend Consensus)**. The choices below are exploratory, not approved parameters or proven regime classifications. A separate specification and review must fix the rules before evaluation; this report does not freeze v1 or authorize reserved data access.

### Timeframe Hierarchy & Indicator Roles

| Timeframe | Lookback | Indicator / Metric | Strategy Role |
| --- | --- | --- | --- |
| **Monthly (`1M`)** | 12 completed months | **Monthly SMA12 / Halving Phase** | **Macro Regime Gate:** Identifies secular bull vs. multi-year winter. In secular bear, grids are prohibited or constrained to deep accumulation only. |
| **Weekly (`1w`)** | 20–50 completed weeks | **Weekly SMA20 / SMA50** | **Primary Bias Filter:** If Weekly Close < SMA20, primary trend is broken $\rightarrow$ blocks new grid deployment even during 1-hour bounces. |
| **Daily (`1d`)** | 50 & 200 daily bars | **Daily SMA50 / SMA200 (Variant A)** | **Tactical Trend & Liquidation Switch:** Evaluates 2-day hysteresis confirmations and the 24-hour orderly trend liquidation. |
| **1-Hour (`1h`)** | 14 & 20 hourly bars | **Hourly SMA20 & ATR14** | **Grid Geometry & Boundaries:** Sets fair value center, computes geometric spacing ensuring spacing covers round-trip fees ($S \ge 3 \times \text{Cost}$). |
| **1-Minute (`1m`)** | 15 completed minutes | **Taker Buy/Sell Flow (Variant F)** | **Micro Execution Gate:** Blocks buy placement during aggressive market sell cascades. |

### MTF Consensus Scoring
$$\text{MTF Consensus} = w_{\text{Monthly}} \cdot \text{Vote}_{\text{1M}} + w_{\text{Weekly}} \cdot \text{Vote}_{\text{1w}} + w_{\text{Daily}} \cdot \text{Vote}_{\text{1d}} + w_{\text{Hourly}} \cdot \text{Vote}_{\text{1h}}$$

- **All Timeframes Bull:** Full grid deployment, normal 8-level spacing, micro-rebuy active.
- **Mixed Timeframes (e.g. Daily Bull / Weekly Bear):** Cautious mode, 20%–40% inventory cap, wider ATR spacing.
- **Bear Consensus:** Complete pause of new buys, resting sells remain active to offload inventory on bounces.

---

## 3. Repository Naming Note

- The owner noted intent to rename the public GitHub repository from `crypto-grid-bot` to a more discreet quantitative/engine name (e.g. `adaptive-market-engine` or `quant-grid-research`).
- This change will be handled cleanly with GitHub URL redirects, remote updates, and internal string updates without breaking CI or branch tracking.

---

## 4. Questions & Next Steps for Claude & Codex

1. **For Claude:**
   - Does this multi-timeframe consensus structure align with the roadmap for Spec v2 or as an additional pre-registered variant?
   - Can the daily warmup pipeline (P3) be extended cleanly to support weekly/monthly bar aggregations from existing Binance archives?
2. **For Codex:**
   - Are there any architectural or point-in-time boundary concerns with weekly/monthly bar closures (e.g. Sunday 23:59:59 UTC alignment for weekly candles)?
