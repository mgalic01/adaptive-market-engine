# Partial V3 futures diagnosis after the holding failure

Index: Hash-checked diagnostics for 18 saved futures runs; primary misses A1–A3; no completed invocation or A5 verdict.

## Scope and conclusion

The original invocation remains failed. These are diagnostics recovered from its saved futures journals, not a new replay or a certified experiment report. The holding comparison failed before settlement and A5 remains unmeasured. The primary saved account misses A1, A2 and A3 on the frozen formulas; another unchanged run is not a strategy improvement. Finish diagnosis before deciding whether a complete repeat is worth its time.

The evaluation window is July 2021 through December 2024, starting with 10,000 USDT. The primary account ends at 13,446.86435 USDT: +34.47% total, 8.82% CAGR, 66.82% maximum drawdown, Sharpe 0.412, trade profit factor 1.235 and Calmar 0.132. It has 342 lifecycles, 97 wins and 245 losses (28.36% win rate), including terminal censored lifecycles. Its trade/equity residual is -7E-56 USDT, within the existing 1E-18 bound.

| Frozen criterion | Required | Primary diagnostic |
| --- | --- | --- |
| A1 Sharpe | >= 1.0 | 0.412: below threshold |
| A2 trade profit factor | >= 1.3 | 1.235: below threshold |
| A3 Calmar | >= 0.5 | 0.132: below threshold |
| A4 CAGR | >= 8% | 8.82%: above threshold |
| A5 matched-size holding comparison | Strategy Sharpe exceeds holding Sharpe | Unavailable |

This does not replace the missing final receipt or assert complete acceptance verification. No liquidation event is recorded for these 18 runs, which is not an estimate of future liquidation probability.

## Complete saved evaluation and diagnostic menu

All percentages below are percentages, not fractions. Fixed rules are reported comparisons, not replacements selected after observing these results.

| Account | Size multiple | Cost multiple | CAGR % | Max drawdown % | Sharpe | Trade PF | Calmar |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Sensitivity | 1 | 1 | 6.81 | 40.29 | 0.443 | 1.301 | 0.169 |
| Sensitivity | 1 | 2 | 5.17 | 41.81 | 0.361 | 1.221 | 0.124 |
| Sensitivity | 2 | 2 | 5.11 | 68.71 | 0.319 | 1.132 | 0.074 |
| Sensitivity | 3 | 1 | 6.79 | 82.78 | 0.397 | 1.143 | 0.082 |
| Sensitivity | 3 | 2 | 1.15 | 84.21 | 0.300 | 1.023 | 0.014 |
| R1 | 2 | 1 | 9.66 | 58.08 | 0.429 | 1.100 | 0.166 |
| R1L | 2 | 1 | 28.64 | 53.59 | 0.892 | 1.771 | 0.535 |
| R2 | 2 | 1 | -13.92 | 75.66 | -0.169 | 0.767 | -0.184 |
| R2L | 2 | 1 | 26.86 | 50.97 | 0.850 | 2.107 | 0.527 |
| R3 | 2 | 1 | -0.97 | 65.30 | 0.168 | 0.982 | -0.015 |
| R3L | 2 | 1 | 19.05 | 53.28 | 0.701 | 1.785 | 0.358 |
| R4 | 2 | 1 | 31.10 | 45.31 | 0.875 | 1.994 | 0.686 |
| R4L | 2 | 1 | 34.90 | 46.46 | 1.017 | 3.906 | 0.751 |
| R5 | 2 | 1 | 11.74 | 50.01 | 0.477 | 1.125 | 0.235 |
| R5L | 2 | 1 | 21.16 | 55.87 | 0.712 | 1.640 | 0.379 |
| R6 | 2 | 1 | 1.84 | 63.64 | 0.248 | 1.026 | 0.029 |
| R6L | 2 | 1 | 21.51 | 54.02 | 0.742 | 1.685 | 0.398 |
| Primary walk-forward | 2 | 1 | 8.82 | 66.82 | 0.412 | 1.235 | 0.132 |

## What the saved evidence shows

- **More size did not produce better compounded return.** At ordinary costs, size 1 has 6.81% CAGR and 40.29% drawdown, size 2 has 8.82% and 66.82%, and size 3 has 6.79% and 82.78%. This is direct evidence against merely increasing leverage for this menu.
- **Short lifecycles lost money in the selected account.** Longs: 236 lifecycles, +7,369.11 USDT net. Shorts: 106 lifecycles, -3,922.24 USDT net. That is attribution, not proof that removing shorts from the selected account would reproduce the same longs or equity path.
- **Costs matter, but maker-fee engineering alone is not the whole answer.** The primary account pays 442.68 USDT in explicit fees and 1,481.82 USDT net funding. Slippage is already embedded in prices and not separately isolated here. At doubled fees/slippage, size-2 CAGR falls to 5.11% and drawdown reaches 68.71%.
- **Selection deserves investigation.** Several fixed long-only comparisons exceed the selected account. R4L reports 34.90% CAGR, Sharpe 1.017 and 46.46% drawdown. This is a hindsight diagnostic across 12 comparisons, not permission to promote R4L or claim it passes A5.
- **Profits are concentrated.** Two of 42 reported months exceed both 20% and 30%: February 2024 (+31.87%) and November 2024 (+60.22%). The mean monthly return is 1.51%, while total growth corresponds to about 0.708% compounded per month over 42 months. The worst month is March 2023 (-19.57%). These are realized historical observations, not monthly targets.
- **Exit attribution suggests a whipsaw question, not a proven cause.** Lifecycles ending in a flip sum to -4,040.31 USDT; signal-zero endings sum to -3,431.07. Attribution assigns each whole lifecycle to its exit reason. It does not measure the counterfactual effect of changing that exit.

## Research implications without changing frozen V3

Prioritize separately specified tests of short-entry quality, selection stability and exposure control over more leverage. Investigate whether repeated direction changes, weak trend persistence or the selection window explain losses. Any future candidate or stop rule needs a new explicit design and preregistration; do not optimize these observed losses away and call that the original V3 result. Keep all 12 fixed comparisons visible and apply the multiple-testing discipline before promoting any candidate.

The broader requested product remains incomplete: a daily trend experiment is not proof of the four-state real-time regime/strategy matrix, IOC/post-only/limit-chase lifecycle, Sortino metric or liquidation-probability model. This report does not implement or certify those capabilities. Nor do 10,000-USDT results prove executable economics at approximately EUR100.

## Evidence and reproduction

[Detailed JSON](../backtests/v3-20261010-partial-diagnostics/futures-diagnostics.json) contains all 18 metrics, every monthly return, and lifecycle attribution by symbol, direction and exit reason. [Extractor source](../backtests/v3-20261010-partial-diagnostics/futures-diagnostics.py.txt) is the exact read-only script used. [Original invocation start](../backtests/v3-20261010-partial-diagnostics/invocation-started.json) and [18 completion receipts](../backtests/v3-20261010-partial-diagnostics/receipts/) retain the original execution identities and recorded journal hashes. The large journals remain at `E:/adaptive-market-engine/v3/replay-20261009-01/attempts`; they are not reproduced by this Git bundle.

The extractor reads no market archives, calls no replay/selection routine, checks each journal byte count, record count and SHA-256 against its receipt, rejects recorded errors or unaccepted accounting audits, rejects active lifecycles, and invokes existing `metrics.summarize` and `monthly.monthly_diagnostics`. The primary journal has 265,149 records, 204,317,679 bytes and 61,441 accepted accounting audits. Those are recorded accounting checks, not an independent reconstruction of all fills. It compares lifecycle net PnL to account growth with the already-approved bound.

The analysis uses the reporting/accounting dependencies from main `242faacc0041a00571902320cae95315bf8c551f`. A Git diff confirmed metrics.py, monthly.py, account.py, runner.py, lifecycles.py and evidence_journal.py are unchanged from original execution revision `4d1e37c0637f8401f3903ea56d036f34c3bfd5cd`. The original code pin was `f622d4b1b6ffe6d92aaf31cb6b194919301af30b`; the source inventory is retained in the invocation start. Directory-to-trial attribution remains an operator-reviewed linkage, not cryptographic authentication.

To reproduce on the owner machine, copy the `.py.txt` source to a separate scratch `.py` file and run it with the existing Python 3.12 environment. It uses the three explicit repository/evidence/output paths near its top; other machines need those paths adjusted and the same original journals and reporting code. Outputs are diagnostic files only; it does not append the trial register. Full all-attempt result-event verification/export is separately in progress; no final publication receipt exists.

## Handoff and recovery decision

Codex → Claude/Bob: independently review the metric reconstruction, units, all comparisons and the limits on causal claims. [The recovery proposal](2026-10-10-proposed-v3-recovery.md) is now conditional on this evidence: defer a full repeat while assessing the value of completing the missing comparisons. A repeat can complete the report after the spot correction, but cannot by itself repair the weak selected strategy. Owner approval is still required for any second invocation. No parameter change, historical retry, reserved-window access or live trading occurred.
