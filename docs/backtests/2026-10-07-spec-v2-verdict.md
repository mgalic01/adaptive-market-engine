# Spec v2: the mode switcher fails on drawdown (C1); it passes C2–C6

- **Date and author:** 2026-10-07, written by Claude (session `b9db01ca`).
- **Scope:** paper replay only, under [spec v2](../EXPERIMENT_SPEC_V2.md) as frozen in #175. Nothing here is live trading or advice.
- **Result: spec v2 fails.** On the scored window, `full-range-2017-2024` (evaluated 2019-01 to 2024-12), the mode switcher passes C2, C3, C4, C5 and C6, and fails C1.
  - **C1 fails.** The worst total-equity drawdown is 21.91% on BTCUSDT and 11.02% on ETHUSDT. The worst active-equity drawdown is 26.41%. The limit is 10% on both. No hard-drawdown halt fired.
  - **Spec v2 §8:** the mode switcher passes only if C1–C6 all pass. So it fails, and the reserved 2025–26 window stays closed. C7 was not evaluated, because it is not settled and it selects nothing.
- **The return was positive.** Over the six years it made +30.13% / +30.29% on BTCUSDT and +36.08% / +36.89% on ETHUSDT (the `high_first` / `low_first` paths), a median annualised return of about 4.9%.
  - It beat always-grid (variant F) and cash in all 4 runs. Always-grid made −1.80% / −0.00% on BTCUSDT and −38.57% / −35.01% on ETHUSDT.
  - Buy-and-hold made +2,419.60% on BTCUSDT and +2,430.53% on ETHUSDT. As a share of that six-year rise, the mode switcher's return is about 1.2% on BTCUSDT (30.13 of 2,419.60) and 1.5% on ETHUSDT (36.08 of 2,430.53).
  - Spec v2's registered upside capture is a different, monthly measure: over the months in which buy-and-hold rose, the run's summed monthly returns divided by buy-and-hold's (§8). It is 0.0605 on BTCUSDT and 0.045 on ETHUSDT.
- **The sanity windows** (`practice-2022`, `verify-2024h1`) are reported only and decide nothing (spec v2 §8). The mode switcher lost money in all 8 of their runs, as in the first read (decisions 10–13).
- **The owner's decision (2026-10-08): v2 closes as failed, and a v3 is designed.**
  - Claude reported the verdict on 2026-10-07 at about 21:20 UTC. The owner then shared a multi-strategy trading-bot brief: 25% a month, 50 coins, 20x leverage, live trading. Claude assessed it against v0–v2's evidence and asked what to do with it.
  - The owner chose **"Test the core idea first"**. The option said: "Before any big build: a new pre-registered spec (v3), paper-only, testing trend-following (long and short) across a wider set of top coins, held to the spec's own walk-forward gate (Sharpe at least 1.0, profit factor at least 1.3). Build infrastructure only for what passes. No profit promise."
  - The other options were "Build the full spec, paper-only", "Just your assessment for now" and "Close v2 and stop here".
  - Spec v3 is drafted separately. Nothing in this record changes.

## How the runs were made

Three sets of the same six runs were dispatched. Each set holds the mode switcher with D (`variant=MS`, `trend_benchmark=true`) and always-grid (`variant=F`) on each of the three windows, at spec v1's primary fees (maker 0, taker 0.0009). The scorer accepts only a batch from one clean commit, so the sets are never mixed.

1. **`0f30e95`** (#200 merged), dispatched at 14:10 UTC. Each job ran one at a time (`run_nopool.py`).
   - The full-range mode-switcher run was cancelled at GitHub's 6-hour job limit (run 37634426637).
   - Its full-range F run finished in 5 h 50 min, but marked itself invalid. See "A false accounting failure" below.
2. **`9a3f9fa`** (#201 merged: the workflow runs the CLI in a pool of 4), dispatched at 18:19 UTC. All six finished: the full-range runs in 2 h 31 min (F) and 2 h 48 min (MS). **This set is scored.**
3. **`7d309a2`** (#204 merged: the accounting fix), dispatched at 20:53 UTC as a hedge. All six finished; the full-range runs took 2 h 36 min (F) and 2 h 51 min (MS).
   - **Every file is valid,** with no failures. The fix clears the false accounting flag on the ungated baseline rows.
   - **Every row is identical to set 2's,** apart from the commit fields and those four rows' `accounting_problems`.
   - **`acceptance_v2`,** run from a clean checkout of `7d309a2`, prints a verdict identical to set 2's from the comparison mask on: fail, on C1. Its verdict JSON's SHA-256 is `a6be8a3b50dca94ce9a482fb765ffa1528e5bc5203e62188ab3b56d97f4ccdd2`.
   - **Its inputs,** every one with `code_commit` `7d309a2068dca2b358c5887a2ca074c5e6e40cc1`, clean:

     | Workflow run | What | results.json SHA-256 | valid |
     | --- | --- | --- | --- |
     | [37685358642](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37685358642) | full-range-2017-2024, MS with D | `7a8870efcc325f973359e2925f6618a0bdd6f7cf882a190c11ed0bc341773401` | true |
     | [37685366857](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37685366857) | full-range-2017-2024, F | `ce85832668ac1469f7b904878355a004d4c29918beb4ce5d0ec51d139715eb9c` | true |
     | [37685374982](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37685374982) | practice-2022, MS with D | `b7c1cc86f84d069e43b746a68596ab097fef9e30aa8a1d871b50b354a9046960` | true |
     | [37685384065](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37685384065) | practice-2022, F | `8f796bfa6eaf8a7c5d035136bf00e015c14ac6e50bfad31a8a0710480a80e5a2` | true |
     | [37685392610](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37685392610) | verify-2024h1, MS with D | `f115b06a64d0a3dbc4c72ff96cd77170200f8b0d5e2728c44510b224fb0f0271` | true |
     | [37685401222](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37685401222) | verify-2024h1, F | `889c4aa37a9cec55ae60b3fe4b9c9220dcc3efa499fbc07fabc2723539ecfd89` | true |


**Set 2 matches set 1.** Apart from the commit fields, set 2's results equal set 1's for the full-range F run and for verify-2024h1 MS. A pool writes the same results as one job, which #201's test also shows.

**The scorer:**
- **Command:** `python -m crypto_grid_bot.backtest.acceptance_v2 <the 6 results.json files> --out <verdict>`.
- **Where it ran:** a clean, detached checkout of `9a3f9fa`, importing from that checkout's `src`, with the same `code_commit` and `code_sha256` as every run.
- **Its verdict JSON:** SHA-256 `b415d2e2c10e423d4baad1c3649c7b88f3bec4b8e9c68746f75d786b26dd8c2a`. It is not committed, because it lists the inputs by local paths. "Inputs" below gives every input's SHA-256.
- **Its output** is in the appendix, verbatim.

**Where the raw results are:** each run's GitHub Actions artifact, `backtest-<dataset>`, kept for 30 days, until about 2026-11-06.

### A false accounting failure

In sets 1 and 2, each full-range results file marks itself `valid: false`. All four ungated grid baseline rows (BTCUSDT and ETHUSDT, both paths) fail one check: "exit P&L by reason does not sum to the exit total".
- **The accounting is right; the check was too strict.** Each reason's sum and the exit total are accumulated fill by fill at the simulator's precision (50 digits), so with two reasons (`range_exit` and `liquidation`) they round differently, by about 1e-46. The check compared them exactly.
- **The fix:** #204 gives the check P6's tolerance, 1e-18, and set 3 carries it.
- **No scored row is affected.** v2's scorer ignores the ungated baseline rows ("which every results file carries, and which is ignored", `acceptance_v2.py`). The scored rows (MS, F, D) carry no accounting problem: a run with one is counted invalid, and C4 reports 4 of 4 valid.

## The comparison mask (spec v1 §5, carried over by spec v2 §2)

| Window | Pair | Included | Reason |
| --- | --- | --- | --- |
| full-range-2017-2024 | BTCUSDT | yes | |
| full-range-2017-2024 | ETHUSDT | yes | |
| full-range-2017-2024 | XRPUSDT | no | `tick_limit_quotes=545`: its actual-quotes test breaches (rule 8) |
| practice-2022 | BTCUSDT | yes | |
| practice-2022 | SOLUSDT | no | `daily_days_missing=102`, and no sourced historical exchange filters |
| practice-2022 | XRPUSDT | yes | |
| verify-2024h1 | ADAUSDT | yes | |
| verify-2024h1 | BTCUSDT | yes | |

**The daily cross-check, under decision 14.** In the full-range run, BTCUSDT, ETHUSDT and XRPUSDT each show `daily_days_volume_excused=1` and `daily_days_mismatched=0`, with no `daily_mismatched_days`.
- So 2021-01-21's prices agreed exactly with its hours for all three, which was the premise of the owner's exception. It was the only day whose official 1d bar disagreed with its hours.
- The days compared: 2,370 for BTCUSDT, 2,371 for ETHUSDT and 2,360 for XRPUSDT. Days holding a masked hour (35–46 per pair) are skipped under rule 3.

## The scored window, criterion by criterion

| Criterion | Result | Figures |
| --- | --- | --- |
| C1: drawdown ≤ 10%, total and active | **fail** | worst total-equity drawdown 21.91%; worst active-equity drawdown 26.41%; no hard-drawdown halt; all 4 runs exceed 10% |
| C2: positive median annualised return on each path | pass | median 4.88% (`high_first`), 4.94% (`low_first`); mean 4.91% |
| C3: below buy-and-hold's drawdown | pass | 4 of 4 |
| C4: valid runs | pass | 4 of 4 |
| C5: ≥ 12 round trips a year | pass | mean 14.50 |
| C6: beats always-grid and cash in ≥ 60% | pass | 4 of 4 (100%) |
| R1 (reported only) | | mean monthly return 0.46%; capital for EUR 5 a month, 1,079.53 |

| Runs (scored window) | Mean annualised | Mean return | Mean max drawdown |
| --- | ---: | ---: | ---: |
| mode switcher | +4.91% | +33.35% | 16.46% |
| always-grid (F) | −3.76% | −18.84% | 29.24% |
| D (reported only) | +68.66% | +2,358.79% | 60.64% |

## What the numbers show

### Where the drawdown came from

| Pair | Path | Total-equity drawdown | Peak | Trough | Active-equity drawdown | Buy-and-hold drawdown | Soft-drawdown rebases | Hard-drawdown halts |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| BTCUSDT | high_first | 21.91% | 2021-02-21 | 2024-11-07 | 26.41% | 77.56% | 10 | 0 |
| BTCUSDT | low_first | 21.91% | 2021-02-21 | 2024-11-07 | 26.41% | 77.56% | 10 | 0 |
| ETHUSDT | high_first | 11.02% | 2020-02-15 | 2020-07-23 | 11.38% | 81.88% | 9 | 0 |
| ETHUSDT | low_first | 11.01% | 2020-02-15 | 2020-07-23 | 11.38% | 81.88% | 9 | 0 |

- **BTCUSDT's drawdown was a slow decline over 3¾ years, not a crash.** Its equity peaked on 2021-02-21 and reached its low on 2024-11-07, while BTCUSDT itself rose.
- **The 12% hard stop never fired, and the risk layer's peak was lowered 10 times on BTCUSDT and 9 times on ETHUSDT.** The runtime risk layer measures drawdown from `risk_high`, and spec v1's amendment 1 lets a soft-drawdown recovery rebase `risk_high` downward. The runs record the rebases and that no halt fired. That the halt would have fired without the rebases is an inference, not something the runs record.
- **C1 never rebases** (spec v1's C1 row and amendment 1, §3). C1(a) measures total equity from a running peak that is never scaled or rebased. C1(b) measures active equity against a reference that follows `risk_high` except for its rebases. The runtime risk layer and C1 differ by design, and this run is the case where they part: the risk layer's own peak was lowered 10 times on BTCUSDT, while C1 kept measuring from 2021-02-21.
- **ETHUSDT's worst drawdown, 11.02%, came in 2020,** from 2020-02-15 to 2020-07-23, which takes in the March 2020 crash. It exceeds the limit by about one point.

### Per calendar year (`high_first`; `low_first` is within 0.4 points)

Each year runs from its first hour's equity, or the previous year's last, to its last hour's, from each row's `hourly_equity`. Cash returns 0%.

| Pair | Year | Mode switcher | Its max drawdown in the year | Always-grid (F) | Buy-and-hold |
| --- | --- | ---: | ---: | ---: | ---: |
| BTCUSDT | 2019 | +16.89% | 10.8% | −5.53% | +94.55% |
| BTCUSDT | 2020 | +26.36% | 8.9% | +9.23% | +303.39% |
| BTCUSDT | 2021 | +2.73% | 7.1% | −2.41% | +59.57% |
| BTCUSDT | 2022 | −7.20% | 7.6% | +0.53% | −64.37% |
| BTCUSDT | 2023 | +1.50% | 10.4% | +1.39% | +155.90% |
| BTCUSDT | 2024 | −8.94% | 12.9% | −4.35% | +121.03% |
| ETHUSDT | 2019 | −4.39% | 9.3% | +1.28% | −1.76% |
| ETHUSDT | 2020 | +18.72% | 10.5% | −0.64% | +472.42% |
| ETHUSDT | 2021 | +12.31% | 8.5% | −10.39% | +398.71% |
| ETHUSDT | 2022 | −4.70% | 6.1% | −25.31% | −67.57% |
| ETHUSDT | 2023 | +5.01% | 9.4% | −2.25% | +90.54% |
| ETHUSDT | 2024 | +6.67% | 7.9% | −6.71% | +46.46% |

- **On BTCUSDT, nearly all the gain came in 2019–2020.** From 2021 to 2024 the mode switcher lost a net 12%, while buy-and-hold more than tripled.
- **ETHUSDT's gain is spread more evenly.**
- **In 2022, the bear year for both pairs,** the mode switcher lost 7.2% on BTCUSDT and 4.7% on ETHUSDT, where buy-and-hold lost 64% and 68%.

### Grid cycles by ISO year (mode switcher, `high_first`)

`completed_cycles_by_week` is keyed by ISO week, so cycles are counted by ISO year (#202).

| Pair | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 12 | 2 | 10 | 7 | 0 | 0 |
| ETHUSDT | 5 | 10 | 22 | 5 | 0 | 1 |

### Realised profit and loss by source (mode switcher, on a 100 start)

Nothing is held at the end of any run, so the sources sum exactly to each run's return. Fees are inside each figure.

| Pair | Path | Grid sells | `uptrend_risk` | `uptrend_stop` | `uptrend_fade` | `range_exit` | Sum = return |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | high_first | +4.88 | +65.59 | −19.56 | −11.20 | −9.57 | +30.13 |
| BTCUSDT | low_first | +4.88 | +65.71 | −19.56 | −11.19 | −9.55 | +30.29 |
| ETHUSDT | high_first | +8.27 | +51.87 | −2.53 | −8.39 | −13.15 | +36.08 |
| ETHUSDT | low_first | +8.65 | +52.01 | −2.48 | −8.40 | −12.90 | +36.89 |

- **The profit is the uptrend's.** The grid's sells added +4.9 to +8.7 over six years, and its range exits cost more than that. These are realised profit and loss by source, not an exact net return per mode (#202).
- **`uptrend_risk` covers the uptrend sales that began when the risk layer paused or halted the account**: a soft-drawdown REDUCE, a daily-loss pause, a halt (`runner.py`, `_begin_exit(..., "risk")`). Most of the uptrend's gains were realised that way, not by its own trailing stop (`uptrend_stop`) or trend fade (`uptrend_fade`).

### Time in each mode, and what kept Uptrend out

| Pair (both paths) | Cash | Grid | Uptrend | Switches | Uptrend trades | Stops | Fades | Round trips (grid + uptrend) | Upside capture (registered, monthly) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 70.28% | 2.90% | 26.82% | 413 | 48 | 12 | 17 | 31 + 48 | 0.0605 |
| ETHUSDT | 71.85% | 2.36% | 25.79% | 416 | 51 | 12 | 18 | 43–45 + 51 | 0.045 |

Of its hourly decisions, the `high_first` row made 38,579 on BTCUSDT and 39,102 on ETHUSDT. The rest were hours skipped while a position was held. The decisions that a single condition alone kept out of Uptrend (`modes.decisions.uptrend_sole_blocker`, #197):

| Pair | Daily trend not up | 4h trend not up | Daily RSI ≥ 75 | Regime bear or stress | Other |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTCUSDT | 7,033 | 2,619 | 1,110 | 16 | 15 |
| ETHUSDT | 6,782 | 1,961 | 248 | 75 | 13 |

- **The daily trend filter is the main blocker,** followed by the 4h one.
- **In the sanity window `verify-2024h1`,** during BTCUSDT's rally in 2024-02, the daily RSI ≥ 75 rule alone kept Uptrend out of 260 of 696 hourly decisions. That is `modes.decisions.by_month["2024-02"]` of the BTCUSDT `high_first` MS row, in run 37665924005 (this set) and in 37634466270 (set 1), identically.

### Not recorded in these runs (#202)

These need a reporting-only addition to the rows and new runs, if the owner wants them:
- an exact net return per mode;
- costs, trades and time invested per year;
- any figure per regime.

Fees, buys, sells, `time_with_inventory_pct`, `modes.time_ms` and `regimes_by_bar` are whole-run totals.

## The sanity windows (reported only)

| Window | Pair | Mode switcher | Always-grid (F) | Buy-and-hold | Mode switcher's max drawdown |
| --- | --- | ---: | ---: | ---: | ---: |
| practice-2022 | BTCUSDT | −5.55% / −5.56% | +1.51% / +3.19% | −27.44% | 5.98% |
| practice-2022 | XRPUSDT | −4.88% / −4.91% | +4.28% / +5.33% | −4.15% | 7.03% |
| verify-2024h1 | ADAUSDT | −0.16% | −4.31% / −4.11% | −34.13% | 2.83% |
| verify-2024h1 | BTCUSDT | −5.73% | −5.31% / −5.53% | +47.94% | 7.13% |

Both windows fail C2 and C6 there, and `practice-2022` fails C5 as well. These are the same figures as the first read at `552c32c`. The instrumentation (#197) changed no decision.

## What follows

- **The owner decided (2026-10-08):** v2 closes as failed, and a v3 is designed. See the top of this record.
- **A caution for any v3:** `full-range-2017-2024` has now been seen. A v3 tested on the same years is not an out-of-sample test there, so it needs a fixed trial register (#169's Addendum B2), and only the reserved window could confirm it.
- **Two findings for a v3:**
  - the drawdown came from a slow decline that the rebasing risk layer never stopped;
  - the mode switcher's six-year return was about 1.2% (BTCUSDT) and 1.5% (ETHUSDT) of buy-and-hold's rise, with a registered monthly upside capture of 0.06 and 0.045. Most of its gain was realised through exits the risk layer began.
- **Proposed to the owner as a task:** #169's Addendum A1, a check that a halt blocking new exposure never blocks a protective exit (#202). It is related, since `uptrend_risk` exits are exactly the risk layer's.
- **Merged during this run:**
  - #201: the backtest workflow runs a pool of 4;
  - #204: the accounting check's tolerance.
- **In review:** #203 (progress lines), to be merged after this verdict.

## Inputs

| Workflow run | What | results.json SHA-256 | valid | failures |
| --- | --- | --- | --- | --- |
| [37665890228](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665890228) | full-range-2017-2024, MS with D | `65b39d14e82da723771b31f883674d3d742be5d190651825759022fd828e4a85` | false | the 4 ungated baseline rows (the false accounting failure above) |
| [37665898847](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665898847) | full-range-2017-2024, F | `77bbd2e0fb292ef416979c498634210d4370f1202fd10530f215780194337999` | false | the 4 ungated baseline rows (the same) |
| [37665907336](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665907336) | practice-2022, MS with D | `cea1859550d92a7f9336e95aca02a10aab3d8094d00f50b69da6a102ba8e4d72` | true | none |
| [37665915836](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665915836) | practice-2022, F | `0e980825e6202e140926f7231838a39d7bb01bdc6b849b07ca8c3ce26da151c9` | true | none |
| [37665924005](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665924005) | verify-2024h1, MS with D | `d50364327bd8f7e0c31b76578b2139b6af1158a926d7b17b70585fae551b4377` | true | none |
| [37665932069](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665932069) | verify-2024h1, F | `aa750fe4a9af8e1611a03d02fbaa1b574e68f13c9be45b3cfb3fdba1500514dd` | true | none |

Every input carries `code_commit` `9a3f9fa0339e012ea5fb242b80ac6602707f57cd`, clean, and `code_sha256` `62e8c6f5c5366d4a068227df1b7583c40691fee0c38681130c460a093d8a59e6`.

## Appendix: the scorer's output, verbatim

```
Spec v2 scoring spec-v2-section-8: the mode switcher against always-grid (variant F) and cash; primary fees maker 0 / taker 0.0009, engine drawdown-recovery-v2, integrity rules drift-tolerance-v1
Inputs: 6 results files (paths and SHA-256 in the JSON verdict)

Comparison mask (spec v1 section 5, carried over by spec v2 section 2)
| Window | Pair | Included | Reasons |
| --- | --- | --- | --- |
| full-range-2017-2024 | BTCUSDT | yes |  |
| full-range-2017-2024 | ETHUSDT | yes |  |
| full-range-2017-2024 | XRPUSDT | no | XRPUSDT: tick_limit_quotes=545 |
| practice-2022 | BTCUSDT | yes |  |
| practice-2022 | SOLUSDT | no | SOLUSDT: daily_days_missing=102; no sourced historical exchange filters (spec v1 P4, section 5) |
| practice-2022 | XRPUSDT | yes |  |
| verify-2024h1 | ADAUSDT | yes |  |
| verify-2024h1 | BTCUSDT | yes |  |

full-range-2017-2024: scored: the mode switcher passes only if C1-C6 all pass; R1 is reported only
Mode switcher: 4 included runs, FAIL
- C1 FAIL: worst total-equity drawdown % 21.9136; worst active-equity drawdown % 26.4077; hard-drawdown halts 0; limit % 10
    full-range-2017-2024 BTCUSDT high_first
    full-range-2017-2024 BTCUSDT low_first
    full-range-2017-2024 ETHUSDT high_first
    full-range-2017-2024 ETHUSDT low_first
- C2 pass: median annualised return % (high_first) 4.8770; median annualised return % (low_first) 4.9393; mean annualised return % 4.9082
- C3 pass: runs below buy-and-hold drawdown 4 of 4
- C4 pass: valid runs 4 of 4
- C5 pass: mean round trips per year 14.4967; minimum 12
- C6 pass: runs beating always-grid and cash 4 of 4; share % 100.0000; required % 60
- R1 (reported only): mean monthly return % 0.4632; capital for EUR 5/month 1079.5316
| Runs | Mean annualised % | Mean return % | Mean max DD % |
| --- | ---: | ---: | ---: |
| mode switcher | 4.9082 | 33.3478 | 16.4647 |
| always-grid (F) | -3.7573 | -18.8444 | 29.2359 |
| D (reported only) | 68.6613 | 2358.7850 | 60.6402 |
| Run | Round trips (grid + uptrend) | Time cash / grid / uptrend % | Switches | Stops | Fades | Buy-and-hold % | Upside capture |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| full-range-2017-2024 BTCUSDT high_first | 31 + 48 | 70.2821 / 2.8988 / 26.8191 | 413 | 12 | 17 | 2419.5953 | 0.0605 |
| full-range-2017-2024 BTCUSDT low_first | 31 + 48 | 70.2821 / 2.8988 / 26.8191 | 413 | 12 | 17 | 2419.5953 | 0.0605 |
| full-range-2017-2024 ETHUSDT high_first | 43 + 51 | 71.8522 / 2.3628 / 25.7851 | 416 | 12 | 18 | 2430.5323 | 0.0449 |
| full-range-2017-2024 ETHUSDT low_first | 45 + 51 | 71.8522 / 2.3628 / 25.7851 | 416 | 12 | 18 | 2430.5323 | 0.0448 |

practice-2022: reported only; it decides nothing (spec v2 section 8)
Mode switcher: 4 included runs, FAIL
- C1 pass: worst total-equity drawdown % 7.0263; worst active-equity drawdown % 7.0327; hard-drawdown halts 0; limit % 10
- C2 FAIL: median annualised return % (high_first) -7.6685; median annualised return % (low_first) -7.7009; mean annualised return % -7.6847
- C3 pass: runs below buy-and-hold drawdown 4 of 4
- C4 pass: valid runs 4 of 4
- C5 FAIL: mean round trips per year 9.6903; minimum 12
- C6 FAIL: runs beating always-grid and cash 0 of 4; share % 0.0000; required % 60
    practice-2022 BTCUSDT high_first: return -5.5467309087558% does not beat cash
    practice-2022 BTCUSDT low_first: return -5.5559026467558% does not beat cash
    practice-2022 XRPUSDT high_first: return -4.875956716055% does not beat cash
    practice-2022 XRPUSDT low_first: return -4.9114554633025% does not beat cash
- R1 (reported only): mean monthly return % -0.6528; capital for EUR 5/month not reachable
| Runs | Mean annualised % | Mean return % | Mean max DD % |
| --- | ---: | ---: | ---: |
| mode switcher | -7.6847 | -5.2225 | 6.4949 |
| always-grid (F) | 5.3855 | 3.5764 | 6.0954 |
| D (reported only) | -8.7112 | -5.9563 | 34.7465 |
| Run | Round trips (grid + uptrend) | Time cash / grid / uptrend % | Switches | Stops | Fades | Buy-and-hold % | Upside capture |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| practice-2022 BTCUSDT high_first | 3 + 2 | 93.4864 / 2.8912 / 3.6224 | 47 | 1 | 1 | -27.4394 | -0.0262 |
| practice-2022 BTCUSDT low_first | 3 + 2 | 93.4864 / 2.8912 / 3.6224 | 47 | 1 | 1 | -27.4394 | -0.0263 |
| practice-2022 XRPUSDT high_first | 6 + 2 | 76.9218 / 1.9048 / 21.1735 | 37 | 0 | 2 | -4.1543 | -0.0104 |
| practice-2022 XRPUSDT low_first | 6 + 2 | 76.9218 / 1.9048 / 21.1735 | 37 | 0 | 2 | -4.1543 | -0.0104 |

verify-2024h1: reported only; it decides nothing (spec v2 section 8)
Mode switcher: 4 included runs, FAIL
- C1 pass: worst total-equity drawdown % 7.1254; worst active-equity drawdown % 7.1254; hard-drawdown halts 0; limit % 10
- C2 FAIL: median annualised return % (high_first) -5.7504; median annualised return % (low_first) -5.7504; mean annualised return % -5.7504
- C3 pass: runs below buy-and-hold drawdown 4 of 4
- C4 pass: valid runs 4 of 4
- C5 pass: mean round trips per year 15.0515; minimum 12
- C6 FAIL: runs beating always-grid and cash 0 of 4; share % 0.0000; required % 60
    verify-2024h1 ADAUSDT high_first: return -0.163874856% does not beat cash
    verify-2024h1 ADAUSDT low_first: return -0.163874856% does not beat cash
    verify-2024h1 BTCUSDT high_first: return -5.73234774647% does not beat cash
    verify-2024h1 BTCUSDT low_first: return -5.73234774647% does not beat cash
- R1 (reported only): mean monthly return % -0.4914; capital for EUR 5/month not reachable
| Runs | Mean annualised % | Mean return % | Mean max DD % |
| --- | ---: | ---: | ---: |
| mode switcher | -5.7504 | -2.9481 | 4.9779 |
| always-grid (F) | -9.4325 | -4.8189 | 8.1418 |
| D (reported only) | 18.0342 | 3.6123 | 27.3790 |
| Run | Round trips (grid + uptrend) | Time cash / grid / uptrend % | Switches | Stops | Fades | Buy-and-hold % | Upside capture |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| verify-2024h1 ADAUSDT high_first | 9 + 1 | 95.9478 / 2.9304 / 1.1218 | 36 | 0 | 1 | -34.1344 | -0.0268 |
| verify-2024h1 ADAUSDT low_first | 9 + 1 | 95.9478 / 2.9304 / 1.1218 | 36 | 0 | 1 | -34.1344 | -0.0268 |
| verify-2024h1 BTCUSDT high_first | 0 + 5 | 75.5495 / 5.5632 / 18.8874 | 52 | 1 | 4 | 47.9436 | -0.0472 |
| verify-2024h1 BTCUSDT low_first | 0 + 5 | 75.5495 / 5.5632 / 18.8874 | 52 | 1 | 4 | 47.9436 | -0.0472 |

Outcome (spec v2 section 8): fail
- full-range-2017-2024: C1 fails
C7 not evaluated: it is not yet settled (spec v1 section 6). It selects nothing, and the reserved window stays closed until it is settled and passed, or waived.
```
