# Verification run: `verify-2024h1`

- **Harness and features:** harness v1, features `price-only-v1`, code at commit
  `98baf70`.
- **Dataset:** [`config/datasets/verify-2024h1.toml`](../../config/datasets/verify-2024h1.toml),
  manifest created 2026-09-24T10:21:23Z (92 archive files, all SHA-256 verified, no
  gaps, all millisecond timestamps).
- **Window:** 2024-01-01 to 2024-06-30, 262,080 one-minute bars per pair, with no bars
  lost to warm-up.
- **Capital and costs:** 100 USDT initial capital, 0.1% fee, 0.05% slippage, 0.05%
  assumed spread.
- **Runtime:** 5 min 57 s on 4 cores; 21.6 CPU-minutes for 8 replays.

**This is a development window used to verify the software. It is not a performance
test.** BTC and ADA are today's survivors, six months is one market episode, and
historical news is absent (`news_risk` = 0). Nothing below is a forecast.

## Integrity checks: all passed

| Check | Result |
| --- | --- |
| Local files match the committed manifest | 92 / 92 |
| 1m bars aggregated to hours equal Binance's 1h archive (OHLCV) | ADAUSDT 4,368 / 4,368 hours, BTCUSDT 4,368 / 4,368 hours, 0 mismatches |
| Official hours in the window with no minute data (added after Codex's PR #9 review; re-run on the fixed code, results unchanged) | 0 for both pairs |
| Exact cash / inventory / fee / reserve-journal identities | 0 problems in all 8 runs |
| Quotes rejected as stale or out of order | 0 in all 8 runs |
| Paper demo output unchanged by the engine changes | byte-identical |

The final run on commit `98baf70` reproduced an earlier run on the pre-fix code
exactly.

## Results

| Pair | Path | Strategy | Return % | Max DD % | Buy&hold % | B&H DD % | Fees | Buys/Sells | Grids | Range exits | Invested % | Halted |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ADAUSDT | high_first | gated grid (price-only-v1) | -2.27 | 5.93 | -34.15 | 55.24 | 0.66 | 13/11 | 8 | 6 | 1.1 | no |
| ADAUSDT | high_first | ungated grid baseline | -10.01 | 12.82 | -34.15 | 55.24 | 2.14 | 37/34 | 23 | 9 | 2.2 | 2024-03-05T19:55:19+00:00 |
| ADAUSDT | low_first | gated grid (price-only-v1) | -2.08 | 5.75 | -34.15 | 55.24 | 0.67 | 13/11 | 8 | 6 | 1.1 | no |
| ADAUSDT | low_first | ungated grid baseline | -9.97 | 12.76 | -34.15 | 55.24 | 2.14 | 37/34 | 23 | 9 | 2.2 | 2024-03-05T19:55:09+00:00 |
| BTCUSDT | high_first | gated grid (price-only-v1) | 0.00 | 0.00 | 47.92 | 23.28 | 0.00 | 0/0 | 0 | 0 | 0.0 | no |
| BTCUSDT | high_first | ungated grid baseline | -4.93 | 11.67 | 47.92 | 23.28 | 1.10 | 17/13 | 14 | 11 | 1.5 | no |
| BTCUSDT | low_first | gated grid (price-only-v1) | 0.00 | 0.00 | 47.92 | 23.28 | 0.00 | 0/0 | 0 | 0 | 0.0 | no |
| BTCUSDT | low_first | ungated grid baseline | -11.20 | 12.02 | 47.92 | 23.28 | 0.45 | 8/4 | 4 | 4 | 0.2 | 2024-03-05T19:57:09+00:00 |

How to read the table:
- **Return % and Max DD %** use total equity, including reserve and unsold inventory
  marked at a conservative exit price.
- **Cash** is 0% in every row.
- **"Invested %"** is the share of bars holding inventory.
- **Halted** runs hit the 12% hard-drawdown limit. That halt is latched and has no
  automatic resume, so they did not trade again.
- **"Max DD %"** is measured on total equity, while the risk engine measures active
  equity against its own adjusted high-water mark. That is why a halt can show 13.00%
  next to a table value of 12.82%.

Month by month for the `high_first` path (strategy / buy-and-hold, % change):

| Month | ADA gated | ADA ungated | ADA buy-and-hold | BTC gated | BTC ungated | BTC buy-and-hold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2024-01 | +0.3 | +1.9 | -16.1 | 0.0 | -4.4 | +0.5 |
| 2024-02 | -2.7 | -2.1 | +30.0 | 0.0 | 0.0 | +43.8 |
| 2024-03 | -0.6 | -9.7 | -0.2 | 0.0 | -2.7 | +15.8 |
| 2024-04 | +0.8 | 0.0 (halted) | -32.1 | 0.0 | +1.5 | -14.7 |
| 2024-05 | 0.0 | 0.0 (halted) | +1.8 | 0.0 | +0.7 | +11.6 |
| 2024-06 | 0.0 | 0.0 (halted) | -12.3 | 0.0 | 0.0 | -6.7 |

The broad-market regime (BTC proxy, per bar) was RANGE 32.6%, TRANSITION 40.1%,
BEAR 17.3% and BULL 10.0% of the time.

## Why the strategy almost never traded

Decision reasons by bar for the gated runs:

| Reason | ADAUSDT | BTCUSDT |
| --- | ---: | ---: |
| Paused: opportunity score below 0.70 | 84.1% | 92.5% |
| Paused: waiting in cash after an out-of-range exit | 9.4% | — |
| Cash: grid spacing below 3× round-trip costs | 5.5% | 7.5% |
| Holding a grid | 1.0% | 0% |

The cost rule is the structural reason. An 8-level grid over `SMA20 ± 2 × ATR14`
passes the engine's "spacing ≥ 3 × round-trip cost" rule only when hourly ATR is at
least ~1.83% of price. The round-trip cost is 0.35%: fees, slippage and spread on
both sides.

| Pair | Median hourly ATR | 10th-90th percentile | Hours in which a grid was allowed |
| --- | ---: | ---: | ---: |
| ADAUSDT | 1.09% | 0.66-1.99% | 12.4% |
| BTCUSDT | 0.70% | 0.37-1.24% | 1.8% |

## Findings for the owner and Codex

These are design questions rather than harness bugs. None was tuned on this window.

1. **The cost rule picks the worst moments.**
   - Grids become allowed mainly in the most volatile hours, which is when price is
     most likely to leave the range.
   - On ADA, 6 of the gated strategy's 8 grids ended in a six-hour out-of-range exit
     instead of a profit harvest at a flat point.
   - The ungated grid had the same problem (9 of 23 grids).
   - The harness does not yet record profit or loss per grid; adding that is a
     follow-up.
2. **The opportunity gate blocks almost everything.**
   - The score stayed below 0.70 for 84-93% of bars; BTC never passed.
   - Together with finding 1, the gated strategy is essentially a cash position: it
     held inventory 1.1% of the time on ADA and never on BTC.
   - It avoided ADA's -34%, but through inactivity, not skill. It also missed BTC's +48%.
3. **One crash ends the strategy.**
   - The ungated grid hit the 12% hard drawdown in the 2024-03-05 crash in 3 of 4 runs,
     then stayed halted for the remaining 64% of the window.
   - With a latched halt and no operator, a single bad day is terminal. The owner needs
     to decide on an operator procedure or a rule-based cool-off.
4. **Capital concentrates in a few orders.**
   - `_open_grid` splits the 80% budget over only the buy levels below the current
     price. Near the bottom of the range that can put most of the capital into one or
     two orders.
   - While invested, the unsold coins averaged 38-70% of the portfolio.
5. **The cost model needs a decision.**
   - The viability rule charges `2 × (fee + slippage) + spread` (0.35%).
   - A resting limit order fills at its limit price, so slippage here acts as a
     trade-through requirement rather than a cash cost.
   - On fees plus spread alone, the requirement would be 0.75% instead of 1.05%. This
     constant is the main constraint, so it deserves an explicit owner and Codex
     decision.

## Verdict for this step

- **The harness is verified:** data integrity, chronology and accounting all check out.
- **The strategy result is not promising:** under `price-only-v1` with the current
  configuration, the strategy barely trades. When it does, it loses slightly after
  costs, and there is no sign of an edge.
- **Recommendation:** this does not justify building more infrastructure. The next
  decision belongs to the owner:
  - agree the acceptance criteria in [BACKTEST_METHOD.md](../BACKTEST_METHOD.md);
  - decide whether to pre-register a small set of variants before running an untouched,
    multi-market window. Candidates: a wider range based on 4-hour or daily volatility;
    fewer levels; the cost-rule decision in finding 5; a cool-off after a hard drawdown.
  - Test those variants against the current v1, not tuned on this window.
