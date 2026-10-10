# V3 invocation failure and spot filter correction

Index: Failed single invocation preserved; zero spot minimum validation corrected; recovery not authorized.

Codex Desktop → Claude and Bob, 2026-10-10.

Goal: restore faithful implementation of the frozen holding comparison while
preserving the failed experiment and its evidence. This is not strategy tuning.

## Outcome

The single authorized invocation at revision
`4d1e37c0637f8401f3903ea56d036f34c3bfd5cd` ended with exit 1 at
2026-10-10T04:40:37.868874Z. Its 186 futures attempts have completion records with
no recorded execution error. Attempt 187, the primary-cost holding comparison,
failed with `SpotReplayExecutionError: ValueError: positive value required`.
The two remaining comparisons never started. No publication receipt or acceptance
verdict exists. Completed execution is not a claim of profitability or validity.

Small original evidence files and a completion-record census are preserved in
[`../backtests/v3-20261010-failed-invocation/`](../backtests/v3-20261010-failed-invocation/).
The census copies recorded journal hashes; it does not independently rehash the
186 large futures journals. Original artifacts remain on the owner's drive at
`E:/adaptive-market-engine/v3/replay-20261009-01` and logs at
`E:/adaptive-market-engine/v3/replay-logs-20261009-01`.

## Root cause

The committed spot snapshot contains `MARKET_LOT_SIZE.minQty = 0` for ADAUSDT,
BTCUSDT and ETHUSDT (among other symbols). The existing filter parser permits this
nonnegative minimum and uses the LOT_SIZE step when the market step is zero.
Both `SpotAccount.execute` and `SpotAccount.fill` instead required the minimum
quantity to be strictly positive. The first attempted holding purchase therefore
failed before settlement. The failure journal retains initial cash of 10000 and
no holdings. A synthetic order reproduces the same exception in both methods.

The correction allows zero minimum quantity while rejecting negative, nonfinite
or unbounded minima. Maximum quantity and effective step remain strictly positive;
minimum notional, cash affordability, sell ownership, fees and exact reconciliation
remain enforced. No futures logic, parameters, data or acceptance rules change.

## Validation

Baseline spot-account tests: 7 passed. Added tests failed at both affected methods
before the correction. After correction, all 38 spot account, benchmark, evidence
and report tests passed. Regression coverage includes a zero-minimum buy/sell
round trip, minimum-notional rejection and negative-minimum rejection without
state mutation. Targeted lint passed. Full-suite verification and external review
are pending at preparation time.

## Recovery boundary

No historical replay was retried or resumed. The original invocation and inputs
are untouched. This correction alone does not authorize a second invocation.
Before any recovery, prepare a separately reviewed registration and execution
proposal stating whether and how completed futures evidence can be reused, how
the failed attempt remains visible, and which comparisons/calculations must run.
Do not silently combine outputs from different code identities into a completed
original invocation. Obtain explicit owner approval under the one-run/no-retry
restriction. Reserved 2025+ market data and live trading remain prohibited.

Compatibility risk: callers that previously expected zero market minimum to raise
will now settle an otherwise valid order. This matches the existing parser
contract. No new dependencies or known security changes.
