# V3 continuous signal implementation

Index: Codex implemented the frozen twelve-rule signal menu with continuous state and Decimal precision; synthetic tests only, sizing/execution and external review pending.

Branch `codex/v3-signals` follows the data integration in PR #212. It adds only
`src/crypto_grid_bot/trend/signals.py`, its synthetic tests, plan and this handoff.
The frozen spec and existing strategies remain unchanged.

## Behavior

`SignalState.update(Kline)` consumes one eligible spot daily bar in chronological
order. `signal_series` produces immutable points from the whole series; replay
windows should reuse that series rather than reinitializing signals.

- R1 uses50 closes including the current close. R2 seeds each EMA from its first
  n closes and waits for55 closes before emitting its comparison.
- R3 uses55 prior bars for breakout/reversal, then20 prior bars for exits. Equality
  does not break a channel. Reversal takes precedence over an exit.
- R4 uses the last available close on/before365 calendar days earlier, refusing
  a reference more than7 days stale.
- R5 seeds ATR from10 true ranges at bar11, applies Wilder updates, trailing final
  bands, and strict reversal comparisons in the frozen order. No missing day update.
- R6 averages all five signals, counting warming rules as0. Long-only versions
  clip each completed base rule; R6L clips after blending.
- Each update uses an explicit60-digit ROUND_HALF_EVEN Decimal context. Input dates,
  OHLC order and archive-compatible numeric bounds are validated before state changes.
  Missing dates retain state; reserved daily dates are refused.

Signal points expose SMA/EMA/ATR/band diagnostics for later decision records. They
do not place orders or apply portfolio exclusions. The future decision/account layer
must enforce no-bar/no-order behavior, mandatory closes, sizing and funding chronology.

## Verification

13 signal tests pass;114 combined signal/data/inventory tests pass. Repository Ruff,
format, mypy (76 files) and Bandit pass. Tests were developed failing first for each
rule family and numeric-bound handling. Golden Supertrend cases use hand-computed
ATR/band values and two reversals; EMA precision was checked with independent
Decimal Context operations after correcting an overlong expected literal.
Prefix stability, recursive-state continuity across gaps and caller Decimal-context
independence are covered. No market archive, backtest result or parameter tuning.

An independent Codex reviewer found no actionable issue at
755f528c26f54177dd4aa9d65382808bde0e16c7. Besides the13 tests, its separate synthetic
oracle matched all signals and diagnostics over1,500 gapped bars, including hostile
ambient Decimal settings and prefix replay. This covers signals only, not sizing,
execution, portfolio exclusions or performance. External exact-head review and full
CI remain pending. Codex owns this branch and subsequent sizing/account integration.
