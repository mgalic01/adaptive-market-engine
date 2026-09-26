# V0 development scorecard (C1–C6, R1)

- **Task file:** `docs/tasks/2026-09-25-bob-v0-dev-scorecard.md`
- **Written by:** Bob, 2026-09-26
- **Status:** diagnostic on development windows only; not a selection or performance claim.
  No parameter was tuned on these results.

---

## 1. Run metadata

| Item | Value |
| --- | --- |
| Commit | `876f7ce9d3a32b4a31bc558a0eb038a462c1472e` |
| Python version | 3.12.14 |
| Start time | 2026-09-26T00:45:20Z |
| End time | 2026-09-26T01:23:41Z |
| Spec | `config/default.toml` |
| Primary fees | maker 0, taker 0.0009 |
| Reference fees | maker 0.001, taker 0.001 |

### Commands run

```
# Step 1: fetch and verify
python -m crypto_grid_bot.backtest fetch --spec config/datasets/practice-2022.toml --data-dir data
git checkout -- config/datasets/practice-2022.manifest.json
python -m crypto_grid_bot.backtest verify --spec config/datasets/practice-2022.toml --data-dir data \
  > data/verify-practice-2022.json

python -m crypto_grid_bot.backtest fetch --spec config/datasets/verify-2024h1.toml --data-dir data
git checkout -- config/datasets/verify-2024h1.manifest.json
python -m crypto_grid_bot.backtest verify --spec config/datasets/verify-2024h1.toml --data-dir data \
  > data/verify-verify-2024h1.json

# Step 2: runs
python -m crypto_grid_bot.backtest run --spec config/datasets/practice-2022.toml \
  --data-dir data --out data/backtests --jobs 4 --maker-fee 0 --taker-fee 0.0009 \
  | tee data/run-practice-2022-m0-t0.0009.log
python -m crypto_grid_bot.backtest run --spec config/datasets/practice-2022.toml \
  --data-dir data --out data/backtests --jobs 4 --maker-fee 0.001 --taker-fee 0.001 \
  | tee data/run-practice-2022-m0.001-t0.001.log
python -m crypto_grid_bot.backtest run --spec config/datasets/verify-2024h1.toml \
  --data-dir data --out data/backtests --jobs 4 --maker-fee 0 --taker-fee 0.0009 \
  | tee data/run-verify-2024h1-m0-t0.0009.log
python -m crypto_grid_bot.backtest run --spec config/datasets/verify-2024h1.toml \
  --data-dir data --out data/backtests --jobs 4 --maker-fee 0.001 --taker-fee 0.001 \
  | tee data/run-verify-2024h1-m0.001-t0.001.log

# Step 3: scoring
python data/score.py
```

### SHA-256 hashes

| File | SHA-256 |
| --- | --- |
| `data/score.py` | `8324d14b275e672e1e29d2511609144fe4c2a610cc44de5c091d4ce222d04c2b` |
| `data/backtests/practice-2022/20260926T010022Z-m0-t0.0009/results.json` | `f0167a194fdc935daea07750a88fc8c4b0911678665e8e565a31ab7040c841da` |
| `data/backtests/practice-2022/20260926T011114Z-m0.001-t0.001/results.json` | `58504abe5ca6ec914a64244aea4ea14ee55093f2428677ef9e2cb272d121376f` |
| `data/backtests/verify-2024h1/20260926T011617Z-m0-t0.0009/results.json` | `343cbfc056538985756eec55db8a9d3c71318bbffa9ebbb96b159e3da8428b77` |
| `data/backtests/verify-2024h1/20260926T012149Z-m0.001-t0.001/results.json` | `15f9e9c67651ee95774cd18a680d4bb77e4fa2777b774cd61f310c622723e6c4` |

---

## 2. Data verification

Both `verify` commands exited 0 with `"status": "valid"` and `"version": "drift-tolerance-v1"`.

All hourly cross-checks clean: zero `hours_mismatched`, `hours_missing`, `hours_absent_from_minutes`,
`hours_absent_from_both`, `hours_incomplete`, `minutes_missing` for every traded pair and the market
proxy. All breadth-basket symbols had zero `series_hours_missing` and `series_hours_duplicated`.
Source: `data/verify-practice-2022.json` and `data/verify-verify-2024h1.json`.

Manifests were restored by `git checkout -- config/datasets/practice-2022.manifest.json` and
`git checkout -- config/datasets/verify-2024h1.manifest.json` immediately after each fetch.
`git status --porcelain` showed a clean working tree before each run. The repo stayed clean
throughout.

---

## 3. Result counts

| File | Results | Valid |
| --- | ---: | --- |
| practice-2022 primary (m0, t0.0009) | 12 | No (SOL only) |
| practice-2022 reference (m0.001, t0.001) | 12 | No (SOL only) |
| verify-2024h1 primary (m0, t0.0009) | 8 | Yes |
| verify-2024h1 reference (m0.001, t0.001) | 8 | Yes |

12 = 3 pairs × 2 paths × 2 strategies; 8 = 2 pairs × 2 paths × 2 strategies.
Counts match task expectations. Source: `len(d["results"])` in `data/score.py`.

---

## 4. Comparison mask (§5)

### Exchange-filter check — SOLUSDT practice-2022

The `results.json` failures list from `result_failures()` in
`src/crypto_grid_bot/backtest/__main__.py` (line 199) reports `transient_pauses`
(field name from `Metrics.transient_pauses`, defined at line 207 of `replay.py`):

```
SOLUSDT/high_first/gated grid (price-only-v1): 82792 rejected frames
SOLUSDT/high_first/ungated grid baseline: 82792 rejected frames
SOLUSDT/low_first/gated grid (price-only-v1): 82792 rejected frames
SOLUSDT/low_first/ungated grid baseline: 82792 rejected frames
```

Every SOLUSDT run (gated and ungated, both paths) has 82,792 rejected frames.
Every non-SOLUSDT run (BTCUSDT and XRPUSDT in practice-2022; ADAUSDT and BTCUSDT in
verify-2024h1) has zero rejected frames. Assertion verified in `data/score.py`.

This matches the exchange-filter cause described in §5 and in
`docs/backtests/fee-levels-2026-09.md` (Validity section): today's SOL tick (0.01)
at 2022 prices of roughly $10–14 makes the simulated spread exceed the 0.15% limit.
The `transient_pauses` field in `results.json` is produced by `result_failures()` in
`__main__.py`.

**Mask decision:** SOLUSDT is excluded from practice-2022 for every variant.
This is a mask exclusion (§5), not a failed V0 run, and does not count under C4.

### Included pair-windows

| Dataset | Pairs | Note |
| --- | --- | --- |
| practice-2022 | BTCUSDT, XRPUSDT | SOLUSDT excluded (exchange-filter invalidity) |
| verify-2024h1 | ADAUSDT, BTCUSDT | All pairs valid |

Minimum evidence rule (§5): practice-2022 keeps 2 pairs; verify-2024h1 keeps 2 pairs. Both windows meet the minimum.

---

## 5. Per-run table (primary fees: maker 0, taker 0.0009)

Fields sourced from `results.json` `results` array per run:
`return_pct`, `max_drawdown_pct`, `active_max_drawdown_pct`, `hard_drawdown_halts`,
`buy_and_hold_max_drawdown_pct`, `completed_cycles`, `time_with_inventory_pct`.

Rate = `completed_cycles ÷ (window_days ÷ 7)` (exact; see C5).

| Dataset | Pair | Path | Strategy | Return % | Max DD % | Active DD % | Hard Halts | B&H DD % | Cycles | Rate | Inv % |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| practice-2022 | BTCUSDT | high_first | gated | +1.2152 | 5.3547 | 5.3964 | 0 | 51.4461 | 81 | 2.3143 | 9.13 |
| practice-2022 | BTCUSDT | low_first  | gated | +2.9805 | 5.3490 | 5.3909 | 0 | 51.4461 | 87 | 2.4857 | 9.08 |
| practice-2022 | XRPUSDT | high_first | gated | −4.1472 | 10.9344 | 11.1611 | 0 | 46.2904 | 99 | 2.8286 | 8.73 |
| practice-2022 | XRPUSDT | low_first  | gated | −2.8657 | 10.4723 | 10.7280 | 0 | 46.2904 | 100 | 2.8571 | 9.04 |
| practice-2022 | SOLUSDT | high_first | gated | −10.0149 | 10.6239 | 10.6239 | 0 | 83.4618 | 0 | 0 | 0.25 | **EXCLUDED** |
| practice-2022 | SOLUSDT | low_first  | gated | −9.8852 | 10.5362 | 10.5362 | 0 | 83.4618 | 0 | 0 | 0.25 | **EXCLUDED** |
| verify-2024h1 | ADAUSDT | high_first | gated | −8.4371 | 10.0561 | 10.0846 | 0 | 55.8376 | 11 | 0.4231 | 1.11 |
| verify-2024h1 | ADAUSDT | low_first  | gated | −8.3808 | 10.0008 | 10.0292 | 0 | 55.8376 | 11 | 0.4231 | 1.11 |
| verify-2024h1 | BTCUSDT | high_first | gated | −7.8841 | 9.2825 | 9.3057 | 0 | 23.3194 | 21 | 0.8077 | 3.27 |
| verify-2024h1 | BTCUSDT | low_first  | gated | −7.9276 | 10.3249 | 10.3713 | 0 | 23.3194 | 42 | 1.6154 | 5.06 |

Ungated baseline (needed for C6):

| Dataset | Pair | Path | Return % | Max DD % |
| --- | --- | --- | ---: | ---: |
| practice-2022 | BTCUSDT | high_first | −5.6692 | 8.4150 |
| practice-2022 | BTCUSDT | low_first  | −6.4178 | 9.1578 |
| practice-2022 | XRPUSDT | high_first | −8.5674 | 10.0495 |
| practice-2022 | XRPUSDT | low_first  | −8.5490 | 10.0501 |
| verify-2024h1 | ADAUSDT | high_first | −10.5781 | 12.1986 |
| verify-2024h1 | ADAUSDT | low_first  | −10.5781 | 12.1986 |
| verify-2024h1 | BTCUSDT | high_first | −7.2858 | 8.5542 |
| verify-2024h1 | BTCUSDT | low_first  | −7.0894 | 8.7724 |

---

## 6. Criterion results (primary fees: maker 0, taker 0.0009)

### C1 — Worst drop

C1 spec (§6): (a) `max_drawdown_pct` ≤ 10 in every included run. (b) `active_max_drawdown_pct` ≤ 10
and `hard_drawdown_halts == 0` in every included run.

Fields sourced from `results.json`: `max_drawdown_pct` (total-equity drawdown), `active_max_drawdown_pct`
(defined at `Metrics.active_max_drawdown`, `replay.py` line 232), `hard_drawdown_halts`
(`replay.py` line 233).

| Dataset / Pair / Path | max DD % | ≤ 10? | active DD % | halts | both ≤ 10 & halts=0? |
| --- | ---: | --- | ---: | ---: | --- |
| practice-2022 BTCUSDT high_first | 5.3547 | PASS | 5.3964 | 0 | PASS |
| practice-2022 BTCUSDT low_first | 5.3490 | PASS | 5.3909 | 0 | PASS |
| practice-2022 XRPUSDT high_first | 10.9344 | **FAIL** | 11.1611 | 0 | **FAIL** |
| practice-2022 XRPUSDT low_first | 10.4723 | **FAIL** | 10.7280 | 0 | **FAIL** |
| verify-2024h1 ADAUSDT high_first | 10.0561 | **FAIL** | 10.0846 | 0 | **FAIL** |
| verify-2024h1 ADAUSDT low_first | 10.0008 | **FAIL** | 10.0292 | 0 | **FAIL** |
| verify-2024h1 BTCUSDT high_first | 9.2825 | PASS | 9.3057 | 0 | PASS |
| verify-2024h1 BTCUSDT low_first | 10.3249 | **FAIL** | 10.3713 | 0 | **FAIL** |

**C1(a): FAIL** (5 of 8 included runs exceed 10%)
**C1(b): FAIL** (same 5 runs; no hard-drawdown halts in any run)

Note: `active_max_drawdown_pct` is consistently 0.04–0.27 pp higher than `max_drawdown_pct`
because the active-equity drawdown is measured against a separate `risk_high` watermark
(sampled at every pre/post-fill risk evaluation), while total-equity drawdown is measured
against the peak total equity.

### C2 — Makes money on the worse path

Spec (§6): median return per path > 0 and mean across all included runs > 0.
Median rule: even count → mean of two middle values (§6).

8 included runs (4 high_first, 4 low_first), sorted:

high_first: [−8.4371, −7.8841, −4.1472, +1.2152] → median = (−7.8841 + −4.1472) / 2 = **−6.0157%**
low_first:  [−8.3808, −7.9276, −2.8657, +2.9805] → median = (−7.9276 + −2.8657) / 2 = **−5.3967%**
mean(all 8): (1.2152 + 2.9805 − 4.1472 − 2.8657 − 8.4371 − 8.3808 − 7.8841 − 7.9276) / 8 = **−4.4309%**

**C2: FAIL** (both path medians negative; mean negative)

### C3 — Safer than holding

Spec (§6): `max_drawdown_pct` < `buy_and_hold_max_drawdown_pct` in every included run.
A zero buy-and-hold drawdown fails.

All 8 included runs compared; buy-and-hold max drawdowns range from 23.3% to 55.8%
(bear market for practice-2022; bull market for verify-2024h1 where buy-and-hold rose).
V0 max drawdowns range from 5.3% to 10.9%. In every case V0 < buy-and-hold.

**C3: PASS** (all 8 included runs satisfy max_dd < bh_max_dd)

### C4 — Integrity

All included runs: `transient_pauses == 0` and `accounting_problems == []`.
Source: verified in `data/score.py` from `results.json` fields.

**C4: PASS**

### C5 — Minimum activity

Spec (§6): rate = `completed_cycles ÷ (window_days ÷ 7)`. Window is `[first day of start month,
first day after end month)` UTC. Mean over all included runs (exact, using `fractions.Fraction`)
must be ≥ 1.

Window lengths (self-check: spec says 245 and 182):
- `practice-2022`: 2022-06-01 to 2023-02-01 = **245 days** ✓
- `verify-2024h1`: 2024-01-01 to 2024-07-01 = **182 days** ✓

Per-run detail:

| Dataset | Pair | Path | Cycles | Rate (exact) | Rate (decimal) | Inv % | Weeks w/ cycle |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: |
| practice-2022 | BTCUSDT | high_first | 81 | 81/35 | 2.3143 | 9.13 | 21 |
| practice-2022 | BTCUSDT | low_first | 87 | 87/35 | 2.4857 | 9.08 | 22 |
| practice-2022 | XRPUSDT | high_first | 99 | 99/35 | 2.8286 | 8.73 | 17 |
| practice-2022 | XRPUSDT | low_first | 100 | 20/7 | 2.8571 | 9.04 | 17 |
| verify-2024h1 | ADAUSDT | high_first | 11 | 11/26 | 0.4231 | 1.11 | 1 |
| verify-2024h1 | ADAUSDT | low_first | 11 | 11/26 | 0.4231 | 1.11 | 1 |
| verify-2024h1 | BTCUSDT | high_first | 21 | 21/26 | 0.8077 | 3.27 | 5 |
| verify-2024h1 | BTCUSDT | low_first | 42 | 21/13 | 1.6154 | 5.06 | 10 |

Mean rate (exact): sum = (81+87+99+100)/35 + (11+11+21+42)/26 = 367/35 + 85/26 = 9542/910 + 2975/910
= 12517/7280. Mean = (12517/7280) / 8 = 12517/7280. Wait — sum of 8 rates divided by 8:
sum = 81/35 + 87/35 + 99/35 + 100/35 + 11/26 + 11/26 + 21/26 + 42/26
    = 367/35 + 85/26
    = (367×26 + 85×35) / (35×26)
    = (9542 + 2975) / 910
    = 12517/910
Mean = 12517/910 / 8 = 12517/7280 ≈ **1.7194**

Source: `data/score.py` prints `Mean rate (exact): 12517/7280 = 1.719368`.

**C5: PASS** (mean rate 12517/7280 ≈ 1.72 ≥ 1)

Note: ADA and BTC (high_first) in verify-2024h1 are below 1 individually (0.42 and 0.81),
but the mean over all 8 runs passes. This asymmetry is worth watching: if verify-2024h1
were scored alone, C5 would fail.

### C6 — The gate earns its place

Spec (§6): V0's `return_pct / max(max_drawdown_pct, 0.1)` vs ungated baseline's same ratio,
per included run. Passes if V0 is higher in ≥ 60% of runs.

| Dataset | Pair | Path | V0 return | V0 max DD | V0 ratio | Ungated return | Ungated max DD | Ungated ratio | Win? |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| practice-2022 | BTCUSDT | high_first | +1.2152 | 5.3547 | 0.2269 | −5.6692 | 8.4150 | −0.6737 | WIN |
| practice-2022 | BTCUSDT | low_first | +2.9805 | 5.3490 | 0.5572 | −6.4178 | 9.1578 | −0.7008 | WIN |
| practice-2022 | XRPUSDT | high_first | −4.1472 | 10.9344 | −0.3793 | −8.5674 | 10.0495 | −0.8525 | WIN |
| practice-2022 | XRPUSDT | low_first | −2.8657 | 10.4723 | −0.2736 | −8.5490 | 10.0501 | −0.8506 | WIN |
| verify-2024h1 | ADAUSDT | high_first | −8.4371 | 10.0561 | −0.8390 | −10.5781 | 12.1986 | −0.8672 | WIN |
| verify-2024h1 | ADAUSDT | low_first | −8.3808 | 10.0008 | −0.8380 | −10.5781 | 12.1986 | −0.8672 | WIN |
| verify-2024h1 | BTCUSDT | high_first | −7.8841 | 9.2825 | −0.8494 | −7.2858 | 8.5542 | −0.8517 | WIN |
| verify-2024h1 | BTCUSDT | low_first | −7.9276 | 10.3249 | −0.7678 | −7.0894 | 8.7724 | −0.8081 | WIN |

V0 wins in 8/8 = **100.0%** of included runs.

**C6: PASS** (100% ≥ 60%)

Note: BTCUSDT high_first and low_first in verify-2024h1 are close calls (ratio differences of
0.0023 and 0.0403). The gate wins in both cases but the margin in high_first is narrow.

### R1 — Economics (reported only)

Mean monthly return per run = run `return_pct` / window months in calendar (practice-2022: 8 months
June 2022–January 2023; verify-2024h1: 6 months January–June 2024).

Per-run monthly returns: +0.1519%, +0.3726%, −0.5184%, −0.3582%, −1.4062%, −1.3968%,
−1.3140%, −1.3213% (from `data/score.py`).
Mean monthly return: **−0.7238%**

**R1: not reachable** (mean monthly return ≤ 0; no capital threshold computable).

---

## 7. Verdict

| Criterion | Primary fees | Reference fees (reported) |
| --- | --- | --- |
| C1(a) max drawdown ≤ 10% | **FAIL** | PASS |
| C1(b) active drawdown ≤ 10%, no hard halts | **FAIL** | PASS |
| C2 makes money on worse path | **FAIL** | FAIL |
| C3 safer than holding | PASS | PASS |
| C4 integrity | PASS | PASS |
| C5 minimum activity (mean rate ≥ 1) | PASS | FAIL (0.24) |
| C6 gate earns its place (≥ 60%) | PASS | PASS (75%) |

**V0 fails the development scorecard at primary fees** (C1 and C2 fail).

**V0 also fails at reference fees** (C2 fails; C5 also fails at reference fees due to
fewer grids qualifying at 0.1%/0.1% — BTCUSDT at 0.1% has 0 completed cycles in both
windows, XRP 22/20, ADA 9/9; mean rate ≈ 0.24).

---

## 8. Comparison with fee-levels-2026-09.md

The earlier report used the same datasets and fee levels. All return figures match within
rounding (differences < 0.005 pp; shown as "−0.00" or "0.00" in `data/score.py` output).
No differences requiring explanation were found.

Source: the `data/score.py` comparison section prints the difference for each of the 16
gated V0 runs (8 primary, 8 reference).

The fee-level report noted "the range-exit counter fix `f136773` came after all runs;
for BTC and XRP (no rejected frames) it changes nothing." The current commit is
`876f7ce` which is after that fix; returns are identical, confirming the note.

---

## 9. Ambiguities in the criteria

1. **C1 threshold: strict inequality vs ≤.** §6 says "≤ 10%", so 10.0008% (ADAUSDT
   low_first) fails. This is clear, but the margin is 0.0008 pp — a 0.001 pp precision
   error in the drawdown sampler could swing the result. The scoring code must preserve
   full Decimal precision from `Metrics.active_max_drawdown` rather than converting to
   float before comparison. Spec line: "≤ 10%" (§6 C1).
   **Assumed:** strict interpretation; any value > 10.0 fails.

2. **R1 — "window return to monthly" conversion.** The spec says "state how you converted
   window returns to monthly" (§6 R1) but does not specify the method. I used a simple
   division: monthly return = total window return ÷ number of calendar months in the
   window (8 or 6). An alternative is compounding: `(1 + r)^(1/months) − 1`. At the
   returns here (mostly negative, small magnitudes), the difference is negligible.
   **Assumed:** arithmetic (simple) division of window return by calendar months.

3. **C5 — ISO-week count.** The spec asks for "the number of ISO weeks with at least one
   cycle" and says it is "reported, not scored." For ADA in verify-2024h1, both paths
   had 11 cycles all in 2024-W01 (the week of 2024-01-01 to 2024-01-07). After that,
   zero cycles in the remaining 25 weeks. This likely means the grid opened once in early
   January and sold all its levels, then the 3× cost filter prevented re-entry for the
   rest of the window. This is diagnostic information, not a scoring issue.

4. **C6 — The `max(max_drawdown_pct, 0.1)` floor.** For the ungated ADAUSDT baseline, the
   hard drawdown halted the run. Its `max_drawdown_pct` is 12.2%, so the floor doesn't
   apply. But if a variant had zero drawdown (e.g., no trades), the floor of 0.1 would
   apply, making a zero-return, zero-drawdown run score as 0/0.1 = 0. The spec text at
   §6 C6 is clear: "max(max drawdown, 0.1 percentage points)". No ambiguity here; noted
   for implementation.

---

## 10. Ideas and proposals

**For the scoring code (Claude):**

1. **Preserve Decimal precision through C1.** The current code in `summarise()` converts
   `active_max_drawdown` to float (`float(metrics.active_max_drawdown * 100)`). A C1
   scorer reading `results.json` must re-parse the float. For ADAUSDT low_first, the
   active DD is 10.0008%, and the difference from 10 is 0.0008 pp. At float64 precision
   this should be safe, but the scorer should compare against `Decimal("10")` or 10.0
   with an explicit tolerance statement in the code, not rely on floating-point equality.
   A 16-digit float holds 0.0008 reliably, so the current output format is sufficient —
   this is documentation for the coder, not a bug.

2. **C5 mean-rate computation must use `fractions.Fraction`.** The task spec says "compute
   the mean exactly with `fractions.Fraction`, from the integer counts." The scoring code
   should read `completed_cycles` (an integer in `results.json`) and the window days from
   the dataset spec, not from `results.json`. The window days are not recorded in
   `results.json`; they must come from `month_bounds_ms(start)` and `month_bounds_ms(end)`.
   This is a design question for Claude: should the scoring code call into the dataset
   module, or should the `results.json` record the window boundaries? Currently `results.json`
   records `"window": [first_bar_ms, last_bar_ms]`, which is the actual evaluation window
   from the data, not the spec window. The two differ by warmup and by the first-bar offset.
   The spec says the C5 window is fixed from the dataset spec, not the data. The scorer
   must use the spec window, not the data window.

3. **C5 individual-run check vs mean.** C5 scores the mean, but individual runs can be
   far below 1 (ADA verify-2024h1: 0.42). A companion check of the minimum per-path
   rate (or per-window rate) would make the scorecard more informative. This is not a
   spec change — just a "report also" item for the scoring code.

4. **C6 implementation: match by (dataset, symbol, path_mode).** The ungated run for
   each gated run must be matched by the same `(symbol, path_mode)` from the same
   `results.json` file. The current code does this correctly. The scorer should assert
   that every gated run has exactly one matching ungated run, and fail loudly if not.

**For the spec (Claude):**

5. **C1 threshold precision.** Three of the four failing runs are within 1 pp of 10%
   (10.0008, 10.0561, 10.4723, 10.9344%). The ADAUSDT cases are within 0.1 pp. The spec
   says "≤ 10%" without a tolerance band. This is intentional (owner decision), but the
   scoring code should not round before comparison. Worth a comment in the spec that the
   10% bound is exact.

6. **C2 median formula for even counts.** The spec says "the median of an even count is
   the mean of the two middle values" (§6 C2). With 4 runs per path, this is the mean
   of values at index 1 and 2 (0-indexed) of the sorted list. This is correctly stated;
   no ambiguity. But the spec does not say what happens with 0, 1 or 3 runs per path
   (pathological cases if pairs are excluded). A note that "at least 2 included runs per
   path are required for a meaningful median" would clarify.

7. **R1 monthly conversion.** The spec asks Bob to "state how you converted window returns
   to monthly" (§6 R1) but leaves the method open. For the scoring code, the spec should
   specify the method. Arithmetic division is simpler and consistent with how the spec
   talks about "mean monthly return." Recommend Claude lock this down before implementation.

**Diagnostic notes (not proposals):**

8. **ADA verify-2024h1 activity concentration.** All 11 completed cycles for ADAUSDT
   (both paths) occurred in 2024-W01, the first week of the window. The grid appears to
   have traded actively in early January 2024 (ADA was volatile around $0.60–$0.65 in
   that week) and then the 3× cost-multiple filter prevented new grids for the rest of
   the window. The very low `time_with_inventory_pct` (1.11%) confirms this. The spec
   criteria do not score this pattern specifically; it is captured by C5's mean rate.

9. **BTC verify-2024h1 path asymmetry in cycles.** BTCUSDT low_first had 42 completed
   cycles vs 21 for high_first. The `time_with_inventory_pct` is also 5.06% vs 3.27%.
   This likely reflects the path assumption: `low_first` sees the low before the high
   within each bar, so buys fill more readily at the low, leading to more completed
   buy-sell cycles. This path asymmetry is expected and does not indicate an error.

10. **No hard-drawdown halts at primary fees.** Zero hard-drawdown halts across all 8
    included gated runs at primary fees. The ungated ADA (both paths) did halt
    (`hard_drawdown_halts = 1`), which is consistent with the ungated baseline
    accumulating more inventory and suffering larger drawdowns on a bear-market move.
    This distinction is correctly not counted under C4 (C4 scores included gated runs).
