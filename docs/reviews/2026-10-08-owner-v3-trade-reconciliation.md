# Owner decision: bounded trade-total reconciliation

Index: Owner approved inclusive 1e-18 USDT trade-total residual; raw residual retained.

On 2026-10-08 the owner selected "Approve bounded reconciliation tolerance
(Recommended)" after Codex reproduced a completed synthetic round trip whose net
lifecycle result exceeded account profit by 5e-57 USDT at Decimal60. Equity audits
were accepted, but the separate exact summary check rejected the run.

Replace that exact check with an inclusive absolute bound of 1e-18 USDT. Report
the signed residual rather than zeroing it. Larger and nonfinite values fail.
Trading arithmetic, wallet and quantity identities and performance criteria stay
unchanged. Disclosed downside: a genuine reconciliation error under the bound can
pass. This is a separate approval from the earlier equity-audit amendment.

No historical V3 replay occurred. Commit this spec amendment before replacement
registration and implementation; completing registration is still required.
