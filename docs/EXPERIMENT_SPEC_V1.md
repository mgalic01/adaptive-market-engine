# Experiment specification v1 (DRAFT for review, not yet frozen)

**Status:** draft by Claude. It becomes frozen only when Codex has reviewed it and the
owner has confirmed the acceptance criteria in §6. After that, a change requires a new
version (v2), and results under v1 stay reported. **No strategy code exists for these
variants yet.** This document fixes what will be built and how it will be judged,
*before* any variant is run.

The scope is paper trading and historical replay only. Nothing here authorises live
trading, API keys or withdrawals. The default risk limits (3% daily pause, 8% soft and
12% hard drawdown, latched halt), the 50/50 profit vault and the paper-only boundary
are unchanged by every **grid** variant (V0, A, B, C, E, F, G, H, C+G, C+H). The benchmark D is the one
labelled exception (§3 D): it is a replay-only calculation with its own sizing and no
risk controls or vault, and it never touches persisted paper state.

## 1. Question

Starting from `price-only-v1` (V0), do any of the pre-registered mechanisms reduce
forced-exit losses enough to make money after Revolut X fees, with a smaller worst drop
than simply holding? The diagnostic
[fee-levels-2026-09.md](backtests/fee-levels-2026-09.md) motivates the question: resting
grid sells realised gains, and forced marketable exits realised as much or more in
losses.

## 2. Prerequisites (implemented and reviewed before any variant run)

These are measurement and data changes, with two qualified exceptions:
- **P4 can change V0 decisions** on formerly invalid SOL runs. Those runs become a
  newly labelled scenario, "SOL with sourced historical filters". Today's filters are
  never backdated as historical ones.
- **P5 changes how invalid CLI input is handled:** an empty fee value is rejected.

**Equivalence requirement:** on every existing valid default run (`verify-2024h1` ADA and
BTC, `practice-2022` BTC and XRP, both paths), V0's fills, returns and accounting must be
identical before and after P1–P7. Valuation sampling (P2) must not change V0's engine
risk logic or fills. It records marks from the same actual quote, after that quote's
fills, for both the strategy and buy-and-hold.

| # | Change | Why |
| --- | --- | --- |
| P1 | **Record the exit reason** on every `exit/` fill: `range_exit`, `drain` (the engine's `draining` state), `liquidation` (halt or emergency) and, for variant A, `trend_exit`. Report the realised P&L per reason. | Codex (PR #14): losses cannot be attributed to range exits without it. |
| P2 | **Common drawdown sampling:** strategy total equity and buy-and-hold equity are sampled on the same schedule: every quote of every bar, after that quote's fills. For C1(b), active equity and the reserve-adjusted `risk_high` are also recorded at every pre-fill and post-fill risk evaluation the engine performs, together with any hard-drawdown halt. | Criterion C3 compares the two drawdowns; they must be measured the same way. |
| P3 | **Daily history:** dataset specs gain `daily_warmup_start`. Binance `1d` archives are fetched from that month and checksummed. Over the overlap, every expected day must be present exactly once and contiguous, and must match the aggregation of its 24 unique contiguous `1h` bars, not just an aggregate OHLCV match. | Variants A and D need at least 200 completed daily bars before the evaluation starts. |
| P4 | **Historical exchange filters for SOL:** use dated, sourced point-in-time tick and step sizes if available. If they cannot be sourced, SOL runs stay invalid for every variant (§5). No synthetic spread model in the primary comparison. **Result (2026-09-24):** no dated official spot filter history was found. The archives themselves show that every SOLUSDT open, high, low and close from 2022-06 to 2023-01 has at most 2 decimals (lowest price 8.00), which is consistent with today's 0.01 tick. The invalidity therefore comes from the adapter's assumed spread with outward rounding at low prices (2 ticks ≈ 0.25% > 0.15%), not from a wrong filter. **SOL stays invalid in the primary comparison.** A one-tick spread model may only ever be a separately labelled sensitivity scenario; it is not part of v1. | Codex §4.1 answer on PR #15. |
| P5 | Carried nits: `--maker-fee`/`--taker-fee` use `is not None`, so an empty value is rejected; `replay()` asserts the order book is empty before wrapping it for request counting. | Automated reviews on PR #14. |
| P6 | **P&L reconciliation:** realised P&L by sell type, plus unrealised P&L of the remaining inventory at the final mark, must equal the final total equity minus the initial capital. | Codex (PR #15): attribution must reconcile with the account. |
| P7 | **Completed-cycle count (for C5):** a completed cycle is a grid sell (a child `…/sell` order placed when its buy filled completely) that itself fills completely. It is reported per run and per week. It is a count only, independent of the P1 P&L-by-exit-reason and the average-cost resting-sell attribution, and neither of those counts cycles. | Codex (PR #16): the metric must be defined before it is promised. |
| P8 | **Data for G and H:** BTCUSDT funding-rate archives (checksummed, in the manifest), and daily history from the month of the most recent halving before each window (P3 extended: 2020-05 for both development windows, 2024-04 for the reserved window). The halving timestamps are fixed constants in §3 H. | Needed by G and H. |

## 3. Variants

Every variant is V0 plus exactly the mechanism described. They are selected by config
flags that default to off, so V0 and existing paper accounts are unaffected. Timing rules
common to all:
- Signals use **completed** bars only.
- A daily signal computed from the UTC day ending at 00:00 takes effect at the **first
  valid replay observation at or after 00:00:00 UTC** of the next day, never within the
  bar that produced it. A rejected or stale frame never executes a signal; the next
  valid observation does.
- For every grid variant (V0, A, B, C, E, F, G, H, C+G, C+H), every existing V0 control keeps its trigger
  and deadline: emergency exit, hard-drawdown halt, daily-loss pause, soft-drawdown
  reduction, range exit (6 h), drain and eligibility pauses. **No variant delays,
  suppresses or clears any of them**, and none changes a risk limit, the allocation
  policy or the profit vault. A variant can only add restrictions (fewer buys, an
  earlier exit) or add an exit with its own deadline. There are exactly **three named
  exceptions**, each confined to the one control stated:
  - **E** may delay the **range exit only**, from 6 h to at most 12 h after `t0`, under
    the rules in §3 E. It never delays any other control.
  - **H3** may lower the **opportunity-score minimum for new grids only**, from 0.70 to
    0.60, under the rules in §3 H. Every other entry check still applies.
  - **D** is a benchmark without these controls (§3 D).

  A declared combination (C+G, C+H) inherits only the exceptions of its parts: C+H
  inherits H3's, and no combination inherits E's.

### V0: baseline (`price-only-v1`)
- **Code:** the commit that merges the prerequisites; it is recorded in every
  `results.json`.
- **Unchanged:** default config, fills, costs, data identities and the common mark
  cadence (P2).

### A: trend/cycle switch (daily SMA50 and SMA200)
Inputs are the completed daily close `C`, `SMA50` and `SMA200` of the traded pair. The
state machine runs over the whole daily history from the first day on which SMA200 is
defined, including the warm-up. The state at the first evaluated minute is therefore
already determined. The initial state, before the first classified day, is Middle.

The state is updated once per completed daily bar, from the previous state and `C`:

| State | Entered when | Behaviour |
| --- | --- | --- |
| **Up** | From Up: `C > SMA200`. From Recovering: a second consecutive `C > SMA200`. | Grids allowed, as in V0. |
| **Recovering** | From Middle, Down or Unavailable: the first `C > SMA200`. | Same as Middle. |
| **Middle** | From any state: `C ≤ SMA200` and `C > SMA50`. | No new grid. An existing grid keeps running: its sells, reentries within the grid and range exit behave as in V0. Reentries are allowed deliberately: they only rebuy levels the grid already sold, inside its existing range, and B's cap bounds the exposure in C. |
| **Down** | From any state: `C ≤ SMA200` and `C ≤ SMA50`. | No new grid, and a **Down sequence** starts unless one is already running (see below). |
| **Unavailable** | A daily bar is missing or SMA50/SMA200 is undefined. | Same as Middle: no new grid, and no fill is forced. The two-close count restarts. |

**Down sequence:**
- **Start:** it starts at the effective time of the first Down classification (`T0`).
  Resting buys are cancelled at `T0`, and resting sells stay in place.
- **Deadline:** the trend deadline is `T0 + 24 h`. Further Down days do **not** reset
  it.
- **Existing exits are not postponed:** the deadline is only an **additional upper
  bound**. A range exit, drain, halt or emergency exit that falls due earlier happens on
  its own V0 schedule; the sequence then ends early if the account is flat.
- **At the deadline:** remaining sells are cancelled, then the remaining inventory is
  liquidated with marketable `trend_exit` sells. These are bounded by the same bid-size
  participation limit as V0's liquidation. Unfilled residuals are retried at each
  following valid observation under the same limits until the account is flat.
- **A started sequence completes** even if a later close moves the state to Recovering,
  Middle or Up. A new grid requires both the Up state and no running Down sequence.

**Other rules:**
- **Hysteresis:** Up is reached only through Recovering, so it takes two consecutive
  completed closes above SMA200. Leaving Up takes one close at or below SMA200.
- **Same-step labelling:** if several exits are due at the same observation, the fills
  take the label of the highest-ranked one: halt/emergency `liquidation` >
  daily-loss/soft-drawdown actions (as in V0) > `range_exit` > `drain` > `trend_exit`.
  The ranking changes labels only, never timing.
- **Warm-up:** at least 200 completed daily bars before the first evaluated minute (P3).

### B: inventory cap
- **Definitions:**
  - **Active equity** = cash − pending reserve + inventory × mark. The secured reserve is
    already outside cash, so both reserves are excluded.
  - **Mark** = bid × (1 − slippage) × (1 − taker).
  - **Committed exposure** = inventory × mark + Σ over **every** resting buy of
    (limit price × remaining quantity × (1 + maker fee)) + the proposed buy, valued the
    same way. Resting buys are valued at their cost including the maker fee. This is
    conservative relative to ignoring pending commitments; together with the
    prospective-equity deduction below, it charges each pending buy its full cash cost.
  - **Prospective active equity** = active equity − Σ over every resting buy and the
    proposed buy of limit × quantity × [(1 + maker) − (1 − slippage)(1 − taker)]. This
    is the equity left if all of them filled at their limits and were immediately marked
    at the limit price with the exit haircut, so it deducts their fees and haircuts.
- **Cap:** committed exposure (including the proposed buy) ≤ **40% of prospective active
  equity**.
  - The rule bounds new commitments under this stated valuation.
  - It is **not** a guarantee that the ratio holds afterwards: price moves after a
    fill, or a fill at a better price, can still lift the measured ratio.
- **Placement order:** a new grid places its buy levels from the highest price down.
  - The first level that does not fit completely is **resized** to the largest quantity
    that fits, floored to the lot step.
  - If the resized quantity is below the minimum notional, that level is skipped.
  - Either way, every **lower** level is skipped. Resized and skipped levels are recorded
    in the report.
  - Reentry buys pass the same check when they are created, with the same resize or skip
    rule.
- **Rounding and fills:**
  - A capped quantity is floored to the lot step. If it is then below the minimum
    notional, the buy is not placed.
  - Partial fills do not change the check: the unfilled remainder is still counted.
  - Sell targets are unchanged, and no reserve is ever spent.
- **Price drift:** if rising prices push committed exposure above 40%, this is allowed.
  There is no forced sale, but no new buy is placed until exposure is below the cap
  again.
- **What it does not do:** it never forces a sale and never delays a sell. The cap
  constrains new buy commitments; it does not guarantee the ratio at all times.
- **40% is an experiment parameter,** not a new default, and it gives no authority to
  use protected funds.
- **Required tests:** the prospective-equity arithmetic with fees; the resize-then-skip
  boundary; concurrent resting buys that each fit alone but not together;
  reentry creation at the cap; a partial fill followed by a new buy; a price-driven
  breach (no sale, no new buy, then resumption below the cap); lot flooring below the
  minimum notional.
- **Deferred:** quote skewing by inventory (Avellaneda–Stoikov style) is not in v1. It
  would need its own spec.

### C: A + B, a declared interaction
- **Mechanism:** both mechanisms at once, with A's priority rules.
- **Reporting:** C is reported as an interaction. It is not claimed as a single
  mechanism.

### D: trend benchmark (not a grid)
- **Signal:** each traded pair is held while its completed daily close is above its
  SMA50, and cash is held otherwise. Missing, undefined, zero or negative values mean
  cash.
- **Sizing:** at each entry, all of the run's cash goes into the pair. The quantity is
  floored to the lot step, and a buy is skipped if it is below the minimum notional.
  D keeps no profit vault or reserves: all equity is one pot.
- **Execution:** entries and exits are marketable at the next valid observation, at
  ask × (1 + slippage) for buys and bid × (1 − slippage) for sells, paying the taker
  fee. Each observation fills at most the ask- or bid-size participation limit (10%),
  as V0's liquidation does.
  - **Entry residual = the remaining quote budget, not a fixed base quantity.** At each
    observation, D buys the smallest of (1) the participation limit and (2) the
    remaining cash ÷ (ask × (1 + slippage) × (1 + taker)), floored to the lot step. The
    entry ends when that quantity is below the minimum notional. So a retry can never
    spend more cash than is left.
  - **Exit residual = the fixed base quantity held.** Each observation sells up to the
    participation limit. An unsold remainder below the minimum notional stays as
    reported dust.
  - **Signal reversal while filling:** at the effective observation of a reversal, the
    unfinished side is abandoned and the new side starts at that same observation. An
    entry in progress stops, and the quantity already bought is exited. An exit in
    progress stops; the unsold inventory stays held and marked, and the new entry adds
    to it using the cash on hand.
- **Unchanged from A:** capital, marks, warm-up, timing and fees.
- **Risk controls:** D is **exempt** from the common rule in §3. It has no daily-loss
  pause, soft or hard drawdown halt or emergency exit; it only follows its signal. Its
  return and drawdown are reported as they are, clearly labelled as a benchmark with a
  different risk policy.
- **State:** D is a replay-only calculation and never writes shared or persisted paper
  state.
- **C1 for D:** D has one pot with no reserves, so its active equity equals its total
  equity, and C1(b) reduces to C1(a) measured against its own peak. D has no halts, so
  the hard-halt veto cannot trigger.

### E: volume-confirmed exit (included by the owner, 2026-09-24)
- **Mechanism:** when V0's 6-hour outside-range timer expires, E compares the base
  volume of the **completed** minutes since the first outside observation with
  2 × (the median completed 1h base volume over the previous 720 hours) × 6.
  - At or above that level, the range exit happens exactly as in V0.
  - Below it, the timer is extended **once** to 12 hours in total. At 12 hours the
    range exit happens unconditionally.
- **Reference, frozen at the timer start:** the 720 hours are the completed 1h bars
  whose open times are the 720 hours ending at the last hour that closed at or before
  the first outside observation `t0`. The median is computed once, at `t0`, and is not
  updated during the timer.
- **Measured volume:** the 1m bars with open time in `[floor_minute(t0), floor_minute(t0
  + 6 h))`, i.e. the completed minutes of the 6-hour span. A zero-volume minute is valid
  input.
- **Unavailable means V0:** if any of the 720 reference hours or any of the measured
  minutes is missing, or the reference median is zero, the comparison is
  **unavailable** and the range exit happens at 6 hours exactly as in V0. E never
  extends on missing data. Unavailable checks are counted and reported.
- **Never delayed:** emergency exits, hard-drawdown halts, the daily-loss pause, the
  soft-drawdown reduction and drain are never delayed; the §3 common rule still applies.
- **Extension ends early:** if price returns inside the range during the extension, V0's
  normal reset applies.
- **Boundary rules** (fixed before implementation; Codex, PR #16):
  - **Threshold:** measured volume **≥** the threshold means exit as V0; strictly **<**
    means extend. Equality exits.
  - **One decision per episode:** the comparison is made once, at the first valid
    observation at or after `t0 + 6 h`. A delayed observation still uses the fixed
    interval `[floor_minute(t0), floor_minute(t0 + 6 h))`, never a later one. The
    12-hour deadline is always `t0 + 12 h`, measured from the original `t0`; it is never
    moved.
  - **New episode:** after a return inside the range resets the timer, a later exit
    from the range starts a new episode with a new `t0`, a newly frozen reference and
    its own single extension.
  - **Other risk actions win:** if a halt, emergency exit, daily-loss pause,
    soft-drawdown reduction or drain acts during the extension, it acts exactly as in
    V0. The extension never delays or blocks it.
  - **An exit, once started, stays started:** when the range exit begins (at 6 h, or at
    12 h), it is latched. Remaining quantity keeps being sold under the existing
    participation limits until done, even if price returns inside the range or the
    volume changes. No extension decision can cancel, pause or restart an exit that
    has already begun.
  - **Required tests:** volume below, equal to and above the threshold; a missing
    reference hour, a missing measured minute and a zero-median reference (each exits at
    6 h); a delayed first observation after 6 h (same interval, same deadline); return
    inside the range then a new episode; a halt, emergency exit and drain during the
    extension; a partial range exit at 12 h that stays latched across a return inside
    the range.
- **Reported:** the number of extensions and unavailable checks, the extra hours outside
  the range, and the P&L of extended exits next to the bid at the 6-hour mark. That
  6-hour comparison is a **diagnostic only**: it is not an executable counterfactual
  (it ignores fees, liquidity and residual inventory) and is never used for selection.
- **Risk review:** E increases exposure time by up to 6 hours per exit. The unchanged
  halt, emergency, daily-loss, soft-drawdown and drain controls bound it but do not
  guarantee a realised-loss ceiling. **Codex (2026-09-25, PR #16):** acceptable as a
  paper/replay hypothesis in principle. It is not yet approved for implementation or
  selection. E becomes eligible for selection only after Codex has reviewed its
  implementation and the boundary tests above; until then it is run and reported but
  **not eligible**.

### F: order-flow entry block
F blocks new buys only. It is **not** a V0 pause: it never sets `draining`, never
market-sells inventory and never clears or delays any other pause, halt or exit.
- **Signal:** `share` = taker-buy **base** volume ÷ base volume over the last 15
  **completed, consecutive** one-minute bars.
  - `share` is **unavailable** if any of those 15 bars is missing, which is not the
    same as a zero-volume bar, or if the aggregate base volume over the 15 bars is
    zero.
  - A single zero-volume minute inside an otherwise complete window is valid input.
- **Block:** F's own flag `flow_block` turns on when `share < 0.40` (strict) or `share`
  is unavailable.
  - While it is on, resting buys are cancelled, and no new grid or reentry buy is placed.
  - A buy cancelled after a partial fill leaves its filled quantity unpaired. That
    quantity gets a resting grid sell at the cancelled buy's target, exactly as a
    complete fill would, so it pays the maker fee and needs no drain.
  - **Fragments below the minimum notional** at their target cannot be placed as a
    sell. They are **accumulated per target price**. When the accumulated quantity at a
    target reaches the minimum notional, one resting sell is placed for it.
  - Until then, the fragments are held unreserved and marked in equity like any other
    inventory. They remain subject to V0's range exit, liquidation and, in variants
    combining A, `trend_exit`.
  - Anything still below the minimum at the end of a run is reported as dust, as V0
    already does.
  - When the originating grid ends (range exit or re-centre), its buckets are handled
    like other unreserved inventory: they go through that exit, and only a remainder
    below the minimum becomes dust.
- **Unblock:** `flow_block` turns off when `share ≥ 0.45` (inclusive). Turning it off
  only lifts F's own restriction. Any other active pause, halt, drain or eligibility
  veto stays in force.
- **Startup:** `flow_block` starts on, so it fails closed. A start inside the
  0.40–0.45 band stays blocked until `share ≥ 0.45`.
- **Unaffected:** resting sells, range exits, drain and every risk exit continue as in
  V0.
- **Request budget:** cancellations count against it. The per-day request maximum is
  reported for F specifically.
- **Required tests:**
  - cancellation counts;
  - a partial fill then a block (the resting sell for the unpaired quantity);
  - a below-minimum fragment, then accumulation to the minimum, then a single sell;
  - threshold equalities at exactly 0.40 and 0.45;
  - a missing minute versus a zero-volume minute;
  - an F unblock while a V0 eligibility pause is active (the pause must remain);
  - overlapping F and range-exit states.

### G: funding-rate gate (owner proposal via Bob, included 2026-09-24)
- **Data:** BTCUSDT USDⓈ-M perpetual funding rates from the public archive
  `data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/`. These are monthly
  zips with published checksums, fetched and verified like the klines (manifest,
  SHA-256).
  - The replay never calls a futures API.
  - The live-host rule (public data hosts only) is unchanged.
- **Records and uniqueness:** each record is one settlement: `calc_time` (truncated to
  the second), the funding interval in hours and the rate. Its **scheduled time** is
  `calc_time` floored to the whole UTC hour. Two records with the same scheduled time
  are a data-integrity failure for the window (§5), never collapsed or chosen between.
- **Cadence from the source:** the expected interval comes from each record's own
  interval field in the archive, not from a universal 8-hour assumption. Accepted
  values are 1, 2, 4 and 8 hours; any other value, or a missing field, makes that
  record's successor unknown, so G is unavailable (below) until three consecutive
  valid records exist again.
- **Pending P8 evidence (G cannot be frozen until resolved):**
  - **Interval meaning: resolved by convention (2026-09-25, PR #19 discussion).** The
    archives cannot tell whether a record's interval is the interval **to its next**
    settlement or the interval **ending at** it. G therefore uses the
    **uniform-cadence rule** below. It gives the same decision under both readings
    whenever the latest three records agree, and it is unavailable otherwise.
  - **Missing field:** if some archive months have no interval field, the spec is
    amended before freeze; nothing is assumed.
  - **Modelling conventions, not verified facts:** flooring `calc_time` to the hour
    and the 60-second publication allowance are **assumptions**. Bob's report is
    assessed against them before freeze.
  - **Bob's P8 survey (2026-09-25, `bob/p8-data-survey` `761b2ee`):**
    - Funding archives exist for all 60 months, 2020-01 to 2024-12, with no errors.
    - One sampled month (2022-06) has the header
      `calc_time,funding_interval_hours,last_funding_rate`, millisecond times, interval
      8 and three settlements per day.
    - Some times are a few milliseconds past the hour (for example `+11 ms`), which
      supports flooring to the hour.
    - **Cadence over all months (Bob, 2026-09-25, PR #19 `fe60ec4`):**
      - All 60 months (2020-01 to 2024-12) have the header
        `calc_time,funding_interval_hours,last_funding_rate`.
      - All 5,481 records have interval 8.
      - Every step is exactly 8 hours, with no missing and no duplicate settlements.
      - The largest offset past the hour is 47 ms. Flooring to the hour reconstructs
        the scheduled slots in this sample, but it discards the raw offsets, which are
        kept for provenance. It says nothing about publication time.
      - **Consequence:** in both development windows, the meaning of the interval field
        (next or ending) cannot change any G decision, so these rules apply as written.
        A cadence change, if one ever occurs, needs a documented rule and its test
        before the reserved run. The reserved window's data is not examined until the
        owner's go.
    - The 60-second publication allowance cannot be verified from archives. It stays a
      labelled assumption.
- **Timing:** a record becomes usable at `calc_time + 60 s` (a fixed publication
  allowance, an **assumption** pending P8), at the first valid observation at or after
  that instant.
- **Uniform-cadence rule (latest three):** at an observation at time `t`, take the
  newest usable record `r3` and the two usable records before it, `r1` and `r2`.
  - **Insufficient history:** if fewer than three usable records exist, including at
    replay start before enough funding history has accumulated, the signal is
    unavailable. G fails closed by default.
  - **Invalid newest record:** `r3` is the newest usable record whatever its content.
    If it is invalid (missing or unaccepted interval, non-finite rate), the signal is
    unavailable. It is never filtered out in favour of three older valid records.
  - **Available** only if all of these hold:
    - **Finite rates:** all three records carry finite rates. An invalid rate on
      `r1` or `r2` makes the signal unavailable just as it does on `r3`; invalid
      records are never skipped to substitute older valid records.
    - **Uniform interval:** `r1`, `r2` and `r3` all carry the **same** accepted
      interval `I`.
    - **Exact steps:** `scheduled(r2) − scheduled(r1) = I` and
      `scheduled(r3) − scheduled(r2) = I`.
    - **Not overdue:** `t < scheduled(r3) + I + 60 s`. A settlement that is due and
      absent makes the signal unavailable, and an older record is never substituted
      for it.
  - **Why uniform:** with a constant cadence, the "next" and "ending" readings agree
    on every step, so the decision does not depend on which one is true. Mixed
    intervals make the signal unavailable. This also rejects a hidden gap such as
    (4 h record, missing record, 8 h record), whose 8-hour step the "ending" reading
    would otherwise accept.
  - **Successor = `I` is a modelling convention, not a guaranteed fact.** Uniform past
    records cannot show that the *next* interval has not already changed before its
    first record becomes usable. Until then, the overdue deadline uses `I`:
    - the signal becomes unavailable as soon as either the first record carrying
      the new interval becomes usable (the three are then mixed), or the old
      deadline `scheduled(r3) + I + 60 s` passes without a newer usable record,
      whichever comes first;
    - under the "next" reading the first case happens at the last old-cadence
      settlement; under the "ending" reading it happens at the first new-cadence
      settlement, or the old deadline passes first when the cadence lengthens.

    G blocks on detected disagreement or the convention's overdue deadline.
    It cannot detect an unseen shorter cadence before either condition occurs:
    if the first changed record is absent, three old uniform records can remain
    available until the old deadline. This is a limitation of the convention,
    not a guarantee against every missing settlement under an unknown cadence.
  - **Recovery condition:** after a cadence change, a gap or an invalid record, the
    signal becomes available again at the first observation at which the three newest
    usable records again satisfy all of the conditions above, including the same
    overdue deadline `scheduled(r3) + I + 60 s`; no separate boundary is defined. How long that takes
    depends on the new cadence and on when observations occur; it is not a fixed
    time.
- **Rule:** no new grid while the signal is **unavailable**, or while it is available
  and all three rates are **> +0.0005** (+0.05% per settlement; strict). Otherwise G
  does not block.
  - Negative or low funding never blocks.
  - Existing grids, sells and exits are unaffected, whatever G's state.
- **Required tests** (synthetic series; no reserved-window data):
  - **Constant cadence:** 8 h, available.
  - **Cadence change 8 → 4 h:** the windows (8, 8, 4) and (8, 4, 4) are unavailable,
    and the first (4, 4, 4) with 4-hour steps is available.
  - **Cadence change 4 → 8 h:** the same checks.
  - **Observations between the old and new deadlines, in both directions:**
    - **8 → 4 h:** before the first 4-hour record becomes usable, available until the
      old overdue deadline `scheduled(r3) + 8 h + 60 s`; after it becomes usable,
      unavailable because the window is mixed.
    - **4 → 8 h:** unavailable once the old overdue deadline
      `scheduled(r3) + 4 h + 60 s` passes, until uniform 8-hour records exist.
  - **The first changed record's publication boundary:** exactly at its
    `calc_time + 60 s`, and one second before it.
  - **Hidden gap:** (4 h, missing, 8 h) is unavailable.
  - **Missing newest record:** while three older records are still within 32 hours,
    unavailable.
  - **Invalid newest record** (interval 0, 3, 12 or empty; non-finite rate): unavailable,
    never falling back to three older valid records.
  - **Insufficient history:** zero, one and two usable records, including at replay
    start, are all unavailable.
  - **Invalid older record:** an unaccepted interval on `r1` or `r2` makes the signal
    unavailable through the uniform-interval check. A non-finite rate on either
    older record also makes it unavailable, without substituting another record.
  - **Unseen shortening with missing changed record:** three valid 8-hour records
    remain available after the unknown 4-hour deadline and before the old
    `scheduled(r3) + 8 h + 60 s` deadline; at the old deadline they are unavailable.
    This explicitly tests the convention's detection limitation.
  - **Duplicate scheduled times:** an integrity failure.
  - **Rate boundary:** exactly +0.0005 does not count as above.
  - **Usability boundary:** exactly at `calc_time + 60 s`, and one second before it.
  - **Overdue boundary:** exactly at `scheduled(r3) + I + 60 s` (unavailable), and one
    second before it (available).
  - **Recovery:** after a gap and after a transition, the exact first observation at
    which the signal is available again.
  - **Existing grids and exits:** unchanged in every unavailable state.
- **Runs:** G on its own (V0 + G), and **C + G** as a declared interaction.
- **Reported:** the number of grids blocked, the hours blocked, and the lag between
  settlement and effect.

### H: Bitcoin cycle context (owner proposal via Bob, included 2026-09-24)
- **Halving constants:** the dates are historical facts, so they are fixed in the spec:
  - block 420,000 at 2016-07-09 16:46:13 UTC;
  - block 630,000 at 2020-05-11 19:23:43 UTC;
  - block 840,000 at 2024-04-20 00:09:27 UTC.

  The phase `m` is the number of **whole calendar months** since the most recent halving
  at or before the observation: `(year − year_h) × 12 + (month − month_h)`, minus 1 if
  the observation's day-of-month and time of day are earlier than the halving's. All
  three halving days are ≤ 20, so every month contains the anniversary instant. Phase
  bands are half-open: `[0, 18)`, `[18, 30)`, `[30, 48)` and `≥ 48`.
- **Data:** each traded pair's own completed **daily closes** (P3), with its SMA200.
  **ATH** is the highest completed daily close since the most recent halving, which
  requires daily data from that halving onward (P3 extended accordingly).
  - **Incomplete history:** if a pair's daily data does not reach back to the halving,
    for example because it was listed after it, its ATH is **unavailable** and H3 never
    relaxes entry for that pair. H2 does not use ATH and applies as normal. An ATH
    counted from the listing date is never substituted. Unavailability is reported.
  - **P8 evidence (Bob, 2026-09-25):** SOLUSDT daily data starts on 2020-08-11, three
    months after the 2020-05-11 halving, so SOL's H3 is unavailable until the 2024
    halving. This affects only `practice-2022` SOL, which is already outside the
    primary comparison (P4). BTC, ETH, XRP and ADA daily data is complete from 2020-01,
    and all five pairs have it for 2024-04 to 2024-12 (the surveyed range; 2025 onward was not examined).
- **H2, overextension guard:** for `m` in **[18, 30)**, if `C > 1.60 × SMA200`:
  - no new grid;
  - existing grids use a **2-hour** outside-range threshold instead of 6 hours.

  This is stricter, so it is allowed under the §3 rule.
  - **Running timers:** H2 changes only the *threshold* a running outside-range timer
    is compared with, never its start time `t0`. If H2 turns on while a timer runs,
    the exit happens at the first valid observation with elapsed time ≥ 2 h (at once
    if already past it). If H2 turns off, the threshold returns to 6 h from the same
    `t0`. A timer is never reset, restarted or extended beyond V0's 6 h by H2.
- **H3, deep-discount relaxation:** for `m` in **[30, 48)**, if `C < 0.50 × ATH`, the
  opportunity score minimum is lowered by 0.10 (0.70 → 0.60) for **new grids only**.
  - Every other regime, eligibility, liquidity, spread and risk check still applies.
  - H3 never changes a risk limit.
  - It is the only mechanism in v1 that loosens an entry gate, and it is reported
    separately (grids opened only because of H3, and their P&L).
- **`m` in [0, 18) or ≥ 48:** no change from V0.
- **Runs:** H on its own (V0 + H), and **C + H** as a declared interaction.
- **Reported:** the phase of every evaluated bar, and the H2 and H3 activations.

## 4. Matrix

| Axis | Values |
| --- | --- |
| Variants | V0, A, B, C, D, E, F, G, C+G, H, C+H |
| Baselines | **Ungated V0** (the replay's `strategy: "ungated"`: V0 without the opportunity gate), for C6 only. It is run everywhere V0 runs and is never eligible for selection. |
| Fees | **Primary:** Revolut X, maker 0 / taker 0.0009. **Sensitivity** (reported, not used for acceptance): 0.001 / 0.001. |
| Windows and pairs | `verify-2024h1` (ADA, BTC) and `practice-2022` (BTC, XRP, SOL), each extended with daily warm-up (P3). |
| Intrabar paths | `high_first` and `low_first`, both always reported. No path is chosen after seeing results. |
| Capital | 100 quote units per run, independent per pair. |

- **Unchanged inputs:** slippage 0.05%, assumed spread 0.05% and participation 10%.
- **Reporting:** every attempted run is reported, including invalid runs, halts and zero
  trades.

## 5. Validity and the comparison mask

**Comparison mask, fixed before any variant runs.** For each pair-window, the following
variant-independent checks are run first:
- the manifest and checksums;
- the hourly/minute and daily/hourly cross-checks, and, when the market proxy is not a
  traded pair, the completeness of its hourly bars over warm-up and evaluation (every
  hour exactly once) plus its daily/hourly cross-check;
- the same hourly completeness for every untraded **breadth-basket** symbol. The feature
  engine skips a stale basket member and still counts the remaining votes, so an
  unexplained gap would silently change breadth. Only an absence documented in the
  dataset spec's `[[basket_exclusions]]` (symbol, `from` inclusive, `to` exclusive, whole
  UTC hours, a non-empty reason such as a listing date) is exempt. The proxy and traded
  pairs cannot be exempted. Neither current dataset needs an exclusion: all basket
  symbols are complete over warm-up and evaluation (checked 2026-09-25);
- **integrity rules `drift-tolerance-v1`** (owner decision via Bob, 2026-09-24): a bar
  whose open, high, low and close match exactly and whose volume differs by at most
  0.1% of Binance's figure is counted as volume drift, not as a failure. Every other
  difference, and every missing or duplicated bar, stays fatal. The rules' name and
  tolerance are written to every `results.json`; `--strict-volume` (`strict-v0`, exact
  volume) stays available as a check. Features read Binance's 1h archive as published,
  so a drifted hour feeds its archive volume (within 0.1% of the minute sum) to the
  volume features; prices are identical, and fills use the minutes. Evidence
  (2026-09-24): `verify-2024h1` is valid in both modes; `practice-2022` is valid under
  `drift-tolerance-v1` and invalid under `strict-v0` because of one drifted daily bar
  per pair in its warm-up;
- warm-up sufficiency;
- the availability of sourced exchange filters (P4).

A pair-window that fails any of them is **excluded for every variant alike** and listed
with the reason. Exclusion is per pair-window: a pair can be excluded from one window
and kept in another. The mask is written to the results before scoring and cannot
change afterwards. Every current `practice-2022` SOL pair-window fails the filter check
unless P4 sources historical filters
([fee-levels-2026-09.md](backtests/fee-levels-2026-09.md), tick-size mismatch).

**Minimum evidence:** each development window must keep at least 2 included pairs.
Otherwise the outcome is "insufficient evidence", not a winner.

**Run validity:** a run in the mask is valid when:
- there are zero accounting problems, including the P6 reconciliation;
- there are zero rejected frames.

An invalid run **fails its variant** (C4). A failure in one variant never removes the
pair for the other variants.

## 6. Acceptance and selection (owner decisions, 2026-09-24)

The owner compared his criteria from this conversation with Bob's proposal
(`2025-09-25-owner-acceptance-criteria.md`) and chose this combined set. Acceptance is
judged at the primary fees. A variant passes when **all** of C1–C6 hold across its
included runs (every included pair, window and path):

| # | Criterion | Source |
| --- | --- | --- |
| C1 | **Worst drop,** on two bases in every run. **(a)** The max drawdown of **total equity** (active equity per `Account.equity` plus both reserves) is ≤ **10%** of its running peak. **(b)** The drawdown of **active equity** against the runtime's reserve-adjusted `risk_high` is ≤ **10%**. It is sampled at every pre-fill and post-fill risk evaluation, and **any hard-drawdown halt fails**. Both are measured from peaks, so after growth 10% can exceed 10 quote units. | Owner |
| C2 | **Makes money on the worse path:** for **each** intrabar path separately, the median return across included runs is > 0 after fees; **and** the mean return across all included runs is > 0. All runs have equal weight, and the median of an even count is the mean of the two middle values. | Owner, with Bob's worse-path rule |
| C3 | **Safer than holding:** in every included run, max total-equity drawdown < that run's buy-and-hold max drawdown (common sampling, P2). A run where buy-and-hold has zero drawdown fails. | Owner (strict) |
| C4 | **Integrity:** every included run is valid (§5). | Both |
| C5 | **Minimum activity:** for each included run, its rate = completed cycles (P7) ÷ (evaluation window length in days ÷ 7). The window is `[start of the start month, end of the end month)` in UTC, the same for every run in a dataset, whether or not the run halted. C5 = the arithmetic mean of the per-run rates over all included runs (equal weight), computed exactly (no rounding), and must be **≥ 1**. The ISO-week counter is reported, not scored. The share of bars holding inventory is reported. | Owner's compromise on Bob's 10%-invested rule |
| C6 | **The gate earns its place:** in at least **60%** of included runs, the variant's return ÷ max(max drawdown, 0.1 percentage points) exceeds that of the **ungated V0 baseline** in the same pair, window and path. | Bob |
| R1 | **Economics, reported only:** the capital at which the mean monthly return would cover €5/month of hosting (5 ÷ mean monthly return fraction), or "not reachable" if the mean return is ≤ 0. Running on the owner's own PC costs €0 in hosting. | Bob, as information |

**Selection (deterministic):**
1. The **eligible set** is the passing variants among V0, A, B, C, E (only after Codex's
   implementation review, §3 E), F, G, C+G, H and C+H. D is excluded
   before ranking.
2. Let `M` be the highest mean return in the eligible set, in percentage points rounded
   to 6 decimals. The **tie set** is every eligible variant with mean return ≥ `M − 0.25`
   (inclusive).
3. Within the tie set, pick the lowest mean total-equity max drawdown, rounded the same
   way.
4. If still tied, pick the first in the fixed simplicity order V0, A, B, F, G, H, E, C,
   C+G, C+H.
5. D **cannot be selected.** C1–C6 are still computed and reported for D, for
   information only, next to the winner.

**No winner:** if no variant passes, v1 ends with "no winner". Nothing runs on the
reserved window, and the report says so.

## 7. Reserved evaluation (run exactly once)

**What "untouched" means here:** no replay has been run on this window. It is **not** an
unseen regime:
- While researching the Bitcoin cycle with the owner (2026-09-24), Claude read reports
  of the peak on 2025-10-06, the roughly 50% decline and the June 2026 low. That
  knowledge motivated variant A.
- The window is therefore a prospectively reserved replay window, and its result is
  weaker evidence than a truly unseen period.
- Failures on it are recorded as they are. No variant is retuned and rerun on the same
  window, and a failed attempt is never replaced or reused as a fresh evaluation.

**Prior exposure record (as of this draft):**
- **Seen in chat:** Claude read public reports of the 2025–26 BTC regime (the peak on
  2025-10-06, the roughly 50% decline and the June 2026 low).
- **Not done:** no 2025–26 archive data has been downloaded, and no 2025–26 replay,
  feature or statistic has been computed.
- **Outside the window:** the live-stream and Revolut X order-book checks of September
  2026 fall after it.

Any later exposure before the run is added to this record.

**Frozen before access:** the following are frozen and recorded before the window's data
is fetched:
- the code commit, config, spec version and dataset spec;
- the universe (the pairs listed below);
- the comparison-mask rules (§5);
- the scoring (§6);
- the execution conventions.

Fetching and verifying the data are part of the run and happen only after the owner's
go. The manifest hashes are recorded at that moment and are then fixed.

**Technical reruns:**
- **Allowed** only when a run is invalid because of a harness defect that does not
  change strategy, parameters or data. The fix must be reviewed by Codex, and both the
  failed and the rerun artifacts are kept.
- **Not allowed** for data invalidity: that pair-window is excluded under §5.
- **Not allowed** for a strategy result the owner dislikes.

**Holdout mask:** the §5 rules apply. If fewer than 3 of the 5 pairs are included, the
outcome is "insufficient evidence", not a pass. There is no silent averaging over the
surviving pairs, and every exclusion is listed.

**Owner gate:** this run starts only after the owner explicitly says go in the
conversation. That go is recorded in the report with its date. Finishing §2–§6 does not
start it automatically. Before asking, Claude reports:
- the practice-matrix results;
- the winner, or that there is none;
- the exact code commit, config, dataset specs and manifests to be used, all frozen.

- **Window:** 2025-01 to 2026-08. This is the latest complete month before this spec. It
  includes the October 2025 peak and the decline that followed.
- **Pairs:** BTCUSDT, ETHUSDT, XRPUSDT, SOLUSDT and ADAUSDT as Binance proxies for the
  Revolut X EUR pairs, fixed now. The daily warm-up starts in 2024-04.
  - The set is wider than the development windows on purpose: it is the five
    EUR-quoted coins the owner is likely to trade on Revolut X.
  - ETH is absent from the development windows only because of archive defects in
    `practice-2022` (see that spec).
  - **Robustness set (reported, not deciding):** DOGEUSDT, LTCUSDT, LINKUSDT, AVAXUSDT
    and DOTUSDT, plus every pair that was in Binance's top 30 USDT spot pairs by quote
    volume in 2024-12 and was delisted before 2026-09. That list is determined from the
    2024-12 archives and Binance's delisting announcements, and frozen before the window
    is fetched.
  - This answers Bob's survivorship concern without letting coins that cannot be traded
    on Revolut X decide the result.
- **Runs:** the winner, V0, ungated V0 (the C6 baseline) and D, at the primary fees, on
  both paths.
- **Data problems:** a pair that fails integrity is reported as invalid and is **not**
  replaced by another pair.
- **Judging:** the result is judged against C1–C6 on the five deciding pairs and
  reported whether it passes or not. R1 and the robustness set are reported alongside.
  A pass does not authorise live trading; it only justifies the next step, a proposal
  for paper trading on live Revolut X prices, which needs its own review.

## 8. Scope of the evidence

- The simulation replays **Binance USDT** market data with **Revolut X fees**. It is a
  cost-sensitivity experiment, not a backtest of Revolut X EUR execution: Revolut X
  prices, spreads, queue positions, depth and post-only behaviour are not simulated.
- A pass justifies at most a proposal for paper trading against live Revolut X prices.

## 9. Sources

Venue terms and research claims that motivated this spec. They were checked on
2026-09-24 and may change.
- Revolut X fees: <https://www.revolut.com/legal/crypto-exchange-fees/>
- Revolut X API, including post-only orders and rate limits:
  <https://developer.revolut.com/docs/x-api/revolut-x-crypto-exchange-rest-api>,
  <https://developer.revolut.com/docs/x-api/place-order>
- Inventory-aware market making (Avellaneda–Stoikov):
  <https://hummingbot.org/blog/guide-to-the-avellaneda--stoikov-strategy/>
- Short-horizon crypto mean reversion (about 1.3 bp gross per trade):
  <https://arxiv.org/abs/2608.21888>
- Trend following in crypto: <https://arxiv.org/pdf/2009.12155>,
  <https://research.grayscale.com/reports/the-trend-is-your-friend-managing-bitcoins-volatility-with-momentum-signals>
- Bitcoin four-year cycle, 2025 peak and 2026 status:
  <https://www.fidelity.com/learning-center/trading-investing/four-year-bitcoin-and-crypto-cycles>,
  <https://coinmarketcap.com/academy/article/%20bitcoin-4-year-cycle-october-2026>

## 10. Not decided in v1

These stay open; each needs its own specification:
- the policy after a large loss (cool-off or permanent stop);
- quote skewing;
- a Revolut X price feed;
- any live-trading work;
- a README change to the "Binance spot only" operating rule. Revolut X is named here
  only as the fee scenario and as the venue for a possible later paper-trading
  proposal, which needs its own review.
