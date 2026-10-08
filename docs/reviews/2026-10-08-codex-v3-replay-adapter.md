# V3 in-memory window replay

Index: Parsed hourly inputs feed continuous daily decisions, pending fills, funding
and terminal lifecycle accounting; synthetic replay only, no historical dispatcher.

Purpose: connect existing V3 components into a runnable window using supplied data.
Named writer: Codex Desktop. Stacked on daily decisions (#224), not for merge into it.

Each call creates a fresh account and processes every hour, including missing-bar
hours. One call carries that account across all supplied rule-pick dates. Midnight
uses the previous day's closed spot information; fills start at 01:00 or the next
usable hour. Funding groups retain their original millisecond timestamps and are
charged only for eligible portfolio months. Terminal valuation uses the last
consumed in-window close; no later opening price is requested.

Before account creation, pre-exclusion close availability is checked against the
supplied execution-hour inventory. Exclusions before a coin joins the portfolio
create no close obligation. UnavailableClose becomes an explicit invalid outcome
with its evidence; malformed funding or duplicate hourly rows are input errors.
Liquidation and unrestorable leverage stop the loop immediately. Other engine
errors propagate rather than being relabeled as strategy results.

Validation: seven replay tests and 37 replay/decision/exclusion/runner tests pass.
Ruff and mypy pass. Checks cover actual fills and funding, fresh repeated accounts,
missing hours, terminal censoring, unavailable closes, liquidation stopping,
duplicate hours, pre-portfolio exclusions and bad funding not hidden by invalidity.
Full CI and external review remain required.

Input contract: sources must already have passed hashes, monthly funding cadence,
repair/mask checks, portfolio eligibility and spot aggregation. This module does
not read files, fetch data, verify a manifest or authorize dispatch. The historical
loader and registered dispatcher remain mandatory upstream work. The caller must
supply the frozen quarterly picks (or one fixed rule for training); this low-level
routine does not perform selection or enforce the quarterly calendar. Training
orchestration, reporting and benchmark/bootstrap comparisons remain unfinished.
No historical V3 run or profitability claim. No new dependency or known security
finding; all inputs used in validation were synthetic.

Review follow-up: configuration validation now precedes unavailable-close strategy
invalidity. Two regressions first reproduced the misclassification, then passed.
Additional tests prove inherited rejection of non-midnight ends and off-hour rows,
and exercise a pick change that closes an existing position in the same account.
Thirteen replay tests pass. The existing exclusion preflight already enforces the
end boundary and timestamp alignment; these were not missing source checks.
Outstanding coverage includes held positions across exclusion boundaries, terminal
leverage failure at adapter level, and non-flat last-unmasked-close valuation.
Upstream loader must prove funding completeness and first non-excluded eligibility;
absence of funding is not a validated historical zero-cost assumption.
