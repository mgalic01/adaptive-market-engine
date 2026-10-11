# V3.1 conformance fixes: implementation plan

Spec: [V3.1 design](../specs/2026-10-10-v3-1-design.md), the owner-approved
[observation convention](../specs/2026-10-10-v3-1-intrabar-proposal.md) and the owner
decisions in [the source inventory](../../V3_1_SOURCE_INVENTORY.md). Findings and their
failure scenarios: [conformance review](../../reviews/2026-10-11-claude-v3-1-conformance.md).
Branch `codex/v3-1-runtime-integration`, base of this plan `8244cb3`.

## Global constraints

- New behavior lives in `src/crypto_grid_bot/combined/`. Never modify anything under
  `src/crypto_grid_bot/simulation/`, `trend/`, `strategy/` or `backtest/`, or any frozen
  preset. Frozen baselines are wrapped, never changed.
- Money, price, quantity and ratio math in `Decimal` or `Fraction`, never `float`
  (SVG coordinates in `dashboard.py` are the only exception).
- No network, no credential or environment access, no new dependency, no market data:
  tests use synthetic in-memory inputs (the fixtures in `tests/combined_fixtures.py` and
  the existing test modules). Never read anything at or after 2025-01-01
  (`1_735_689_600_000` ms); inputs at or after it are refused, not ignored.
- Fail closed: a missing input or unverifiable condition makes an outcome unavailable,
  refused or incomplete, never favorable. Every refusal keeps its reason.
- Test first. Each behavior gets a failing test in `tests/test_combined_<module>.py`, then
  the fix. Run the focused test files while iterating and `python -m pytest -q
  tests/test_combined_*.py` once before committing. `python -m ruff check`,
  `python -m ruff format --check` and `python -m mypy` must pass on touched files.
- One commit per task (fix rounds add commits). Commit messages end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push, never change
  branches, never run `git` commands that rewrite history.
- Keep the existing code style: short docstrings that state the rule, comments only
  where the reason is not obvious, names that say what a thing is.

## Task 1: The flow gate withholds resting grid buys while blocked

Spec lines 121-123: the F flow gate "uses 15 completed 1m bars: block below 0.40 /
unavailable; unblock >= 0.45; initial blocked. Missing flow makes grid buys unavailable,
not ungated. Sales bypass flow gates."

Defect: `strategy_replay.decide()` reads `gates[symbol].allowed` only when a basket is
placed. `interval()` passes every resting `RestingBuy` to `replay_held_portfolio` with no
gate check, so a basket placed while flow was allowed keeps buying after the gate blocks.
Probe: taker-buy share 0.6 until START+2h and 0.3 after; the basket is admitted at hour
0, the gate blocks from hour 2, and a grid buy still fills at hour 26.

Required behavior:
- In `interval(hour)`, a symbol whose gate is not `allowed` (as last updated by the frame
  at `hour`) contributes no resting buys to that interval's path. Its levels and its
  reservation stay; they become fillable again in an interval whose opening frame finds
  the gate allowed.
- Held grid lots of that symbol keep their stops and targets (sales bypass the gate).
- The trace records, per symbol, the intervals in which resting buys were withheld
  (a new `StrategyTrace` field, e.g. `withheld_buys: tuple[tuple[str, tuple[int, ...]], ...]`),
  so the report can show it.

Tests (in `tests/test_combined_strategy_replay.py`):
- the probe above: no grid buy fills in any interval that opens with the gate blocked;
- after flow recovers to >= 0.45 the same untouched levels fill again;
- a held lot's target still sells while the gate is blocked.

Ruling recorded in the plan: withholding (not canceling) keeps the frozen V1 variant F
semantics (blocked buys are not working; they work again on unblock) without forcing a
rebuild at a new price, and keeps the capital reserved, which is the conservative side.

## Task 2: A grid-capable coin without its minute input makes the run incomplete

Spec lines 62-63: "Missing grid inputs or comparisons make evaluation incomplete, never
silently drop an arm." Owner decision 2026-10-11: one-minute bars are being fetched for
all ten coins; until registered, a grid run without a coin's minute input is incomplete.

Defect: `SymbolMarket.minutes` defaults to `()`. A grid-enabled arm on a coin with no
minute input never places a basket (flow unavailable) and the report says `complete=True`.

Required behavior:
- For an arm whose routing enables the spot grid (`spot_grid`, `combined` and the
  `combined_without_*` ablations), a symbol whose minute input has no bar at all within
  `[start_ms - 15 min, end_ms)` is a missing grid input. The replay still runs (trend
  components on that coin are unaffected), but the trace records the symbol in a new
  field (e.g. `missing_grid_inputs: tuple[str, ...]`) and
  `replay_records.strategy_report` turns each into a producer issue
  `missing_grid_input:<symbol>`, so the report is incomplete.
- Sparse missing minutes inside an otherwise present input are not a missing input: the
  flow for that hour is unavailable and grid buys are unavailable (existing behavior).
- Arms without the grid (`spot_trend`, `futures_trend`, `futures_trend_long_only`) do not
  require minute inputs.

Tests: the two probes from the review (`combined` with no ETH minutes; `spot_grid` with
ETH minutes missing) now give `complete=False` with the named issue; a trend-only arm with
no minutes stays complete; sparse gaps keep the run complete.

## Task 3: Missing hourly bars do not stop the run

Spec: a missing due bar or stale quote makes a symbol unavailable for increases (line 72;
routing row "Stress/unavailable: cancel increases and prioritize protective reductions");
"Missing bars preserve close obligations, never fills" (line 161). Owner decision
2026-10-11: hours missing from any source are skipped in comparisons (Task 8), and the
run itself must proceed. The committed inventory has, inside 2021-07 to 2024-12, about
ten masked spot hours on every coin and 120 masked futures hours on LTC, SOL, TRX, XRP.

Defect: `strategy_replay._bars` raises "every window hour is required", so every
registered run would be refused.

Required behavior:
- `_bars` keeps its structural checks (immutable klines, sealed boundary, unique sorted
  hour-aligned stamps inside the window) but allows missing window hours. The trace
  records every missing `(symbol, venue, hours)` in a new field `data_gaps`.
- **Interval with a missing bar.** A symbol without its venue bar for the interval is left
  out of that interval's path: no fill of any kind for it (stops, targets, resting buys).
  Its position keeps its last mark. The engine's existing rule then marks it stale and
  requires its close (`stale_position_or_missing_filters`); keep that rule unchanged.
  Ruling: keep the engine's conservative stale-close rule; it is the reviewed safety
  behavior and the spec's "prioritize protective reductions"; disclosed in the report.
- **Obligations without a price persist.** A close or cut-back obligation on a symbol that
  has no price in the current interval or frame is carried, not a failure:
  `portfolio_path`'s end-of-interval check and the boundary executor must not report
  `unresolved_execution_obligations` (or any failure) for symbols that had no price.
  The obligation executes at the first later bar's opening quote (the existing gap rule).
  Obligations on symbols that did have a price keep today's failure semantics.
- **Frame with a missing bar.** `held_market` omits held symbols without a bar at that hour;
  the opening stop check skips them; `decide()` gives a symbol without a spot bar no spot
  quote (`VenueInputs(..., quote=None)`) so the decision is refused with its recorded
  reason, and a missing spot quote never permits futures fallback (spec line 101); a
  missing futures bar gives futures no quote. Management skips trailing for a symbol whose
  completed venue bar is missing.
- **Terminal mark.** If a held symbol has no bar in the last window hour, the terminal
  boundary values it at its last available close and the trace records it as a stale
  terminal mark.
- Funding at a slot whose futures bar is missing is Task 4.

Tests: one masked spot hour on a held spot-trend coin (no fill that hour, close obligation
carried and executed at the next bar's open, run completes, gap recorded); a masked hour
on a coin with a resting grid basket (no buy that hour); a 72-hour masked futures span on
a held futures position (no failure; executed when bars return); a decision at a masked
spot hour is refused and does not fall back to futures; a window whose last hour is masked
gives a stale terminal mark.

## Task 4: Funding schedules with gaps, cadence changes and off-hour records

Spec lines 152-155: futures are admitted only with a source-verified eight-hour cadence
known at decision time; "unknown or changed cadence refuses increases. Actual published
funding events are charged regardless of entry eligibility." The inventory excludes SOL's
2022-11 funding month ("interval changes within month", "record off scheduled slot"); the
data preparation will register those records as published.

Defect: `strategy_replay._funding` raises on any gap or cadence change, so such a window
cannot run.

Required behavior:
- `_funding` keeps validity, uniqueness and sealed-boundary checks, and still requires a
  record at or before the window start. It accepts a cadence change: consecutive records
  are consistent when the later one is scheduled exactly `before.interval_hours` after the
  earlier one, or the later record's own `interval_hours` differs from the earlier one's
  (a declared change) and it is scheduled after the earlier one.
- A **missing settlement** is a slot implied by a record's `interval_hours` with no record
  before the next one. It is never assumed zero: if a futures position on that symbol is
  held at a missing slot's time, the run stops with the retained failure
  `funding_record_missing:<symbol>:<slot_ms>`. No position held: nothing to charge.
- Admission is unchanged: the estimate is the latest record usable at decision time, and
  `risk.py` already refuses a non-eight-hour or stale estimate, so a cadence change or a
  gap refuses increases by itself. Add a test that proves it.
- **Off-hour records** (scheduled time not on an hour) are charged at the first hourly
  boundary at or after their scheduled time, on the holdings that survived to that
  boundary; the funding event records both the scheduled and the booked time, and the
  report discloses the delay.
- **Fixing mark when the futures bar is missing** (Task 3's gaps): the record is still
  charged, valued at the last available futures close before the slot; the fixing records
  that its mark is stale.

Tests: a 8h-to-4h cadence change mid-window (charges every record; refuses increases
after the change); a missing slot with no position (run completes) and with a held
futures position (retained failure naming symbol and slot); an off-hour record charged at
the next boundary with both times recorded; a slot inside a masked futures span charged at
the last available close with a stale-mark flag.

## Task 5: Mid-phase forced closes of other assets fill at the adverse price

Verification item "no favorable intrabar choice"; observation convention point 2
(conservative execution, no fictional liquidation).

Defect: `portfolio_path.drain` settles close and cut-back obligations created at a
sub-event (a buy, stop or target inside a phase) at the other assets' quotes of the
*previous* vertex. Repro (in the review): lifetime drawdown 29.95%, longs A and B of 14
at 100, stop 98, bar O100/H101/L90/C95. OLHC: A's stop crosses 30% and B is sold at 100
although its own stop at 98 is touched in that phase; OHLC: B is sold at 101, the bar high.

Required behavior: when `drain` runs at a sub-event of phase P and reduces a symbol X
other than the symbol whose event triggered it, X's execution reference price is:
- X's own stop price for phase P, if X has a stop event in phase P not yet executed
  (its stop fills when touched; a forced close earlier in the phase is no worse);
- otherwise the adverse one of X's quote at the start of phase P and X's vertex at the
  end of phase P (lower for selling a long, higher for buying back a short).
Drains at the phase-end vertex and at the open keep today's pricing. Marks used for
drawdown are unchanged. The same rule covers lifetime-drawdown closes, margin reductions
and cap cut-backs created at sub-events.

Tests: the repro in both scenarios (B exits at 98 in both; never at 100 or 101); a forced
close of an asset without a stop in that phase fills at the phase-end low (long) or high
(short); a phase-end drain still fills at the vertex.

## Task 6: Engine cut-backs follow the owner's decisions exactly

Spec lines 131-146 (owner decisions "Risk from entry; trim size" and "Cut to 90% of the
limit") and lines 105-108.

Defects and required behavior (all in `engine.py`):
1. **Aggregate-risk breach spares holdings without entry risk.** `_cap_reductions` applies
   the common aggregate-risk fraction to every holding, including one whose stop is at or
   beyond its entry. Ruling (owner informed): a holding is affected by an aggregate-risk
   breach only if its stop is worse than its entry. Spared holdings keep their quantity;
   the common fraction applied to the affected ones is chosen so total risk after the cut
   is 90% of the limit, counting what the spared holdings still contribute (exit costs).
   If the affected holdings cannot reach that target, cut them to zero risk. Gross,
   group-gross and per-asset limits are unchanged (every holding adds notional).
2. **A group breach cancels only the affected pending increases.** Today any group breach
   cancels every pending order. A group breach cancels pending increases in the breached
   group(s) only; an aggregate risk or aggregate gross breach still cancels all pending
   increases; an asset breach cancels that asset's.
3. **A worse-than-planned fill reduces the excess, not the whole position.** Today
   `_require_close(symbol, "post_fill_risk_breach")` closes the position and, through the
   portfolio-protection set, cancels every pending order. Instead: book the fill as
   today; compute the risk the filled quantity actually carries at the booked price; if it
   exceeds the approved risk, record a cut-back of that symbol to the quantity the approved
   risk allows (round down to the step; zero becomes a close of that symbol only), record
   the breach size and the extra cost in the close/trim reasons or a new evidence field,
   and cancel only that symbol's pending increases. A fee above the approved fee rate
   keeps today's integrity handling.

Tests: the reviewer's probe (a trailed BTC long with zero entry risk is not cut when six
other longs breach 3%; total risk after the cut is 90% of the limit); a group breach
leaves a pending order in an unrelated group untouched; a fill one tick worse than planned
trims only that symbol to the approved risk and leaves other symbols' orders.

## Task 7: Futures fallback only when the venue minimum is the cause; daily RSI veto

Owner decision 2026-10-11 ("Only when the minimum is the cause"): a futures long
replaces a spot entry only when the spot size allowed by the risk and size limits, before
any cash or capacity already committed, is below the venue minimum. A spot order that is
too small only because cash or capacity is committed is refused, not moved to futures.
Ruling on spec lines 84-85: the continuation ablation "restores" the frozen veto, which
used the daily RSI(14) (`strategy/mode_selector.py`, `UPTREND_RSI_MAX`), so the restored
long RSI>=75 and short RSI<=25 vetoes read the daily RSI(14), not the 4h RSI.

Defects: `risk.py` returns `below_minimum` for any floored size under the venue minimum
and `decisions.py` treats every such refusal as proof that spot is unexecutable, so a
cash-limited spot entry becomes a leveraged futures long; a fully exhausted bound returns
`portfolio_capacity` and gets no fallback, so the same cause routes differently.
`routing.py` applies the ablation veto to the 4h RSI.

Required behavior:
- The spot preview distinguishes the cause: `below_minimum` only when the size allowed by
  the per-asset risk, asset notional and recovery allowance, computed without free-cash,
  pending-reservation, aggregate-risk, gross or group commitments, is below the venue
  minimum; a size reduced below the minimum by those commitments is refused with a
  separate reason (e.g. `spot_capacity_committed`) that never enables fallback.
- The assessment records the daily RSI(14) from completed daily closes (the reused
  `wilder_rsi`), and the continuation ablation's veto uses it; the 4h RSI stays recorded.

Tests: tiny capital where even an uncommitted spot size is under the minimum still falls
back to futures; ample capital with spot cash committed to pending orders refuses with the
new reason and no futures order; the ablation vetoes a long at daily RSI 76 with 4h RSI 60
and not at daily RSI 60 with 4h RSI 80; the same for shorts at 24 / 40.

## Task 8: Acceptance enforces the owner's baselines, gap-free schedule and early stops

Owner decisions 2026-10-11 (source inventory): membership "V3 family, hold, V0-V2 and D",
each native path mode its own arm; "Skip them for everyone"; "Count it as a finished
result".

Required behavior (in `experiment.py`, `outcomes.py`, `common_series.py`,
`baseline_records.py` as needed):
1. **Membership.** Registration requires every baseline family: `unchanged_v3_selector`;
   `unchanged_v3_r1_long_only` to `r6`; `matched_spot_hold`; the V0 grid, at least one V1
   variant, the V2 grid and comparator D, each of these minute baselines registered in
   both native path modes `high_first` and `low_first`. Use one documented naming
   pattern, e.g. `matched_v0_grid_<mode>`, `matched_v1_<variant>_grid_<mode>`,
   `matched_v2_grid_<mode>`, `matched_d_trend_<mode>`, validate it, and reject a
   registration missing any family or any path mode of a registered minute baseline. The
   exact V1 variant list is supplied by the registration (pinned there). Update the test
   fixtures that register only `matched_v2`.
2. **Gap-free common schedule.** The registration carries the skipped hours (a sorted
   tuple of hour stamps inside each window, the union over every registered source's
   missing bars, pinned with the data). `common_hourly_series` selects every window hour
   except the skipped ones; a missing mark at a scheduled hour stays incomplete; nothing
   is interpolated. The opening and terminal samples are never skipped (a skipped first or
   last hour is a registration error). The report lists the skipped hours. The 30%
   drawdown gate keeps using every native mark.
3. **Early-stopped baseline.** A baseline that ended under its own native rules
   (`liquidation`, `no_tradable_position`, `leverage_not_restored`, or the minute adapters'
   equivalents) is a finished result: its outcome is complete, its native stop reason is
   kept, and its common series holds its last recorded equity at every later scheduled
   hour, each such point labelled frozen. The full arm must still beat it on both measures.
   Other baseline failures (parity failures, missing inputs) stay incomplete.

Tests: a registration without V1, without D, or with one path mode only is rejected; the
complete matrix with every family passes; a schedule with skipped hours compares on the
remaining hours and an unscheduled missing mark does not make the comparison incomplete;
a skipped opening hour is rejected; a baseline liquidated mid-window is complete, frozen
and still has to be beaten.

## Task 9: Baseline adapters check their window and the reserved boundary

Spec lines 27-28 (same dates) and 48 (2025+ closed).

Required behavior:
- `baseline_minute`: refuse inputs with any minute before `start_ms` (beyond the
  warm-up the frozen runner explicitly needs, if any; document it) or at/after `end_ms`;
  today only the end is guarded (`baseline_minute.py:158`).
- `baseline_v3`, `baseline_minute`, `baseline_hold`: refuse any input record (bar, funding,
  minute) at or after `1_735_689_600_000`, before calling frozen code, including the data
  given to `selector_picks` for training.
- `baseline_v3`: the capital adapter's lock also covers `selector_picks`, so training never
  runs while another thread holds a different starting capital.

Tests: a minute input starting a day early is refused; a 2025 bar in any adapter's input
is refused before the frozen call; selector training under a concurrent small-capital run
uses 10,000.

## Task 10: Disclosures and capital labels reach the report and dashboard

Spec lines 31-33 and the owner's baseline decisions ("disclosed", "labelled ... in the report").

Required behavior: `RunOutcome` and `Report` carry a `disclosures` tuple and the capital
scenario label (`research_10000_usdt`, or `owner_small` with currency, amount, FX rate and
FX pin). Baseline disclosures (`BaselineEvidence.disclosures`: hold below minimum, native
timing, capital adapter, frozen-after-stop) and V3.1 disclosures (present-day saved
filters, stale-close rule, stale terminal mark, off-hour funding, withheld grid buys,
skipped hours) are carried through and rendered in a "Disclosures" section of the
dashboard. A 100 USDT capital must never be labelled EUR100: a registration whose
`owner_small` capital has an FX rate of exactly 1 or outside a plausibility band of 0.5 to
2.0 USD per EUR is rejected, and `fx_pin` must be present.

Tests: each disclosure appears in the report and the rendered page (escaped); an FX rate
of 1 is rejected; the capital label appears on the page.

## Task 11: Evidence records carry the full assessment and every blocker

Spec lines 68-70, 86, 190-193.

Required behavior: `Assessment` gets a stable ID and source references; each decision
record (accepted or refused) carries the assessment's costs (spot and futures), funding
estimate, executable size or the reason it is unavailable, existing holdings and
reservations of that symbol, and its correlation group with the group's gross exposure.
Risk admission returns every independent refusal reason, not only the first;
`replay_records.opportunity_records` keeps all reasons; a data-gap refusal with no signal
(missing due daily or 4h bar) is recorded in the funnel as a refused detection with its
reason instead of being dropped. Persist these records (assessment, intent/protection,
admission/refusal, lifecycle, recovery) as versioned files in the artifact bundle.

Tests: a refused short records costs, reservations and correlated exposure; risk admission
with two failing limits returns both; a missing due daily bar appears in the funnel; the
bundle round-trips the new records.

## Task 12: One recovery episode per restart

Spec lines 173-177.

Required behavior: `replay_records.recovery_episodes` starts an episode at each restart
(entry into the 25% allowance) and ends it at its 3% stop, at normal restoration or at the
window end. The forced liquidation after the 30% trigger and each cooldown are their own
records. Incremental P&L of an episode runs from its restart to its end.

Tests: trigger, liquidation, cooldown, restart, 3% stop, cooldown, restart, restoration
gives two episodes with their own P&L, plus the liquidation and both cooldowns.

## Task 13: Dashboard comparison, excursion and bundle size

Spec lines 195-198; observation convention point 5.

Required behavior: `render_report` accepts the cross-version comparison and shows, per
baseline, return and maximum drawdown on the common schedule, the pass/fail of each
measure, and the native diagnostics labelled by version. Combined runs compute each
lifecycle's maximum favorable excursion and profit surrendered from the path marks. A
report whose exact JSON is too large to embed is written as a separate bundle file that
`read_bundle` accepts. "Bad periods" also list the window's three largest drawdown
episodes (peak, trough, recovery or window end).

Tests: the page lists every baseline with both measures; MFE and giveback on a synthetic
trade; a large report round-trips through the bundle; drawdown episodes appear.

## Task 14: Daily bars must equal the registered hourly bars

Spec Package B: daily context from completed information; the registration proposal
lists the daily aggregation as a rule to register. Ruling: use the frozen V3 rule
(`trend/data.py::hourly_month`): a UTC day's bar aggregates its available registered
hourly bars (first open, highest high, lowest low, last close, summed volumes) when at
least 20 of its 24 hours are present; with fewer there is no bar for that day. V3.1 and
its V3 baseline then read the same daily context; the cost if wrong is a few outage days
built from 20-23 hours.

Required behavior: the replay rebuilds the daily bars from the registered spot hourly
bars under that rule (or checks every supplied daily bar inside the assessment's reach
against it and refuses a mismatch before any mutation). A day without a bar is a recorded
gap; a decision whose due daily bar is missing is unavailable (existing behavior).

Tests: a supplied daily bar that differs from its hours is refused; a day with 23 hours
gives a bar equal to the 23-hour aggregate; a day with 19 hours has no bar and the next
day's decisions record the missing due daily bar.

## Task 15: Ablation parity

Verification item "disabled-component baseline parity".

Required behavior (tests only, unless they expose a defect): for each ablation arm, a
synthetic window where its switch never binds produces a trace identical to `combined`
(fills, marks, decisions); and one window where it binds shows the expected difference
(continuation: an RSI veto refusal on daily RSI; short qualification: a daily-UNCLEAR
short; trailing: no trail; funding admission: an admitted entry the filter would refuse;
recovery: no restart after cooldown).
