# V2 diagnosis — 8 October 2026

> 2026-10-10 consolidation: Historical evidence preserved from PR #208, whose V2 implementation is superseded. No V2 runtime patch is included here. Schema, implementation and test claims below describe that unmerged branch, not current main. See the [maintained research index](../RESEARCH_INDEX.md).


Publication note: V2 is now closed as failed (#206). This preserves the diagnosis of its scored artifacts; the recommendations below are historical proposals, not authorization to reopen V2 or change the draft V3 spec (#207). PR #208 remains a diagnostic reference pending review.

## Scope and conclusion

Read-only diagnosis of the saved six scored artifacts, with implementation tracing at `9a3f9fa0339e012ea5fb242b80ac6602707f57cd`. No parameters changed, no strategy rerun, no reserved data opened. The full-range evaluation covers 2019–2024. This is a diagnosis of this experiment, not a comprehensive code audit or evidence that a proposed replacement will profit.

V2 failed its drawdown criterion and captured little of the long-run upside. The evidence supports three design weaknesses: recovery controls do not enforce lifetime drawdown, entry conditions leave very little grid participation, and losses on position exits consume substantial accumulated gains. It does not establish a broken liquidation mechanism or prove that removing filters would improve returns.

## Verified outcome

High-first execution path, starting capital 100 per pair:

| Metric | BTC | ETH |
|---|---:|---:|
| Six-year net return | 30.13% | 36.08% |
| Recorded maximum total drawdown | 21.91% | 11.02% |
| Recorded maximum active-capital drawdown | 26.41% | 11.38% |
| Time in Cash mode | 70.28% | 71.85% |
| Time in Grid mode | 2.90% | 2.36% |
| Time in Uptrend mode | 26.82% | 25.79% |
| Uptrend trades | 48 | 51 |
| Completed grid cycles | 31 | 43 |
| Soft-drawdown reference resets | 10 | 9 |
| Hard-drawdown halts | 0 | 0 |
| Recorded blocked-exit frames | 0 | 0 |
| Fees in initial-capital units | 3.38 | 2.68 |

Both execution paths fail the 10% drawdown criterion for both pairs. Low-first returns are 30.29% and 36.89%, so the headline failure is not dependent on choosing one intrabar path. The registered mean of median annual returns was about 4.91%; that is not CAGR.

Independent reconstruction from hourly equity also fails the threshold: BTC 21.82%, ETH 10.52%. These are sampled estimates, not replacements for the higher-resolution recorded maxima. BTC's sampled peak was 21 February 2021 and trough 7 November 2024. BTC year-end equity fell from 147.70 at end-2020 to 130.13 at end-2024, approximately an 11.9% loss across those four years.

## 1. Recovery and lifetime protection solve different problems

At `src/crypto_grid_bot/simulation/runner.py:516`, risk evaluation uses `risk_high`. At lines 559–600, the recovery procedure can lower that reference after the required cool-off and confirmations. It explicitly checks whether risk would ALLOW with the reference reset to current active equity. This is an intentional recovery mechanism, not evidence of an accidental reset.

The test's total-equity drawdown remains measured against its historical high. Repeated recoveries can therefore permit further trading while the account remains well below that high. The observed combination—multiple resets, no hard halts, and failed lifetime drawdown—is consistent with the implementation. Zero hard halts does not establish that no halt would have occurred without resets; that counterfactual was not run.

**Implication:** a recovery rule alone cannot be treated as a guarantee of the registered lifetime risk budget. A future design needs an explicit relationship between lifetime drawdown, active-capital risk, position sizing, and permission to restart. Changing the pass threshold after seeing this result would not repair the strategy.

## 2. Entry selectivity suppresses participation, but missed profits are not quantified

The selector requires aligned daily and four-hour Up states plus daily RSI below 75 and other conditions. Grid entry requires a narrow conjunction of range persistence, trend states, RSI, ADX and width conditions (`src/crypto_grid_bot/strategy/mode_selector.py`).

BTC made 38,579 hourly decisions while not holding an uptrend position: 36,914 Cash, 1,525 Grid and 140 Uptrend. ETH made 39,102: 37,751 Cash, 1,239 Grid and 112 Uptrend. Selections and completed trades are different measures: execution conditions can prevent an entry, an entry can fill later, and trade completion occurs on exit. These aggregates alone do not explain the difference.

BTC sole Uptrend blockers included daily trend (7,033 decisions), four-hour trend (2,619), and overbought RSI (1,110). ETH corresponding counts were 6,782, 1,961 and 248. Counts with multiple blockers overlap and must not be added as distinct missed trades. Consecutive blocked hours are also not independent opportunities.

At `runner.py:1585` onward, entry additionally requires ALLOW, completion of risk recovery, a flat pair, valid stop distance, and an executable buy under cash/risk budgets. Saved aggregate diagnostics do not attribute each selected-but-unfilled opportunity to those conditions. Therefore, “140 selections versus 48 trades” is an observability gap, not proof of an execution bug.

Cash/Grid/Uptrend figures are mode occupancy, not exact capital-weighted exposure: transitional inventory and different position sizes matter. Nevertheless, the tiny grid occupancy and cycle count establish that this implementation rarely operated as a productive grid.

**Implication:** investigate where viable entries disappear. Do not indiscriminately remove filters; the artifact cannot tell us whether the blocked trades would have won.

## 3. Exit losses materially erode gains

Realized accounting contributions per starting 100, high-first path:

| Contribution | BTC | ETH |
|---|---:|---:|
| Grid sell P&L | +4.88 | +8.27 |
| Uptrend exits labelled risk | +65.59 | +51.87 |
| Uptrend stops | −19.56 | −2.53 |
| Uptrend fades | −11.20 | −8.39 |
| Range exits | −9.57 | −13.15 |
| Total, before display rounding | +30.13 | +36.08 |

Final inventory is zero. These contributions reconcile to the final gain; do not subtract fees again. They are accounting labels, not causal estimates or a complete independent return series for each mode.

BTC stop/fade/range exits together lost 40.33 units; ETH lost 24.06. Grid sell proceeds alone therefore overstate the grid's economic success. Grid sells plus range exits total approximately −4.69 quote units for BTC and −4.88 quote units for ETH, although this grouping is not a fully capital-allocated mode return.

An exit labelled “risk” can realize a profitable position after a pullback. That does not mean the risk rule created the profit. Similarly, a losing stop can have prevented an even larger loss. Neither table justifies removing protective exits.

**Implication:** the next useful diagnostic is trade-level excursion and exit attribution: entry context, maximum favorable/adverse excursion, profit surrendered before exit, duration, fees, and exit trigger. Aggregate results cannot distinguish late entries, avoidable whipsaws and necessary loss containment reliably.

## 4. Evidence against two tempting explanations

**Stuck liquidation:** all four full-range MS rows report zero blocked-exit frames and zero final inventory. The traced runner processes stop/fade triggers before the risk action, preserves the first exit reason, and routes exiting inventory to sale paths (`runner.py:881`, `:1444`, `:1548`, `:1034`). This narrows the investigation; it is not a proof covering every possible execution edge case.

**Fees caused everything:** reported fees were only 3.38 BTC-account units and 2.68 ETH-account units over six years. They matter, but are too small to explain the broad return shortfall alone. This is not a fee-free counterfactual: changed costs can alter execution and subsequent state.

The top-level accounting validity warning discussed in the verdict arose from tiny exact-equality discrepancies in an ungated comparator, later addressed by PR #204. The scored MS rows have no accounting problems. That warning does not explain away their drawdown failure.

## Recommended order of work

1. Preserve this failed result and its original acceptance criteria.
2. Add diagnostic-only recording of each entry rejection and each position lifecycle, including risk-reference resets and total/active equity. Verify that this instrumentation leaves strategy decisions unchanged.
3. Reproduce the same frozen development experiment only if the missing diagnostic records require it, clearly distinguishing diagnostic replay from a new strategy trial. Keep reserved data closed.
4. Use those records to identify the dominant loss mechanisms. Specify lifetime risk-budget behavior before proposing more aggressive participation.
5. Preregister separate experiments for trend entry, exit behavior and grid eligibility. Change one hypothesis at a time, assess costs and drawdown together, and reject improvements that rely on taking unacceptable risk.

Adding more indicators, strategies or an AI decision layer now would make attribution harder. Better decision records and a coherent risk objective are the useful next improvements. A future spot/futures system still needs independent evidence; this result cannot justify leverage.

## Sources

- [Claude's scored verdict and artifact manifest](https://github.com/mgalic01/adaptive-market-engine/blob/bb3e8ca/docs/backtests/2026-10-07-spec-v2-verdict.md)
- [Exact scored runner](https://github.com/mgalic01/adaptive-market-engine/blob/9a3f9fa0339e012ea5fb242b80ac6602707f57cd/src/crypto_grid_bot/simulation/runner.py)
- [Exact scored selector](https://github.com/mgalic01/adaptive-market-engine/blob/9a3f9fa0339e012ea5fb242b80ac6602707f57cd/src/crypto_grid_bot/strategy/mode_selector.py)

### Artifact provenance

Raw result files remain in the local evidence collection and the linked GitHub Actions artifacts; they are not committed here. Each link identifies the producing run. Download its result artifact and locate `results.json`. SHA-256 values below were rechecked against the locally downloaded files when publishing this document. Artifact availability is subject to GitHub retention. No market data was fetched for this publication.

| Run | Artifact directory | results.json SHA-256 |
| --- | --- | --- |
| [Actions 37665890228](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665890228) | `backtest-full-range-2017-2024/20261007T210718Z-m0-t0.0009-variant-MS` | `65b39d14e82da723771b31f883674d3d742be5d190651825759022fd828e4a85` |
| [Actions 37665898847](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665898847) | `backtest-full-range-2017-2024/20261007T205040Z-m0-t0.0009-variant-F` | `77bbd2e0fb292ef416979c498634210d4370f1202fd10530f215780194337999` |
| [Actions 37665907336](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665907336) | `backtest-practice-2022/20261007T183713Z-m0-t0.0009-variant-MS` | `cea1859550d92a7f9336e95aca02a10aab3d8094d00f50b69da6a102ba8e4d72` |
| [Actions 37665915836](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665915836) | `backtest-practice-2022/20261007T183253Z-m0-t0.0009-variant-F` | `0e980825e6202e140926f7231838a39d7bb01bdc6b849b07ca8c3ce26da151c9` |
| [Actions 37665924005](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665924005) | `backtest-verify-2024h1/20261007T183229Z-m0-t0.0009-variant-MS` | `d50364327bd8f7e0c31b76578b2139b6af1158a926d7b17b70585fae551b4377` |
| [Actions 37665932069](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665932069) | `backtest-verify-2024h1/20261007T183316Z-m0-t0.0009-variant-F` | `aa750fe4a9af8e1611a03d02fbaa1b574e68f13c9be45b3cfb3fdba1500514dd` |
