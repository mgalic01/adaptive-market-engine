# Owner decision: Variant G — Binance funding rate confirmation

- **Date:** 2025-09-25
- **Author:** Owner (mgalic01), recorded by IBM Bob (observer/consultant)
- **Recipient:** Codex and Claude
- **Context:** Following multi-agent research into additional signal candidates,
  the Fear & Greed Index was rejected as 60–70% redundant with existing price/volume
  signals. Binance funding rates were identified as a genuinely independent, free,
  and reliable signal not currently in the model. This document pre-registers
  Variant G before any implementation or testing.

## What Variant G does

**Rule:** No new grid opens when the BTC perpetual futures funding rate has been
persistently positive (above +0.05% per 8-hour period) across all three of the
last three funding periods (i.e. the last 24 hours of funding).

A persistently positive funding rate means leveraged long traders are paying a
premium to maintain their positions. This indicates the market is heavily leveraged
long and a deleveraging (forced liquidation cascade) event is elevated risk.
Opening a new grid into this condition increases the probability of being caught
in a sharp downward move driven by liquidations rather than fundamentals.

## Why this signal is genuinely independent

Funding rates are derived from the **perpetual futures basis** — the difference
between perpetual contract price and spot price. They reflect actual money
positioning by leveraged traders, which is a different dimension from:
- Spot price trend (SMA200, SMA50)
- Spot price volatility (ATR)
- Spot volume (liquidity proxy)
- Market breadth (basket SMA50)

A market can be trending up on strong spot volume while funding rates are
dangerously elevated — or vice versa. The signal adds information the existing
model genuinely cannot see.

## Data source

- **Endpoint:** `GET https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3`
- **Cost:** Free, no authentication required
- **Update frequency:** Every 8 hours (00:00, 08:00, 16:00 UTC)
- **Reliability:** Hosted by Binance; same infrastructure as the public data
  already used by the bot
- **Backtest availability:** Binance publishes historical funding rate data;
  the harness can fetch and verify it

## Pre-registration rules

- Variant G runs with the same windows, fee levels and comparison baselines as
  Variants A–F: `verify-2024h1` (bull) and `practice-2022` (bear, after tick fix),
  with both Revolut X fees (0%/0.09%) and 0.1% flat fees
- The threshold (+0.05% per period, 3 consecutive periods) is fixed here and
  must not be changed after the first run
- Variant G is tested both standalone (V0 + G) and combined with the
  best-performing variant from A–F
- Compared to V0, cash and buy-and-hold with no tuning after the first run

## What to measure

- How often does the funding rate gate block a grid that would otherwise open?
- Of the grids it blocks, what fraction would have ended in a forced exit loss?
- Does adding G to Variant C (trend filter + inventory cap) improve return ÷
  max drawdown?

## Failure modes to watch

- **False negatives in bear markets:** Funding rates can be persistently negative
  (shorts paying longs) in bear markets. The gate should only block on elevated
  long positioning, not trigger on short positioning.
- **Irrelevance for spot-only strategy:** Funding rates reflect perpetual futures
  positioning. A purely spot market may not always follow perpetuals immediately.
  Measure the lag and report it.

## Next action

Codex and Claude: fetch historical BTC funding rate data and add it to the
dataset manifest. Implement Variant G behind a config flag (default off).
Run the variant matrix after Variants A–F are assessed.
