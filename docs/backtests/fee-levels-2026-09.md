# Fee-level diagnostic: Binance 0.1%, 0.075%, Revolut X 0% maker / 0.09% taker

- **Purpose:** measure how the fee level changes the current strategy (`price-only-v1`,
  default config) before any strategy work. **This is a diagnostic on development
  windows, not a performance claim.** No parameter was tuned on these results.
- **Code:** fee split `e57439a`; the practice runs at 0.075% and 0%/0.09% also carry
  the profit attribution of `927e1a7`. The range-exit counter fix `f136773` came after
  all runs; for BTC and XRP (no rejected frames) it changes nothing.
- **Datasets:**
  - `verify-2024h1` (ADA, BTC; Jan–Jun 2024; a bull market for BTC);
  - `practice-2022` (BTC, SOL, XRP; Jun 2022 – Jan 2023; a bear market including the
    June crash and the FTX collapse). See the spec for the Binance archive defects its
    window and pairs avoid.
- **Costs:** 100 USDT, 0.05% slippage buffer, 0.05% assumed spread; fees as listed.
  Resting grid fills pay maker; range exits, liquidation, marks and buy-and-hold pay taker.

## Validity

- `verify-2024h1`: all 24 runs valid; the 0.1% runs reproduce the earlier report exactly.
- `practice-2022`: **all SOLUSDT runs are invalid** (the harness marked them so):
  82,792 frames rejected because today's SOL tick (0.01) at 2022 prices of $10–14,
  rounded outward on both sides, makes the simulated spread exceed the 0.15% limit.
  The SOL numbers are excluded below. BTC and XRP runs have no rejected frames.

## Results (return %, both intrabar paths)

### Bear market, `practice-2022` (buy-and-hold: BTC −27.4%, XRP −4.1%)

| Pair | Strategy | 0.1% / 0.1% | 0.075% / 0.075% | 0% / 0.09% |
| --- | --- | --- | --- | --- |
| BTC | gated grid | −1.20 / −1.20 | −1.19 / −1.19 | **+1.22 / +2.98** |
| BTC | ungated grid | −8.03 / −7.89 | −7.83 / −7.69 | −5.67 / −6.42 |
| XRP | gated grid | **+5.60 / +5.83** | **+6.92 / +6.96** | −4.15 / −2.87 |
| XRP | ungated grid | −5.16 / −5.30 (halted) | −10.82 / −10.71 | −8.57 / −8.55 |

### Bull market for BTC, `verify-2024h1` (buy-and-hold: ADA −34.1%, BTC +47.9%)

| Pair | Strategy | 0.1% / 0.1% | 0.075% / 0.075% | 0% / 0.09% |
| --- | --- | --- | --- | --- |
| ADA | gated grid | −2.27 / −2.08 | −6.12 / −4.66 | −8.44 / −8.38 |
| ADA | ungated grid | −10.01 / −9.97 (halted) | −8.95 / −8.74 (halted) | −10.58 / −10.58 (halted) |
| BTC | gated grid | 0.00 / 0.00 (no trades) | −1.07 / −1.06 | −7.88 / −7.93 |
| BTC | ungated grid | −4.93 / −11.20 | −7.99 / −7.97 | −7.29 / −7.09 |

## Where the money goes (practice-2022, realised after fees, USDT)

Attribution is **average-cost**: each sell is charged the running average cost (fees
included) of all inventory held, not the cost of the buy it was paired with. "Resting
sells" are grid sell orders that filled at their limit; "Forced exits" are marketable
`exit/` sells. The split shows which kind of sale realised gains or losses. It is not
the profit of paired buy→sell cycles.

| Run | Grids | Resting sells | Forced exits | Fees |
| --- | ---: | ---: | ---: | ---: |
| BTC gated, 0%/0.09% | 98–101 | **+11.5 to +12.6** | **−9.6 to −10.3** | 0.44–0.46 |
| XRP gated, 0%/0.09% | 119–120 | **+18.2 to +19.0** | **−21.8 to −22.3** | 0.45 |
| XRP gated, 0.075% | 29 | +6.9 to +7.0 | 0 | 0.85–0.86 |
| BTC ungated, 0.075% | 4 | +2.6 | −10.3 to −10.4 | 0.49–0.50 |

## Findings

1. **Fees are not the main problem.** At 0% maker, fees are under 0.5 USDT over eight
   months, yet results are not better and are often worse.
2. **Resting sells realise gains; forced exits realise losses.** At average cost,
   resting grid sells realised +11.5 to +19.0 USDT, and range exits (price leaves the
   range, the inventory is sold at a loss) took back as much or more.
3. **Cheaper fees mean more grids, so more exposure to exits.** The 3× cost rule
   filtered out many grids at 0.1%; at 0% it admits them, including those that end in
   a range exit. On the 2024 bull window, every lower-fee **gated** run was worse
   (ADA −2.2 → −5.4 → −8.4%; BTC 0 → −1.1 → −7.9%, path averages). The ungated
   baseline was mixed: BTC low-first improved (−11.20 → −7.97 → −7.09%) while BTC
   high-first and ADA did not.
4. **In a bull market the grid loses to holding.** BTC 2024: +47.9% buy-and-hold versus
   −11.2% to 0% across every grid run (gated and ungated, all fee levels and paths).
5. **The order budget is not binding.** The counts in these runs' `results.json`
   undercount: Codex found (PR #14) that a reentry buy placed and cancelled within
   one step was invisible to the before/after count. After the fix, counting at each
   book operation, four of the busiest runs (0%/0.09%) were re-run with identical
   returns: their busiest day was 76, 50, 48 and 52 requests (previously reported 64, 44,
   42 and 46), against Revolut X's 1,000. The other runs were not re-run, so no
   corrected global maximum is claimed; their stored counts are lower bounds.
6. **Harness issues found:** today's tick size applied to much lower historical prices
   (SOL) and a range-exit counter that counted rejected frames (fixed in `f136773`).

The next step is not to change fees but to limit losses on exits: a trend/cycle
filter, an inventory cap and volume-confirmed exits. See
[the strategy plan](../reviews/2026-09-24-claude-fees-and-strategy-plan.md).
