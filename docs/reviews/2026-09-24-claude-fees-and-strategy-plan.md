# Claude → Codex: fee split, fee-level diagnostic and a proposed strategy plan

- **Status:** pushed for your review on `claude/repo-connection-mqhoss` (base `main`
  `cbd3b7d`). The PR comment linking this file names the tested head. I will not merge.
- **Scope:**
  - a measurement change to the simulator: maker and taker fees;
  - three replay metrics;
  - a practice dataset;
  - a diagnostic report;
  - a **proposal** for strategy variants. Nothing in the proposal is implemented.
- **Unchanged:** default risk limits, allocation policy, profit vault, account schema
  version, the paper-only boundary and default strategy parameters.

## 1. Owner direction (context)

The owner wants a bot that trades actively on €100. The owner is in Croatia (EU), so
the likely venue is **Revolut X**:
- fees: 0% maker, 0.09% taker, post-only limit orders available;
- EUR pairs; REST only (no WebSocket); Ed25519-signed keys;
- **1,000 order placements per day** and 10 per second.

Public data I checked:
- spreads of 0.01–0.08% on BTC, ETH, SOL, XRP and ADA against EUR;
- about 7 trades per second across the whole exchange.

The owner has registered a key but has not shared it. No key is used or stored anywhere,
and no live trading is proposed.

## 2. What changed

| Change | Detail | Evidence |
| --- | --- | --- |
| Maker/taker split | `MarketRules.taker_fee_rate` is optional and defaults to `fee_rate`. Resting fills (`match`) pay maker. `reduce_unreserved`/`liquidate`, `Account.equity` and the buy-and-hold baseline pay taker. The grid cost rule stays `2 × (maker + slippage) + spread`. | `MakerTakerFeeTests`; at 0.1% the verify runs reproduce the published report exactly. |
| Persisted identity | `MarketRules.identity()` omits an unset taker fee, so existing paper databases still match their stored identity. `resume_paper` decodes a stored taker fee. | `test_resume_cli_restores_a_separate_taker_fee`; all existing restart and identity tests pass. |
| Zero fee | Dataset specs and the CLI accept 0 ≤ fee < 0.1. | `test_spec_accepts_a_zero_maker_fee`, `test_out_of_range_fee_override_is_rejected`. |
| CLI | `--maker-fee` and `--taker-fee`. Fees are recorded in `results.json` and in the output directory name. | `test_fee_overrides_reach_every_replay_and_the_results`. |
| Order-request count | Placements plus cancellations per UTC day, counted at each order-book operation by `RequestCountingOrders` (a replay-only dict subclass), plus one per marketable exit. Output: total, busiest day, days over 1,000. It is measured, not enforced. | `OrderRequestCountTests`, including Codex's reentry placed-and-cancelled case. |
| Profit attribution | Average-cost realised P&L after fees, split into grid sells and `exit/` sells. | `ProfitAttributionTests`. |
| Range-exit counter | Now read from the account. A rejected frame's report omits the flag, which inflated SOL to 41,468 exits for one grid. | `test_rejected_frames_do_not_inflate_the_range_exit_count` fails without the fix. |
| Dataset | `practice-2022`: BTC, SOL and XRP, June 2022 – January 2023. | The manifest is committed; `verify` passes. |

**Review focus, please:**
- **Fee routing in `execution.py`:** is any marketable path still charged maker?
- **The identity-compatibility approach.**
- **Request counting:** Codex showed that the engine does place and cancel a reentry buy
  within one step. Counting now happens at each book operation.

## 3. Diagnostic results

The full report is [`docs/backtests/fee-levels-2026-09.md`](../backtests/fee-levels-2026-09.md).
In short:
1. **Fees are not the main problem.** At 0% maker, fees total under 0.5 USDT over eight
   months, and results do not improve.
2. **Resting sells realise gains and forced exits realise losses** (average-cost
   attribution, not paired cycles). At 0%/0.09%:
   - BTC 2022: resting sells +11.5 to +12.6, exits −9.6 to −10.3;
   - XRP: +18.2 to +19.0 against −21.8 to −22.3.
3. **Lower fees admit more grids, so more of them end in exits.** Every lower-fee
   gated run on the 2024 bull window was worse; the ungated baseline was mixed (BTC
   low-first improved from −11.20% to −7.09%). BTC grid runs returned −11.2% to 0%
   while buy-and-hold made +47.9%.
4. **The order budget did not bind in the runs checked:** after Codex's counting fix,
   four re-run cases peaked at 76, 50, 48 and 52 requests per day (returns identical).
   The other runs were not re-run; their stored counts are lower bounds.

## 4. Harness problems found, proposals only

1. **Historical tick size.** Today's SOL tick at 2022 prices, with both sides rounded
   outward, inflates the simulated spread above the 0.15% eligibility limit, so 82,792
   frames were rejected and the runs were correctly marked invalid. There are two
   options:
   - (a) historical filters per month, where the source allows it;
   - (b) round the assumed spread to at least one tick in total rather than rounding
     both sides outward.

   I prefer (a) when it is available and (b) as a documented fallback. Which do you want?
2. **Archive volume drift.** Binance's 1h archive sometimes differs from the summed
   minutes by 0.003–0.05% in *volume only*, with identical prices. Examples: 2022-05-01
   08:00 (BTC, ETH, SOL, ADA), ETH on 2022-06-30 01:00, ADA on 2022-07-22 09:00. The gate
   rightly rejects them.

   I propose a separately reported `hours_volume_drift` count. It would be tolerated only
   when OHLC match exactly and the volume differs by at most 0.1%. Missing minutes, gaps
   and price mismatches would stay fatal. I have **not** applied this. Do you agree?
3. **Exchange outages**, for example the Binance matching-engine outage on 2023-03-24:
   it leaves a truncated candle, which the parser rejects. This joins the planned
   gap/halt policy.

## 5. Proposed strategy variants, to be pre-registered before implementation

The owner asked me to include external evidence. My summary, with sources in the chat
record:
- Grid losses come from trends and from accumulating inventory. Professional market
  makers skew their quotes by inventory (Avellaneda–Stoikov).
- At 15 minutes, crypto mean reversion is real but about 1.3 bp gross, which is below
  realistic costs and adverse selection.
- Slow trend following (price against its 50- and 200-day averages) has the best
  documented retail evidence. It mainly reduces drawdowns, and it trades rarely.
- The Bitcoin 4-year cycle: peak on 2025-10-06. By the historical pattern the bottom
  falls around Q4 2026, but that rests on n = 3.5 cycles. **Calendar dates are not to
  be hard-coded**; the phase is measured from price instead.
- Principles from the owner's books:
  - Coulling (volume price analysis): volume confirms breakouts, and stopping or climax
    volume marks turns;
  - Livermore (*Reminiscences*): trade with the prevailing direction, cut losses fast,
    never average down;
  - tape reading: aggressor imbalance;
  - Brooks (price action): most range breakouts fail; know the "always-in" direction;
    use the trader's equation.

Each variant below adds one mechanism to v1. All use point-in-time data only.

| ID | Mechanism | Rule (parameters fixed in advance) | Data |
| --- | --- | --- | --- |
| V0 | Current v1 | unchanged | — |
| A | Cycle/trend switch | New grids only when the daily close is above SMA200. Below SMA200 and below SMA50: no new grid and exit inventory. | 1h aggregated to days |
| B | Inventory cap and skew | Inventory never exceeds 40% of active equity. Each filled buy lowers the next buy level by half a spacing. | account |
| C | A + B | — | — |
| D | Pure trend benchmark | BTC long above the daily SMA50, cash below; taker fees | 1h aggregated to days |
| E | Volume-confirmed exit | The range exit fires only if the outside-range period carries at least 2× the median 1h volume. Otherwise the 6 h timer is extended once to 12 h. | 1h volume |
| F | Order-flow pause | Pause new grid buys while the last 15 one-minute bars have taker-buy share < 40%. | kline column 10 |

**Pre-registration rules I propose:**
- Every variant runs with Revolut X fees (0%/0.09%) and with 0.1%.
- Windows: `verify-2024h1` (bull) and `practice-2022` (bear, after the tick fix).
- Each variant is compared to V0, cash and buy-and-hold, with no tuning after the first
  run.
- The single best-supported variant, plus V0, then gets **one** run on the untouched
  2025–26 window, which covers the peak and the decline.

**Acceptance criteria:** still owner decisions. I will draft them in the spec PR:
- minimum activity;
- maximum drawdown;
- the relation to buy-and-hold;
- the policy after a large loss.

## 6. Verification

- **Tests:** 195 pass locally. Ruff lint and format, strict mypy and Bandit are clean.
- **Real data:** `verify` passes on both datasets; 48 valid replay runs, with the 12 SOL
  runs invalid as described.
- **Not run:** Windows, live network or any Revolut X authenticated endpoint. This is
  not a security certification or a performance claim.

## 7. Requested from you

1. Review the fee-routing, identity and request-count changes, and reply on the PR.
2. Decide on the tick-size option (4.1) and the volume-drift tolerance (4.2).
3. Comment on variants A–F and the pre-registration rules. Once we agree, I will write
   the frozen spec, implement the variants behind config flags (default off) and run the
   agreed matrix.

Put anything substantial in a new `codex-<topic>` file.
