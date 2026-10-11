# Claude: V3.1 spec-conformance review at `0677969`

Index: Claude's requirement-by-requirement check of PR #269 against the V3.1 design, the approved observation convention and the owner's baseline decisions. Seven blockers and the majors are listed with failure scenarios and a fix plan; four owner decisions taken on 2026-10-11 are recorded. Synthetic probes only.

Checked at `0677969` (the PR head `411f75a402837214ccc03b14001311443eb6e563` plus
the duplicate-minute guard). Six independent read-only reviewers each took one part of
[the design](../superpowers/specs/2026-10-10-v3-1-design.md), the
[observation convention](../superpowers/specs/2026-10-10-v3-1-intrabar-proposal.md) and
the [source inventory](../V3_1_SOURCE_INVENTORY.md), mapped every requirement sentence to
code and a test, ran the targeted test files (all pass) and confirmed suspected defects
with in-memory synthetic probes. Claude re-read the code behind each blocker. Claude also
read the committed dataset inventory (`config/datasets/v3-20261009/inventory.manifest.json`,
manifest entries only, no prices) to test the draft registration.

## What conforms

- **Scope:** no change under `simulation/`, `trend/`, `strategy/` or `backtest/`
  (`git diff --stat origin/main...HEAD` is empty there); no new dependency; no network,
  credential or environment access in `combined/`; the dashboard has a `default-src 'none'`
  policy and escapes all text.
- **Accounting:** one cash balance; collateral debits it; fees and funding hit the wallet;
  exact Fractions; residuals retained.
- **Limits:** 0.5% asset and 3% aggregate risk, 20% asset and 1.6x gross notional, 80%
  correlation-group gross, atomic reservations, 50% collateral, entry and exit costs
  reserved, funding admission, margin 4 / 3 / 1, the two owner decisions on open positions
  (risk from entry; cut to 90%).
- **Assessment:** no look-ahead found. A probe at off-boundary decision times with full
  and truncated inputs gave identical assessments. The preset matches the spec.
- **Routing and components:** the routing table holds across every arm; stops, the
  2R / 3 ATR trail, grid geometry, the flow hysteresis and the short rules conform.
- **Protection and recovery:** the 30% trigger, cooldown after tradable liquidation, dust
  rules, the 0.25 / 0.5 restart sizing, the 3% episode stop, a lifetime peak that never
  resets, funding before exits, the adverse old-stop precedence and the terminal sample at
  the reserved boundary.
- **Acceptance:** strict "beat every baseline on both measures", the 30% gate on every
  intrabar mark, positive doubled-cost profit, scenarios never pooled, missing cells
  incomplete.

## Blockers

1. **Real data cannot run.** `strategy_replay._bars` refuses a window with any missing
   hour, and `_funding` refuses a cadence change. The inventory has, inside the candidate
   window 2021-07 to 2024-12: about ten masked spot hours on every coin (2021-08: 5,
   2021-09: 2, 2021-12: 1, 2023-03: 2), 120 masked futures hours on LTC, SOL, TRX and XRP
   (2022-02: 72, 2022-04: 48), and a SOL funding month excluded for "interval changes
   within month". Every registered run would be refused. The spec expects the opposite:
   a missing due bar makes a symbol unavailable for increases (line 72), missing bars
   preserve close obligations and never fill (line 161), and a changed cadence refuses
   increases while actual funding is still charged (lines 153-154). The frozen V3 code
   handled masked hours this way.
2. **The flow gate only filters placement.** `decide()` reads the gate, but a resting grid
   basket keeps its buys, and `interval()` passes them to the path with no gate check.
   Probe: flow 0.6 then 0.3 from hour 2; the gate blocks, and a grid buy still fills at
   hour 26. Spec lines 122-123 make grid buys unavailable while blocked. V1's variant F
   cancels resting buys while blocked.
3. **The owner's baseline list is not enforced.** `experiment._BASELINES` holds only the
   V3 family and the hold, and registration needs just one extra baseline. A registration
   without V0, V1, comparator D or one native path mode evaluates to `pass`
   (`test_complete_matrix_passes_and_all_results_are_retained` registers only `matched_v2`).
4. **Missing grid minute inputs leave the report complete.** `SymbolMarket.minutes`
   defaults to `()`; the grid on that coin silently never trades and the run reports
   `complete=True`. Spec line 63: missing grid inputs make the evaluation incomplete.
5. **Mid-phase forced closes of other assets fill at a favorable price.** `portfolio_path.drain`
   settles close and cut-back obligations at the other assets' quotes of the *previous*
   vertex. Probe: lifetime drawdown 29.95%, two longs, bar 100/101/90/95; in the
   high-to-low phase the second long is sold at 101, the bar high, although its own
   stop at 98 is touched in that phase. This breaks "no favorable intrabar choice"
   (Verification) and biases returns, recovery and margin closes upward.
6. **The minute baselines do not check their window start.** The frozen `replay` trades
   every supplied minute, and only the window end is guarded
   (`baseline_minute.py:158`). Minutes from before the start would trade an extra day
   while the opening sample still equals the initial capital.
7. **Baseline adapters accept 2025+ data.** No reserved-boundary check in
   `baseline_v3`, `baseline_minute` or `baseline_hold`; the V3 selector trains on
   whatever it is given.

## Majors

- **Aggregate cut-back trims zero-risk winners.** An aggregate-risk breach applies the
  common fraction to every holding, including one whose stop has passed its entry and
  that adds no risk. Probe: a trailed BTC long with zero entry risk is cut to 8.64 when
  other positions breach 3%. Cutting it removes no risk, costs fees and gives up the
  winner, which is what the owner's "risk from entry" decision set out to stop. Claude's
  reading of "every affected holding": a holding is affected by an aggregate-risk breach
  only if it contributes risk. Gross and group-gross breaches still cut every holding,
  since every holding contributes notional. The owner is told; it is easy to reverse.
- **A worse-than-planned fill closes the whole position and cancels every pending order**
  (`engine.py:1027-1032`) instead of the excess-risk reduction of spec lines 106-108.
  Unreached in the current replay (fills are at or better than planned); fixed so any
  adapter with gap fills behaves as specified.
- **Evidence records** lack required fields: the assessment has no costs, reservations,
  correlated exposure or executable size on refusals, and no stable ID or source refs
  (spec 68-70, 190); risk admission keeps only its first refusal; `Opportunity` keeps only
  the first reason; data-gap refusals with no signal never reach the funnel.
- **Daily bars are not checked against the hourly bars** they must be built from (complete
  days only). The replay accepts any daily input.
- **Recovery episodes are merged:** a restart, 3% stop, cooldown and second restart show
  as one episode, with incremental P&L measured from the 30% trigger.
- **Disclosures never reach the report:** hold-below-minimum, native timing, the capital
  adapter, the capital scenario and its FX pin, present-day filters.
- **The dashboard has no cross-version comparison** (common-schedule return and drawdown
  per baseline, native diagnostics) and never shows favorable excursion or profit
  surrendered for combined runs. A multi-year report breaks the artifact bundle when
  saved next to it.
- **No execution gate binds a run to its pins** (code, config, data, FX, cost profiles);
  pins are checked only at acceptance. The spec schedules the owner execution gate with
  the registration, so it is built there.
- **No ablation parity tests:** nothing shows an ablation arm reproduces `combined` on data
  where its switch never binds.

## Minors and rulings

- The continuation ablation restores the RSI veto on **4h** RSI; the frozen veto it
  restores used **daily** RSI(14). Ruling: daily, since the spec says "restores".
- The short-qualification ablation also changes held long exits (daily UNCLEAR + 4h DOWN
  becomes the DOWN row). This follows the spec's literal text for that row; disclosed.
- Moving from half to quarter allowance at 15% drawdown trims holdings admitted at half.
  The spec allows half risk "only" below 15%, read as a standing condition; disclosed.
- A group breach cancels pending increases in unrelated groups; it should cancel only the
  affected ones.
- The 2x absolute gross cap has no check or metric.
- Futures entries are refused in the window's first hour (the opening estimate starts at
  the first slot, usable a minute later).
- Some Decimal divisions round at 60 digits instead of exact Fractions.
- A residual of at most 1e-18, which the spec allows, is reported as invalid accounting.
- EUR100 accepts an FX rate of exactly 1; no plausibility bound.
- Negative returns make return/drawdown favor larger drawdowns; the doubled-cost profit
  gate makes this unreachable for a passing full arm, but the comparison is reported.
- The V3 capital adapter's lock does not cover `selector_picks`.
- Test gaps listed by each reviewer (structure labels, warmup edges, group cut-backs,
  equality boundaries, replay-level no-short-in-uptrend, recovery sequence).

## Owner decisions, 2026-10-11

Recorded in the [source inventory](../V3_1_SOURCE_INVENTORY.md) and the design:

1. **Data gaps: skip them for everyone.** The comparison schedule is every window hour at
   which every registered price source has its bar; skipped hours are listed; the 30% gate
   still uses every mark.
2. **A baseline that stops early is a finished result**, frozen at its stop and labelled.
3. **Futures fallback only when the venue minimum is the cause**, not committed cash.
4. **Fetch the missing one-minute bars through Bob** for ADA, BNB, DOGE, LINK, LTC, SOL
   and TRX, 2021-06 to 2024-12.

## Plan

Each item gets a failing test first, then the fix:

- **Batch 5, replay:** blockers 1, 2, 4 and 5; the aggregate cut-back; the fallback
  decision; the worse-fill reduction; the RSI ruling.
- **Batch 6, evaluation:** blockers 3, 6 and 7; decisions 1 and 2; disclosures into the report.
- **Batch 7, evidence:** records, episodes, dashboard comparison, daily cross-check and
  ablation parity.

Then a second conformance pass, the exact registration and a separate owner go. There is
no merge before full conformance, no historical run and no 2025+ data.
