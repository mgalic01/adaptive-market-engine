# Experiment specification v2: the spot mode switcher (DRAFT, not yet frozen)

**Status:** a draft by Claude, from the owner's design decisions of 2026-10-06 (recorded in §11).
- **When it freezes:** only after the owner has reviewed this text, and Codex and Bob have reviewed it. The freeze also comes before any code that could be tuned to results, and before any v2 run.
- **After the freeze:** a change requires a new version.
- **Scope:** paper trading and historical replay only. Nothing here authorises live trading, API keys or withdrawals.
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
- **1m:** Binance's archives, for fills only.
- **1h:** Binance's archives.
- **4h:** built from four consecutive 1h bars aligned to 00:00, 04:00, … UTC. A 4h bar exists only if all four hours are present and unmasked. Otherwise it is missing.
- **1d:** Binance's archives, cross-checked as in spec v1 P3.

**The indicators.** Each is computed on completed bars only. Wilder smoothing applies wherever the standard definition uses it.

| Indicator | Timeframes | Definition |
| --- | --- | --- |
| SMA20, SMA50 | 4h, 1d | simple averages of closes |
| RSI(14) | 1h, 1d | Wilder |
| ADX(14), +DI, −DI | 1h, 4h, 1d | Wilder |
| ATR(14) | 1d | Wilder, for the trailing stop |
| Bollinger width | 1h | (upper − lower) ÷ middle of the 20-bar band at 2 population standard deviations |
| Width median | 1h | the median of the last 720 completed 1h widths (30 days) |

An indicator whose history is short, or contains a missing or masked bar inside its lookback, is **unavailable**.

**The 1h regime** is V0's existing classifier (`strategy/regime.py`, `price-only-v1`). Its labels are RANGE, BULL, BEAR, TRANSITION and STRESS.

**The 4h and daily trend states:**

| State | All of these |
| --- | --- |
| **Up** | close > SMA50; SMA20 > SMA50; ADX(14) ≥ 20; +DI > −DI |
| **Down** | close < SMA50; SMA20 < SMA50; ADX(14) ≥ 20; −DI > +DI |
| **Range** | ADX(14) < 20 |
| **Unclear** | anything else, including any unavailable input |

## 4. The mode selector

**When it decides:**
- At each completed hour (the first valid observation at or after the hour boundary), the selector sets each pair's mode.
- The 4h and daily states change only at their own bars' closes.

**How it decides.** It checks Uptrend first, then Grid. Anything else is Cash.

| Mode | All of these must hold |
| --- | --- |
| **Uptrend** | daily state Up; 4h state Up; the 1h regime is neither BEAR nor STRESS; daily RSI(14) < 75; no trailing-stop exit in the last 24 hours (§5) |
| **Grid** | the 1h regime is RANGE at each of the last 4 completed hours; the 4h state is neither Up nor Down; the daily state is not Down; 1h RSI(14) between 35 and 65 inclusive; 1h ADX(14) < 20; 1h Bollinger width ≤ its 720-hour median |
| **Cash** | otherwise, including any unavailable input, warm-up not complete, or a halt |

**What each mode allows:**
- **Grid:** new grids may open, but only when V0's own checks, F's block and the risk layer also allow.
- **Uptrend:** the uptrend engine (§5) may enter.
- **Cash:** neither may.

**Entering versus staying.** The rules above decide which mode a pair *enters*.
- **An uptrend position:** once the pair holds one, the pair stays in Uptrend until one of §5's exits has finished. The selector does not re-decide its mode in between, so a 4h state that stops being Up does not by itself sell the position.
- **An open grid:** it continues by v1's rules when the mode leaves Grid. Only new grids need the Grid conditions.

## 5. The uptrend engine

**Entry:**
- **When:** at the first valid quote after a decision that sets the mode to Uptrend, provided the pair is flat (§6).
- **How:** one marketable buy at the taker fee, bounded by the participation limit and the exchange's precision, as variant D's execution does.

**Size:**
- `size = min(0.60 × active capital, 0.04 × active equity ÷ d)`.
- `d` = (entry price − initial stop) ÷ entry price.
- Active capital and active equity are spec v1's (the vault excluded).
- A stop-out therefore costs about 4% of active equity before fees and slippage.

**The trailing stop:**
- **Value:** the highest daily close since entry, minus 3 × ATR(14) on daily bars.
- **First value:** set from the last completed daily close before entry and that day's ATR.
- **Updates:** at each daily close, the stop becomes the larger of its previous value and (the highest daily close since entry − 3 × that day's ATR). It never moves down.

**Exits.** Each one sells the whole position with marketable sells under the participation limit, and the remainder below the minimum notional stays as dust, as in v1:
1. **The stop is reached:** the bid at any minute's quote is at or below the stop.
2. **The trend fades:** at a daily close, the daily state is no longer Up.
3. **The risk layer acts** (§7).

**After a stop-out:** after exit 1, Uptrend cannot be entered for 24 hours.

## 6. Switching modes

There is one engine per pair at a time. A new mode's engine starts only once the pair is flat.

| From → to | What happens |
| --- | --- |
| Cash → Uptrend | the uptrend engine enters |
| Cash → Grid | a grid may open under §4 |
| Grid → Uptrend | the grid's unfilled buys are cancelled, its resting sells stay, and v1's range exit sells whatever remains; the uptrend entry waits until the pair is flat |
| Grid → Cash | no new grids; the open grid finishes by v1's exits |
| Uptrend → Grid or Cash | only after one of §5's exits has sold the position (§4, "Entering versus staying"); the new mode starts at the next decision once the pair is flat |

## 7. Risk events

Risk events act exactly as in v1, in every mode, and win over the mode selector:
- **A soft-drawdown reduction** sells part of whatever is held, including the uptrend position.
- **A daily-loss pause, halt, hard stop or emergency** blocks every new entry.
- **The hard stop and emergency exits** also liquidate everything.
- **While halted,** the mode is Cash.

## 8. Evaluation

**The window:**
- Spec v1's frozen `full-range-2017-2024` definition, with evaluation from 2019-01 to 2024-12 and warm-up from 2018-06 (214 days).
- Its dataset spec and manifests must exist first (§9, step 2).
- v1's `practice-2022` and `verify-2024h1` are run as a sanity check, and reported only.

**What is run:**
- **Pairs:** BTCUSDT, ETHUSDT and XRPUSDT, as frozen in spec v1 §4. XRP stays in unless its actual-quotes test excludes it (decision 16).
- **Paths:** both.
- **Capital:** 100 USDT per pair-run, as in v1.

**Comparators, run under the same rules:**
- **Always-grid:** v1's variant F, eligible for grids whenever V0 allows.
- **Buy-and-hold.**
- **Cash.**
- **Variant D,** reported only.

### Acceptance (owner decision: "Adapt v1's criteria")

Every criterion applies over the included runs of the scored window:

| # | Criterion |
| --- | --- |
| C1 | As spec v1: maximum drawdown ≤ 10% on total and on active equity in every included run, and no hard-drawdown halt. |
| C2 | As spec v1: for each path, the median annualised return > 0, and the mean annualised return > 0. |
| C3 | As spec v1: in every included run, the maximum total-equity drawdown is below that run's buy-and-hold maximum drawdown, under common sampling. |
| C4 | As spec v1: every included run is valid. |
| C5 | **Activity:** the mean, over included runs, of completed round trips per 365.25 days is ≥ 12. A round trip is either a completed grid cycle (spec v1 P7) or a completed uptrend trade, an entry whose exit has finished. |
| C6 | **Earns its place:** in at least 60% of included runs, the run's annualised return ÷ max(its maximum drawdown, 0.1 percentage points) exceeds both always-grid's in the same pair and path, and cash's, which is 0. |

**Reported, not gating:**
- **Upside capture:** over the calendar months in which buy-and-hold's return is positive, the sum of the run's monthly returns divided by the sum of buy-and-hold's.
- **Behaviour:** the share of time in each mode, the number of mode switches, round trips by mode, and the uptrend stops and fades.
- **Comparators:** D and buy-and-hold.

**Annualising:** compound, as in spec v1 §6.

**Outcome:**
- The mode switcher **passes** v2 only if C1–C6 all pass.
- If it passes, the reserved 2025–26 window may run once (§9). That needs C7 settled or waived in writing (spec v1 §6), and the owner's go.
- If it fails, v2 ends with no pass, and nothing runs on the reserved window.

**Trials:**
- The mode switcher is one new registered configuration. `N_family` (spec v1 §6) gains at least one, settled by the trial register.
- Always-grid is v1's F, an existing configuration run on a new window.

**Prior exposure (disclosed):**
- v1's stage-1 results (2022 and 2024H1) informed this design: F in grid mode, and the risk budget. Both windows lie inside 2019–2024.
- The V2-era runs of 2026-09-30 covered parts of 2022–2024 (2022-06 to 2023-02, and 2023-10 to 2024-12), and Claude saw their figures in the owner's proposal. Those runs are invalid because of the lookahead fixed in #160.
- #137's runs on the development data informed the deferral of shorting.
- 2025–26 has not been downloaded or replayed. Claude has read public reports of its BTC regime (spec v1 §7).
- **Consequence:** 2019–2024 is a development window, not an untouched one. The reserved window is the clean test.

## 9. Build order

Each step is its own PR, reviewed by Codex and Bob, and merged only when both are clean and the PR's checks pass:
1. **This spec,** reviewed and frozen.
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

V0 and every v1 variant must stay byte-identical throughout. The mode switcher runs only behind its own flag.

## 10. Not in v2

Later specs will cover these. Each needs its own owner decision:
- futures and shorting, the owner's 2026-09-27 trend-short mode;
- the separate fast-grid and slow-grid modes (the owner's Modes A and B of 2026-09-30);
- the cycle-based position hold (Mode C), and external signals: Fear & Greed, open interest;
- a capital allocator across modes or pairs;
- any change to the risk limits.

## 11. Owner decisions (2026-10-06, in Claude's session)

Each was a multiple-choice question, and Claude recommended every chosen option except the approach (B).
1. **The first piece.** Question: "Which piece should spec v2 cover first? (The others follow as their own specs.)". Chosen: **"Spot mode switcher"**.
2. **The risk budget.** Question: "What risk budget should v2 be judged against? (Catching uptrends means holding coins through pullbacks.)". Chosen: **"Keep v1's limits"**.
3. **The test periods.** Question: "Which market periods should v2 be developed and judged on? (The 2025-26 window stays reserved for one final test either way.)". Chosen: **"Long windows 2019-2024"**.
4. **The success test.** Question: "How should v2 decide whether the mode switcher works?". Chosen: **"Adapt v1's criteria"**.
5. **The approach.** Question: "Which approach should the v2 mode switcher take?". Chosen: **"B: multi-timeframe gate"** (Claude had recommended A, reusing v1's parts).
6. **The design sections.** The owner approved sections 1–4 of the design as presented: the pieces, the mode rules and thresholds, the uptrend sizing and exits with the transitions, and the testing with the criteria and build order. §3–§9 write them out.
