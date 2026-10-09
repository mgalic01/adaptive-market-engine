# Frozen V3 criterion checks

Index: Account scorer validates prescribed quarterly picks, reconstructed decisions, actual futures/spot submissions and accounting; experiment certification remains upstream.

A1-A4 use the main m=2 base-cost account: Sharpe >=1, trade profit factor >=1.3,
Calmar >=0.5 and CAGR >=0.08. A5 requires base-cost m=1 Sharpe strictly above
risk-matched spot hold Sharpe on identical samples. All start at 10000 USDT.

The caller supplies expected_picks from the frozen walk-forward selection.
Account calendars must start at a quarter boundary, contain every required
quarterly pick, and match that supplied schedule on every day. The experiment
assembler independently recomputes picks from all twelve training scores; this
account scorer does not authenticate training artifact provenance.

Both futures accounts must have identical filters. All account universes agree;
spot uses its separate filters. Spot/futures exclusion unions reconstruct strategy
and hold decisions. Frozen actual-submission snapshots bind those decisions to
the futures and spot engines and are persisted as strategy_input/spot_input rows.
Futures snapshots precede mandatory exclusion overrides. Nonfinite/invalid target
weights are rejected before retention so partial engine-failure evidence remains
serializable. Trading arithmetic is unchanged.

## Verification

Current focused command selects test_trend_acceptance.py,
test_trend_benchmark_comparison.py, test_trend_spot_benchmark.py,
test_trend_evidence_writer.py, test_trend_runner.py, test_trend_run_report.py and
 test_trend_report_markdown.py: **75 tests pass**. Ruff, mypy and Bandit pass.

Review-driven regressions reproduced arbitrary cash benchmarks, copied spot and
futures metadata, omitted spot-only exclusions, differing futures filters,
unprescribed/non-quarterly picks, and nonfinite target failure-artifact loss.
The fixes reject these inputs or accept the correctly excluded account. Actual
nonzero R1 strategy fills are covered. Full current-head CI and substantive Bob
or Claude review remain required before merge.

## Limits

The scorer does not certify full experiment dates, committed registration,
manifest identity, or all other required scenarios. Hourly bars, funding, masking
and each market filter snapshot must be linked to the registered manifest.
Matching submission receipts does not authenticate those inputs or deliberate
private-state manipulation. Futures and spot use different instruments, so their
prices and filters must not be equated.

Accounting/engine failures abort; known invalid criterion accounts are classified
by the experiment report rather than assigned fabricated scores. Legitimate
infinite ratios are supported. No whole-experiment verdict is produced here.
No rule, dependency or data-access change. Codex owns remaining experiment
assembly, provenance validation and registration. No historical replay has run.
