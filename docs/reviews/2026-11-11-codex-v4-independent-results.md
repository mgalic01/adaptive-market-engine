# Codex: independent review of V4 registered run 42953425248

Index: 2026-11-11. Independent local verification of V4's FAIL: all eight conditions reproduced from saved summaries, 750 archive files checked, economics reconciled across 66 non-V3 cells, and actual target-book volatility measured. Claude discussion and executed-holdings risk review remain open; no new strategy or run is authorized

Written by Codex Desktop at the owner's request to follow the V4 run and review its results with
Claude. This continues the [pre-run handoff](https://github.com/mgalic01/adaptive-market-engine/pull/305#issuecomment-6783658317)
and [Claude's agreement](https://github.com/mgalic01/adaptive-market-engine/pull/305#issuecomment-6783798456).
PR #305 is merged, so discussion belongs on this open follow-up.

This file contains aggregated findings and fingerprints, permitted by v4-d29. Original result
files and derived daily series remain on the owner's PC. It does not replace Claude's result
event, verdict record or archive entry under step 12 of the approved plan.

## Verdict and provenance

The [registered workflow](https://github.com/mgalic01/adaptive-market-engine/actions/runs/42953425248)
completed on its first attempt at 2026-11-11 05:57:09 UTC (06:57 Zagreb). All 72 cells completed,
and the verdict and analysis jobs succeeded. The experiment's verdict is **FAIL**: condition 4
fails at both judged capitals. Conditions 1, 2 and 3 pass at both. The 100-USDT cells are
reported only and do not change this verdict.

- Dispatched commit: `58aad6f32dd20a932d00f1ef57768fa521559e17`.
- Registered code pin: `40e5ba8cad74c07083bf7583d2a3e7e1a7b017cb`.
- Registration SHA-256: `2309be5a8cc5e44e9cfd4adc2d01880c902e88b556e1c1cb434db6c9681d42fe`.
- Local archive: `/mnt/backups/v4-run-42953425248/`.
- `verdict.json` SHA-256: `520691853931afb626af155a3d4cf88a89db4ea850ade4835139c06dd863e765`.
- `diagnosis.json` SHA-256: `9db54c6d8ccba5b1536dcb64bbcd48aaa4d777285044e2971476239df49aa797`.

Codex ran `sha256sum -c --quiet SHA256SUMS.txt` at the archive root: exit 0, all 750 listed files
checked. The 150 zip hashes in that manifest equal the archive's recorded GitHub digests. A live
API cross-check matched 104 artifact IDs/digests; this was a partial listing while artifacts were
being removed, not an independent full inventory. GitHub subsequently listed zero remaining
artifacts. Codex did not download or delete them and did not independently observe the disk
remount required of the archiving owner.

All 72 accepted summary hashes and their receipt hashes matched. Expected cell IDs and data pins
matched the committed registration/manifest; missing, refused, rerun and extra-dispatch lists
were empty. An independent Decimal calculation reproduced all eight conditions from the saved
equity marks, including their common-hour intersections and skipped-hour lists. It did not
replay any strategy. For conditions 1 and 2, measure comparisons agreed within `1e-50`.

| Condition | 1,000 USDT | 10,000 USDT |
| --- | --- | --- |
| 1: normal-cost return/drawdown greater than universe hold | 4.0554 > 0.4820 | 4.0116 > 0.4718 |
| 2: normal-cost common-period return greater than V3 | 44.48% > 34.57% | 43.19% > 34.53% |
| 3: doubled-cost final equity greater than initial equity | 2,132.44 > 1,000 | 21,124.84 > 10,000 |
| 4: normal-cost final equity greater than 2025-01-01 equity | 3,358.85 < 3,964.58: fails | 33,342.14 < 39,082.75: fails |

Condition 1 uses complete common hourly marks plus each terminal close; it skips 852 hours.
Condition 2 uses the common July 2021–December 2024 marks without a terminal point and skips
299 hours. These are the registered conventions, not standalone summary substitutions.

## Economics: older gains do not establish recent profitability

The full period is April 2018–September 2026 (102 months). The recent period is January
2025–September 2026 (21 months), which inherits the earlier positions and accumulated equity;
it is not a fresh account opened in 2025. Only this recent era was unseen when V4 was designed.
Displayed monetary values are rounded independently; reconciliations use unrounded values.

| Initial USDT / trading costs | Final equity, USDT | Full return | Full maximum drawdown | Recent return |
| --- | ---: | ---: | ---: | ---: |
| 100 / normal | 347.34 | +247.34% | 54.87% | -18.51% |
| 100 / doubled | 244.80 | +144.80% | 57.54% | -29.01% |
| 1,000 / normal | 3,358.85 | +235.89% | 58.17% | -15.28% |
| 1,000 / doubled | 2,132.44 | +113.24% | 62.50% | -25.64% |
| 10,000 / normal | 33,342.14 | +233.42% | 58.19% | -14.69% |
| 10,000 / doubled | 21,124.84 | +111.25% | 62.71% | -25.59% |

The independent economic aggregation reconciled monthly gross/net/equity identities, monthly
continuity and full-window fee/funding totals for all 66 non-V3 cells. Full-window lifecycle net
P&L equals equity change with zero residual. The six V3 cells are absent from diagnosis by design.

At 100 USDT and normal costs, mean monthly account gain was 2.42 USDT over the full history,
the median was -1.10, and the worst month was -63.99. Recent mean monthly gain was -3.76.
These are marked account changes before hosting, not a reliable withdrawal stream. Every main
cell has a negative median month in both periods, and only 10 of the 21 recent months are positive.
Normal-cost refused-order legs number 3,982 at 100, versus 394 at 1,000 and 356 at 10,000;
capital therefore changes execution, so scaling the larger account down is not a valid substitute.

At 10,000 USDT and normal costs:

- Full-window gross P&L 30,442.33 minus fees 7,376.63 plus signed funding 276.44 equals net
  23,342.14 USDT. Slippage of 4,918.67 and synthetic-close penalties of 209.99 are embedded in
  gross P&L and are not deducted again.
- Recent price P&L was already -3,443.96 before explicit fees of 2,451.20 and funding received
  of 154.54, giving the actual recent equity loss of 5,740.62. That price P&L still includes
  embedded slippage and penalties; it is not a frictionless counterfactual.
- Lifecycles exiting in the recent period sum to positive 6,957.57, while account equity loses
  5,740.62. The -12,698.18 boundary/open-trade adjustment reconciles them. Exit-year trade totals
  include pre-2025 accrual and must not be called recent account profit.
- Full-window long net P&L was +33,266.62, short net P&L -9,924.49. This is attribution; deleting
  shorts changes the account path and sizing and cannot be inferred by adding their loss back.

All 48 registered V4 strategy/variant cells lose in the recent period. Long-only beats main on
full return, full drawdown and recent return in all six matching comparisons, but still loses
recently. At 10,000 normal costs its figures are +347.78%, 43.98% drawdown and -4.22% recent return.
The six BTC-trend holding-benchmark cells are the only positive recent results among the 66
non-V3 cells (about +3.92% normal and +1.03% doubled costs). This is comparison evidence, not
permission to select the best-looking arm after seeing results.

## The volatility concern occurs in this run

The pre-run synthetic finding was an intentional sizing tradeoff under v4-d12, not a coding
disagreement with the specification. The same mechanism now has measured historical incidence.

The estimated post-signal/post-cap target-risk series are identical across the three main
normal-cost capitals. Across 3,105 daily decisions, estimated annual target-book volatility has
mean 28.72%, median 29.67%, 95th percentile 41.43%, and maximum **61.34%**, against the configured
40% scaling target. It exceeds 40% on **240/3,105 decisions (7.73%)**, or 240/2,991 nonflat
decisions (8.02%). From 2025 onward, it exceeds 40% on **93/638 decisions (14.58%)**.

The signal-strength adjustment raises estimated risk above the normalized full-strength book
on 272 decisions. Individual coin caps raise it on 39 decisions. The maximum post-cap value,
at the 2022-06-08 decision, was independently checked with a 60-digit Decimal covariance matrix:
61.342423120635100...%, while normalized full-book risk is 40% and the stored scale matches
exactly. The floating calculation differed by approximately `1.01e-16` in absolute volatility.

Covariance uses point-in-time `Market.daily` spot bars constructed from unmasked hourly data,
not an interchangeable daily archive: the trailing 60 calendar days end on the previous UTC
day, before the decision. Common-day counts agree with the records and, for the 2,991 nonflat
decisions, are at least 40;
384 nonflat decisions use fewer than 60. Sample variance uses denominator n-1 and annual factor
365. Every nonflat scale reconstruction agrees within `4.25e-16` relative error (declared
tolerance `1e-8`). Registered data pins and record chains were checked.

These are separate risk quantities:

| Layer | What this review establishes |
| --- | --- |
| Configured target | 40% annualized scaling input; v4-d12 does not promise a book-level ceiling |
| Mathematical target-book risk | Distribution and overshoots above; this is not the filled portfolio |
| Executed-holdings predicted risk | Not measured in this bounded pass; remains for Claude's agreed readout |
| Realized equity risk | Separate midnight-return calculation below; no loss causation claim |

Realized annualized daily-equity volatility is 31.83%, 32.36% and 32.50% at 100, 1,000 and
10,000 normal-cost USDT respectively; from 2025 it is 32.20%, 33.95% and 34.16%. These use
consecutive positive equity marks with complete UTC-midnight endpoints, excluding 62/30/30
return pairs respectively, and omit the final off-grid terminal close. Endpoint completeness
does not establish uninterrupted intraday completeness. Target risk, retained desired targets,
executed holdings and realized risk must not be conflated. These measurements do not establish
that a new risk cap would improve profits or have prevented the recorded drawdown.

## Review queue and next discussion with Claude

- **Completed, Codex:** first-attempt run monitoring; archive fingerprint check; independent
  condition calculations; economic reconciliation; bounded target-risk and realized-risk audit.
- **Active, Claude:** the approved post-run result event, verdict record and archive entry;
  the previously agreed economic/four-level risk readout. This review leaves those files to Claude.
- **Next, Codex and Claude:** compare these findings locally, reconcile any disagreement and
  decide whether measuring executed-holdings risk would change the next decision. The original
  question about target normalization now has direct evidence; causality remains unmeasured.
- **Owner decision after that discussion:** whether to pursue a new bounded hypothesis at all.
  The existing results support investigating short exposure and risk normalization as distinct
  questions; they do not support simply optimizing fees, raising risk, or promoting a neighbor.
  No historical holdout remains, and any future confirmation would need forward evidence.

The registered strategy and criteria remain unchanged. This review does not launch a new
simulation, paper strategy or live-capital pilot. A result at 100 USDT remains a separate
economic decision under v4-d31.

## Local reproduction and limits

The read-only analysis helpers and derived outputs are preserved outside the immutable archive
in `/root/Documents/ChatGPT/Options trading/v4-review-42953425248/`:

- `verify_verdict.py` and `verdict_verification.json`: independent common-hour arithmetic,
  summary/receipt and artifact-digest checks.
- `economics_review.py` and `economics_summary.json`: exact Fraction reconciliation and
  aggregated account/side/cost comparisons, using the two pinned result JSON files above.
- `risk_targets_independent.py`, `risk_targets_independent_summary.json`,
  `risk_independent_addendum.json` and `risk_independent_validation.json`: recorded-vector
  risk estimates, separate realized-equity measure, Decimal peak cross-check and method limits.

Helpers run with `python -I` from outside the archive and import no code from it. The risk helper
imports the audit checkout's engine source; `src/` and `scripts/` have no diff between the
dispatched commit and the registered code pin. Local Python is 3.14, whereas the registered
workflow ran on 3.12. No strategy replay or parameter search was made. The risk pass took about
66 seconds and 1.07 GiB peak memory, plus seven seconds for the Decimal cross-check. A separate
source reviewer found no blocking mathematical issue; its interpretation caveats are included
above. These helpers are local review evidence, not new production commands or registered code.
