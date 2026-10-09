# V3 experiment diagnostics assembly

Index: Assemble the complete supplied futures/fixed-rule/spot menus, audited quarterly selections, intervals and published D comparison; historical certification remains explicitly unavailable.

## What changed

The report requires exactly six futures accounts (m=1/2/3 at base/double cost),
twelve fixed-rule accounts, both risk-matched spot costs and every quarter's
complete twelve-score training menu. It checks frozen calendar coverage, account
settings/filters, prescribed decisions, submitted inputs and effective runtime
exclusion overrides (including every sensitivity and fixed-rule account). Selection is
recomputed, including tie order and all-invalid quarters. Monthly portfolio coin
counts and long-only pick frequency are explicit.

All futures results pass the existing accounting/lifecycle report builder. Spot
results pass cash/quantity audits and completed-sample/path validation. Unknown
or engine-failed outcomes abort. Known invalid accounts retain partial costs and
risk diagnostics without completed metrics. An invalid main or base m=1 account suppresses
criterion scoring; a diagnostic m=3 invalid account does not. No experiment verdict
is issued by this descriptive API, including when all account checks pass.

JSON retains exact decimals. Markdown shows comparison tables, training scores,
monthly/economics/cost/risk/coin-side details, minimum-capital scaling and the
main/m1/hold bootstrap intervals. Existing frozen bootstrap arithmetic is reused;
its seed resets independently for each series. Fewer than 60 returns gives no
interval. Published variant D numbers are quoted from the pinned v1 stage-1
report, not rerun; the differing windows and engine are disclosed.

Spot fills now retain their unslipped open price; exact signed fill quantity times
the slipped/open price difference reports slippage for both buys and sells, at
base and doubled costs. It is already in net PnL and is not deducted again.
Spot comparison tables include slippage and gross traded notional alongside fees.
An invalid main account has no full-period capital estimate: its later intended
orders are unknowable. The report explicitly distinguishes this from a completed
account with no intended opening.

## Evidence

Missing-API tests failed before each component was implemented. The 56 focused
tests in selection_report, spot_report, experiment_report, spot_account and
evidence_writer now pass (32 are in the three new report test files).
They include a real synthetic 2024-Q4
all-flat replay menu, missing/extra scenarios, wrong rule/size, truncated evidence,
wrong picks, duplicate scores/run IDs, poisoned accounting and real synthetic
funding-triggered liquidation at m=1/m=2/m=3. Review regressions reproduced missing
spot slippage, an incorrectly described invalid-main capital estimate, and a
mismatched runtime exclusion calendar in a sensitivity account before correction.
Integration tests substitute cheap
bootstrap intervals to check wiring; the bootstrap module's separate tests cover
its actual 10,000-resample method. No market data was read or downloaded.

Ruff and mypy pass. Independent read-only review found no actionable defect in
the stated descriptive scope. Full CI and substantive current-head Bob/Claude
review remain required before merge. This branch incorporates PR238 and must
follow that PR into main.

## Outstanding dependencies

This is not the historical dispatcher. Training artifacts/failed-attempt history,
registered hourly bars/funding/masks/filter snapshots, completing registration and
code/manifest/trial linkage still need validation before a historical verdict.
The full-size buy-and-hold diagnostic awaits the owner's missing-first-purchase-bar
decision. The report names these prerequisites and leaves verdict null; it does
not infer that matching in-memory symbols establish input provenance.

Codex owns remaining integration. The owner chooses storage and the missing-bar
rule, and starts the separately reviewed Bob data task. Existing archive/input
retention constraints remain. No dependency, strategy, criterion or live-trading
change is introduced.
