# Experiment specification v2: the spot mode switcher (frozen 2026-10-06)

**Status:** frozen on 2026-10-06. Claude wrote it from the owner's design decisions of that day (§11).
- **How it was frozen:**
  - The owner approved the draft (§11, decision 7), and gave the go to freeze it once its reviews were clean (decision 8).
  - PR #174 settled every finding of 13 review rounds. At its final head, `1672f60`, Codex reported no finding, Bob reported NO ISSUES, and CI passed.
  - The freezing PR adds the automated review's last required fix at that head: the disclosure that C5's bar was set after v1's results were seen (§8, "Prior exposure"), and the owner's exception to the no-tuning rule for that bar (§11, decision 9). It merges only when Codex, Bob and CI are clean on it.
- **Before any build:** the freeze comes before any code that could be tuned to results, and before any v2 run.
- **After the first read (2026-10-07):** decisions 10 to 13 (§11) record the owner's choice to continue to the scored window with reporting-only instrumentation, and three readings of this spec. None of them changes a registered rule.
- **After the freeze:** a change requires a new version. The freeze covers this file only. The build plan may still change, and where the two differ, this spec rules (§9, step 1).
- **Scope:** historical replay only. Nothing here authorises live trading, API keys or withdrawals.
  - The mode switcher's runtime state is not saved, and neither is variant F's. So, like v1's E and F, it runs in replay, and a persisted paper account refuses it.
  - Running it as a paper account needs that state saved, with a schema change. That is a separate step before any forward paper test (§10).
- **Spec v1:** it stays frozen as the record of its own experiment. [Spec v1](EXPERIMENT_SPEC_V1.md) ended on 2026-10-06 with no winner ([report](backtests/2026-10-06-spec-v1-stage-1.md)).

**Names.** In v1, "V2" was the market-structure variant. This document is **spec v2**, and the strategy it tests is **the mode switcher**.

## 1. Question

Can one spot bot do better than v1's grids by choosing, per pair and per hour, between three modes, under v1's risk limits?
- **Grid:** in sideways markets.
- **Uptrend:** a single long position with a trailing exit, in clear uptrends.
- **Cash:** whenever the rules are not clearly met.

**Why this question:**
- **v1's stage 1.** No grid variant made money on 2022 or 2024H1. Grids lose in trends and miss bull runs.
- **v1's long-only benchmark D.** Its mean return was positive, but its drawdowns reached 40%, so a trend position must be sized to the risk budget.
- **#137.** Shorting confirmed downtrends lost money on the development data, so shorting is left to a later spec (§10).

## 2. What stays exactly as in v1

These carry over unchanged, as frozen in spec v1 at `f144510`:
- **The engine:** the paper simulator and replay, engine `drawdown-recovery-v2`. Its risk layer applies to the whole account in every mode:
  - the 3% daily-loss pause;
  - the 8% soft drawdown with its recovery (amendment 1, D7), and the 12% hard stop with automatic restart after 24 h;
  - amendments 2 and 3, and the manual resume (D17, D18);
  - the profit vault, which is never traded;
  - drains, liquidation and the dust rules.
- **The grid:** V0's grid (`price-only-v1`) with **variant F's order-flow entry block** exactly as in spec v1 §3 F. This was the best stage-1 result.
- **Data validity:** spec v1 §5 in full:
  - hour-level masking and the repair rule;
  - the post-mask expected set, and the unique-bars condition;
  - the 17% coin-month rule, and the treatment of an untraded proxy;
  - XRP's actual-quotes test;
  - the comparison mask's scoping, including a traded proxy's split.
  - These are owner decisions 13, 15, 16, 20 and 22 in the [test-plan record](reviews/2026-10-05-claude-owner-decisions-test-plan.md).
- **Fees and timing:**
  - the primary fees: maker 0, taker 0.0009;
  - slippage and participation as in the dataset specs;
  - both intrabar paths;
  - spec v1's point-in-time rules: a signal uses completed bars only, and takes effect at the first valid observation at or after its bar's close.

## 3. Perception: three timeframes

**The bars:**
- **1m:** Binance's archives, for fills, and for variant F's order-flow share (spec v1 §3 F), which the grid keeps.
- **1h:** Binance's archives.
- **4h:** built from four consecutive 1h bars aligned to 00:00, 04:00, … UTC. A 4h bar exists only if all four hours are present and unmasked. Otherwise it is missing.
- **1d:** Binance's archives, cross-checked as in spec v1 P3. Each daily bar is used as delivered, because daily bars are never masked (spec v1 §5, rule 3). So a masked hour inside a day leaves that day's daily bar, and the daily state, in use. A missing or duplicated daily bar excludes the pair-window, as in v1 (§5).

**The indicators.** Each is computed on completed bars only. Wilder smoothing applies wherever the standard definition uses it.

| Indicator | Timeframes | Definition |
| --- | --- | --- |
| SMA20, SMA50 | 4h, 1d | simple averages of closes |
| RSI(14) | 1h, 1d | Wilder |
| ADX(14), +DI, −DI | 1h, 4h, 1d | Wilder |
| ATR(14) | 1d | Wilder, for the trailing stop |
| Bollinger width | 1h | (upper − lower) ÷ middle of the 20-bar band at 2 population standard deviations |
| Width median | 1h | the median of the last 720 completed 1h widths (30 days) |

**Zero cases.** RSI is 50 when the average gain and the average loss are both 0. ±DI are 0 when the smoothed true range is 0, and DX is 0 when +DI + −DI is 0, as in V0's hourly ADX (`backtest/features.py`).

**Gaps and availability.** v2 follows the convention of V0's hourly features (spec v1, D13), so that one masked hour, such as an exchange outage, does not blank a 30-day median for a month.
- **Skipping gaps:** each timeframe's indicators are computed over the bars that exist, in time order. A missing or masked bar is skipped, not filled, and every recursion continues with the next bar that exists. A true range uses the previous existing bar's close.
- **Minimum bars,** counted over the bars that exist since the data starts:

  | Indicator | Minimum | First value |
  | --- | --- | --- |
  | SMA20 | 20 bars | |
  | SMA50 | 50 bars | |
  | RSI(14) | 15 bars | seeded with the mean gain and mean loss of its first 14 changes |
  | ATR(14) | 15 bars | seeded with the mean of its first 14 true ranges |
  | ±DI | 15 bars | from Wilder sums seeded over their first 14 values |
  | ADX(14) | 28 bars | seeded with the mean of its first 14 DX values |
  | Bollinger width | 20 bars | |
  | Width median | 720 widths | the median uses the last 720 widths that exist |

- **Unavailable:** a timeframe is **unavailable** at time *t* if either holds:
  - the bar that should have closed last before *t* is missing or masked (the bar opening at ⌊t ÷ L⌋ × L − L, for a bar of length L);
  - any of the timeframe's inputs lacks its minimum bars.
- **The inputs:**
  - A 4h or daily trend state reads all of close, SMA20, SMA50, ADX(14), +DI and −DI, even where the matching row needs fewer. For example, a daily ADX with its 28 bars but an SMA50 without its 50 gives Unavailable, not Range.
  - The 1h timeframe's inputs are RSI(14), ADX(14), the Bollinger width and the width median (§4, Grid).
  - The Uptrend row also needs the daily RSI(14) and ATR(14) (§4).

**The 1h regime** is V0's existing classifier (`strategy/regime.py`, `price-only-v1`). Its labels are RANGE, BULL, BEAR, TRANSITION and STRESS.

**The 4h and daily trend states.** Unavailable is checked first, and it always means Cash (§4).

| State | All of these |
| --- | --- |
| **Unavailable** | the timeframe is unavailable (above) |
| **Up** | close > SMA50; SMA20 > SMA50; ADX(14) ≥ 20; +DI > −DI |
| **Down** | close < SMA50; SMA20 < SMA50; ADX(14) ≥ 20; −DI > +DI |
| **Range** | ADX(14) < 20 |
| **Unclear** | anything else |

## 4. The mode selector

**When it decides:**
- At each completed hour (the first valid observation at or after the hour boundary), the selector sets each pair's mode.
- The 4h and daily states change only at their own bars' closes.

**How it decides.** It checks Uptrend first, then Grid. Anything else is Cash.

| Mode | All of these must hold |
| --- | --- |
| **Uptrend** | daily state Up; 4h state Up; V0's classifier reports its inputs as sound (`input_quality_ok`), and its regime is neither BEAR nor STRESS; daily RSI(14) < 75, with the daily RSI and ATR(14) available; no trailing-stop exit in the last 24 hours (§5) |
| **Grid** | V0's classifier gives RANGE at this hour's decision and at the decisions of the 3 hours before it, which must be consecutive (an hour without a decision, such as a masked one, restarts the count); the 4h state is Range or Unclear; the daily state is Up, Range or Unclear; the 1h timeframe is available, with 1h RSI(14) between 35 and 65 inclusive, 1h ADX(14) < 20, and the 1h Bollinger width ≤ its median |
| **Cash** | otherwise: a row fails when its 4h or daily state is Unavailable, or when an input it reads is unavailable. The 1h inputs are the Grid row's alone, so they never block Uptrend. Cash also holds while warm-up is incomplete, and during a halt |

**What each mode allows:**
- **Grid:** new grids may open, but only when V0's own checks, F's block and the risk layer also allow.
- **Uptrend:** the uptrend engine (§5) may enter.
- **Cash:** neither may.

**Entering versus staying.** The rules above decide which mode a pair *enters*.
- **An uptrend position:** once the pair holds one, the pair stays in Uptrend until one of §5's exits has finished. The selector does not re-decide its mode in between, so a 4h state that stops being Up does not by itself sell the position.
- **An open grid:** when the mode leaves Grid, it winds down (§6). It keeps its resting sells, places no buy, and ends by v1's own exits. If the mode returns to Grid first, it resumes. Only new grids need the Grid conditions.

## 5. The uptrend engine

**Entry:**
- **When:** an entry starts only at a decision's own observation (§4), when that decision sets the mode to Uptrend, the pair is flat (§6) and the risk action is ALLOW (§7).
  - If any of these fails there, or `s ≤ 0` (below), no entry starts before the next decision, which may try again.
  - So a pair that becomes flat between decisions waits for the next one.
- **How:** marketable buys at the taker fee, priced as variant D's: the ask × (1 + slippage), rounded up to the tick. Each is bounded by the participation limit on the ask size and by the exchange's precision.

**Budget, set once when the entry starts:**
- **Two limits:**
  - a cash cap of `0.60 × active capital`, in USDT;
  - a risk allowance of `0.04 × active equity`: the most the entry may lose if the stop is reached, before fees and slippage.
- **Each buy is bounded by both.** A buy of quantity q at buy price p uses q × p × (1 + taker fee) of the cash cap, and q × (p − stop) of the risk allowance. It may use no more than what is left of either. So a later buy at a higher price, which would lose more per unit at the same stop, buys less.
- **For an entry filled at one price,** this is `min(0.60 × active capital, 0.04 × active equity ÷ s)` in USDT, before fees. Here `s`, the stop distance, is (p − initial stop) ÷ p, where p is the first entry quote's buy price. (C5's `d` is the window's length in days, as in v1.)
- **No entry starts when s ≤ 0,** that is, when the price is at or below the initial stop, **or when the quote's bid is at or below the initial stop,** since exit 1 would then fire at once. Neither is a stop-out, so no pause starts.
- Active capital and active equity are spec v1's (the vault excluded).
- A stop-out therefore costs at most about 4% of active equity before fees and slippage, however many quotes the entry took. On a fast fall within one day, the 3% daily-loss pause can drain the position before the stop is reached (§7), and the loss is then smaller.
- **A gap can cost more.** A price gap through the stop loses more than that, and C1 can fail on such a gap even with the 12% hard stop behind it. That is an expected failure mode, not a defect.

**Partial fills:**
- The entry buys at each quote until one of these ends it:
  - what is left of the cash cap, or of the risk allowance, buys less than the minimum notional at that quote's price;
  - a daily close: the position then holds what was bought, and the close is processed as for any held position. So the stop never trails while the entry is still buying;
  - an exit (below), or any risk action other than ALLOW (§7). Under a risk drain, what was bought is sold.
- **Each buy is also bounded by the cash the account can spend,** as any v1 buy is. Dust or held fragments can leave less than the cash cap.
- **Thin depth is not an end.** A quote whose participation limit alone allows less than the minimum notional buys nothing, and the entry waits for the next quote.
- The two limits and the stop stay as set when the entry started. The position is whatever was bought.
- If the stop is reached during the entry, the entry ends and exit 1 sells what was bought.

**The trailing stop:**
- **Value:** the highest daily close since entry, minus 3 × ATR(14) on daily bars.
- **First value:** `c0 − 3 × ATR`, where `c0` is the last completed daily close before entry and the ATR is that day's. The highest close starts at `c0`, so "since entry" includes it.
- **Updates:** at each daily close, the highest close becomes the larger of itself and that close. The stop becomes the larger of its previous value and (the highest close − 3 × that day's ATR). It never moves down, and a shrinking ATR can raise it without a new high.
- **When a close takes effect:** at the first quote after it. That quote is checked against the stop as it stood, then the close is processed, and a raised stop is checked against the same quote again.
- **Daily closes missed in a gap.** If one or more daily closes pass with no quote, they are processed in order at the first quote after them, one at a time:
  - a close whose daily state is not Up ends the processing with exit 2;
  - each other close updates the highest close and the stop, and the quote is checked against that stop before the next close is processed.
  So the first exit, a stop or a fade, ends the processing.

**Exits.** Each one sells the whole position with marketable sells under the participation limit, and the remainder below the minimum notional stays as dust, as in v1:
1. **The stop is reached:** the bid at an available minute's quote is at or below the stop.
   - A missing or masked minute has no quote, so there is no check until the next quote, whose check comes first.
   - A data gap does not force an exit by itself, and it does not stop an entry in progress. v1's frame-gap rule only restarts the recovery confirmations (spec v1 §5, rule 4).
2. **The trend fades:** at a daily close, the daily state is no longer Up. Unavailable counts as no longer Up, so this exit fails closed.
3. **The risk layer acts** (§7).

**After an exit:**
- After a stop-out (exit 1), Uptrend cannot be entered for 24 hours. The pause runs from the observation at which exit 1 first triggers, however many observations its sells then take. A decision may enter again when `now − trigger ≥ 24 hours` (86,400,000 ms), so exactly 24 hours later it may. The pause starts even when the entry had bought nothing yet, because the stop was still reached. A refused start is different: when no entry starts at all, because `s ≤ 0` or the bid is already at or below the initial stop ("Budget", above), nothing is stopped out, and no pause starts.
- **An entry that bought nothing** ends as soon as an exit, a risk event or a halt ends it. It is not a trade, so C5 does not count it (§8).
- After a trend fade (exit 2), there is no pause, because re-entry already needs the daily state to be Up again.

## 6. Switching modes

There is one engine per pair at a time. A new mode's engine starts only once the pair is flat.

**Flat.** A pair is flat when it has no resting order and holds nothing the market would still buy. Any remainder is dust below the exchange's minimum, as in v1's test for a resolved account (`PaperSimulator._resolved`). This covers every leftover:
- A grid that is winding down is not flat while any of its orders rest.
- v1's dust does not stop a pair being flat once its grid's orders are gone. Nor do F's held fragments, even when together they exceed the minimum, because v1's unpaired exit exempts them while F holds them (spec v1 §3 F).

**The uptrend position is not grid inventory.** v1 sells any inventory without a resting sell on every frame, and an uptrend position has none. So the position is left out of that per-frame exit, out of the range exit and out of the grid settlement. It is also left out of the draining that v1's pauses start, with one exception:
- **A risk drain sells it.** A pause or reduction the risk engine sets (a daily-loss PAUSE, or a soft-drawdown REDUCE) drains the account to flat, exactly as in v1, so the position is sold (§7).
- **Other pauses do not.** V0's grid-eligibility pause and a transient frame's pause belong to the grid and the data, so they never sell it.

Otherwise only §5's exits and §7's risk events sell it.
- **After it is sold,** the account is flat, and v1's settlement and profit vault apply exactly as after a grid. The vault is never traded.
- **At the end of the window,** a position still held is valued at v1's exit mark, as `Account.equity` values all inventory. That is the same mark at which C1 and C3 sample equity (spec v1 P2). It is a position, not an exit owed, so it does not make the run invalid. The same holds for a held position's dust, and for an entry still in progress.
- **An exit under way at the end** is different. Once one of §5's exits or a risk drain (§7) has started, the position is an exit owed, as v1 treats inventory it is draining. If the market would still take what remains, the run ends incomplete and is invalid (spec v1 §5).

| From → to | What happens |
| --- | --- |
| Cash → Uptrend | the uptrend engine enters |
| Cash → Grid | a grid may open under §4 |
| Grid → Uptrend | the grid winds down (below); see also "Grid → Uptrend, in detail" |
| Grid → Cash | the grid winds down (below) |
| Uptrend → Grid or Cash | only after one of §5's exits has sold the position (§4, "Entering versus staying"); the new mode starts at the next decision once the pair is flat |

**A grid winding down.** When the mode leaves Grid, for Uptrend or for Cash, the open grid places no buy of any kind until it has ended, as variant F's block does (spec v1 §3 F):
- resting buys are cancelled;
- no re-entry buy is created when one of its sells fills;
- its resting sells stay.

Without this, every sell would re-create a buy, and the grid would never end.

**Returning to Grid before it ends.** If a decision sets the mode back to Grid while the grid is still winding down, the wind-down lifts, as F's block lifts. Re-entry buys resume as its sells fill, and the cancelled buys are not restored. So a one-hour move out of Grid suspends the grid's buying, and does not end the grid.

**Grid → Uptrend, in detail:**
- **No forced sale.** The winding-down grid ends only by v1's own exits: its resting sells filling, or v1's range exit after 6 hours outside the band. The switch itself sells nothing.
- **The entry can be late, or missed.** The uptrend entry starts only at a decision where the pair is flat and the mode is still Uptrend.
- **The cooldown is the grid's alone.** v1's re-centring cooldown after a range exit applies to new grids only, not to the uptrend entry. Decisions continue during it, so the uptrend entry may start once the pair is flat, and the range exit then leaves the position alone (above).

## 7. Risk events

Risk events act exactly as in v1, in every mode, and win over the mode selector:
- **New uptrend entries need a risk action of ALLOW,** as V0's new grids do. A soft-drawdown REDUCE, a PAUSE or an EXIT blocks them. So do a daily-loss pause, a halt, a hard stop and an emergency.
- **A daily-loss PAUSE or a soft-drawdown REDUCE drains the account to flat, as in v1** (`PaperSimulator._pause`).
  - The uptrend position is sold under the participation limit, and any entry stops at once.
  - The position ends when it is sold, or when what remains is dust.
- **Recovery before a new entry.** After such a drain, and after a restart from a halt, a new uptrend entry also waits for v1's recovery confirmations: `recovery_frames` (2) consecutive valid observations whose risk action is ALLOW. A frame gap restarts the count, as in v1.
  - V0's grid eligibility is not part of this count, because it belongs to the grid. New grids keep v1's own recovery, which needs it.
  - Decisions continue during the recovery, but no uptrend entry starts before it ends.
  - v1's own rules still end a soft-drawdown episode and allow the automatic restart after a hard stop, and both need V0's eligibility (amendment 1). So the uptrend engine can wait on V0's eligibility through them.
- **The hard stop and emergency exits** liquidate everything. The halt ends any uptrend position and entry at once, so no uptrend state survives it.
- **While halted,** the mode is Cash. After a restart, the mode is decided afresh at the next decision, and an entry waits for the recovery above.

## 8. Evaluation

**The window:**
- Spec v1's frozen `full-range-2017-2024` definition, with evaluation from 2019-01 to 2024-12 and warm-up from 2018-06 (214 days). The name is #156's, whose dataset reached back to 2017. Spec v1 §4 set the warm-up at 2018-06 because XRPUSDT's data starts on 2018-05-04, so 2019-01 is the first evaluation month.
- Its dataset spec and manifests must exist first (§9, step 2).
- v1's `practice-2022` and `verify-2024h1` are run as a sanity check, and reported only.

**What is run:**
- **Pairs:**
  - In `full-range-2017-2024`: BTCUSDT, ETHUSDT and XRPUSDT, as frozen in spec v1 §4. XRP stays in unless its actual-quotes test excludes it (decision 16).
  - The two sanity windows keep their own frozen v1 pairs: BTCUSDT, SOLUSDT and XRPUSDT in `practice-2022`, and ADAUSDT and BTCUSDT in `verify-2024h1`.
- **Paths:** both.
- **Capital:** 100 USDT per pair-run, as in v1.

**Comparators.** These run on the same data, paths, timing and fees as the mode switcher:
- **Always-grid:** v1's variant F, eligible for grids whenever V0 allows, with v1's risk layer.
- **Buy-and-hold.**
- **Cash.**
- **Variant D,** reported only. It keeps its frozen exemption from the risk layer and the vault (spec v1 §3 D).

### Acceptance (owner decision: "Adapt v1's criteria")

Every criterion applies over the included runs of the scored window:

| # | Criterion |
| --- | --- |
| C1 | As spec v1, C1(a) and C1(b): maximum drawdown ≤ 10% on total and on active equity in every included run. Any hard-drawdown halt (v1's 12% hard stop) fails C1, even though the automatic restart after 24 hours (§2) lets the run continue. |
| C2 | As spec v1: for each path, the median annualised return > 0, and the mean annualised return > 0. |
| C3 | As spec v1: in every included run, the maximum total-equity drawdown is below that run's buy-and-hold maximum drawdown, under common sampling. |
| C4 | As spec v1: every included run is valid. |
| C5 | **Activity:** each run's rate is its completed round trips × 365.25 ÷ `d`, where `d` is the evaluation window's length in days, as in spec v1 §6 (2,192 for `full-range-2017-2024`). The mean of the rates over included runs, computed exactly, is ≥ 12. A round trip is either a completed grid cycle (spec v1 P7) or a completed uptrend trade: an entry that bought something, and whose exit has finished. Both kinds count alike, so grid cycles alone can meet C5. That is intended: C5 checks that the bot trades, not which mode does. Round trips by mode are a required readout. **This bar is lower than v1's.** v1's C5 needs a mean of at least 1 completed cycle a week, about 52 a year (spec v1 §6). The mode switcher waits in Cash whenever its rules are not clearly met, and an uptrend trade can last weeks. So a weekly bar would mostly measure the grid's share of the time, not whether the bot trades. 12 a year, one a month, still fails a bot that only waits in cash (§11, decision 6). |
| C6 | **Earns its place:** in at least 60% of included runs, the run's ratio exceeds both always-grid's in the same pair and path, and cash's, which is 0. The ratio is the annualised return in percent ÷ max(the maximum total-equity drawdown in percent, 0.1), in the units of v1's scorer (`acceptance.gate_ratio`). For example, 5% a year with a 2% drawdown scores 2.5, and with a 0.05% drawdown it scores 5 ÷ 0.1 = 50. The return is compound-annualised as in C2, which differs from v1's C6: it kept raw returns (spec v1 §6, "Annualised returns"; §11, decision 7). An annualised return is computed as v1's scorer computes C2's (`acceptance.annualise`): in `Decimal` at 60 significant digits, with the error bound that function states. A comparison that the bounds cannot settle is not scored, rather than guessed, as v1's scorer treats C2 (`acceptance.certain`). Annualising never changes a return's sign, so a run beats cash only with a positive return, in either form, and its comparison with always-grid only matters among positive returns. A run whose always-grid run is missing or invalid cannot show that it beats it, so it counts against C6, as v1's scorer counts a missing or invalid baseline. |

**Reported, not gating:**
- **Upside capture:** over the calendar months in which buy-and-hold's return is positive, the sum of the run's monthly returns divided by the sum of buy-and-hold's.
  - A month's return runs from the first equity sample at or after its start to the first at or after the next month's start. The first month starts from the initial capital, and the last ends at the final equity.
  - The run and buy-and-hold use the same samples (spec v1 P2). A month with no sample of its own then has a zero return, and the movement across it falls in the month before.
- **Behaviour:** the share of time in each mode, the number of mode switches, round trips by mode, and the uptrend stops and fades.
- **Comparators:** D and buy-and-hold.
- **R1, economics, as spec v1 §6:** the capital at which the mean monthly return would cover €5 a month of hosting.

**Annualising:** compound, as in spec v1 §6, in C2 and C6. R1 uses raw returns, as in v1, and upside capture uses raw monthly returns.

**Outcome:**
- The mode switcher **passes** v2 only if C1–C6 all pass.
- If it passes, the reserved 2025–26 window may run once (§9). That needs C7 settled or waived in writing (spec v1 §6), and the owner's go.
- If it fails, v2 ends with no pass, and nothing runs on the reserved window.

**Trials:**
- The mode switcher is one new registered configuration. `N_family` (spec v1 §6) gains at least one, settled by the trial register.
- Always-grid is v1's F, an existing configuration run on a new window.

**Prior exposure (disclosed):**
- v1's stage-1 results (2022 and 2024H1) informed this design: F in grid mode, the risk budget, and C5's bar (below). Both windows lie inside 2019–2024.
- The V2-era runs of 2026-09-30 covered parts of 2022–2024 (2022-06 to 2023-02, and 2023-10 to 2024-12), and Claude saw their figures in the owner's proposal. Those runs are invalid because of the lookahead fixed in #160.
- #137's runs on the development data informed the deferral of shorting.
- **Where the thresholds come from:**
  - **The owner's 2026-09-30 proposal** ([record](reviews/2026-09-30-owner-v2-master-strategy-proposal.md)):
    - its fast grid's 1h RSI(14) of 35–65 and ADX below 20;
    - its slow grid's four consecutive RANGE hours;
    - its multi-timeframe gate, in which the 1h, 4h and daily views must agree;
    - the daily RSI(14) of 75 as the overbought line (its Mode C);
    - SMA20 and SMA50 as trend direction (V0's features, which it lists);
    - the Bollinger width for squeezes.
  - **Standard indicator conventions:** period 14 for RSI, ATR, ADX and ±DI; ADX 20 as the line between trend and range; and Bollinger 20 at 2σ.
  - **Claude's design choices:** the 720-hour (30-day) width median as the squeeze reference, 3 × ATR, 4%, 60%, 24 hours, and C5's 12 round trips a year (§11, decisions 6 and 7).
- **What 2019–2024 results informed.** v1's stage-1 results (above) informed three choices:
  - two qualitatively: F's block in grid mode, and sizing the trend position to the risk budget after D's 40% drawdowns;
  - and C5's lower bar, which was set with the full stack's C5 result known (next bullet).
  No v2 result exists yet, so no v2 threshold was tuned against one.
- **C5's bar was set after v1's results were seen.** In v1's stage 1, the full stack, which had the smallest drawdowns, failed v1's C5 at 0.69 completed cycles a week ([report](backtests/2026-10-06-spec-v1-stage-1.md)). C5's 12 round trips a year, one a month and about a quarter of v1's bar, was chosen with that result known.
  - It is a relaxation of a criterion made after a result, which START_HERE's rule "No tuning after seeing results" forbids without an exception. The owner approved the bar (§11, decision 6) and, on 2026-10-06, granted an exception to that rule **on record** for C5's bar alone (§11, decision 9), as spec v1 §3 records for the drawdown controls. It is disclosed here, and v1's results stay published beside v2's.
  - Grid cycles alone can pass it (C5).
  - C1–C4, and C6's 60% share, are v1's, unchanged. C6's comparator is v1's F (always-grid), because F is the grid this spec uses, and F was stage 1's best grid.
- 2025–26 has not been downloaded or replayed. Claude has read public reports of its BTC regime (spec v1 §7).
- **Consequence:** 2019–2024 is a development window, not an untouched one. The reserved window is the clean test.

## 9. Build order

Each step is its own PR, reviewed by Codex and Bob, and merged only when both are clean and the PR's checks pass:
1. **This spec,** reviewed and frozen. The freeze covers this file only. The build plan (`docs/superpowers/plans/2026-10-06-mode-switcher.md`) may still change during the build, and its changes are not spec changes. Where the two differ, this spec rules.
2. **Long-window data:**
   - the reader with the repair rule and hour-level masking (spec v1 §5);
   - Bob's re-fetch of the long window's archives;
   - the XRP actual-quotes measurement;
   - the dataset spec and manifests matching spec v1 §4.
   - It must leave every v1 stage-1 result identical, in the sense of spec v1 §6 (decision 18).
3. **Perception:**
   - 4h bars;
   - RSI, ADX/±DI, ATR, the Bollinger width and its median, on their timeframes;
   - the trend states;
   - tests that no value reads a bar that has not closed.
4. **The mode selector:** §4's rules, with boundary tests: equality at every threshold, the four-hour RANGE count, the 24-hour re-entry pause, and unavailable inputs giving Cash.
5. **The uptrend engine and the transitions,** inside the paper account (§5–§7), with the risk layer's interactions tested.
6. **Integration:**
   - a CLI flag;
   - results rows that record the mode history;
   - the scorer's new C5 and C6, and upside capture;
   - the evaluation runs, from one frozen commit.

V0 and every v1 variant must stay byte-identical throughout. The mode switcher runs only behind its own flag. The check of byte identity ships with step 3, as a script any reviewer can run.

## 10. Not in v2

Later specs will cover these. Each needs its own owner decision:
- futures and shorting, the owner's 2026-09-27 trend-short mode;
- the separate fast-grid and slow-grid modes (the owner's Modes A and B of 2026-09-30);
- the cycle-based position hold (Mode C), and external signals: Fear & Greed, open interest;
- a capital allocator across modes or pairs;
- any change to the risk limits;
- running the mode switcher as a persisted paper account, which needs its state and F's saved with a schema change (§1, Scope).

## 11. Owner decisions (2026-10-06, in Claude's session)

Each was a multiple-choice question, and Claude recommended every chosen option except the approach (B) and the PR's shape (decision 8).
1. **The first piece.** Question: "Which piece should spec v2 cover first? (The others follow as their own specs.)". Chosen: **"Spot mode switcher"**.
2. **The risk budget.** Question: "What risk budget should v2 be judged against? (Catching uptrends means holding coins through pullbacks.)". Chosen: **"Keep v1's limits"**.
3. **The test periods.** Question: "Which market periods should v2 be developed and judged on? (The 2025-26 window stays reserved for one final test either way.)". Chosen: **"Long windows 2019-2024"**.
4. **The success test.** Question: "How should v2 decide whether the mode switcher works?". Chosen: **"Adapt v1's criteria"**.
5. **The approach.** Question: "Which approach should the v2 mode switcher take?". Chosen: **"B: multi-timeframe gate"** (Claude had recommended A, reusing v1's parts).
6. **The design sections.** The owner approved sections 1–4 of the design as presented: the pieces, the mode rules and thresholds, the uptrend sizing and exits with the transitions, and the testing with the criteria and build order. §3–§9 write them out.
   - **C5's bar.** Section 4 set the new C5 as "on average at least 12 completed round trips a year (grid cycles plus uptrend trades), so a bot that just sits in cash can't pass". v1's C5 needs about 52 a year (1 completed cycle a week). §8, C5, gives the reason for the lower bar. Section 4 did not set out the comparison with v1. The lower bar was chosen after v1's stage-1 results were known, including the full stack's C5 failure at 0.69 cycles a week (§8, "Prior exposure").
7. **This written draft.** The owner reviewed it and approved it on 2026-10-06: "its all good". The owner added that the work is agile: if the mode switcher does not work, a later spec will adapt it or try something new. Within this spec, the registered rules stay fixed once it is frozen.
   - **What the draft already held,** and later rounds kept: C6 on annualised returns (§8). The review rounds of PR #174 since then clarified the rules and closed gaps, and changed no threshold that the owner approved.
8. **The freeze.** Question: "Do you give your go to freeze spec v2 once its reviews are clean? It locks in C5 at 12 round trips a year (v1 had about 52) and C6 on annualised returns." Chosen: **"Yes, freeze when clean"**. The owner also chose to keep this spec and its build plan in one PR until Codex's review is clean ("Keep current approach"). Claude had recommended splitting them, so that the spec could freeze sooner.
9. **The exception for C5's bar.** Codex's review of the freezing PR (#175) found that decision 8 approved the number but did not name the exception that START_HERE's rule "No tuning after seeing results" requires. Question: "Codex (#175) asks for your explicit decision: spec v2's C5 bar of 12 round trips a year was set after v1's results were seen, which START_HERE's "no tuning after seeing results" rule forbids unless you grant an exception on record, as you did for the drawdown controls on 2026-09-27. Your earlier "freeze when clean" approved the number but did not name the exception. Which do you choose?" Chosen: **"Grant the exception on record"**, over "Restore v1's bar (52 a year)". So C5's bar stays at 12 round trips a year, under an exception to the no-tuning rule granted on record for that bar alone (§8, "Prior exposure"). Claude recommended the chosen option: 12 a year already fails a bot that waits in cash, which is C5's purpose, and a weekly bar would measure the grid's share of the time rather than the design.

Decisions 10 to 13 were given on 2026-10-07, after the first read on the two sanity windows (§8). On `practice-2022` and `verify-2024h1` the mode switcher lost money in all 8 runs, so C2 and C6 failed there, and in BTCUSDT's 2024H1 it stayed out of a 61% rise. These windows are reported only, so that read decides nothing under §8.

10. **Continue to the scored window, with decision reasons recorded.** Claude offered three options: finish the pre-registered 2019-2024 test, add decision-reason instrumentation first, or stop v2. The owner chose: **"go merge 193 once reviews are clear, add decision-reason instrumentation first"**.
    - Merging #193 started Bob's fetch of `full-range-2017-2024`.
    - The instrumentation is reporting only. Each MS row gains `modes.decisions`: the decisions by mode, every condition that kept Uptrend or Grid out at each hourly decision, the decisions a single condition kept out, and the same counts by month.
    - The instrumentation leaves `select_mode` and every decision as they were. A golden SHA-256 of three MS replays, recorded on main before the change, still matches. No criterion reads the new block (§8, "Reported, not gating").
11. **The first decision after a restart.** Question: "After a halt clears (the bot restarts mid-hour), when should the mode switcher make its first decision?" Chosen: **"At once"**, the reading built and recommended. §7's "After a restart, the mode is decided afresh at the next decision" means the first valid frame after the restart, because the hour's decision was missed while halted. A test pins this.
12. **An empty entry's stop-out.** The first question treated this as open: "If an Uptrend entry's stop is hit before it has bought anything (an 'empty' entry), should that start the 24-hour re-entry pause?" The owner chose **"Only if it bought something"**. §5 already settles it, though: "The pause starts even when the entry had bought nothing yet, because the stop was still reached." Claude corrected the question: "Correction: frozen spec v2 already says an empty entry's stop-out DOES start the 24-hour pause (§5). Changing it now, after the first read, is a rule change the no-tuning rule allows only as an exception on record. Which do you want?" Chosen: **"Keep the frozen rule"**, over "Grant an exception on record". So §5 stands unchanged, and the code change made for the first answer was reverted before any run used it.
13. **A window whose proxy is masked whole.** Question: "If the 17% data rule ever masked every hour of the market proxy or of a basket member, what should happen to that window? No registered window can reach this today." Chosen: **"Fail closed"**, the behaviour built and recommended. Such a window fails its integrity check ("no hours compared") and is reported as invalid, although spec v1 §5 says "the window stays": a window with no proxy data cannot be judged honestly. Spec v1's eligibility record puts every measured pair-month of `full-range-2017-2024` under 17%.
