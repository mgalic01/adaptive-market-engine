# V3 profit breakdown by coin and side

Index: Added supplied-lifecycle profit totals by coin, long/short and coin/side, including terminal unrealized PnL and costs; synthetic validation only.

Frozen section 8 requires the long/short split and coin attribution. The new
helper reports count, censored count, realized and unrealized PnL, fees, funding
paid and received, and net PnL. Empty long/short groups remain explicit zero rows.
Snapshots are immutable and arithmetic uses Decimal60/half-even regardless of
the caller's context. Unfinished and nonfinite evidence is rejected.

The caller still supplies the complete reconciled lifecycle list. This helper
does not certify account provenance, detect omitted trades, or issue acceptance.
Fixed-rule reports can label the whole account with its known rule; changing-pick
accounts must not assign a spanning lifecycle's entire PnL to its opening rule.

Seven tests failed for the missing API before implementation. Twenty focused
breakdown/lifecycle tests then passed, including actual synthetic fill/funding
events, censored short profit, empty and zero outcomes and ambient precision.
An independent read-only reviewer reran all twenty and found no actionable issue.
Mypy passes; an import-order lint finding was corrected and lint now passes.
Full CI and substantive exact-head external review are still required.

No dependency, trading behavior, cost or data-access change. No historical
market run occurred. Codex owns the enclosing report assembly and registration.

Review follow-up: Bob and Codex Cloud identified validation and explicit-row gaps.
Seven new failing cases reproduced acceptance of empty-fill lifecycles, malformed
numeric/symbol fields, inconsistent censor reasons and missing zero-side rows.
They are fixed, and expanded coverage of rejection branches brings the focused
breakdown/lifecycle total to 35 passing tests. Lint and mypy pass.
Both sides now have explicit rows for every observed coin. A lifecycle must have
fills and a recognized exit reason consistent with its censor flag.

Per-rule splits will come from the twelve fixed-rule full-period accounts, each
labelled with its rule. This helper supplies those groups when called on each
account; it does not itself assemble that twelve-run report or assign main-run
PnL across changing picks. These limits remain explicit until report assembly.
