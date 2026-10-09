# V3 supplied-input experiment runner

Index: Codex connects the frozen replay menu and durable attempts to the combined report; historical dispatch remains gated.

## Purpose and change

The individual V3 replays and reports existed but no single function connected
them. `trend.experiment_runner.run_experiment` now selects once, uses those picks
for five sensitivity accounts, runs the twelve fixed-rule accounts, and runs
base/double-cost risk-matched spot holds before assembling the existing report.
Each attempt uses the existing durable recorder. Market-specific hourly data and
filters remain separate; both decision sources use the union of exclusions.

The output directory must be new. Exceptions abort without retries or report
assembly, retaining already written evidence. A new directory is not permission
to rerun a registered experiment. Known strategy-invalid accounts remain visible
under the existing replay/report behavior.

## Verification

Six new tests first failed because the runner did not exist, then passed.
The combined focused run covered 49 tests: experiment runner, experiment report,
orchestration and evidence writer. Ruff and focused mypy passed. A separate
read-only Codex reviewer found no actionable defects; this does not substitute
for the required current-head Bob/Claude review.

## Limits and handoff to Claude / Bob

Inputs must already be validated and authorized by the caller. There is no CLI,
data fetch, registration certification, result-register append or final verdict.
Full-size hold remains pending the owner's missing-first-purchase-bar decision.
No historical data was accessed. No new dependency, trading rule or known
compatibility change. The wrapper retains the existing account objects through
report assembly; historical memory/storage capacity still needs operational
validation before dispatch. This is the connection layer, not a completed
historical experiment.
