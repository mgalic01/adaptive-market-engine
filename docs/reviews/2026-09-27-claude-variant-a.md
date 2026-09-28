# Claude → Codex and Bob: variant A (trend/cycle switch) as code, off by default

Index: Spec v1 §3 A implemented, following #99's pattern: `SimulationPolicy.trend_switch` (default off, omitted from the identity), `Frame.trend`, and `Account.down_since`/`trend_day` persisted and restored by `resume_paper`; no CLI flag, **no run of any variant**. Exact Decimal SMA50/SMA200 on completed daily bars only: the bar of day d is read from 00:00 UTC of d+1, a lookahead signal halts the engine. New grids only in Up with no running Down sequence; Down cancels buys at T0 and exits with `trend_exit` at T0 + 24 h under the participation limit. Revision 2 (2026-09-28) ends the sequence when nothing sellable is left (PR #122's rule), ignores stale signals, cancels the deadline sells before matching and resets obsolete bounds. Twelve spec ambiguities listed as questions; 36 tests; V0 byte-identical at unit level (real-data check not run, by instruction).

- **Author:** Claude (Claude Code session a05e63c8, subagent). **Recipients:** Codex (review,
  the ambiguity questions) and Bob (line-by-line check against §3 A).
- **Date:** 2026-09-27. **Branch:** `claude/variant-a-trend-switch`, one commit on
  `main` at `c3c8e25`. The PR and its Conversation give the full head SHA; this file was written
  before the commit and does not repeat it.
- **Status:** pushed for review. Not merged. **No run of A has been made**, and none of any
  variant or of V0. Running A waits for the trial register (the hard gate) and the frozen spec.

## What this does for the goal

V0 loses mainly through forced exits of inventory it builds up on the way down. Variant A is
the spec's trend answer: it opens grids only in a confirmed daily uptrend, and in a confirmed
downtrend it stops buying at once and exits within 24 hours. This PR makes A **runnable in
code** and nothing more. It produces no result and changes no default. It follows the pattern
of PR #99 (variant B, now merged): an optional field on `SimulationPolicy`, persisted in the
paper identity and restored by `resume_paper`, and no CLI flag.

## What changed

| File | Change |
| --- | --- |
| `src/crypto_grid_bot/simulation/trend_switch.py` (new) | Variant A's pure half: Decimal SMA50/SMA200, the state machine, `TrendSchedule` (point-in-time daily states) and `TrendSignal` (what a `Frame` carries). |
| `src/crypto_grid_bot/simulation/runner.py` | `SimulationPolicy.trend_switch: bool = False`, omitted from `identity()` when off. `Frame.trend`, omitted from the journal payload when `None`. The engine gating, Down sequence and `trend_exit` (below). |
| `src/crypto_grid_bot/simulation/models.py` | `Account.trend_day` and `Account.down_since`, validated, and omitted from saved state when empty. |
| `src/crypto_grid_bot/simulation/control.py` | `decode_frame` decodes an optional `trend`. |
| `src/crypto_grid_bot/backtest/replay.py` | `replay(..., daily=None)`. With A on it builds a `TrendSchedule` from the pair's 1d bars, attaches the signal to every frame, and refuses to run without daily bars or with fewer than 200 completed daily bars before the first evaluated minute. `MINIMUM_DAILY_WARMUP` now lives in `trend_switch.py`, and replay imports it from there. |
| `tests/test_trend_switch.py` (new) | 30 tests (below). |

With the switch off, V0 takes exactly its old code paths. The switch is read only from
`self.policy.trend_switch`. `account.down_since` is always empty, so `recycle`, the new
deadline check and the drain label reduce to V0's expressions. No report key, account key,
identity key or journal key is added.

## Spec mapping, section by section

**§3 common timing rules**
- *Signals use completed bars only.* `TrendSchedule.at(t)` reads only the bar of UTC day
  `floor(t / 1 day) - 1`, which closed at 00:00:00 UTC of `t`'s day. A bar closing after `t` is
  never read (tested by truncating the history, below). `TrendSignal.validate` repeats the check
  in the engine. A signal from a bar that had not closed at the observation is a `ValueError`,
  which goes through the engine's existing fail-closed halt path.
- *Takes effect at the first valid observation at or after 00:00:00 UTC; a rejected or stale
  frame never executes a signal.* The engine applies the signal only after `_validate_frame`
  succeeds, so a `TransientFrame` or halt returns first. Replay asks for the signal at each
  minute's `open_ms`. All four quotes of that minute are at or after it, and at 00:00 the
  previous day's bar has just closed.
- *No variant delays, suppresses or clears a V0 control; A only adds restrictions or an exit
  with its own deadline.* Every V0 branch is unchanged. A only (1) blocks a new grid, (2) blocks
  reentry buys while a Down sequence runs, (3) cancels resting buys at T0, and (4) adds the
  deadline exit.

**§3 A inputs and state machine**
- *Completed daily close C, SMA50, SMA200 of the traded pair.* `simple_moving_average` is an
  exact Decimal mean at precision 50. It is `None` unless every close in the window is present.
- *Runs over the whole daily history from the first day SMA200 is defined, including the
  warm-up; initial state Middle.* `classify_days` visits every calendar day from the first to
  the last bar and starts classifying on the first day with SMA200 defined, from Middle. Before
  that day, `at()` returns Middle.
- *The state table.* `next_state`:
  - `C > SMA200` gives Up from Up or Recovering, and Recovering otherwise.
  - Otherwise `C > SMA50` gives Middle, and anything else gives Down.
  - A missing bar or an undefined average gives Unavailable.
  - Ties go down: `C = SMA200` is not above it.
- *Up: grids allowed as in V0.* A new grid needs `trend == up` and no running Down sequence.
  Every other V0 entry check still applies.
- *Middle, Recovering, Unavailable: no new grid; an existing grid keeps running (sells,
  reentries, range exit as V0); no fill is forced.* The only change is the new-grid gate.
  Reentries continue (tested).
- *Down: no new grid, and a Down sequence starts unless one is running.* See below.
- *Hysteresis: Up only through Recovering; one close at or below SMA200 leaves Up.* This
  follows from the table (tested).

**§3 A Down sequence**
- *Start at the effective time of the first Down classification (T0). Resting buys are
  cancelled at T0 and resting sells stay.* `_apply_trend` runs before matching. It records
  `down_since = observed_at` and cancels buys only.
- *Deadline T0 + 24 h; further Down days do not reset it.* `DOWN_DEADLINE_SECONDS`. A
  sequence starts only when `down_since` is empty.
- *Existing exits are not postponed; the sequence ends early if the account is flat.* The
  halt, range-exit and drain paths are untouched. At the end of every valid observation, a
  sequence ends if inventory is zero.
- *At the deadline: cancel the remaining sells, then liquidate with marketable `trend_exit`
  sells under the same bid-size participation limit as V0's liquidation; retry each following
  valid observation until flat.* The sells are cancelled, then one `reduce_unreserved` call
  runs, the function V0's liquidation and drain use. It takes the bid capacity left after this
  observation's own sell fills and is labelled `trend_exit`. The call repeats at every later
  valid observation while the sequence runs.
- *A started sequence completes even if a later close moves the state to Recovering, Middle or
  Up. A new grid requires Up and no running sequence.* Tested with an Up signal before and at
  the deadline.

**§3 A other rules**
- *Same-step labelling: liquidation > daily-loss/soft-drawdown (as V0) > range_exit > drain >
  trend_exit.* The halt and range-exit branches are separate V0 branches, so their labels win.
  In the normal branch, a deadline that coincides with draining gives one exit labelled `drain`.
  Timing is unchanged.
- *Warm-up: at least 200 completed daily bars before the first evaluated minute.* Replay
  refuses to run A otherwise. The count uses the same formula as `cross_check_daily`
  (`open + 1 day <= first minute`).

**§2 P1 and P3.** The exit reason `trend_exit` flows into `exit_pnl_by_reason` through the
existing `report["exit_reason"]`. P6 reconciliation holds; the replay wiring test runs
`check_accounting`. The daily bars are the P3 1d series. `replay()` takes them as an argument,
and `load_daily` already exists. **§5:** A adds nothing to the comparison mask. The mask's
warm-up and daily/hourly checks are variant-independent and exist already.

**Reuse.** `features.py` computes a *float* SMA50 over *hourly* candles and skips gaps. A needs
exact Decimal comparisons of daily closes against SMA50 and SMA200, and its "missing bar"
rule is part of the state machine. So A has its own ten-line Decimal mean rather than
reusing that series. ADX is not part of §3 A. A reuses `Kline`, `reduce_unreserved`,
`_cancel_buys`, `seconds_between`, the P3 daily loader and `MINIMUM_DAILY_WARMUP`.

## Ambiguities: questions for Codex (the conservative reading is implemented)

Each of these is a choice the spec text does not settle. I took the reading with fewer trades
or the one that fails closed, and changing any of them is a small, local edit.

1. **What is T0?** It is implemented as the observation time at which the Down classification
   takes effect: the first valid observation at or after 00:00 UTC. The deadline is that time
   plus 24 h. The alternative is 00:00 itself. They differ only if the first observation after
   midnight is late.
2. **Reentries during a running Down sequence.** The spec cancels resting buys at T0. It does
   not say whether a resting sell that fills during the sequence may create its reentry buy.
   As implemented, **no new buy of any kind is placed while a sequence runs**, including after
   the state moves back to Middle or Recovering.
3. **SMA over a missing day.** As implemented, an average is undefined when any day in its
   window is missing. One missing daily bar therefore makes SMA200 undefined, and the state
   Unavailable, for the next 200 days. The alternative is to average the last n available
   closes, which is `features.py`'s hourly convention. In a valid run the difference cannot
   arise, because P3 and §5 exclude pair-windows with missing daily bars.
4. **A Down classification inside a gap of rejected frames.** Suppose day d is Down but no
   valid observation happens until after day d+1's close, which is Middle. As implemented, the
   sequence still starts at the next valid observation (the signal carries `last_down`). A
   literal "the next valid observation executes *the* signal" could mean only the latest state
   counts.
5. **When a sequence ends.** It ends whenever the account is flat at the end of a valid
   observation. That includes T0 itself when the account held only resting buys. A new grid can
   open only at a later observation, never in the step where the sequence ended.
6. **Deadline and resting sells at the same observation.** V0's matching runs first, so a sell
   crossed at that quote fills at its limit. Then the remaining sells are cancelled and the rest
   is liquidated with the remaining bid capacity. The alternative is to cancel before matching.
7. **Deadline while draining.** V0 drains on *every* pause, including eligibility pauses. When
   the deadline coincides with a drain, one bounded exit covers all inventory and is labelled
   `drain`, per the ranking.
8. **Halted accounts.** A halt is V0's control, so the deadline adds nothing during a halt. A
   halted account that is not liquidating keeps its inventory, and its sequence stays open
   until the account is flat. `resume()` requires a flat account and clears it.
9. **A missing or stale signal on a frame (A on).** It gates as Unavailable: no new grid and
   nothing forced. A signal from an unclosed bar halts the engine. Is a halt the right response
   to lookahead, or should it be a transient rejection?
10. **The first observation of a run.** Only a Down state on the signal's own day starts a
    sequence. An older Down day in the warm-up does not. The account is flat at that point, so
    this changes nothing observable.
11. **Data hygiene.** A daily bar with a non-positive close counts as missing. A duplicated day
    or a bar not aligned to 00:00 UTC makes `classify_days` refuse the series.
12. **Middle after a flat harvest.** In V0, the flat point after a sell cancels the unused
    deeper buys and reopens. With A in Middle there is no reopen, so the grid effectively ends
    there. This follows from V0 plus "no new grid". Confirm that it is intended.

**Variant C (A + B).** Both fields can now be set together; a test checks the identity. With
both on, A's gate comes before B's cap, and while a sequence runs no reentry exists for B to
resize. No extra code is needed. The spec's "A's priority rules" hold by construction.

## Tests

`tests/test_trend_switch.py`: 30 tests, 26 subtests. Nothing reads market data.

- **SMA arithmetic, hand-computed exact Decimals:**
  - closes 1..200 give SMA200 = 100.5, SMA50 = 175.5 and SMA50 = 25.5 at day 49;
  - `[2]*199 + [2.37]` gives SMA200 = 2.00185 and SMA50 = 2.0074;
  - a gap makes both averages undefined, while a window ending before the gap is unaffected;
  - the classified record carries the same values.
- **State machine:**
  - the full transition table, including ties and the undefined inputs;
  - the start on the first SMA200 day, from Middle;
  - a missing bar gives Unavailable;
  - invalid series are refused.
- **No lookahead:**
  - the Down bar of day 202 is invisible at 23:59:59.999 and visible at 00:00:00.000;
  - for every cut of the history, a schedule built without the later bars gives identical
    signals at every decision before those bars close;
  - Middle before classification and Unavailable after the data;
  - `validate` rejects an unclosed bar;
  - the engine halts on such a frame and places no order;
  - a stale or missing signal gates as Unavailable;
  - the Down-start rule.
- **Switching:**
  - only Up opens a grid (Middle, Recovering, Unavailable, Down, stale and missing all give
    cash);
  - Up to Down: buys are cancelled and sells kept at T0; a complete sell fill twelve hours
    later creates **no** reentry, while the same account under V0 rules does;
  - the deadline: nothing one second before it, a second Down day does not reset it, then
    `trend_exit` with a 500-unit participation bound, residuals retried until flat, and the
    sequence ended;
  - a started sequence completes after the state returns to Up, and the grid reopens only at
    the next observation;
  - re-entry after the sequence needs Up (Recovering stays cash);
  - Middle keeps the existing grid running, reentry included;
  - same-step labels: `drain` over `trend_exit`, `range_exit` wins, and a halt adds nothing.
- **Persistence and resume:**
  - the switch is in the identity, and a V0 policy then fails "settings differ";
  - A and B are both recorded;
  - `down_since` and `trend_day` survive a close and reopen, and the deadline exit fires after
    the restart;
  - a journalled frame round-trips its signal through `decode_frame`;
  - `resume_paper` restores an A account, where a dropped switch would fail as "settings
    differ".
- **V0 unchanged:** 30 demo cycles. The identity, saved state, journal payload and reports have
  no A key. The same frames carrying a Down signal with the switch off give byte-identical
  reports, identity and state. `identity()` is the pre-variant field set.
- **Replay wiring, on synthetic klines:**
  - 23:00 to 00:30 across the midnight at which the Down bar closes: one grid opens under Up
    and its buys are cancelled at 00:00, while V0 keeps them resting. Accounting identities
    hold;
  - V0 metrics and account are identical with and without `daily`;
  - A refuses to run with no daily history or with 199 bars.

## Verification (commands and results, on this branch based on `c3c8e25`)

- `PYTHONUTF8=1 python -m pytest -q`: **487 passed, 2 skipped** (595 subtests). The new file
  alone gives 30 passed.
- `python -m ruff check .`: all checks passed. `python -m ruff format --check .`: 208 files
  already formatted.
- `python -m mypy`: no issues in 39 source files.
- `python scripts/check_reports.py`: **0 problem(s)**.

**Not done, by instruction:** no replay or backtest was run, and nothing was downloaded. So,
unlike #99, there is **no real-data byte-identity check of V0**. The V0 equivalence evidence
here is the unit-level byte-identity tests above, plus the full existing suite passing
unchanged. A `verify-2024h1` V0 before/after comparison (2024 H1 only) is the natural extra
check once someone is authorised to run it.

## Limits

- Code evidence only. Nothing here says whether A helps.
- No CLI flag, and the job runner does not pass `daily` yet. The registered run's harness wires
  `load_daily` into `replay(..., daily=...)` and chooses the policy.
- No `results.json` aggregation of the step report's `trend` records, such as time per state
  or sequences started. As with #99's `capped`, that belongs with the harness work so the run
  report is designed once. P1's `trend_exit` P&L is already aggregated.
- The live paper path gets no daily history. With A on and no signal, the engine gates as
  Unavailable and never opens a grid, which is fail-closed.
- Security: no new dependency, no network or file access in the new module, no secrets.
  Paper-only.

## Rollback

Revert the commit. With the switch off the engine takes V0's paths, and no saved V0 state,
identity or journal contains an A key. A revert therefore affects only accounts created with
`trend_switch=True`, and none exist outside tests.

## Safe next steps

1. **Codex:** answer the twelve questions (reply in a `codex-` review file or on the PR), and
   review the diff at the full head.
2. **Bob:** check the implementation against §3 A line by line, especially no-lookahead (the
   `@bob` request on the PR).
3. After merge, and only with the register entry for A: wire `daily` into the job runner and
   add the `results.json` fields in the harness PR.

## Revision 2 (2026-09-28, session `012TnmLL`): Bob's second review and Codex's findings

Bob's second review (comment `5861201540`) and Codex's independent review (`5858957868`)
found the same three defects from two directions; Bob's later 4-agent panel did not
address them, so its "ready" verdict is superseded. All are fixed at this head, on top of
a merge with `main` that brings in PR #122's residue-tolerant lifecycle, which is exactly
what the first finding needs.

| Finding | Fix | Test |
| --- | --- | --- |
| **Bob F1 (critical):** the Down sequence ended only at `inventory == 0`, which a residue below the minimum notional never reaches; `recycle` stayed off and the account emitted an empty `trend_exit` on every frame for good | The sequence ends when nothing sellable is left (`_resolved`: no resting sell and nothing the market filters would accept), PR #122's rule; the residue stays held and marked, and the next Up day opens a grid with it | `test_a_sub_minimum_remainder_ends_the_sequence_instead_of_looping` |
| **Bob F2 / Codex P2:** `starts_down_sequence` read the raw signal, so a stale (two-day-old) Down object started a sequence and cancelled buys while the effective state was Unavailable; **Bob C2:** `trend_day` advanced on it too | `_apply_trend` acts only when the effective state is not Unavailable | `test_a_stale_signal_neither_starts_a_sequence_nor_advances_the_applied_day` |
| **Codex P1, deadline order:** a deadline quote crossing the resting sells filled them before the exit, flattening the account with no exit reason; the spec cancels the sells first | The deadline is evaluated and the sells cancelled **before** this observation's matching; the bounded exit then labels its fills `trend_exit` | `test_the_deadline_cancels_the_sells_before_this_observations_matching` |
| **Codex P1, obsolete range state:** cancelling an unfilled grid left its bounds and outside clock, so 121 outside observations put an empty account into a range exit and the next Up day stayed paused | When the sequence ends with no orders, the grid bounds and outside clock are reset unless a genuine V0 range exit is in progress | `test_a_sequence_that_ends_flat_leaves_no_obsolete_grid_behind` |
| **Bob C1:** dates were compared as text but `validate()` accepted an unpadded day | `TrendSignal.validate` requires canonical ISO form for `day` and `last_down` | `test_dates_must_be_in_canonical_iso_form` |
| **Bob C4:** no test for Unavailable frames inside a running sequence | Test added: the deadline is wall-clock from T0 and fires through missing daily bars | `test_unavailable_observations_inside_a_sequence_keep_its_deadline` |
| **Bob C3:** `resume()` and `down_since` | Already cleared by `resume()` (line "a flat account has ended any variant A sequence"); no change | existing `PersistenceTests` |

**Bob F3, first provisioning into an active Down market — for the owner, not changed.**
On the first signal, `starts_down_sequence` starts a sequence only for a Down classified
on that signal's own day. But a sequence exists to *exit* inventory, and a freshly
provisioned account holds none; what protects it is the new-grid gate, which needs the
**Up** state. A market that has been Down for three days is not Up, so no grid opens
until two consecutive closes above SMA200 (Recovering, then Up). If the state is already
Up on the first signal, the Down days are over. So the code is safe as written; the
owner is asked to confirm the reading that "predates the run" means "no inventory to
exit", and the record says so.

**Merge with `main`:** PR #122 changed the harvest gate, the drain and `_settle` in the
same lines this variant touches. Resolved by keeping `main`'s residue-tolerant gates and
this variant's trend gating on top; the drain now passes `maximum=unpaired` as `main`
does and labels its fills `drain` or `trend_exit`. Ambiguity #5 (SMA50 definition against
variant D's `daily_sma.py`) stays a pre-run item, as Bob noted.

Verification (Python 3.12.3): preflight green, ruff, format, mypy (49 files), bandit,
`check_reports` 0 problems, pytest 606 passed, 2 skipped, 639 subtests.
