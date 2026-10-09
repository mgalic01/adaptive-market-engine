# Frozen V3 criterion checks

Index: Implemented A1-A5 checks on reconciled accounts, matching strategy decisions and actual hold submissions; historical provenance and experiment verdict remain upstream.

A1-A4 use the main m=2 base-cost account: Sharpe >=1, trade profit factor >=1.3,
Calmar >=0.5 and CAGR >=0.08. A5 requires base-cost m=1 Sharpe strictly above
risk-matched spot hold Sharpe on identical samples. All accounts start at 10000
USDT and pass existing accounting checks. Main/m=1 must have complete matching
rule schedules and identical futures filters; spot filters remain separate.

Supplied daily spot history, portfolio-start months and the union of futures/spot
exclusions reconstruct both strategy and hold decisions. Immutable snapshots of
the hold targets/reasons actually submitted at every hour must match those
reconstructed decisions. Artifacts retain these snapshots as spot_input rows.

Review found and reproduced four defects before their fixes: arbitrary cash could
stand in for hold; copied daily metadata could disguise that cash-only execution;
spot-only exclusions were omitted from strategy reconstruction; differing futures
filters could pass. Regressions now reject these cases or accept the correctly
excluded account. Actual nonzero R1/R2 strategy fills and a mid-window pick change
are covered, including rejection of altered strategy signals.

Validation: 45 focused tests across test_trend_acceptance.py,
test_trend_benchmark_comparison.py, test_trend_spot_benchmark.py and
 test_trend_evidence_writer.py pass. The complete trend test selection passed at
356198fbff3eba28ab18e29a832bc32ff8e30ab0, before the additional coverage/doc changes.
Ruff, mypy and Bandit pass. Independent review found no remaining concrete defect
in the execution-receipt and exclusion/filter fixes. Full CI and substantive
external review of the latest full head remain required before merge.

## Limits and remaining integration

This helper does not certify full experiment dates, committed registration,
manifest identity, or completeness/accounting of every other required scenario.
Hourly execution bars, funding, masking and each market's filter snapshot must be
linked upstream to the registered manifest. Checking submitted targets does not
authenticate execution inputs or deliberate private-state manipulation. Futures
and spot use different instruments: their prices and filters must not be equated.

Unknown engine failures abort; invalid criterion accounts are classified by the
enclosing experiment report rather than given fabricated scores. Legitimate
infinite ratios are supported. No whole-experiment verdict is produced here.
No criterion, trading rule, dependency or data-access change. Codex owns remaining
experiment assembly, provenance validation and registration. No historical replay
has run and no historical performance claim is made.
