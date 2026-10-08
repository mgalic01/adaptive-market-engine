# Experiment specification v3: trend-following, long and short, on perpetual futures (draft)

**Status:** draft, not frozen. Claude wrote it from the owner's design decisions of 2026-10-08 (§11).
- **Before any build:** the owner reviews this draft, Codex and Bob review it, and the owner gives the go to freeze it. The freeze comes before any code that could be tuned to results, and before any v3 run.
- **After the freeze:** a change requires a new version. The freeze covers this file only. The build plan may change, and where the two differ, this spec rules.
- **Scope:** historical replay only, on paper. Nothing here authorises live trading, exchange credentials, API keys or withdrawals. No v3 code places, signs or routes an order.
- **The bot's operating rules, as amended for v3** (§11, decision 11). The README and SECURITY.md said the bot trades "only Binance spot markets; no leverage, futures, or martingale". The owner amended both in the PR that adds this spec:
  - futures and short positions are allowed in historical backtests and paper trading, at no more than 1x leverage;
  - live futures trading still needs a separate owner decision.
  - v3 itself is historical replay only (above).
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
  - The fetch also records today's exchange filters (quantity step, minimum notional) for the 10 symbols, once, in the manifest: the USDⓈ-M perpetuals' for the account, and spot's for the hold benchmark (§8). Historical filters are not published (spec v1 P4), so today's are used and the record says so.
- **Integrity:** the 1h futures klines go through the repairing reader of the long-window data (#186, #189).
  - Spec v1 §5 rule 5, "Untraded basket symbols' repaired hours are masked", covers a symbol that has only its 1h archive, so a repaired hour cannot be checked against minutes. v3's futures are in the same position. So every hour the reader repairs is masked, and so is every missing hour (rule 1).
  - A coin-month with more than 17% of its hours masked is excluded, under spec v1 §5's 17% rule.
  - So is a coin-month whose funding file is missing, or does not match its exact schedule:
    - every record of the month must declare the same interval I (`funding_interval_hours`), and I must divide 24;
    - the expected slots are 00:00 UTC + k × I hours, for every k that falls inside the month;
    - each record's timestamp must lie within 60 seconds after one slot, and every slot must have exactly one record;
    - a missing slot, a duplicate, a record off its slot, or a change of interval inside the month excludes the month.

    Slots run continuously across months, since each month's start is a slot. The record lists every month excluded this way.

    Bob's funding audit found BTCUSDT's 2020–2024 records always at an 8-hour interval, with offsets of at most 47 ms (`docs/reviews/2026-09-25-bob-funding-cadence.md`).
  - **An excluded coin-month** gives that coin a target of 0 for the whole month, in every run: the out-of-sample account, the training runs and the hold benchmark.
    - An open position closes at the decision made after the close of the day before the previous month's last day. That decision fills at 01:00 UTC on the previous month's last day, so the coin is flat through every funding timestamp of the excluded month.
    - The coin trades again from the first decision whose fill falls after the excluded month.
    - Exclusions are a data fact, settled from the committed manifest before any run, so knowing one a month ahead uses no market information. In live trading a data gap would not be known in advance, so the record states this simplification.
    - If that closing fill has no unmasked hour on the previous month's last day, it moves to the next unmasked hour before the excluded month starts. If there is none, the run is invalid (§8). The record lists every time this happens, in training runs too.
  - Spec v1 §5's other rules concern minute replay, the daily/hourly cross-check and the spot spread limit (rule 8, "XRP below the tick limit"). They do not apply to v3, which neither replays minutes nor quotes inside the spread.

**Spot data:**
- **1h spot klines for all 10 coins,** from 2018-06, or the coin's first full spot month if later, to 2024-12.
  - Nine coins' files are already in `full-range-2017-2024`'s committed manifest (#199), and are reused with the same checksums.
  - ADAUSDT is not in that dataset, so its files are fetched in the same Bob task.
  - The kline integrity rules above apply to them too: the repairing reader, hour masking, the 17% rule and the per-day completeness rule. The funding rules apply to futures months only, since spot has no funding.
  - **A spot coin-month that is excluded** gives that coin a target of 0 for the same month, as a futures exclusion does, and its days drop out of the daily series.
- **Daily bars for signals** (§4) are aggregated from these spot 1h bars: R5 needs highs and lows, and the other rules use closes.
- **The hold benchmark** (§8) uses the same spot 1h bars.
- **Why spot for signals:** the slow rules need up to a year of history. Spot history from 2018-06, or from a coin's first full spot month if later, gives each coin more than a year before its futures data start (§3), except where the spot listing is too late for that. The fetch records each coin's first spot month and first futures month in the manifest, and the record lists every coin with less than a year of spot history before its futures start. SOLUSDT, whose spot is listed from 2020-08 in `full-range-2017-2024`, is expected to be one. There, a rule gives 0 until it has enough history (§4). Signals from spot let a coin trade from its first futures day. Fills, profit and loss, and funding all use futures prices.

**Daily bars** are UTC days, built from the unmasked 1h bars of each day:
- open is the first unmasked hour's open, and close is the last unmasked hour's close;
- high and low are the maximum and minimum over the unmasked hours;
- a day needs at least 20 of its 24 hours unmasked to give a bar. That is the 17% rule applied to the day: up to 4 masked hours. A day with some hours masked but at least 20 unmasked still gives a bar, and is reported as such;
- a day with more than 4 hours masked, or in an excluded month, gives no bar.

**The daily series** of a coin is its bars in date order, with missing days simply absent:
- "n closes" means the last n available bars, and "the close 365 days earlier" (R4) means the last available close on or before that calendar date. If that close is more than 7 days before the date, R4 gives 0 for that day;
- a daily return is the simple return between two consecutive available closes. It is a **one-day return** if the two bars are on consecutive UTC days. σ and Σ (§5) use only one-day returns: a return across a gap is left out of both.

## 3. Coins

BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, LTCUSDT, LINKUSDT and TRXUSDT, as perpetuals.
- **A coin joins the portfolio** at its first month that has both a full month of futures klines and a funding file, and leaves only for an excluded month (§2). The fetch settles each coin's first month.
- **Hindsight (disclosed):** these coins were chosen in 2026, and all of them are still large today. Coins that crashed or were delisted are not in the set, so the results are flattered.
  - The reserved window cannot remove this bias. The set was chosen knowing that these coins stayed large through 2025–26, which is information from inside that window, even though its prices stay unopened.
  - A reserved run would test unseen prices for a set chosen with hindsight. It would not be a bias-free confirmation, and any record of it must say so.

## 4. The rules

Each rule maps a coin's daily closes, up to and including day d, to a signal for day d+1: **+1 long, −1 short, 0 flat.** The menu, with fixed, standard settings:

| # | Rule | Signal |
| --- | --- | --- |
| R1 | **SMA50** | close > SMA(50) → +1; close < SMA(50) → −1; equal → 0. D's rule, with a short side. |
| R2 | **EMA 21/55** | EMA(21) > EMA(55) → +1; below → −1; equal → 0. Each EMA starts as the simple average of its first n closes, at bar n, then `EMA_t = α × C_t + (1 − α) × EMA_{t−1}` with `α = 2 ÷ (n + 1)`. |
| R3 | **Donchian 55/20** | "Prior n-day" means the n bars ending the bar before. Each day, in this order: a close above the prior 55-day high → +1; else a close below the prior 55-day low → −1; else a long whose close is below the prior 20-day low → 0; else a short whose close is above the prior 20-day high → 0; else unchanged. Starts flat. A close that breaks both a long's 20-day exit and the 55-day low reverses to −1, and likewise for a short. Highs and lows are the daily bars' (§2). |
| R4 | **12-month momentum** | close ÷ close 365 days earlier − 1: > 0 → +1; < 0 → −1; = 0 → 0. |
| R5 | **Supertrend 10/3** | Defined in full below the table. Uptrend → +1, downtrend → −1. |
| R6 | **Equal blend** | the mean of R1–R5's signals, a value in [−1, +1]. It is the only rule whose signal is not just −1, 0 or +1. A rule still warming up counts as 0 in the mean, which dilutes R6 early on, and that is intended. |

**R5 in full**, on daily bars (H, L, C):
- **True range:** `TR_t = max(H_t − L_t, |H_t − C_{t−1}|, |L_t − C_{t−1}|)`, from the second bar on.
- **ATR:** the first ATR is the mean of the first 10 true ranges, at bar 11. After that, `ATR_t = (9 × ATR_{t−1} + TR_t) ÷ 10` (Wilder).
- **Basic bands:** `mid = (H_t + L_t) ÷ 2`; `basic_upper = mid + 3 × ATR_t`; `basic_lower = mid − 3 × ATR_t`.
- **Final bands:** at bar 11 they equal the basic bands. After that:
  - `upper_t = basic_upper_t` if `basic_upper_t < upper_{t−1}` or `C_{t−1} > upper_{t−1}`, else `upper_{t−1}`;
  - `lower_t = basic_lower_t` if `basic_lower_t > lower_{t−1}` or `C_{t−1} < lower_{t−1}`, else `lower_{t−1}`.
- **Trend:** at bar 11, uptrend if `C_t ≥ mid`, else downtrend. After that, an uptrend turns down when `C_t < lower_t`, and a downtrend turns up when `C_t > upper_t`. Otherwise it continues.

- **Signals run on each coin's whole spot daily series,** from its first spot bar, once and continuously. They are never restarted at a training window or a test quarter: every run reads the same signal series.
  - Recursive state carries across days with no spot bar: a day that fails the per-day rule, or a spot month excluded under §2. That state is the EMAs, R5's ATR, bands and trend, and R3's held position, so a missing day adds no update and resets nothing.
  - A month excluded on the futures side only (its futures klines or funding fail §2) keeps its spot bars. They go on updating the signals, and only the coin's target is 0 that month.
- **A date with no spot bar for a coin:** for the decision after that date, the coin keeps its previous signal and takes no order (its position stays as it is), and any deferred order it already has stays pending. The other coins are decided as usual. Its σ and its Σ entries use its one-day returns as available (§2).
  - **The mandatory close before an excluded month (§2) overrides this.** It does not depend on the signal, so it is made even when its decision day has no bar, and it cancels any deferred order the coin still has.
- **A rule with too little history** for a coin gives 0 for that coin until it has enough: 50 closes for R1, 55 for R2, 56 bars for R3 (55 prior bars and the current one), a close at least 365 days earlier for R4, and 11 bars for R5.
- **No other strategy family is in v3.** That covers mean reversion, scalping, breakout variants, pattern recognition, market structure, pairs trading and funding arbitrage (§10). Each extra rule is another trial, and more trials make a lucky pass more likely.

## 5. Sizing

At each daily decision, after day d's close:

1. **Raw weight:** for each coin with a non-zero signal `s`, `raw = s × (1 / σ)`, where σ is the annualised volatility of the coin's daily spot simple returns over the last 60 days (sample standard deviation × √365).
   - σ uses the coin's last 60 one-day returns (§2). A coin with fewer than 60, or with σ = 0, gets a raw weight of 0.
   - **A coin in an excluded month (§2)** has its signal set to 0 before this step. So it has a raw weight of 0, and it is not in Σ. The hold benchmark follows the same rule.
   - Spot history precedes every coin's futures history (§2), so a coin that joins mid-window normally already has its 60 returns.
2. **Volatility target:** the portfolio's estimated volatility is `√(rawᵀ Σ raw)`, where Σ is the 60-day sample covariance matrix of the same returns, annualised, over the coins with a non-zero raw weight. All raw weights are scaled by `0.20 ÷ that estimate`, so the portfolio targets **20% volatility a year**.
   - Σ uses the last 60 UTC days, keeping only the days on which every coin with a non-zero raw weight has a one-day return (§2), so every pair of returns spans the same calendar day. If fewer than 40 such days remain, every target is 0.
   - Σ is never inverted, so a singular Σ needs no special case.
   - σ (each coin's own last 60 returns) and Σ's diagonal (the common days only) can differ. That is intended: σ sets each coin's relative weight, and Σ estimates the whole book's risk.
   - If every raw weight is 0, or the estimate is 0, every target is 0: the book goes flat.
3. **Caps,** applied after scaling, in this order:
   - each coin's |weight| ≤ 0.10 of equity;
   - the sum of |weights| ≤ 0.80;
   - if the sum exceeds 0.80, every weight is scaled down proportionally.

   These caps bind the targets at each decision. Between decisions, price moves can push actual leverage above them; the hourly check in §6 enforces 1x on the actual book.
4. **Rebalancing:** a coin trades to its target only if `|target weight − current weight| > 0.01`, or if the signal changes sign or goes to or from 0. Otherwise its position stays.
   - The current weight is `quantity × the fill hour's open ÷ equity at that open`.
   - The band is tested on weights, before any rounding.
5. **Quantity:** `target quantity = target weight × equity ÷ open`, where equity is the account's mark at the fill hour's open, before that hour's fills, and open is that hour's unslipped open (§6).
   - The quantity rounds toward zero to the symbol's quantity step.
   - A trade that opens or increases a position on one side is not made if its notional, `|quantity change| × open`, is below the symbol's minimum notional, and it is reported. A flip is never tested as one trade (below).
   - A trade that reduces or closes a position is always made, at any size, as a reduce-only order is on Binance.
   - **A flip** (long to short, or short to long) is two orders at the same fill price: first a close of the whole position, always made; then an opening order for the new side. The opening order rounds to the quantity step and must meet the minimum notional on its own, `|new quantity| × open`. If it does not, the coin is left flat, and this is reported. Each order pays its own fee.

**Precision:** every sizing computation runs in `Decimal` at 60 significant digits with `ROUND_HALF_EVEN`, including the covariance, the square roots (`Decimal.sqrt`) and the scaling. Prices and rates are used exactly as archived.

## 6. The account

**One portfolio account** at 10,000 USDT, with cross margin, run on hourly futures bars.
- **Fills:** each daily decision fills at the open of the 1h bar that starts one hour after the UTC day's close (01:00 UTC). A buy fills at `open × (1 + 0.0005)` and a sell at `open × (1 − 0.0005)`, which is the slippage. Each fill pays the taker fee, 0.05% (Binance USDⓈ-M, VIP 0), of its slipped notional, `|fill quantity| × fill price`, so buys and sells both pay a positive fee. Quantities come from §5 step 5.
- **A masked fill hour:** the fill moves to the open of the next unmasked hour of that coin, on the same terms. The current weight, the equity and the open of §5 steps 4 and 5 are all taken at that actual fill hour.
  - **Colliding decisions:** a coin has at most one pending daily order. If a later daily decision comes while an earlier one is still deferred, the earlier one is cancelled. Only the latest decision's target is filled, with its band test and quantity computed at the fill hour. Each cancellation is reported.
- **Funding:** each timestamp in the coin's funding file belongs to the 1h bar whose hour contains it, so millisecond offsets map to the hour they fall in.
  - The position pays `quantity × price × rate` if it is long and the rate is positive. A short receives it. A negative rate reverses both.
  - The price is that bar's open, or, if the bar is masked or missing, the open of the last unmasked bar before it.
  - Binance charges funding on the mark price, not on the last-trade price. Using the bar's open is a disclosed approximation: the two differ by the basis, which is small next to the funding rate's own variation.
  - **Order within an hour:** see "Order of events in an hour" below.
  - Funding is charged at exactly the timestamps in the file. A month whose file breaks its schedule is excluded (§2), so no included month has a missing payment.
- **Order of events in an hour,** for every hour from the first to the last of the run:
  1. **The open mark,** at the bar's open time, before any of the hour's fills or funding. The daily 01:00 sample (§8) is this mark, and no funding falls at 01:00.
  2. **The pre-fill liquidation check,** on the quantities held at the open, at the open prices. A book that gapped through the threshold is liquidated (below), and the hour's fills are cancelled.
  3. **The hour's events,** in the order of their raw timestamps:
     - fills happen at the bar's open time: the daily decision's orders;
     - funding happens at its recorded timestamp, which is at or a few milliseconds after the open;
     - so, except on an exact tie, a fill at the open is charged that hour's funding on the post-fill quantity;
     - on an exact tie, funding comes first, and the pre-fill liquidation check (step 2) is repeated right after that funding, before the tied fill. A book the funding pushes through the threshold is liquidated there, and the fill is cancelled.
  4. **The post-fill mark:** equity after step 3, at the same open prices, so the fees, slippage and any realised loss of those fills, and that hour's funding, show at once.
  5. **The 1x-ceiling check,** on the quantities after the fills, at the open mark. If gross leverage exceeds 1.0, the delevering (below) fills at this same open, and the post-fill mark is taken again after it.
  6. **The post-fill liquidation check,** on the quantities after any delevering, at the bar's adverse extremes.

  **Within one hour's fills:**
  - **The daily decision's orders come first.** Among them, every order that reduces or closes a position goes first, then every order that opens or increases one, each group in alphabetical order of symbol.
  - **Then any delevering** (step 5): k is computed on the book after all of the hour's daily fills, and its orders follow at the same open, in alphabetical order of symbol. One delevering per hour at most. It targets 0.80, so a book above 1.0 is brought well under it.
- **Marking:** equity is marked at every hour's open (the wallet and equity are defined under "Wallet and equity" below).
  - **A coin's mark price** in an hour is that hour's open.
  - **In a masked or missing hour,** which an included month may have (up to 17%), the coin's mark is the open of its last unmasked hour before it. Its funding price is the same (above), and its liquidation check uses that same price, since the hour has no usable high or low.
  - **At the first unmasked hour after a gap,** the mark, the adverse extremes and the liquidation check use that hour's own bar, so a move across the gap is caught there.
  - Hours with an open position and a masked bar are counted and reported.
- **Liquidation:** each hour, equity is also computed at each position's adverse extreme of that 1h bar: the low for a long, the high for a short, all at once.
  - If that equity is ≤ 1% of the gross open notional, the account is liquidated.
  - **Either kind of liquidation,** the pre-fill check at the open or this post-fill check, is recorded at the hour of the check, with each position's price in that check. The run is invalid from then on (§8), and no later order is simulated. The gross open notional is `Σ |quantity| × price` at the same adverse-extreme prices.
  - The 1% threshold is Claude's design choice, deliberately conservative. It is a simplified stand-in for Binance's tiered maintenance margin. Checked at the open and at the bar's adverse extremes, it can fail a run that Binance would not have liquidated, so it leans against v3.
  - It is expected never to happen at these sizes.
- **The 1x ceiling, on the actual book:** at every hourly mark, gross leverage is `Σ |quantity| × mark ÷ equity`.
  - If it exceeds 1.0, the account delevers **in the same hour, at the same open** (step 5 of the hour's order). Gross leverage is checked at hourly opens, so it can exceed 1.0 inside an hour between two checks. The record reports the highest gross leverage seen at the bars' adverse extremes.
  - **The factor** is `k = 0.80 × equity ÷ gross notional`, on the book after that hour's daily fills, at its open mark.
  - Each coin's position is reduced, on the side it is actually held, to `held quantity × k`, rounding toward zero to the quantity step, by reduce-only orders at that open, with the usual slippage and fees.
  - A delevering order is reduce-only, so it ignores the minimum notional.
  - **When some positions cannot trade** because their hour is masked, they stay at their carried marks. The tradable positions are then reduced by `k' = (0.80 × equity − masked gross) ÷ tradable gross`, so gross leverage falls to 0.80 at once:
    - if k' ≤ 0, every tradable position is closed;
    - if the masked positions alone exceed 1.0 × equity, the ceiling cannot be restored, and the run is invalid (§8);
    - a masked position is checked again at its next unmasked hour, by the ordinary rule.
  - If equity is ≤ 0 at a mark, the ratio is not computed: the liquidation check has already failed the run.
  - Each such delevering is reported.
  - **After a delevering,** the next daily decision tests its band (§5 step 4) against the post-delevering weight, so a gap above 1% is rebalanced back toward the target. A slow cycle is therefore possible: delever, re-size at the next decision, then delever again after a further rise. Each step is reported, and none can repeat within an hour.
- **Wallet and equity.** A perpetual futures position does not exchange its notional with the wallet: opening it moves no cash. Only fees, funding and realised profit and loss move the wallet.
  - **Average entry price:** each coin's position carries one. An order that opens or increases the position updates it to the quantity-weighted average of the old position and the fill. An order that reduces or closes it leaves it unchanged.
  - **Realised profit and loss** of a reducing or closing fill is `closed quantity × (fill price − average entry)` for a long, and `closed quantity × (average entry − fill price)` for a short.
  - **The wallet** is the initial capital, plus realised profit and loss, minus fees, minus funding paid, plus funding received.
  - **Unrealised profit and loss** of a position is `quantity × (mark − average entry)`, with quantity signed (negative for a short).
  - **Equity** is the wallet plus the unrealised profit and loss of every position.
- **Accounting identities,** exact and checked at the end of every run, as in spec v1 P6:
  - the wallet equals the initial capital + Σ realised profit and loss − Σ fees − Σ funding paid + Σ funding received, each summed from the fill and funding records;
  - each coin's quantity equals its bought quantity minus its sold quantity;
  - the change in equity equals realised plus unrealised profit and loss, minus fees, minus funding paid, plus funding received.

**No recovery, restart or rebasing.** v3 has no soft-drawdown recovery, halt, restart or any other rule that moves a reference peak. Drawdown is measured from the run's true peak, the running maximum of the hourly equity marks, and that peak is never lowered. Codex's diagnosis of v2 found that v2's risk layer could lower its own peak after a recovery, so it never enforced the lifetime drawdown that C1 measured (§11, decision 10). v3's sizing is the only risk control, and A3 judges it against the true peak.

**Costs stress, reported only:** every run is repeated at double fees and double slippage.

## 7. Walk-forward

- **Windows:** train on 18 calendar months, then test on the next 3, and roll forward by 3.
  - The first test quarter is the first calendar quarter that starts at least 18 months after BTCUSDT's first month in the portfolio (§3).
  - If BTCUSDT's funding archives begin in 2020-01, as #137 found, that is **2021-Q3**, giving 14 test quarters. The fetch settles it, and the record states the count.
  - The last test quarter is **2024-Q4**.
- **Picking:** in each training window, each of R1–R6 is run on the whole portfolio, with the sizing, costs and funding of §5–6. The rule with the highest Sharpe ratio (§8) over that window trades the next test quarter. A tie goes to the lower rule number.
- **Continuity:** one account runs through all test quarters.
  - **The start:** it starts flat, with 10,000 USDT, at 00:00 UTC on the first test quarter's first day. Its first decision is the one made after the close of the day before, with that quarter's pick, and it fills at 01:00 on the quarter's first day.
  - **At each boundary:** the decision made after the last day of quarter q uses quarter q+1's pick, and fills on q+1's first day. The book moves to the new rule's targets there, by the normal band test.
  - **Training runs** are separate, fresh accounts, and never touch it. Each one starts the same way: flat, with 10,000 USDT, at 00:00 on its window's first day, with its first decision after the close of the day before.
- **Sample series,** the same for every run, training or out-of-sample:
  - the daily samples at 01:00 before fills, from the run's first day (equal to 10,000, since the account is flat);
  - one terminal sample at the close of the last 1h bar of the run's last day, with each coin at its last unmasked close (§8);
  - the first return runs from the first day's 01:00 sample.
- **Out-of-sample** means only the test quarters, stitched in order. Every pass criterion is computed on that stitched run.

## 8. Evaluation

**Metrics,** on the stitched out-of-sample run, from the daily equity series at 01:00 UTC before that hour's fills. One terminal sample closes the series: equity at the close of the last 1h bar of 2024-12-31, the 23:00 bar, with each coin marked at its last unmasked close of 2024.
- That is a deliberate exception to the open-mark convention of §6. There is no later open inside the window, and the 23:00 bar's close is in the 2024-12 archive.
- So the last daily return covers the window's final 23 hours, and no 2025 data is read.
- The maximum drawdown includes this terminal mark.
- **Sharpe ratio:** mean ÷ sample standard deviation (n − 1) of the daily simple returns, × √365, with a risk-free rate of 0. The hold benchmark's Sharpe ratio (A5) uses the same formula over the same days. With fewer than two returns, or a standard deviation of 0, the Sharpe ratio is 0. In training windows that means it cannot beat a rule with a positive one, and in A1 it fails.
- **Profit factor:** the sum of the positive daily changes in equity (in USDT, between consecutive daily samples) ÷ the absolute sum of the negative ones.
  - With no negative day and at least one positive day, it is +∞, and A2 passes.
  - With no positive day, it is 0, and A2 fails.
- **CAGR:** compound annual growth over the out-of-sample days (365.25-day years).
- **Maximum drawdown:** the largest fall from a running peak along one path of equity states. Each hour contributes four states, in this order:
  1. its open mark;
  2. its post-fill mark;
  3. its favourable-extreme equity: every position at its bar's favourable extreme at once (the high for a long, the low for a short);
  4. its adverse-extreme equity: every position at its bar's adverse extreme at once (the post-fill liquidation check's).

  The terminal mark ends the path. Peak and trough use the same path.
  - Putting the favourable extreme before the adverse one in every hour, and taking every coin's extreme at once, can overstate a drawdown. That leans against v3.
- **Calmar ratio:** CAGR ÷ maximum drawdown.
  - With a maximum drawdown of 0 and a positive CAGR, it is +∞, and A3 passes.
  - With a maximum drawdown of 0 and a CAGR of 0 or less, it is 0, and A3 fails.
- **Precision:** A1–A5 are computed in `Decimal` at 60 significant digits with `ROUND_HALF_EVEN`, as sizing is. The bootstrap interval below is reported only, and may use binary floating point.

**Acceptance.** v3 passes only if all five hold:

| # | Criterion |
| --- | --- |
| A1 | Sharpe ratio ≥ 1.0 |
| A2 | Profit factor ≥ 1.3 |
| A3 | Calmar ratio ≥ 0.5 |
| A4 | CAGR ≥ 8% (the owner's passive-investment hurdle) |
| A5 | The Sharpe ratio exceeds the hold benchmark's over the same days |

**The hold benchmark:** long-only, equal signal (+1) for every coin in the portfolio at that time, on spot prices with no funding. It answers one question: does timing add anything over just holding the same coins at the same risk?
- **The same as the account:** the sizing (§5: volatility target, caps, rebalancing band), the fees and slippage, the fill timing, the masked-hour rule, the excluded months (§2: both the futures exclusions, which decide when a coin is in the portfolio, and its own spot exclusions) and the order of events (§6).
- **It is one account** that starts flat at the first test quarter's start, as the main account does (§7), and runs continuously to the end of 2024-Q4.
- **Its own account is a spot account,** 10,000 USDT:
  - a buy spends its notional plus its fee from cash, and a sell adds its notional minus its fee;
  - sells go before buys, as in §6. A buy larger than the cash then available is cut to what the cash pays for, fee included, rounded down to the step. If that is below the minimum notional, it is skipped and reported. Neither case invalidates the run;
  - equity is cash plus each holding's quantity × its spot mark;
  - quantities round to the spot quantity step;
  - spot's minimum notional applies to buys and sells alike, as the project's spot execution refuses a sell below it (`simulation/execution.py`);
  - a holding too small to sell stays as dust. It is marked in equity, reported, and sold once it can be: it may not be sellable during an excluded month, and that does not invalidate the run;
  - its gross exposure is at most 0.80 by the caps, and it never borrows, so the 1x ceiling and the liquidation check do not apply to it;
  - its accounting identities are spot's: cash reconciles to the initial capital minus buys plus sells minus fees, and each quantity to its buys minus its sells.
- **It holds spot, without funding, on purpose.** That is the realistic "just hold" alternative. In 2020–2024 funding was mostly positive (#137), so holding long perpetuals would have paid funding and done worse. The asymmetry leans in the benchmark's favour, against v3.

**A run is invalid** if an accounting identity fails, a liquidation occurs, or a fill the rules require cannot be made.
- **The out-of-sample account or the hold benchmark invalid:** v3 fails.
- **A training run invalid:** only that rule is out of the pick for that window, and the record says so.
- **All six training runs invalid in a window:** the book is flat (every target 0) for that test quarter, and the record says so.

**Reported, deciding nothing:**
- **The owner's monthly target:** every out-of-sample month's return, beside the owner's 20–30% target, and how many months reached 20%.
- each rule's full-period results, as if picked every quarter;
- **each rule's long-only twin:** the same rule and sizing with every negative signal set to 0, including R6's fractional ones;
- the long-versus-short split of profit and loss, per rule and per coin;
- funding paid and received, fees, slippage and turnover;
- the time invested, gross and net;
- the realised portfolio volatility against the 20% target, and the share of decision days on which a cap bound: some coin's target was clipped at 10%, or the 80% gross cap scaled the book. This counts whatever the number of coins in the portfolio that day. With few coins early on, the 10% cap can hold the book below target, and A4 is not scale-free;
  - **Reading the coin count:** the few-coin effect falls mainly on the training windows. By the first test quarter, every coin whose futures started in 2019–2020 is already in the portfolio. The record gives the coin count for each test quarter;
- a 95% interval for the Sharpe ratio, beside A1 and A5. It is a stationary block bootstrap of the daily returns (Politis and Romano):
  - block lengths are geometric, with a mean of 20 days, and blocks wrap around the end of the series (circular, as in Politis and Romano);
  - with fewer than 60 daily returns, no interval is reported;
  - 10,000 resamples;
  - Python's `random.Random(20261008)` as the only source of randomness;
  - the 2.5th and 97.5th percentiles of the resampled Sharpe ratios, by the nearest-rank method;
- the double-cost results;
- the worst drawdown's dates, and the maximum drawdown beside equal-weight buy-and-hold's;
- the picks quarter by quarter;
- variant D, and plain equal-weight buy-and-hold at full size;
- **the minimum account size:** computed by scaling, not by rerunning. For each order that opens or increases a position in the 10,000-USDT out-of-sample run, the ratio of the symbol's minimum notional to that order's notional, × 10,000 USDT. The largest such value, rounded up to the next 10 USDT, is reported.
  - It ignores how rounding and refusals at a smaller account would change the later path, and the record says so.
- **the lowest margin ratio reached:** the minimum, over every liquidation check with an open position, of equity ÷ gross open notional, against the 1% threshold. A check on a flat book has no ratio and is skipped. If the book is never open, the record says so. This shows how close the run came to the threshold;

**Decision and trade records** (required outputs, written with every run, and never read back by any decision; §11, decision 10):
- **Every daily decision, per coin:**
  - the signal of every rule R1–R6, and which rule is picked;
  - σ, the raw weight, the scaled weight and which cap bound;
  - the final target, and whether the band skipped the trade;
  - any minimum-notional refusal, or flat-after-flip;
  - the fill hour (and whether it was deferred), the filled quantity, the fill price and the fee.
- **Every position's lifecycle.** A position runs from flat to non-zero, and ends back at flat or at a flip. For each one:
  - the coin and side;
  - every fill, with its time, quantity and price;
  - the exit's trigger: the signal going to 0, a flip, a pick change, an excluded month, a delevering that rounds the position to 0, or a liquidation;
  - **a position still open when a run ends** is not closed: no fill, fee or slippage is charged. It is marked at the terminal mark (§8), its profit and loss stays unrealised, and its record is labelled censored, with that unrealised profit and loss. This holds for training runs and for the out-of-sample run;
  - its duration;
  - its maximum favourable and maximum adverse excursion, in USDT, before fees and funding. For each hour the position is open, two values are taken: the profit and loss realised so far in the lifecycle, plus the remaining position's unrealised profit and loss at the bar's favourable extreme, and the same at its adverse extreme. Both use the quantity and average entry price in force during that hour, and earlier hours are never recomputed against a later average entry. The excursions are the maximum and the minimum of these hourly values;
  - **Each reducing or closing fill** adds one more excursion state: the lifecycle's realised profit and loss after that fill, plus the remaining position's unrealised profit and loss at the fill price. So a close after a favourable gap counts in the maximum favourable excursion, and profit given back cannot be negative;
  - the profit given back: the maximum favourable excursion minus the lifecycle's final profit and loss before fees and funding. For a closed position that is its total realised profit and loss. For a censored one it is the profit and loss realised so far plus the unrealised at the terminal mark;
  - its realised profit and loss, fees, and funding paid and received.
- **Every walk-forward window:** each rule's training Sharpe ratio and validity, and the pick.
- **The equity series:** hourly total equity, the running peak and the drawdown, never rebased.
- The design follows Codex's entry-attribution work on v2 (#208).

**Outcome:**
- **If v3 passes,** the reserved 2025–26 window may run once, as a confirmation. Before it runs, two things are needed, and nothing in v3 runs on it before then:
  - **A written rule,** as spec v1's C7 ([§6](EXPERIMENT_SPEC_V1.md#6-acceptance-and-selection-owner-decisions-2026-09-24)), including a multiple-testing correction over the whole family tried on these years: v1's variants, v2's mode switcher, D, #137's rules, and v3's six rules with its picking procedure. Alternatively, the owner may waive that correction in writing.
  - **The owner's go.**
- **If it fails,** v3 ends with no pass, and nothing runs on the reserved window.

**Trials:** six rules and one picking procedure, all fixed in this draft before any v3 result. The long-only twins are reported, never picked.

**Prior exposure (disclosed):**
- **v2's runs** covered 2019–2024 on spot for BTCUSDT and ETHUSDT, with a different strategy. Their results, and D's, were seen before this design.
- **#137** (2026-09-28) ran three published trend rules on BTCUSDT 2017–2024. Adding a short side made each one worse: 12-month momentum fell from +1,423% to +700%, a Donchian breakout from +2,643% to +377%, and 50/200 averages from +593% to +57%. This is why every report shows the long-only twins and the long-versus-short split (§11, decision 7).
- **Codex's diagnosis of v2** (2026-10-08) informed v3's records, and the statement on lifetime drawdown (§11, decision 10).
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
   - The pass bar the owner approved afterwards carries the Calmar ratio as A3, and has no separate drawdown-versus-buy-and-hold criterion. The maximum drawdown and buy-and-hold's are both reported (§8). Two later answers record that pass bar:
     - **Decision 5's option,** quoted below, lists the pass as the gate, Calmar, 8% a year, and beating the same coins held at the same risk.
     - **Design section 4.** The question put to the owner was: "Section 4 (walk-forward and scoring): 18-month train / 3-month test, rolling quarterly; 15 out-of-sample quarters (2021-Q2 to 2024-Q4); the best-Sharpe rule of the menu trades each next quarter; pass = all of Sharpe >= 1.0, profit factor >= 1.3 (daily), Calmar >= 0.5, >= 8%/yr net, and a higher Sharpe than the same coins held at the same 20% risk; monthly returns vs your 20-30% target reported. OK?" The owner answered "Looks right".
     - Its quarter count was later corrected by review: funding archives begin in 2020-01, so the start is conditional on the fetch. §7 now expects 2021-Q3 and 14 quarters if they do.
3. **Shorts.** Question: "How should v3 handle the short side?" Chosen: **"Long and short on futures data"**: perpetual-futures prices and funding history fetched by Bob, real funding charged, at 1x leverage.
4. **Coins.** Question: "Which coins should v3 trade?" Chosen: **"Our 10 coins, bias stated"**.
5. **The pass bar.** The owner first answered: "our strategy needs to make 20-30% profits per month." Claude explained that 20% a month is about +790% a year, and that at 1x leverage and a 20% risk budget it would need a Sharpe ratio near 30. Question: "Given that 20-30% a month can't be reached at 1x leverage and a 20-25% risk budget, how should v3 judge a pass?" Chosen: **"Realistic bar, report vs 20-30%"**. The option said: "Pass = the gate (Sharpe >= 1.0, profit factor >= 1.3) + Calmar >= 0.5 + at least 8% a year + beats holding the same coins at the same risk. Every report also shows monthly returns against your 20-30% target, so the gap is visible."
6. **The rules.** Question: "How should v3 choose its trend rules?" Chosen: **"Walk-forward pick from a fixed menu"**: about six standard rules fixed in advance; in each 18-month window the best is picked and traded for the next 3 months; only those months count.
7. **The short side, after #137.** Claude disclosed #137's finding that shorts made trend rules worse on BTCUSDT. Question: "How should v3 treat the short side?" Chosen: **"Keep long+short, report long-only alongside"**.
8. **The build approach.** Question: "Which way should the v3 test be built?" Chosen: **"A: new hourly backtester"**: its own module, hourly futures bars, exact decimals, real funding, fills at the next hour's open with slippage and fees.
9. **The design sections.** The owner approved Claude's five design sections, on the data, the rules, sizing and costs, walk-forward and scoring, and the build, and asked for this draft: "Looks right, write the spec".
10. **Codex's input.** The owner said: "Codex will send you his brainstorming and info on what he things we should do next, we should incorporate all of it in V3."
    - **Codex's input:**
      - its diagnosis of v2's scored runs, published in #208 as `docs/backtests/2026-10-08-spec-v2-diagnosis.md` (at `558c86d`). Its earlier local copy, `DIAGNOSIS.md`, has the same findings;
      - its entry-attribution work, #208 and `docs/reviews/2026-10-08-codex-entry-attribution.md`.
    - **The diagnosis concludes:**
      - v2's recovery controls did not enforce lifetime drawdown;
      - entries left very little participation;
      - exit losses consumed much of the gain.
    - **It recommends:**
      - recording every entry rejection and every position's lifecycle;
      - settling lifetime risk before more participation;
      - testing one change at a time.
    - Claude put the one tension to the owner. Question: "Codex advises testing one change at a time; v3 as designed changes several at once (futures, shorts, new rules, new sizing, 10 coins). How should v3 handle this?" Chosen: **"Keep v3, add Codex's records"**. The option said: "v3 stays one combined test, with its existing breakdowns (long-only twins, each rule alone, hold at the same risk, double costs, funding split) plus Codex's full decision and trade-lifecycle records, so every result can be traced to its cause. One test, one verdict."
    - **In this spec:**
      - the records are in §8;
      - the statement that v3 measures drawdown from the true peak, with no rebasing, is in §6.
11. **The spot-only rule.** The owner set a standing way of working (2026-10-08): "when i say that we add new features we add them. IF i say a rule is this and that your role is to tell me about the rule and ask me do i wish to modify it."
    - Claude then put the bot's rule to the owner. Question: "The README says the bot trades "only Binance spot markets; no leverage, futures, or martingale", and SECURITY.md says "Do not ... enable leverage/futures." v3 tests trend-following long and short on futures data. Do you want to modify these rules?"
    - Chosen: **"Allow futures in research and paper"**. The option said: "Amend README and SECURITY: futures and shorts allowed in backtests and paper trading (no live, no leverage above 1x); live trading still needs a separate decision."
    - Both files are amended in the PR that adds this spec. ROADMAP.md's live pilot stays spot-only, since live futures need their own decision.
