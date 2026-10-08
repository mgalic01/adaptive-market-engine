# V3 volatility sizing handoff

Index: Codex implemented consecutive-day returns and frozen V3 volatility/covariance portfolio weights; execution and replay remain outstanding.

Branch: `codex/v3-sizing`, following `codex/v3-signals` (#213).
Spec: `docs/EXPERIMENT_SPEC_V3.md` sections 2 and 5 steps 1â€“3.

## Implemented

`src/crypto_grid_bot/trend/sizing.py` exposes `daily_returns` and `size_portfolio`.
Daily returns require consecutive UTC dates; missing days are never bridged.
Positive finite archive-bounded closes and chronological development dates are
validated. Sizing validates simple returns and excludes future observations from
both statistics, even when the supplied series contains later development dates.

Each active coin needs 60 returns. Its sample volatility is annualized with
sqrt(365), and its raw weight is signal times reciprocal volatility. Excluded or
zero-signal coins receive zero raw weight and do not restrict the common-day set.
Covariance uses the intersection of active coins' returns within the last 60 UTC
days, including the decision date. Fewer than 40 common days makes every target
zero. Covariance is never inverted; singular positive covariance is usable and
zero portfolio volatility produces a flat target.

All arithmetic uses a fresh Decimal context, precision 60 and ROUND_HALF_EVEN.
The matrix product evaluates `(raw^T Sigma) raw` in sorted symbol order. A negative
computed portfolio variance raises an error; no undocumented epsilon or absolute
value changes the frozen arithmetic. The future runner must stop and diagnose this as an engine/numerical failure,
not classify it as a strategy-invalid run or silently replace the result. This
corrects the original handoff wording: §8 reserves strategy-invalid outcomes for
liquidation, unrestorable leverage and required fills that cannot be made.

The volatility target is 0.20*m, followed by per-coin absolute caps of 0.10*m,
then proportional gross scaling to 0.80*m, for the fixed m=1,2,3. Result fields
preserve raw weights, individual volatilities, common days, estimated portfolio
volatility and the reason for an all-zero target.

## Verification and limits

30 sizing tests and 13 signal tests pass locally. Initial APIs failed their tests
before implementation. Tests cover exact simple returns, gap omission, 59/60
history, 39/40 overlap, old returns outside the covariance calendar, excluded/zero
signals, singular and zero covariance, all caps/multiples, prefix consistency,
ambient Decimal context and invalid dates/values. A symmetric return fixture has
sample variance 15/59; high-precision independent calculations supply its expected
annual volatility and target. Ruff and mypy pass. Full CI and independent reviews
are separate, pending at this writing.

No market data was read or fetched; only synthetic fixtures. No dependency, legacy
strategy, exchange endpoint, configuration parameter or frozen-spec change.

This is the target-weight layer only. Band checks, rounded quantities, order
splitting/refusals, reductions, account/funding/liquidation chronology, WFO and
analytics remain to implement. No replay can start until reviewed data and code
are pinned in the completing registration event. Additional regimes and strategy
families remain separate future experiments; this does not complete the owner's
broader bot objective or demonstrate profitable returns.
