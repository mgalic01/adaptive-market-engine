# Owner decision: V3 equity-change audit tolerance

Index: Owner accepts an absolute 1e-18 USDT tolerance for the equity-change audit
only; wallet and quantity audits stay exact, signed residuals remain evidence.

On 2026-10-08 Codex reported that exact-zero equity-change reconciliation stops
a synthetic weighted-entry round trip on a -1e-59 USDT Decimal rounding residual.
The proposed replacement was an inclusive absolute tolerance of 1e-18 USDT for
that identity only, retaining every residual and leaving wallet and quantity
checks exact. Codex disclosed the downside: a genuine error below that bound
could pass. The owner replied, "ok do it. thank you."

This approval changes only audit acceptance. It does not authorize changing
trading arithmetic, precision, fees, funding, sizing, risk limits, strategy
parameters or A1-A5. Nonfinite residuals and larger differences remain engine
failures. An accepted residual is never set to zero or called exact.

This is a pre-run numerical amendment, not tuning from strategy performance.
The old registered spec hash remains in append-only history. A correction and
replacement candidate registration must pin the amended spec before the new
audit behavior is committed. Completing registration, reviewed data delivery and
the other execution gates still apply; this decision does not launch a replay.

The separate lifecycle-total-to-equity reconciliation in the metrics layer is
not relaxed by this amendment. Any further tolerance needs a concrete proposal.

Implementation evidence: the account exposes `accepted` separately from `exact`;
accepted nonzero residuals never become exact. Runner pre-hour, post-hour and final
audits all use the approved acceptance test and retain their original residuals.
Pre-hour audits are now retained too, including failures. Decimal `copy_abs()`
avoids ambient-context rounding of the bound comparison.

Validation: 79 account/runner/lifecycle/execution/pending synthetic tests pass,
including both signed boundaries, just-outside values, NaN/infinity, exact wallet
and quantity guards, the actual weighted-entry round trip and runner rejection.
Ruff, mypy and append-only trial validation pass. External review and full CI are
pending; these checks establish behavior, not historical profitability.
