# Experiment specification v3: trend-following, long and short, on perpetual futures (draft)

**Status:** draft, not frozen. Claude wrote it from the owner's design decisions of 2026-10-08 (§11).
- **Before any build:** the owner reviews this draft, Codex and Bob review it, and the owner gives the go to freeze it. The freeze comes before any code that could be tuned to results, and before any v3 run.
- **After the freeze:** a change requires a new version. The freeze covers this file only. The build plan may change, and where the two differ, this spec rules.
- **Scope:** historical replay only, on paper. Nothing here authorises live trading, exchange credentials, API keys or withdrawals. No v3 code places, signs or routes an order.
- **Earlier specs:** [spec v1](EXPERIMENT_SPEC_V1.md) ended with no winner ([report](backtests/2026-10-06-spec-v1-stage-1.md)). [Spec v2](EXPERIMENT_SPEC_V2.md) failed on its drawdown criterion, C1 ([verdict](backtests/2026-10-07-spec-v2-verdict.md)). Both stay frozen as the records of their experiments.

## 1. Question

Does trend-following, long and short, on a portfolio of the 10 coins this project has vetted, earn a cost-aware, risk-adjusted edge out of sample, at a modest risk budget, over and above simply holding the same coins at the same risk?

**Why this question:**
- **v1's grids lost money,** and v2's mode switcher made about 4.9% a year with a 21.9% drawdown, capturing about 1.2–1.5% of buy-and-hold's six-year rise.
- **v1's long-only trend benchmark D** (hold while the daily close is above its SMA50, otherwise cash) made about 69% a year on 2019–2024, with drawdowns near 60%. It is the only rule tested so far that showed real signal, but at a risk the owner does not accept.
- **The owner's brief of 2026-10-08** asked for a multi-strategy, long-and-short bot. The owner chose to test its core idea first, trend-following long and short, before any larger build (§11, decision 1).

**What v3 does not promise.** It promises no return. The owner's target of 20–30% a month cannot be reached at 1x leverage and this risk budget (§8, "The owner's monthly target"). v3 reports how far each strategy falls short of it.

## 2. Data

**Futures prices and funding:**
- **Source:** Binance USDⓈ-M perpetual-futures public archives (data.binance.vision): monthly 1h klines and monthly funding-rate files for the 10 coins of §3.
- **Months:** from each coin's first full month of 1h futures klines to 2024-12. Nothing dated 2025 or later is fetched or read. The reserved window stays sealed (§8, "Outcome").
- **Fetch:** by Bob, in a task file the owner starts, with a pinned script, as in #193.
  - Every archive is checked against Binance's published SHA-256.
  - Each file's checksum and statistics are recorded in a committed manifest.
  - The fetch also records today's USDⓈ-M exchange filters (quantity step, minimum notional) for the 10 symbols, once, in the manifest. Historical filters are not published (spec v1 P4), so today's are used and the record says so.
- **Integrity:** the 1h futures klines go through the repairing reader of the long-window data (#186, #189).
  - As spec v1 §5 rule 5 treats a symbol that has only 1h archives, every hour the reader repairs, and every missing hour, is masked.
  - A coin-month with more than 17% of its hours masked is excluded, under spec v1 §5's 17% rule. So is a coin-month whose funding file is missing.
  - Spec v1 §5's other rules concern minute replay, the daily/hourly cross-check and spot quoting (rule 8, the actual-quotes test). They do not apply to v3, which neither replays minutes nor quotes inside the spread.

**Spot data:**
- **1h spot klines for all 10 coins,** from 2018-06, or the coin's first full spot month if later, to 2024-12.
  - Nine coins' files are already in `full-range-2017-2024`'s committed manifest (#199), and are reused with the same checksums.
  - ADAUSDT is not in that dataset, so its files are fetched in the same Bob task.
  - The integrity rules above apply to them too.
- **Daily closes for signals** (§4) are aggregated from these spot 1h bars.
- **The hold benchmark** (§8) uses the same spot 1h bars.
- **Why spot for signals:** the slow rules need up to a year of history. Spot history from 2018-06 gives every coin more than a year before its futures start (2019-10 at the earliest), except where a coin's spot listing is later (SOLUSDT, 2020-08). There, a rule gives 0 until it has enough history (§4). Signals from spot let a coin trade from its first futures day. Fills, profit and loss, and funding all use futures prices.

**Daily bars** are UTC days, built from 1h bars. A day with a masked hour still produces a daily close from its last unmasked hour, and is reported as such.

## 3. Coins

BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, LTCUSDT, LINKUSDT and TRXUSDT, as perpetuals.
- **A coin joins the portfolio** at its first full month of futures klines, and leaves only for an excluded month (§2).
- **Hindsight (disclosed):** these coins were chosen in 2026, and all of them are still large today. Coins that crashed or were delisted are not in the set, so the results are flattered. Only the reserved window can check a pass free of this bias.

## 4. The rules

Each rule maps a coin's daily closes, up to and including day d, to a signal for day d+1: **+1 long, −1 short, 0 flat.** The menu, with fixed, standard settings:

| # | Rule | Signal |
| --- | --- | --- |
| R1 | **SMA50** | close > SMA(50) → +1; close < SMA(50) → −1; equal → 0. D's rule, with a short side. |
| R2 | **EMA 21/55** | EMA(21) > EMA(55) → +1; below → −1; equal → 0. |
| R3 | **Donchian 55/20** | Flat until a close above the prior 55-day high (+1) or below the prior 55-day low (−1). A long exits to 0 on a close below the prior 20-day low; a short exits to 0 on a close above the prior 20-day high. "Prior" means the window ending the day before. |
| R4 | **12-month momentum** | close ÷ close 365 days earlier − 1: > 0 → +1; < 0 → −1; = 0 → 0. |
| R5 | **Supertrend 10/3** | ATR(10) with Wilder smoothing, multiplier 3, standard band carry-forward: close above the line → +1, below → −1. |
| R6 | **Equal blend** | the mean of R1–R5's signals, a value in [−1, +1]. It is the only rule whose signal is not just −1, 0 or +1. |

- **A rule with too little history** for a coin gives 0 for that coin until it has enough: 50 closes for R1, 55 for R2 and R3, 366 for R4, and 11 for R5.
- **No other strategy family is in v3.** That covers mean reversion, scalping, breakout variants, pattern recognition, market structure, pairs trading and funding arbitrage (§10). Each extra rule is another trial, and more trials make a lucky pass more likely.

## 5. Sizing

At each daily decision, after day d's close:

1. **Raw weight:** for each coin with a non-zero signal `s`, `raw = s × (1 / σ)`, where σ is the annualised volatility of the coin's daily spot simple returns over the last 60 days (sample standard deviation × √365).
2. **Volatility target:** the portfolio's estimated volatility is `√(rawᵀ Σ raw)`, where Σ is the 60-day sample covariance matrix of the same returns, annualised. All raw weights are scaled by `0.20 ÷ that estimate`, so the portfolio targets **20% volatility a year**.
3. **Caps,** applied after scaling, in this order:
   - each coin's |weight| ≤ 0.10 of equity;
   - the sum of |weights| ≤ 0.80;
   - if the sum exceeds 0.80, every weight is scaled down proportionally.

   So leverage never exceeds 1x.
4. **Rebalancing:** a coin trades to its target only if `|target − current| > 0.01` of equity, or if the signal changes sign or goes to or from 0. Otherwise its position stays.
5. **Exchange filters:** a target below a symbol's minimum notional is not opened, and is reported. Quantities round toward zero to the symbol's quantity step.

The weights are computed in exact `Decimal`. The square root and the covariance are evaluated at 60 significant digits, with the bound the implementation states.

## 6. The account

**One portfolio account** at 10,000 USDT, with cross margin, run on hourly futures bars.
- **Fills:** each daily decision fills at the open of the 1h bar that starts one hour after the UTC day's close (01:00 UTC). A buy fills at `open × (1 + 0.0005)` and a sell at `open × (1 − 0.0005)`, which is the slippage. Each fill pays the taker fee, 0.05% of its notional (Binance USDⓈ-M, VIP 0).
- **A masked fill hour:** the fill moves to the open of the next unmasked hour of that coin, on the same terms.
- **Funding:** at each funding timestamp in the coin's funding file, the position pays `quantity × the 1h bar's open at that hour × rate` if it is long and the rate is positive. A short receives it. A negative rate reverses both.
- **Marking:** equity is marked at every hour's open. Total equity is cash plus the unrealised profit and loss of every position, after every fee and funding payment.
- **Liquidation:** if equity at any hourly mark is ≤ 1% of the gross open notional, the account is liquidated at that hour's opens. The run fails (§8). It is expected never to happen at these sizes.
- **Accounting identities,** exact and checked at the end of every run, as in spec v1 P6:
  - cash = initial capital − the sum of buy notionals + the sum of sell notionals − fees ± funding;
  - each coin's quantity = its buys − its sells;
  - realised plus unrealised profit and loss equals the change in equity.

**Costs stress, reported only:** every run is repeated at double fees and double slippage.

## 7. Walk-forward

- **Windows:** train on 18 calendar months, then test on the next 3, and roll forward by 3.
  - The first test quarter is the first calendar quarter that starts at least 18 months after BTCUSDT's first full futures month. With futures from 2019-09, that is expected to be **2021-Q2**, and the fetch confirms it.
  - The last test quarter is **2024-Q4**.
- **Picking:** in each training window, each of R1–R6 is run on the whole portfolio, with the sizing, costs and funding of §5–6. The rule with the highest Sharpe ratio (§8) over that window trades the next test quarter. A tie goes to the lower rule number.
- **Continuity:** one account runs through all test quarters. At a quarter boundary where the pick changes, the book moves to the new rule's targets at the next daily decision. Training runs are separate, fresh accounts and never touch it.
- **Out-of-sample** means only the test quarters, stitched in order. Every pass criterion is computed on that stitched run.

## 8. Evaluation

**Metrics,** on the stitched out-of-sample run, from the daily equity series at 01:00 UTC before that hour's fills:
- **Sharpe ratio:** mean ÷ standard deviation of the daily simple returns, × √365, with a risk-free rate of 0.
- **Profit factor:** the sum of positive daily profit and loss ÷ the absolute sum of negative daily profit and loss.
- **CAGR:** compound annual growth over the out-of-sample days (365.25-day years).
- **Maximum drawdown:** on the hourly equity marks, from the running peak.
- **Calmar ratio:** CAGR ÷ maximum drawdown.

**Acceptance.** v3 passes only if all five hold:

| # | Criterion |
| --- | --- |
| A1 | Sharpe ratio ≥ 1.0 |
| A2 | Profit factor ≥ 1.3 |
| A3 | Calmar ratio ≥ 0.5 |
| A4 | CAGR ≥ 8% (the owner's passive-investment hurdle) |
| A5 | The Sharpe ratio exceeds the hold benchmark's over the same days |

**The hold benchmark:** long-only, equal signal (+1) for every coin in the portfolio at that time, on spot prices with no funding. It uses the same sizing (§5: volatility target, caps, rebalancing rule) and the same fees and slippage (§6). It answers one question: does timing add anything over just holding the same coins at the same risk?

**A run fails** if it is invalid: an accounting identity fails, a liquidation occurs, or a fill or funding payment the rules require cannot be made.

**Reported, deciding nothing:**
- **The owner's monthly target:** every out-of-sample month's return, beside the owner's 20–30% target, and how many months reached 20%.
- each rule's full-period results, as if picked every quarter;
- **each rule's long-only twin:** the same rule and sizing with every −1 set to 0;
- the long-versus-short split of profit and loss, per rule and per coin;
- funding paid and received, fees, slippage and turnover;
- the time invested, gross and net;
- the double-cost results;
- the worst drawdown's dates;
- the picks quarter by quarter;
- variant D, and plain equal-weight buy-and-hold at full size;
- **the minimum account size:** the smallest account at which every target position of the out-of-sample run meets its symbol's minimum notional (§5).

**Outcome:**
- **If v3 passes,** the reserved 2025–26 window may run once, as a confirmation. That needs its own written rule first (as spec v1's C7), and the owner's go. Nothing in v3 runs on it before then.
- **If it fails,** v3 ends with no pass, and nothing runs on the reserved window.

**Trials:** six rules and one picking procedure, all fixed in this draft before any v3 result. The long-only twins are reported, never picked.

**Prior exposure (disclosed):**
- **v2's runs** covered 2019–2024 on spot for BTCUSDT and ETHUSDT, with a different strategy. Their results, and D's, were seen before this design.
- **#137** (2026-09-28) ran three published trend rules on BTCUSDT 2017–2024. Adding a short side made each one worse: 12-month momentum fell from +1,423% to +700%, a Donchian breakout from +2,643% to +377%, and 50/200 averages from +593% to +57%. This is why every report shows the long-only twins and the long-versus-short split (§11, decision 7).
- **Where the settings come from:**
  - R1 is D's rule;
  - R2's 21/55 is from the owner's brief;
  - R3, R4 and R5 use textbook settings;
  - the 20% volatility target is from the owner's choice of about 20–25% (§11, decision 2);
  - the caps of 10% per coin and 80% total are from the owner's brief;
  - the gate's Sharpe ≥ 1.0 and profit factor ≥ 1.3, and the 18-month and 3-month windows, are from the owner's brief;
  - the 8% hurdle is the owner's;
  - Calmar ≥ 0.5, the 60-day estimators and the 1% rebalancing band are Claude's design choices.

## 9. Build order

1. **This spec is frozen** after the owner's review and clean reviews from Codex and Bob.
2. **Futures data:** the dataset spec, a pinned fetch script with tests that block the network, and Bob's task file. The owner starts Bob's run, and the manifest is committed from Bob's digest.
3. **The rules, the sizing and the account,** in a new package `crypto_grid_bot.trend`, kept apart from the grid code. They are tested first on synthetic data:
   - each rule against hand-worked examples;
   - no look-ahead;
   - the accounting identities;
   - funding signs;
   - the caps and the volatility target;
   - determinism.
4. **Walk-forward and the scorer:** the pass criteria, the benchmarks, and the JSON and Markdown reports in `docs/backtests/`.
5. **The runs and the verdict record,** through the backtest workflow, with progress lines.

**V0, every v1 variant and the mode switcher stay byte-identical,** checked by `scripts/byte_identity.py` on every PR.

## 10. Not in v3

Each needs its own owner decision and a later spec:
- the other strategy families of the owner's brief: mean reversion, momentum variants, breakout and structure variants, scalping, pattern recognition, market structure, pairs trading and funding arbitrage;
- a universe beyond the 10 coins, or a point-in-time top-N universe;
- leverage above 1x, or any change to the risk budget;
- intraday signals, and minute-level execution;
- live trading, exchange credentials, WebSocket feeds, databases, dashboards and alerts;
- the reserved 2025–26 window, until a pass and its own written rule (§8, "Outcome").

## 11. Owner decisions (2026-10-08, in Claude's session)

Each entry gives the question, and the option the owner chose.

1. **What to do with the brief.** The owner shared a brief for a 25%-a-month, 50-coin, multi-strategy, 20x-leverage bot with live trading. Claude assessed it against v0–v2's evidence. Question: "What do you want me to do with this spec?" Chosen: **"Test the core idea first"**. The option said: "Before any big build: a new pre-registered spec (v3), paper-only, testing trend-following (long and short) across a wider set of top coins, held to the spec's own walk-forward gate (Sharpe at least 1.0, profit factor at least 1.3). Build infrastructure only for what passes. No profit promise." This also closes spec v2 as failed.
2. **Drawdown.** Question: "What drawdown should v3 accept?" Chosen: **"Size to a risk budget"**. The option said: "No fixed cap kills a run on its own. Positions are sized so the portfolio targets a set volatility (e.g., ~20-25% a year), which keeps drawdowns moderate, and the gate also requires drawdown well below buy-and-hold's and a Calmar ratio (return / drawdown) of at least ~0.5. Most room for trend-following to show an edge."
   - v3 uses a 20% target (§5).
   - The pass bar the owner approved afterwards (decision 5, and design section 4) carries the Calmar ratio as A3. It has no separate drawdown-versus-buy-and-hold criterion. The maximum drawdown and buy-and-hold's are both reported (§8).
3. **Shorts.** Question: "How should v3 handle the short side?" Chosen: **"Long and short on futures data"**: perpetual-futures prices and funding history fetched by Bob, real funding charged, at 1x leverage.
4. **Coins.** Question: "Which coins should v3 trade?" Chosen: **"Our 10 coins, bias stated"**.
5. **The pass bar.** The owner first answered: "our strategy needs to make 20-30% profits per month." Claude explained that 20% a month is about +790% a year, and that at 1x leverage and a 20% risk budget it would need a Sharpe ratio near 30. Question: "Given that 20-30% a month can't be reached at 1x leverage and a 20-25% risk budget, how should v3 judge a pass?" Chosen: **"Realistic bar, report vs 20-30%"**. The option said: "Pass = the gate (Sharpe >= 1.0, profit factor >= 1.3) + Calmar >= 0.5 + at least 8% a year + beats holding the same coins at the same risk. Every report also shows monthly returns against your 20-30% target, so the gap is visible."
6. **The rules.** Question: "How should v3 choose its trend rules?" Chosen: **"Walk-forward pick from a fixed menu"**: about six standard rules fixed in advance; in each 18-month window the best is picked and traded for the next 3 months; only those months count.
7. **The short side, after #137.** Claude disclosed #137's finding that shorts made trend rules worse on BTCUSDT. Question: "How should v3 treat the short side?" Chosen: **"Keep long+short, report long-only alongside"**.
8. **The build approach.** Question: "Which way should the v3 test be built?" Chosen: **"A: new hourly backtester"**: its own module, hourly futures bars, exact decimals, real funding, fills at the next hour's open with slippage and fees.
9. **The design sections.** The owner approved Claude's five design sections, on the data, the rules, sizing and costs, walk-forward and scoring, and the build, and asked for this draft: "Looks right, write the spec".
