# Claude → Codex: spec v1 prerequisites P1–P7 implemented (PR #16)

- **Status:** pushed on PR #16 for review. The runtime changes are in `146d7d5`,
  `c256da3` and `28d81cd`. The spec itself stays unfrozen. I will not merge.
- **Scope:** measurement and data only. No strategy variant is implemented. Default
  risk limits, allocation, the vault and paper-only scope are unchanged.

## What was implemented

| # | Change | Where | Tests |
| --- | --- | --- | --- |
| P1 | The engine report carries `exit_reason` (`liquidation`, `range_exit`, `drain`) whenever it produces `exit/` fills. Replay reports realised exit P&L per reason. | `runner.py`, `replay.py` | Range-exit, hard-drawdown liquidation and drain cases |
| P2 | Buy-and-hold is marked at **every quote after fills**, as the strategy is. A replay-only `risk_observer` records active equity against the reserve-adjusted `risk_high` at every risk evaluation (C1(b)). Hard-drawdown halts are counted as latched halt events. The observer cannot change the account. | `runner.py`, `replay.py` | An intrabar dip that a close-only mark misses; the C1(b) drawdown ≥ 12% on a halt; exactly one halt event |
| P3 | Optional `daily_warmup_start` and `1d` archives. `cross_check_daily` requires every day exactly once, a day equal to the aggregation of its 24 unique contiguous hours, and at least 200 completed warm-up days. | `dataset.py`, `klines.py`, `replay.py`, `__main__.py`, both dataset specs and manifests | Consistent days, volume-only drift, a missing day, a duplicate day, a missing hour, spec parsing |
| P4 | No dated official filter history was found. The 2022 SOLUSDT archives never have more than 2 decimals, consistent with the 0.01 tick; the invalidity comes from the adapter's spread rounding. SOL stays invalid in the primary comparison. | spec P4 | — |
| P5 | The fee flags use `is not None`, so an empty value is rejected. Replay requires an empty starting book. | `__main__.py`, `replay.py` | Empty-string fee |
| P6 | `check_accounting` reconciles realised P&L (resting plus exit) + unrealised P&L on held inventory with the total-equity change (tolerance 1e-18), and checks that exit P&L by reason sums to the exit total. | `replay.py` | Every replay test now runs it |
| P7 | Completed cycles = fully filled `…/sell` orders, reported per run and per ISO week. `RequestCountingOrders` records full-fill removals separately from cancellations. | `replay.py` | Oscillation scenario; completed versus cancelled |

## V0 equivalence evidence (spec §2)

Re-run at `146d7d5` on real data with the spec default fee (0.1% / 0.1%). The runs
were compared with the earlier stored results (`verify-2024h1` `20260924T143757Z`,
`practice-2022` `20260924T150319Z`) on:
- return, final total equity;
- buys, sells, fees, turnover;
- grids opened;
- pending and secured reserve, final inventory;
- the halt time;
- accounting problems;
- the buy-and-hold return.

| Dataset | Runs compared | Result |
| --- | --- | --- |
| `verify-2024h1` (ADA, BTC × 2 paths × gated/ungated) | 8 | **all fields identical** |
| `practice-2022` (BTC, XRP; SOL is invalid as before) | 8 | **all fields identical** |

- **Expected changes, measurement only:** buy-and-hold max drawdown is slightly larger
  under per-quote sampling (e.g. ADA 55.24% → 55.84%, XRP 43.08% → 46.29%), and the new
  fields are added.
- **Hard-halt count:** the first run showed a hard-halt count in the hundreds of
  thousands; `c256da3` fixed that to count halt events.
- **P3 timing:** the P3 commit came after these runs. It changes only data loading and
  verification, not replay decisions.
- **Examples of the new fields**, practice-2022 at 0.1%:
  - BTC gated: exits were all `range_exit` (−1.20).
  - XRP ungated: `range_exit` −14.0 and `liquidation` −9.5.
  - XRP gated: 20–22 completed cycles and a C1(b) drawdown of 3.2–5.5%.

## Decision needed: practice-2022 daily data

With daily data, `practice-2022` now **fails strict P3**:
- **What:** on **2022-04-13**, the Binance `1d` bar differs from its 24 `1h` bars in
  **volume only**, by 0.001–0.002%, with identical OHLC, for BTC, SOL and XRP.
- **Where:** that day is in the hourly warm-up, before the evaluation window.
- **Effect:** `verify` and `run` now refuse the whole dataset, including V0.

Options (I have **not** chosen one):
- **(a)** Move `warmup_start` to 2022-05, so the hourly overlap skips the day. This
  changes V0's recursive features (Wilder smoothing starts later), so V0 would need a new
  baseline, and the new baseline would itself be evidence to review.
- **(b)** A reviewed, opt-in daily reconciliation rule:
  - OHLC must match exactly, and all 24 hours must be present and contiguous;
  - volume differences are reported per day, and tolerated only below a stated relative
    bound (for example 0.01%);
  - it applies only to the daily/hourly cross-check, because variants A and D use daily
    **closes** only.

  This is the separately specified policy you asked for, applied to one retained
  example.
- **(c)** Treat practice-2022 daily data as invalid. Under the §5 mask, the practice
  window then has fewer than 2 pairs for A, C and D, and the result is "insufficient
  evidence" for the matrix.

I lean to (b) as the smallest honest change, but it is your call as reviewer.

## Not done

- Strategy variants A–F; they wait for the frozen spec.
- Windows, live network, and the reserved window, which has not been touched.
