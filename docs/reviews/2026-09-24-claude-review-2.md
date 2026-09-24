# Claude review 2: PR #4 (strategy-review fixes)

Reviewed `main` at cf9b952. I checked out the merged code and reran my original
probes against it:

| Check | Result |
| --- | --- |
| Lint (`ruff`), strict types (`mypy`) | Clean |
| Oscillation probe | Now 100 fills and 51 cycles (was 2 and 1). Finding 1 is fixed. |
| Mixed-signal regime (trend 0.10, breadth −0.05, others 0.10) | Now RANGE, confidence 0.73 (was TRANSITION, 0.57). Finding 3 is fixed. |
| Unused float exchange stub, transfer journal, zero-capital guard | Resolved as described |

I agree with `docs/BACKTEST_PLAN.md` and the reordered roadmap. There are two
new issues in the pause and range-exit logic. Both show up only when the time
between frames is longer than the gaps the tests use.

## A. Frame interval above 30 s disables recovery and the range timeout (high)

`runner._step` and `runner._track_range` treat any gap between frames longer
than `maximum_data_age_seconds` (30 s by default) as broken continuity:

- `_step` resets `recovery_count` to 0 before it can reach 2;
- `_track_range` restarts `outside_since` on every frame.

`maximum_data_age_seconds` is a *freshness* limit: how old one observation may
be. It is being reused as a *cadence* limit: how far apart observations may be.
The repo's own collector cannot poll faster than every 60 s
(`market_data/command.py`: `poll_seconds` must be 60 to 3600). So at any
cadence the project actually supports:

- a pause never clears, because `recovery_count` never gets past 1;
- the six-hour out-of-range exit never fires.

Reproduction: open the standard demo grid at 0.02300, then drop the price to
0.0205 to 0.0206 and hold it there for 3 days, one frame every **60 s**, with
fair value following the price. Result: inventory 3566 stuck, the bot paused
for all 3 days (`recovery_count` alternates between 0 and 1), `range_exit`
never becomes true, and 4 fills in total. The same run with **20 s** frames
exits after 6 h as designed.

Proposal: add a separate `SimulationPolicy.maximum_frame_gap_seconds`, with a
default that suits the planned cadence (for example 180 s against 60 s
polling). Use it for both continuity checks. Keep `maximum_data_age_seconds`
for per-frame freshness only. Add regression tests at 60 s cadence covering
both pause recovery and the range timeout.

## B. After a range exit, the bot waits for the old range indefinitely (medium)

After a range exit, trading resumes only if `bid` returns to the old
`[grid_lower, grid_upper]`. In the 20 s run above, the bot exited correctly,
then stayed in cash for more than 60 h at the new, stable price level. It will
never trade again unless the old price comes back. After any lasting crash or
breakout, the strategy becomes permanently idle.

Proposal: keep "no automatic recentring while holding inventory". Once the
account is flat after a range exit, allow a fresh grid at the *current* fair
value after a cool-down. For example: N hours of continuous, eligible frames
inside a new ATR-based band, plus the usual regime and opportunity checks.
Record the old and new bounds in the event report. Treat the cool-down length
as a backtest parameter, not a tuned constant.

## Smaller notes

- `_open_grid` rebuilds at every flat point, so every harvest also recentres.
  That is reasonable, but the backtest should report cycles and turnover so
  fee drag from frequent rebuilds shows up.
- Please confirm the "fresh ineligible frame keeps sells working" path is
  tested at 60 s cadence as well, once A is fixed.

## Suggested next step

Fix A and B with 60 s-cadence tests, then start backtest step 1 from
`docs/BACKTEST_PLAN.md`: data manifest and chronology checks on one or two
pairs. Either assistant can take it. Claude can do A and B on
`claude/repo-connection-mqhoss` (PR #5) if the owner prefers.
