# Owner decision: archive volume drift tolerance

- **Date:** 2025-09-25
- **Author:** Owner (mgalic01), recorded by IBM Bob (observer/consultant)
- **Recipient:** Codex and Claude
- **Context:** Binance's 1h kline archive occasionally differs from the sum of its 1m
  bars by 0.003–0.05% in volume only, with identical OHLC prices. Examples found by
  Claude: BTC, ETH, SOL, ADA on 2022-05-01 08:00; ETH on 2022-06-30 01:00; ADA on
  2022-07-22 09:00. The current harness hard-rejects these hours, blocking valid
  datasets over what appears to be a Binance rounding or aggregation artefact. This
  decision resolves harness problem 4.2 from
  [`2026-09-24-claude-fees-and-strategy-plan.md`](2026-09-24-claude-fees-and-strategy-plan.md).

## Decision

**Approve Claude's proposal:** tolerate small volume drift with a separately reported
counter, subject to the following conditions:

- **OHLC prices must match exactly** — this remains a hard, non-negotiable gate.
  Price mismatches are still fatal.
- **Volume drift is tolerated only up to 0.1%** when OHLC prices match exactly.
  Differences above 0.1% remain fatal.
- **Missing minutes, gaps and any price mismatch remain fatal** — no tolerance there.
- **Count separately:** report `hours_volume_drift` in `results.json` so every run
  shows how many hours were affected. This keeps the artefact visible rather than
  silently absorbed.

## Rationale

Volume in the harness is used as a liquidity proxy — a rough measure of whether
there is enough market activity to justify opening a grid. A 0.003–0.05% volume
discrepancy has no meaningful impact on that calculation. Blocking entire datasets
over an exchange rounding artefact, while price data is perfectly intact, loses real
market data for no meaningful reason. The OHLC hard gate and the visible counter
preserve integrity without unnecessary data loss.

## What this unlocks

Datasets affected by the Binance volume rounding artefact will no longer be blocked,
provided prices match exactly and volume drift stays within 0.1%. The
`hours_volume_drift` count in results makes the occurrence traceable.

## What remains open

1. **Acceptance criteria for the untouched 2025–26 window** — next and final decision
   before variant implementation can begin.

## Next action

Codex and Claude: implement the `hours_volume_drift` counter and the conditional
tolerance (OHLC exact, volume ≤ 0.1% drift). Update `verify` and `run` accordingly.
Keep all other chronology gates fatal. Report the count in `results.json` and the
run summary.
