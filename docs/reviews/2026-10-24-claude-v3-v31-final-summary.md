# Claude: V3.0 and V3.1, the final record before their run files are deleted

Index: Final record of V3.0 (no verdict, misses A1-A3) and V3.1 (FAIL) before file deletion.

Author: Claude Code (session f7f187df), 2026-10-24 UTC. Branch `claude/v3-v31-summary` on
main `184be44`. Documents only. Nothing was run, re-aggregated or fetched. On the owner's
PC only small summary, verdict and log files were opened, read-only.

The owner is about to delete the run files of V3.0 and V3.1 from his PC (section 7). This
file is meant to keep everything worth keeping once they are gone. The repository is
public, so it holds only aggregated numbers and SHA-256 fingerprints, as
[the run archive's rules](../RUN_ARCHIVE.md) allow.

## 1. In plain words

- **V3.0** (2026-10-08 to 2026-10-10) was a daily trend-following bot on Binance perpetual
  futures, long and short, on 10 coins. Its one run on the owner's PC crashed at the very
  end, in the buy-and-hold comparison, so **no verdict was ever issued**. The saved
  results show it would have failed anyway: 10,000 USDT became 13,446.86 USDT
  (+34.47%, 8.82% a year), but with a 66.82% drawdown, so three of its five pass
  conditions (Sharpe, profit factor, Calmar) were missed. Shorts lost money. The
  long-only version of every rule had a higher CAGR than its long-and-short version.
- **V3.1** (2026-10-10 to 2026-10-17) combined spot trend, futures shorts and a spot grid
  in one shared account, with stops, a 30% shutdown and a recovery mode. Its one
  registered GitHub run (38703911852) finished every cell. The verdict, computed on the
  owner's PC after GitHub's summary job ran out of disk, is **FAIL**. The full system lost
  4.84% to 27.67% over 2021-07 to 2024-12. It fell more than 30% in 9 of 12 cells, lost
  money at doubled costs in 6, and beat none of its 32 baselines on return. Over the same
  dates, V3's simple long-only rules made +75% to +186%.
- **What it taught:** slow daily signals with volatility sizing were the only thing that
  worked; tight stops, trailing stops, shutdown-and-recovery and the grid all hurt; shorts
  need their own evidence; a 100 USDT account is too small for ten coins; and a verdict
  step must be built to run at real scale. V4 is built on those lessons (section 6).

## 2. Sources

Every number below names its source by these codes. "Repo" files are on `main`; "PC" files
are on the owner's PC and go away with the deletion.

| Code | File |
| --- | --- |
| R1 | Repo: `docs/trials/register.jsonl` (V3 lines 27-227, V3.1 lines 228-230) |
| R2 | Repo: `docs/EXPERIMENT_SPEC_V3.md` (the frozen V3 spec) |
| R3 | Repo: `docs/reviews/2026-10-09-codex-v3-data-delivery.md` |
| R4 | Repo: `docs/reviews/2026-10-09-v3-launch-preparation.md` |
| R5 | Repo: `docs/reviews/2026-10-10-codex-v3-spot-failure.md` |
| R6 | Repo: `docs/reviews/2026-10-10-codex-v3-partial-diagnosis.md` and its JSON |
| R7 | Repo: `docs/reviews/2026-10-10-codex-v3-return-diagnosis.md` and its `diagnosis.json` |
| R8 | Repo: `docs/reviews/2026-10-10-codex-v3-attempt-reconciliation.md` and |
|  | `docs/backtests/v3-20261010-failed-invocation/` |
| R9 | Repo: `docs/reviews/2026-10-10-proposed-v3-recovery.md` |
| R10 | Repo: `docs/reviews/2026-10-10-codex-cross-version-diagnosis.md` |
| R11 | Repo: `docs/superpowers/specs/2026-10-10-v3-1-design.md` |
| R12 | Repo: `docs/V3_1_SOURCE_INVENTORY.md` |
| R13 | Repo: `docs/reviews/2026-10-15-claude-v3-1-registration.md` |
| R14 | Repo: `docs/reviews/2026-10-17-claude-v3-1-verdict.md` (PR #286) |
| R15 | Repo: `docs/superpowers/specs/2026-10-17-v4-design.md` |
| R16 | Repo: `docs/RUN_ARCHIVE.md` |
| R17 | Repo: git history (merge commits; PR #287's commit `fe6273d`) |
| P1 | PC: `E:\adaptive-market-engine\v3\replay-20261009-01\` (`finished.json`, |
|  | `execution-task.json`, `started.json`) and `replay-logs-20261009-01\` |
| P2 | PC: `E:\adaptive-market-engine\v3\diagnosis-20261010\diagnosis.json` |
| P3 | PC: `E:\v31-run-38703911852\summary-out-4\summary\summary.md` and `verdict.json` |
| P4 | PC: `E:\v31-run-38703911852\analysis\findings-2026-10-17.md` |
| P5 | PC: `E:\v31-run-38703911852\analysis\tables-w1.txt` (table T1) |
| P6 | PC: `E:\v31-run-38703911852\summary-out-4\DEVIATION.md`, `meta\aggregate*.log`, |
|  | `meta\spotcheck.jsonl` |
| P7 | PC: `F:\v31-run-38703911852-backup\SHA256SUMS.txt` (its own SHA-256 and line count) |
| P8 | PC: folder listings and byte totals from file metadata, taken 2026-10-24 |

Zagreb time is CEST (UTC+2) for every date in this record before 2026-10-25.

## 3. V3.0: trend-following on perpetual futures

### 3.1 What it was

- **Strategy (R2 §1, §4, §7):** daily trend-following, long and short or long only. A
  menu of 12 fixed rules: R1 SMA50, R2 EMA 21/55, R3 Donchian 55/20, R4 12-month
  momentum, R5 Supertrend 10/3, R6 their equal blend, and the long-only twins R1L-R6L.
  Each quarter, the rule with the best Sharpe ratio over the previous 18 months traded the
  next 3 months (walk-forward). Signals came from spot daily closes; fills, profit and
  funding used futures prices.
- **Coins and venue (R2 §2-3):** BTC, ETH, BNB, SOL, XRP, ADA, DOGE, LTC, LINK and TRX,
  as Binance USDT-margined perpetuals. Data to 2024-12 only; the 2025+ window stayed shut.
- **Sizing (R2 §5):** volatility targeting at 20% x m a year, with caps of 10% x m per coin
  and 80% x m in total, and a leverage limit of m. The main test used m = 2 (40% target).
  m = 1 was run for the hold comparison (A5), m = 3 for information.
- **Account (R2 §6):** one 10,000 USDT cross-margin account on hourly bars. Daily
  decisions filled at the 01:00 UTC open, with 0.05% taker fee and 0.05% slippage per
  side, and published funding charged with its sign.
- **Safety (R2 status block, §6):** no stop-losses and no recovery, restart or peak reset.
  Sizing was the only risk control. The leverage limit was checked every hour and after
  every funding payment, with a liquidation check. Never more than 3x.
- **Pass rule (R2 §8):** all five of A1 Sharpe >= 1.0, A2 trade profit factor >= 1.3,
  A3 Calmar >= 0.5, A4 CAGR >= 8% (on the m = 2 run), and A5: the m = 1 run's Sharpe above
  the hold benchmark's. Because 2021-2024 had already been seen, a pass would only have
  been a "development pass", allowing a reserved-window confirmation and nothing more.

### 3.2 Pins

Spec frozen 2026-10-08 (draft PR #207 landed as `2675941`, freeze PR #209 as `66bddf8`).
The registration was corrected six times before any run (bootstrap seed, two accounting
tolerances, the all-invalid-quarter close, hold timing, local executor): R1 lines 27-39.
The seventh holds.
Config hashes are of the git blob (LF line endings), so check them with
`git show <commit>:<path> | sha256sum`, not on a Windows CRLF checkout.

| Item | Value |
| --- | --- |
| Trial | `v3-candidate-space-7` (registration 2026-10-09T14:10:44Z, R1) |
| Spec at `5822e0d` | `e337dbcaa89ca1bfeb5293f678aded60c3350aa8465c594e7a8c1c78aae3c191` |
| Code pin (PR #260) | `f622d4b1b6ffe6d92aaf31cb6b194919301af30b` |
| Code digest, 122 files | `da7192ac43ac90b1c8b5178bce78418d47728f7cd3146f2579581724d556f6f4` |
| Data manifest | `78d997a2f0a6e83705df339cc2ec0a0421faebdc18ee4337de8f07400a4b013a` |
| Run config | `49378c3dbce9ad7f29f6fa13ed3714b59d89176ab48881c1633cf7df28f3bdd2` |
| Execution task | `c28dc4fb9aef8f798f305f0c29e4e633351bcfb847b23b3bc23024e903bc486a` |
| Bootstrap `launch.py` | `737b9d45d354507674b61931debd248c4a03d5ee3ba98798772ecd71535f34ef` |
| Spot filter snapshot | `d5dbeeb908dde49269e7e654359b59981e7958636b2ed61103999bdec826b05d` |
| Futures filter snapshot | `db6a0c5bde5fc247224826f26be78729da74eecd2bc419a93728f255fd9244f4` |
| Result index | `bcd1936567dc8fe2894ec28cd898ec5eb20f41480472cb5a6a2d5d247d87250b` |
| Primary journal | `b2d0e8515e86d9ba9f4388df0a72ab9d42ceb11f27403f0a3a0a9bac403631af` |
| Failed hold journal | `117e3f4b6c10cc16116f9cd493865d5caa1c994bfc8f2632c94d46517682e773` |

The manifest is `config/datasets/v3-20261009/inventory.manifest.json`, the run config
`config/v3-development-run.json` and the task `config/v3-development-execution.json`
(R1 line 40, R4, P1). The execution revision was main `4d1e37c` (PR #261). The primary
journal (run `a16aa7a730c6476da353dc48ad7e9d81-out-of-sample-m2`) has 265,149 records
and 204,317,679 bytes (R6). The bootstrap equals the committed
`docs/reviews/2026-10-09-v3-local-launch.py.txt` (P1, checked 2026-10-24).

### 3.3 How it was tested

- **Data (R3):** 1,914 Binance archives (spot and futures hourly klines, funding), all
  checked against Binance's SHA-256 and recorded in the manifest, 68,680,581 bytes in
  all. A first collection attempt had failed and was kept: its spot snapshot exceeded a
  size ceiling (`docs/reviews/2026-10-09-codex-v3-collection-failure.md`).
- **Calendar (R3, R4):** BTC's first portfolio month was 2020-01, so the test ran
  2021-07-01 to 2025-01-01: 14 test quarters, 2021-Q3 to 2024-Q4. SOL's 2022-11 was
  excluded (funding file broke its schedule).
- **The menu (R4, R8):** 189 planned runs: 168 training runs (14 quarters x 12 rules),
  the walk-forward account at m = 2, the m = 1 and m = 3 runs and the doubled-cost runs
  (5 sensitivity runs), the 12 fixed-rule runs, and the hold comparisons.
- **Where and when (P1, R4):** one local run on the owner's PC by Codex Desktop, under an
  owner waiver of the GitHub workflow, with Bob's independent review. Started
  2026-10-09T21:28:08Z (23:28 CEST) at revision `4d1e37c`, Python 3.12.14; ended
  2026-10-10T04:40:37Z (06:40 CEST) with exit code 1. Files under
  `E:\adaptive-market-engine\v3\`. There was no GitHub run.

### 3.4 Results (saved futures evidence, diagnostic, never certified)

**The walk-forward account, m = 2, normal costs** (R6, R7):

| Measure | Value | Pass condition |
| --- | --- | --- |
| Equity | 10,000 to 13,446.86 USDT (+34.47%) | - |
| CAGR (A4) | 8.82% | >= 8%: met |
| Maximum drawdown | 66.82% | reported only |
| Sharpe (A1) | 0.412 | >= 1.0: missed |
| Trade profit factor (A2) | 1.235 | >= 1.3: missed |
| Calmar (A3) | 0.132 | >= 0.5: missed |
| A5, against the hold | unavailable (the hold run crashed) | - |
| Trades | 342: 97 won, 245 lost (28.36%) | - |

**Every saved run** (R6; CAGR and maximum drawdown in %). The walk-forward runs:

| Size m | Costs | CAGR | Max DD | Sharpe | Trade PF | Calmar |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 (main) | 1x | 8.82 | 66.82 | 0.412 | 1.235 | 0.132 |
| 1 | 1x | 6.81 | 40.29 | 0.443 | 1.301 | 0.169 |
| 1 | 2x | 5.17 | 41.81 | 0.361 | 1.221 | 0.124 |
| 2 | 2x | 5.11 | 68.71 | 0.319 | 1.132 | 0.074 |
| 3 | 1x | 6.79 | 82.78 | 0.397 | 1.143 | 0.082 |
| 3 | 2x | 1.15 | 84.21 | 0.300 | 1.023 | 0.014 |

Each fixed rule over the whole window, m = 2, normal costs. These are comparisons seen
after the fact, not candidates (R6):

| Rule | CAGR | Max DD | Sharpe | Trade PF | Calmar |
| --- | ---: | ---: | ---: | ---: | ---: |
| R1 | 9.66 | 58.08 | 0.429 | 1.100 | 0.166 |
| R1L | 28.64 | 53.59 | 0.892 | 1.771 | 0.535 |
| R2 | -13.92 | 75.66 | -0.169 | 0.767 | -0.184 |
| R2L | 26.86 | 50.97 | 0.850 | 2.107 | 0.527 |
| R3 | -0.97 | 65.30 | 0.168 | 0.982 | -0.015 |
| R3L | 19.05 | 53.28 | 0.701 | 1.785 | 0.358 |
| R4 | 31.10 | 45.31 | 0.875 | 1.994 | 0.686 |
| R4L | 34.90 | 46.46 | 1.017 | 3.906 | 0.751 |
| R5 | 11.74 | 50.01 | 0.477 | 1.125 | 0.235 |
| R5L | 21.16 | 55.87 | 0.712 | 1.640 | 0.379 |
| R6 | 1.84 | 63.64 | 0.248 | 1.026 | 0.029 |
| R6L | 21.51 | 54.02 | 0.742 | 1.685 | 0.398 |

**By calendar period, walk-forward account** (R7; opening equity at 00:00 UTC on 1 January):

| Period | Net, USDT | Return |
| --- | ---: | ---: |
| 2021-07 to 2021-12 | +1,039.61 | +10.40% |
| 2022 | -5,218.22 | -47.27% |
| 2023 | +1,155.33 | +19.85% |
| 2024 | +6,470.14 | +92.74% |

- **Months (R6):** best February 2024 (+31.87%) and November 2024 (+60.22%); worst March
  2023 (-19.57%). Mean month +1.51%; about 0.708% a month compounded over 42 months.
- **Worst drawdown (R7):** from 13,896.72 USDT on 2021-09-07 to 4,611.07 on 2023-04-26,
  9,285.65 USDT over 596.54 days. The peak was regained on 2024-12-03; an 18.12% drawdown
  followed before the end. All ten coins lost in that episode. Fees and net funding were
  about 6.11% of the fall; price exposure was the rest.
- **Costs (R7):** fees 442.68 USDT; funding paid 2,197.12, received 715.30, so 1,481.82
  net, about 3.35 times the fees. 2,481 fills; traded notional 885,365.21 USDT.
  Leverage after fills: mean 0.789, maximum 1.809.
- **Long against short (R6, R7):** 236 long trades made +7,369.11 USDT; 106 short trades
  lost 3,922.24, and still lost 3,845.27 before fees and funding.
- **By coin (R7, USDT):** BTC +1,155.56, BNB +1,093.44, TRX +1,085.42, SOL +742.31,
  XRP +482.18, ADA +436.08, ETH +430.03, DOGE -406.35, LINK -440.15, LTC -1,131.66.
- **By exit (R7):** 200 trades ending in a flip made -4,040.31 USDT and 121 ending at a
  zero signal -3,431.07. 239 of 245 losing trades had been in profit at some point.
- **Picks (R7 `diagnosis.json`), from the quarter named on:** 2021-07 R5L, 2021-10 R6L,
  2022-01 R5L, 2022-04 R2L, 2022-07 R1, 2022-10 R4, 2023-01 R5, 2023-07 R4, 2024-01 R4L,
  2024-07 R1L, 2024-10 R4L: 10 changes of rule over 1,280 daily decisions.

### 3.5 Verdict: none issued, and why

- **The crash (R5, P1):** run 187 of 189, the hold comparison at normal costs, failed with
  `SpotReplayExecutionError: ValueError: positive value required`. The two remaining hold
  runs never started. The cause: the saved spot filters give a minimum market quantity of
  0 for ADA, BTC, ETH and others, which the filter parser allowed but the spot account
  refused.
  The first hold purchase failed before settling. Fixed in PR #262 (`242faac`,
  2026-10-10T05:25Z, 07:25 CEST). The other 186 runs had completed (R8).
- **No verdict exists (R5, R8, P1):** `finished.json` records status `failed`, verdict
  `null` and no publication receipt. The register holds 187 result events: 186 `success`
  (meaning only that the run completed) and 1 `failed` (R1 lines 41-227).
- **What the evidence says (R6):** on the frozen formulas the main account misses A1
  (0.412 against 1.0), A2 (1.235 against 1.3) and A3 (0.132 against 0.5), and meets A4
  (8.82% against 8%). A pass needs all five, so a completed run could not have passed on
  these figures, but the figures were never certified.
- **No second run (R9, R11):** a one-time recovery run was proposed (PR #263) and never
  authorized or made. The V3.1 design, which the owner approved on 2026-10-10, says not
  to restart the failed V3 invocation. V3's hold comparison (A5) was never measured. The
  "matched spot hold" of V3.1 is a different, buy-once hold (R12).

### 3.6 What V3.0 taught

From R6, R7 and R10:
- Shorts were the losing side, even before costs. Every long-only twin had a higher CAGR
  than its long-and-short rule.
- More leverage did not help: m = 1, 2, 3 gave 6.81%, 8.82%, 6.79% CAGR with drawdowns
  of 40.29%, 66.82%, 82.78%.
- Funding was the largest explicit cost, but the big drawdown came from price exposure.
- The quarterly selector did worse than several fixed rules (a hindsight comparison).
- Profit came from a few months (February and November 2024).
- Direction flips and zero-signal exits lost money.

## 4. The cross-version diagnosis of 2026-10-10

Codex's read-only study of V0 to V3 (R10, PR #265). It re-checked 36 original GitHub
result artifacts (24 V1, 6 scored V2, 6 later V2) against their published SHA-256s, and
reused the V3 diagnosis. Its evidence is committed: `evidence.json`
(`2505f193ec78891d05d96353dd120ec78de4e5d23776ebbb07b120d8737c486b`) and `analyze.py.txt`
(`4d128f1990c38a87532cc44bb4b1e86da5f0258d59312d623ccade7cff2734be`) in
`docs/backtests/cross-version-20261010/`. On 2026-10-24 the PC copies
(`cross-version-evidence.json` and `analyze.py`) had exactly these hashes (P8).

What it found (R10):
- **V0/V1 grids** (means of 8 rows per configuration, each starting at 100 units): small
  grid wins did not pay for inventory exits. V0: grid sales +19.22, exits -24.57, net
  -5.35%. The best variant, F (order-flow block), still lost 0.62%. No configuration was
  profitable on average.
- **V2 mode switcher (BTC / ETH, 2019-2024):** cash 70.28% / 71.85% of the time, grid
  2.90% / 2.36%, uptrend 26.82% / 25.79%. Lifetime drawdown 21.91% / 11.02% against a 10%
  limit; its recovery reset the reference peak 10 and 9 times. In BTC's February 2024 rise,
  the RSI veto alone blocked 260 hourly decisions.
- **V3:** the figures of section 3.4.
- **Its advice for V3.1, in order:** a never-reset 30% lifetime risk limit; separate rules
  for long and short entries; avoid piling up filters; protect profit without clipping
  trend winners; price funding into entries; make the selector earn its place; bring the
  spot grid back only with evidence. The V3.1 design took these up as hypotheses (R11);
  section 5.7 shows how they fared.

## 5. V3.1: spot and futures in one account

### 5.1 What it was

From R11 and R13:
- **Strategies:** spot trend (long) when daily and 4-hour trends are both UP; futures
  short when both are DOWN with a bearish breakout, continuation or pullback; spot grid
  in a calm range; futures long only if a spot buy is too small. In conflict, only
  existing positions are managed; under stress, increases are cancelled. One strategy owns
  a coin at a time.
- **Market reading:** SMA20/SMA50, ADX14 above 20 with directional DI, 20-bar 4-hour
  breakouts, pullbacks within 1 ATR of the 4-hour SMA20, a stress test (4-hour ATR at 3x its
  median), an extension limit, and funding known at decision time.
- **Exits:** an initial stop 2 completed 4-hour ATR14 away; a trailing stop from 2R,
  following 3 ATR. Grid: three buy levels, spaced by the larger of 0.5 ATR and two
  round-trip costs, and an inventory stop.
- **Risk:** 0.5% of equity at risk per coin and 3% in total; 20% notional per coin; gross
  exposure 1.6x, absolute cap 2x; correlated groups capped at 80%; margin checks.
- **Shutdown and recovery:** at a 30% lifetime drawdown, cancel increases and close. After
  at least 24 hours, restart at quarter size with a 3% stop per recovery episode, half
  size below 15% drawdown, normal below 10%. The lifetime peak never resets.
- **Coins and venues:** the same 10 coins, on Binance spot and USDT-margined futures.

### 5.2 Pins

From R13 and R1 lines 228-229 (code commit `615b7a7`, branch base main `5357674`):

| Item | Value |
| --- | --- |
| Trial | `v3-1-registered-1` (registration 2026-10-15T02:16:34Z) |
| Spec at `5357674` | `dbf3b23222cef3eb36e5e8f337cb424b1917d3b23a2ce34a5f1bead64cbfca5d` |
| Code pin | `615b7a78fe71e5582ac87df32d50b28d9c091bc2` |
| Code digest, 176 paths | `af9fc72e213d32bac73e679f186d8ccf7d2556e98bf39376fdbe48ba95df0ff1` |
| Registration | `05b8315054ce12cdf3da8c818b1d8144f5f65a60a54e04e0d5a89bfe5867efa3` |
| Run-manifest | `41d841244d906019f2c512133a5e883902b4d05f6923159b714265d907d74254` |
| Prepare config | `71954170e9ebd35be5af1b199147df6f18e4b905912642e9d8ea961a02ce8293` |
| Window pack W1 | `1bc5feea67af4aa978e11ed6deb6947d35721c8de24008665b65e2b75f3341fd` |
| Window pack W0 | `16e4cce6c426944c3a38a411baa136ef5f6126412adbe31db38a43e6be44683c` |
| V3 input pack | `8a4780009bfe580995396b60fd30e52bbc21888a470e49eedb84910087a55dee` |
| V3 picks receipt | `8c707dbfbb1a40b8b46fce8fb9e67d3ce0e718f907170c32073a9cd2d0102b08` |
| `verdict.json` | `38e76612b712a7e064c3b21ef081d618701d17017f58e543db3d9d862510881d` |
| `summary.md` | `68e94b678334b11e3a5fe9905102c95fe3e3690fcae0a7f58bdb6698b4c85847` |

The registration is `config/v3_1_registration.json`, the run-manifest
`config/v3_1_run_manifest.json`, the prepare config `config/v3_1_prepare.json`. The data
manifests, filter snapshots, cost profiles, adapter pins and skipped-hour hashes are listed
in R13 ("Every pin"). The picks receipt is from P3; the two verdict files' hashes are in R14
and R1 line 230, and the PC files had them on 2026-10-24 (P8).

### 5.3 How it was tested

From R13:
- **Windows:** W1, 2021-07-01 to 2025-01-01 UTC, the 10 coins, the only judged window.
  W0, 2020-03-01 to 2025-01-01, 8 coins (no SOL, DOGE), full system only, reported only.
- **Capitals:** 10,000, 1,000 and 100 USDT ("research", "medium", "small").
- **Costs:** 1x (spot fee 0.10%, futures fee 0.05%, slippage 0.05% each) and 2x.
- **Price-path scenarios:** open-low-high-close (olhc) and open-high-low-close (ohlc).
- **Arms:** the full system (`combined`, the only judged arm); 4 components alone; 5
  ablations (without continuation, short qualification, trailing stop, funding admission,
  recovery).
- **Baselines (32):** the unchanged V3 selector, V3's six long-only rules, a matched
  buy-once spot hold, and the minute-based V0, V1 (9 variants) and V2 grids and
  comparator D, each of these in both path modes.
- **Cells:** 324, each run once: in W1 120 V3.1, 42 V3, 6 hold and 144 minute-baseline
  cells; in W0 12. Skipped hours, the same for every arm: 140 in W1, 159 in W0.
- **Pass rule:** in every W1 cell, the full system must strictly beat every baseline on
  compounded return and on return / maximum drawdown, at every capital, both costs and
  both scenarios. Also needed: lifetime maximum drawdown at most 30%, net profit at
  doubled costs, no liquidation or unexplained accounting residual, and every comparison
  present.
- **The run:** GitHub Actions run **38703911852**, dispatched once from main `d4a4f09` at
  2026-10-15T08:11:32Z (10:11 CEST), on the owner's go of 00:56Z (02:56 CEST, v31-d26).
  All cells succeeded; the last finished about 18:37Z (R14).
- **Files:** downloaded to `E:\v31-run-38703911852\`, backed up to
  `F:\v31-run-38703911852-backup\` (R16).

### 5.4 Results

**The 12 judged cells, full system, W1** (P3; return and drawdown on the common hourly
series, as acceptance measured them):

| Capital, costs | olhc return | olhc max DD | ohlc return | ohlc max DD |
| --- | ---: | ---: | ---: | ---: |
| 10,000, 1x | incomplete | - | -21.35% | 35.28% |
| 10,000, 2x | -27.67% | 37.88% | -26.60% | 37.71% |
| 1,000, 1x | -22.48% | 35.93% | -23.60% | 36.57% |
| 1,000, 2x | -27.11% | 37.97% | -27.01% | 37.99% |
| 100, 1x | -17.83% | 30.20% | -17.83% | 30.21% |
| 100, 2x | -4.84% | 19.24% | -4.84% | 19.24% |

Every cell beats 0 of 32 baselines on return. On return / drawdown, three cells (1,000 1x
in both scenarios, and 10,000 1x ohlc) beat 8 of 32: the V0 grid and V1's e, g and h
grids, in both path modes. The rest beat none (P3).
The incomplete cell crashed (section 5.6); its later diagnostic replay, not part of the
verdict, ended at -22.25% with a 35.53% drawdown (P4, R14).

**Every arm** (P5, table T1): mean return / mean maximum drawdown in %. V3.1 arms average
4 cells (2 scenarios x 2 costs); baselines average 2 cells (2 costs, native timing). An
asterisk counts cells that crashed early at 10,000 USDT, which pull those means up.

| Arm | 10,000 USDT | 1,000 USDT | 100 USDT |
| --- | --- | --- | --- |
| combined (full system) | -19.4 / 32.0 (1*) | -25.0 / 37.3 | -11.3 / 25.1 |
| spot trend alone | -19.4 / 32.1 | -19.1 / 32.3 | -1.2 / 16.3 |
| futures trend alone | -19.1 / 35.6 | -18.6 / 34.1 | -10.5 / 29.4 |
| futures trend, long only | -17.1 / 31.8 | -15.8 / 31.6 | +10.2 / 19.3 |
| spot grid alone | -10.8 / 11.0 | -13.5 / 13.7 | -0.4 / 0.7 |
| without continuation | -18.6 / 32.0 (1*) | -25.9 / 37.6 | -10.1 / 22.4 |
| without trailing stop | -3.6 / 22.9 (3*) | -15.9 / 36.6 | -13.3 / 29.6 |
| without short qualification | -18.0 / 32.0 (1*) | -23.8 / 35.9 | +0.2 / 15.5 |
| without funding admission | -19.4 / 32.0 (1*) | -25.0 / 37.3 | -11.3 / 25.1 |
| without recovery | -14.2 / 26.7 (1*) | -19.3 / 30.6 | -11.2 / 24.9 |
| V3 selector, unchanged | +26.8 / 66.5 | +27.6 / 65.0 | +24.6 / 46.1 |
| V3 R1L | +124.8 / 54.4 | +121.9 / 52.5 | +96.6 / 26.7 |
| V3 R2L | +124.0 / 48.7 | +123.4 / 47.2 | +138.7 / 29.2 |
| V3 R3L | +80.5 / 53.4 | +78.0 / 53.1 | +97.2 / 31.0 |
| V3 R4L | +178.0 / 46.3 | +165.2 / 44.5 | +101.3 / 29.3 |
| V3 R5L | +90.0 / 56.0 | +88.8 / 54.7 | +109.2 / 31.9 |
| V3 R6L | +89.7 / 54.7 | +88.4 / 53.0 | +84.6 / 28.6 |
| matched spot hold | +120.0 / 80.7 | +120.0 / 80.7 | +119.2 / 80.5 |
| D trend (high first) | +77.3 / 57.4 | +77.4 / 57.4 | +77.2 / 57.3 |
| D trend (low first) | +77.2 / 57.4 | +77.4 / 57.4 | +77.2 / 57.3 |
| V2 grid (each path mode) | -3.1 / 14.0 | -2.7 / 14.2 | -1.7 / 14.2 |
| V0 grid (high first) | -2.5 / 4.9 | -2.5 / 4.9 | incomplete |
| V0 grid (low first) | -1.9 / 4.3 | -1.9 / 4.3 | incomplete |

The nine V1 variants' rows lie between -3.8% and +1.8% in return and 1.1% and 6.5% in
drawdown at 10,000 and 1,000 USDT. Every V0 and V1 cell at 100 USDT was incomplete (P5).
The completed crashed cells' corrected means (P4, correction of 2026-10-19): full system
about -24.5% at 10,000 USDT; without trailing stop about -15.0%; without recovery
about -18.1%.

**A cross-check of V3.0:** the unchanged V3 selector at 10,000 USDT, 1x costs, made
+34.47% inside V3.1 (P3), the same as V3.0's own main account (R6).

**Inside the full system, at 10,000 USDT** (P4; per simulation, the sum of 4 cells / 4):
- spot trend, long: -1,479 USDT; 383 trades, 32% won; profit given back from trade peaks
  7,300. By year: 2021 +107, 2022 -1,151, 2023 -304, 2024 -130.
- futures shorts: -109 USDT. By year: 2021 -253, 2022 +906, 2023 -549, 2024 -213.
- spot grid: -349 USDT; 65% of trades won, but target exits (+1,074) were outweighed by
  range exits (-1,047) and stops (-1,667); P4 marks these three "all caps".
- by entry type, all capitals: spot pullback -5,401, continuation -1,124, breakout -162;
  short continuation +2,580, pullback -2,371, breakout -669.
- most spot-trend trades ended at the initial stop: 3,629 trades, -7,547 USDT (all
  capitals).
- the 30% shutdown fired in 9 of 12 full-system cells, all between 2023-03-20 and
  2023-04-20, at about 80-83% of starting equity; 7-8 recovery episodes followed.
- of 427,745 opportunities seen, the most frequent blocks were portfolio capacity
  (122,618), below the exchange minimum (121,068) and grid child orders below the minimum
  (45,870).

**W0, reported only** (P3; net return / maximum drawdown):

| Capital | olhc 1x | ohlc 1x | olhc 2x | ohlc 2x |
| --- | --- | --- | --- | --- |
| 10,000 | -2.15 / 36.24 | +0.56 / 36.03 | -10.84 / 36.98 | -12.35 / 37.19 |
| 1,000 | -0.60 / 35.61 | -1.46 / 36.33 | -10.32 / 36.28 | -10.64 / 36.49 |
| 100 | +8.50 / 31.36 | +8.51 / 33.05 | +8.06 / 33.47 | +18.44 / 12.36 |

### 5.5 Verdict: FAIL, and exactly why

From P3, R14 and R1 line 230:
- **Cells:** 312 W1 and 12 W0 cells completed; 0 failed, killed, missing or invalid. No
  re-run and no second dispatch.
- **535 acceptance failures:**
  - 9 cells with a maximum drawdown above 30%: 10,000 USDT ohlc 1x and both 2x; 1,000
    USDT all four; 100 USDT both 1x. The worst on the common series was 37.99%
    (1,000 USDT, ohlc, 2x), against the 30% limit.
  - 6 cells not profitable at doubled costs: all six 2x cells, from -27.67% to -4.84%.
  - the rest: the full system did not strictly beat a baseline.
- **48 incomplete outcomes:** 40 small-capital minute-grid baselines and 8 V3.1 cells at
  10,000 USDT that stopped early.
- **Why FAIL and not "incomplete":** the registered acceptance code returns fail when any
  failure exists, before it considers missing evidence. The 30% and doubled-cost failures
  rest on the 12 combined cells, which were fully re-verified (section 5.6).
- **Register:** status `failed`, the GitHub run's own conclusion, with the local FAIL
  verdict and the deviations in its reason (R1 line 230).

### 5.6 Incidents during the run

- **GitHub's summary job died on a full disk.** Aggregate job 116602181861 failed at
  2026-10-15T18:49:44Z (20:49 CEST): "No space left on device" while downloading the
  artifacts, 6.14 GB zipped and 107 GB unpacked (R14). The one aggregate-only re-run the
  owner had allowed (v31-d28) was not used: it would fail the same way.
- **Owner decisions to compute the verdict locally** (R14, P6):
  - **v31-d30** (18:57Z, 20:57 CEST): run the frozen aggregate at `d4a4f09` on the PC. All
    328 artifact zips matched GitHub's upload digests. Python 3.14.7 (3.12 on GitHub).
  - **v31-d31:** more virtual memory. Attempt 1 (from 19:37Z) hit a MemoryError at a
    35.8 GB commit limit; attempt 2 (from 20:19Z) was killed by a Windows Update restart;
    attempt 3 (from 23:46Z) read everything in about 8 hours, but the report rebuild took
    over 30 minutes per judged cell, one to two weeks in all.
  - **v31-d32** (2026-10-16): a wrapper skipped only that rebuild. Attempt 4 ran from
    09:15:21Z and finished 21:51:51Z (23:51 CEST) with status fail. No frozen file was
    edited. The full rebuild was run on the 12 judged combined cells: all 12 equal their
    saved reports. One of them, olhc 1x at 10,000 USDT, also fails the end-point check
    because its replay stopped early. The other 300 judged cells' reports were not rebuilt.
- **The crash in 8 cells.** Eight V3.1 cells at 10,000 USDT stopped early with
  `replay_failure:execution_failure:ValueError`, "novel fill contradicts acknowledged
  finality". Root cause: inside one settlement batch, the routine cap check could cancel
  the very order whose fill was being booked (R17, `fe6273d`). Fixed in PR #287, with
  follow-ups in PR #288, merged 2026-10-19 23:19Z and 23:46Z (2026-10-20 01:19 and 01:46
  CEST). GitHub diagnostic run 39321704392 replayed the 8 cells with the fix; all
  completed with no liquidation. It is not part of the verdict (P4, R14).
- **A wrong figure, corrected.** The first analysis said removing the trailing stop gave
  -19% to -4% at 10,000 USDT. Three of those four cells were crashed ones. Corrected on
  2026-10-19 to about -24.5% to about -15% (P4, R14).
- **Scale finding (R14, R15):** the frozen aggregate could never have run on GitHub at
  real scale. It needed 107 GB of disk, about 75 GB of memory, and more time than the
  335-minute step limit. The rehearsals used three-day synthetic windows and never showed
  it.

### 5.7 What V3.1 taught

From P4, R14 and R15:
- Every V3.1 component lost money; the spot trend lost most, with most trades ending at
  the initial 2-ATR stop and about five times the final loss given back from peaks.
- Pullback entries were the worst type. Short continuation entries in a confirmed
  downtrend were the only clearly profitable ones, mostly in 2022.
- The grid lost in every year, as in V1.
- The 30% shutdown fired in 9 of 12 combined cells in March-April 2023, and the
  quarter-size recovery after it lost more. Removing recovery helped about 6 points.
- Removing the trailing stop helped most, about 9.5 points, and still lost money.
- V3's slow daily long-only rules made the most of any arm (up to +178.0% mean for R4L at
  10,000 USDT, P5). Exchange minimums distorted the 100 USDT capital (R13, R15).
- A verdict step must be resumable and memory-light, with each cell verifying its own
  report.

## 6. What V4 changed because of V3.0 and V3.1

From R15 ("Why V4 exists", owner decisions v4-d01 to v4-d23, "Safety", "Engineering",
"Pass rule"):

- **Slow daily trend with volatility sizing worked (V3).** V4 uses three daily speeds
  (SMA20; EMA 21/55 with V3's Donchian 55/20; SMA200), V3's volatility sizing, and holds
  until the signal turns.
- **Stops, trailing, shutdown and recovery hurt (V3.1).** V4 has no tight stop, no
  trailing stop, no lifetime shutdown and no recovery mode. There is no hard drawdown
  limit; the worst drop is reported and decides nothing (v4-d02).
- **The grid lost every year in V3.1, as in V1 (R15).** V4 has no grid arm ("Versions in the run").
- **Shorts lost in V3; only confirmed-downtrend shorts paid in V3.1.** V4's shorts key on
  the medium speed plus a confirmed market reading (v4-d08). A version that shorts only
  while BTC is below its SMA200 is reported (v4-d22).
- **Funding was V3's largest explicit cost.** V4's additions include "longs on spot
  first" and "funding on shorts" (v4-d09).
- **100 USDT was broken by exchange minimums.** V4 runs 1,000 and 10,000 USDT only
  (v4-d05).
- **Hand-picked coins flatter results (R2 §3).** V4 chooses coins by a rule, the monthly
  top 10 (v4-d09, v4-d16).
- **V3.1 had to beat 32 baselines, on years already seen.** V4's pass rule has four
  conditions: beat holding the universe on return / drawdown, beat V3 as built on return,
  profit at doubled costs, and gain after 2025-01-01 (v4-d04). The 2025+ window is opened
  for V4, and forward paper trading is the final test (v4-d03).
- **The aggregate could not scale.** Each V4 cell verifies its own report, and the verdict
  step resumes after an interruption and needs at most 2 GB of memory and 5 GB of disk.
- **The V3.1 crash.** Fixed first, in the shared code V4 reuses (PR #287).
- **What worked mechanically in V3.1 is kept:** the shared spot and futures account, the
  market reading, the decision records, exact accounting and margin safety.

## 7. Files on the owner's PC that are to be deleted

Sizes are as given for this record, in the units Windows shows (GiB). The byte counts
come from file metadata only (P8). No large folder was read or hashed.

| Folder | Size | Bytes (P8) | What it holds |
| --- | ---: | ---: | --- |
| `E:\v31-run-38703911852\` | 142.4 GB | not measured | V3.1 working copy |
| `F:\v31-run-38703911852-backup\` | 35.2 GB | 37,807,960,663 | V3.1 backup |
| `E:\v31-diag\` | 0.5 GB | 569,084,582 | V3.1 crash diagnosis |
| `E:\adaptive-market-engine\` | 17.3 GB | 18,612,701,825 | V3.0 run, cross-version |

**`E:\v31-run-38703911852\`** (R16, P8): `zips\`, the 328 artifacts as downloaded
(6,143,387,351 bytes); `meta\` (`artifacts.tsv`, `zips.json` with each zip's SHA-256 and
GitHub digest, `files.tsv`, and the download, verify, aggregate, memory and spot-check
logs); `summary-out-4\` (`verdict.json`, `summary.md`, 132 report pages, `DEVIATION.md`,
the wrapper; 31,400,755,674 bytes); empty `summary-out\`, `summary-out-2\` and
`summary-out-3\` from aggregate attempts 1-3; `analysis\` (findings, tables, 324 per-cell
statistics files); `scripts\` (11 scripts); `cells\`, the artifacts unpacked (107 GB).
This copy has no `SHA256SUMS.txt` of its own.

**`F:\v31-run-38703911852-backup\`** (R16, P7, P8): `zips\`, `meta\`, `summary-out-4\`,
`analysis\`, `scripts\`, and since 2026-10-19 `diagnostic-replay-2026-10-19\` (the 8
replay zips of run 39321704392 and `artifacts.tsv`), plus `SHA256SUMS.txt`: 967 files.
`SHA256SUMS.txt` has **966 lines** and its own SHA-256 is
`3720870ced59d11e2700597fb56e9161562570739b0ac1da8a7717dc100a85e2`.

**`E:\v31-diag\`** (P8): the local reproduction of the crash (`run1-valueerrors.txt`,
`run2-finality.txt` to `run4-finality.txt`, four cell outputs, prepared packs), a local
replay attempt whose 8 cells all exited with code 127 (`replay8\`), and `replay8-github\`,
the same 8 diagnostic zips and `artifacts.tsv` as on F: (same file sizes; the two
`artifacts.tsv` files are byte-identical).

**`E:\adaptive-market-engine\`** (R3, R4, P1, P8):
- `v3\replay-20261009-01\`: the V3 run's 187 attempts, 561 files (start, finish,
  journal each), 17,973,500,680 bytes, plus the run's start and finish records. The
  repository records no other copy (R3: "No independent backup has been verified").
- `v3\replay-logs-20261009-01\`: launch script, start and end records, stdout, stderr.
- `v3\replay-checkout-20261009-01\`: the checkout at `4d1e37c`; `v3\python312\`: the
  isolated Python 3.12.14.
- `v3\inventory-20261009-02\`: the 1,914 archives, two snapshots and the manifest
  (68,680,581 bytes); `v3\inventory-20261009-01\` is the empty failed first attempt.
- `v3\collector-5822e0d\`, `v3\collector-6fae092\`, `v3\inputs-5822e0d\`,
  `v3\logs-20261009-01\`, `v3\logs-20261009-02\`: the collector checkouts, inputs and logs.
- `v3\failure-analysis-20261010-01\` to `-03\` and `v3\diagnosis-20261010\`: the V3
  diagnoses. The `-03` copy of `futures-diagnostics.json` equals the committed one
  (`6be7d3f6a7de292948ea61da4c46bf49deb84514d2500353b6eacef1ca4e7ac4`). The `-01` copy
  differs: an earlier output, and R6 says the revised extractor added only a source
  inventory. The `diagnosis-20261010` copy is the pre-review return diagnosis (section 8).
- `cross-version-diagnosis-20261010\`: the 36 downloaded GitHub result artifacts
  (runs 37441444046 to 37685401222; 403,340,926 bytes), `analyze.py`,
  `cross-version-evidence.json` and `pr-body.md`.

**How to check anyone's copy after the deletion:**

```sh
sha256sum SHA256SUMS.txt          # V3.1 backup root: expect 3720870c...a85e2, 966 lines
sha256sum -c SHA256SUMS.txt       # every listed file
sha256sum summary-out-4/summary/verdict.json   # 38e76612...0881d
```

The V3 run's identities (spec, code, manifest, config, journals) are in section 3.2 and in
`docs/backtests/v3-20261010-failed-invocation/`, whose `artifact-sha256.json` pins its own
files. The V3.1 registration and run-manifest are on `main` (section 5.2).

**What remains after the deletion:**
- in the repository: the register events (R1), the specs, these reviews, the committed V3
  evidence under `docs/backtests/v3-20261010-*` and `cross-version-20261010/`, and this
  record;
- on GitHub: the 328 artifact zips of run 38703911852, until GitHub deletes them on
  2027-01-13 08:11 UTC (09:11 CET), as R16 records (not re-checked). The retention of
  diagnostic run 39321704392's artifacts is not recorded;
- the 1,914 V3 market-data archives are public Binance files whose SHA-256s are in the
  committed manifest, so a re-fetch can be checked against it (R2 §2, R3);
- nothing else: the V3 journals, the V3.1 cell folders, report pages and per-cell
  statistics have no other recorded copy.

## 8. Where the sources disagree

1. **V3 calendar returns.** The PC's `diagnosis-20261010\diagnosis.json` (P2) is the
   pre-review version: 2022 -47.10%, 2023 +20.23%, 2024 +91.52%. The committed, reviewed
   `diagnosis.json` (R7) gives -47.27%, +19.85% and +92.74%, with calendar boundaries at
   the 00:00 UTC opening equity. R10 calls these the "corrected" figures. This record uses
   R7. 2021 is the same in both (+10.40%).
2. **The full system at 10,000 USDT.** P4's table and R15 say about -19%. That mean
   includes the crashed cell, stopped near its starting balance. P4's own correction of
   2026-10-19 gives about -24.5% with the replayed cell. The verdict used cells, not means.
3. **V3's rules inside V3.1.** R15 and P4 say long-only +78% to +178% and selector +25% to
   +28%: means per capital over both costs (P5). R14 says +75% to +186% and +19% to +35%:
   the single-cell range (P3). Same cells, two summaries.
4. **W0's dates.** P4 labels W0 "2020-03..2021-07", and R15 repeats that the full system
   "lost 6% even in the 2020-21 bull market". The registration (R13, R1 line 228) and the
   prepare config define W0 as 2020-03-01 to 2025-01-01. P4's -6.2% matches the mean of
   P3's four 10,000 USDT W0 cells, which cover that full window. W0 decides nothing.
5. **Two drawdown measures.** P3 measures drawdown on the common hourly series. A cell's
   own report uses every native mark: for ohlc 1x at 10,000 USDT, 35.28% in P3 and 35.64%
   in `meta\spotcheck.jsonl` (P6). The 30% gate uses every native mark (R13).
6. **The backup's file count.** R16 says 957 files, about 38 GB, verified 2026-10-17. Now
   `SHA256SUMS.txt` has 966 lines and the folder 967 files, 37,807,960,663 bytes: about
   38 GB in decimal units, the 35.2 GB of section 7 in Windows' units (P7, P8). The
   diagnostic replay copy (9 files) was added on 2026-10-19. The list's lines were not
   read, so it was not checked that they name those 9 files.

## 9. Limits of this record

- Every number is copied from a named source. None was recomputed, except the one check
  of section 8, item 4, and the byte totals and file counts of section 7. V3.0's figures
  are uncertified diagnostics from saved journals (R6). V3.1's comparisons rest partly on
  300 reports that were not rebuilt (R14).
- Nothing large was hashed. On the PC only `SHA256SUMS.txt`, the two V3.1 verdict files,
  the bootstrap and a few small V3 and cross-version files were hashed (P8).
- I found no recorded owner decision on V3's recovery proposal (R9). The record shows only
  that it was never run.
- `E:\v31-code-d4a4f09\` (a code checkout used by the diagnosis) also exists. It was not in
  the list of folders to delete and is not described here.
