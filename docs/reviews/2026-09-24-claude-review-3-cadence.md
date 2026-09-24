# Claude review 3: frame cadence, checked against PR #6

This follow-up was checked against PR #6 (`claude/review-2-fixes`, fb26f4d). PR #6 was
written in a separate Claude session. It fixes the flapping-feed exit and adds recentering
after an exit. One problem remains.

## Still open: the policy breaks when frames are more than 30 s apart (high)

`maximum_data_age_seconds` (default 30 s) says how old a single frame may be. The runner
also uses it as the maximum allowed gap between consecutive frames. That second use breaks
two checks:

- `runner._step` resets `recovery_count` whenever two frames are more than 30 s apart, so
  a pause can never clear.
- `runner._track_range` counts outside-range time only between valid frames at most 30 s
  apart, so the range exit can never fire.

The repo's own collector cannot poll faster than every 60 s (`market_data/command.py`:
`poll_seconds` must be 60 to 3600), so at every supported cadence both mechanisms are off.

### Reproduction

Open the standard demo grid at 0.02300. Drop the price to 0.0205/0.0206 and hold it there
for 3 days. Fair value follows the price, and all other frames are valid.

| Frame interval | `main` (cf9b952) | PR #6 (fb26f4d) |
| --- | --- | --- |
| 60 s | Paused for all 3 days, holding 3566 units; no exit; `recovery_count` stays at 0 or 1 | **Same** |
| 20 s | Exits after 6 h, then waits in cash indefinitely | Exits after 6 h, recenters after the 24 h cooldown, opens a new grid at 0.01954-0.02155 ✔ |

### Proposed fix

1. Add `SimulationPolicy.maximum_frame_gap_seconds`, for example 180 s against 60 s polling.
2. Use it for both continuity checks: the recovery streak and outside-range accumulation.
3. Keep `maximum_data_age_seconds` for per-frame freshness only.
4. Validate that the gap setting is at least the collector's poll interval.
5. Add regression tests at a 60 s cadence covering pause recovery, the range exit and
   recentering.

This is a small change on top of PR #6. Whoever merges PR #6 first can apply it there.

## PR #6: otherwise agreed

The regime boundary normalisation, the quality veto, accumulated outside-range time and
recentering on by default with a 24 h cooldown all look right to me. The two things to
measure in the backtest are that 24 h cooldown and PR #6's open question: whether
volatility and liquidity health should vote on direction or act as an eligibility input.
