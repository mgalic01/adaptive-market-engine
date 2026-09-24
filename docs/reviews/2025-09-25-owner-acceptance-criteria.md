# Owner decision: acceptance criteria for the untouched 2025–26 test window

- **Date:** 2025-09-25
- **Author:** Owner (mgalic01), recorded by IBM Bob (observer/consultant)
- **Recipient:** Codex and Claude
- **Context:** These criteria must be locked before the untouched 2025–26 window is
  run. Adjusting them after seeing the results would invalidate the test. They are the
  go/no-go gate that determines whether the strategy proceeds to a live pilot or is
  redesigned. Claude proposed five criteria in
  [`BACKTEST_METHOD.md`](../BACKTEST_METHOD.md) and
  [`2026-09-24-claude-fees-and-strategy-plan.md`](2026-09-24-claude-fees-and-strategy-plan.md);
  criterion 6 is added by the owner to explicitly enforce the active-trading goal.

## Agreed criteria (all six are required to pass)

### 1. Integrity
Zero accounting problems and zero chronology rejections in every run. If the
accounting does not add up, no other result is meaningful.

### 2. Beats cash robustly
The gated strategy's median return across all tested markets is above 0% after all
costs, in **both** intrabar path modes (high-first and low-first). The worse path
decides. A strategy that cannot beat cash on the pessimistic path, across a range
of markets, is not ready.

### 3. Risk
- No single market exceeds the 12% hard-drawdown limit by more than slippage.
- The gated strategy's median maximum drawdown is below buy-and-hold's median maximum
  drawdown across the same markets.

### 4. The gate earns its place
The gated strategy beats the ungated grid on return ÷ max drawdown in at least 60%
of tested markets. The regime filter and opportunity gate must add measurable value
over simply running the grid continuously.

### 5. Economics
Report the capital required for grid profit to cover €5/month hosting costs. If
that capital exceeds the owner's intended budget of **€100**, the result is a no-go
at that size regardless of percentage returns. A €100 budget is not automatically
100 USDT/USDC; FX and conversion costs apply.

### 6. Minimum activity *(added by owner)*
The gated strategy holds inventory in at least **10% of evaluated bars**, on average
across all tested markets, in the untouched window. This ensures that "beats cash"
reflects genuine trading activity and not a strategy that simply stayed in cash.
This criterion directly reflects the owner's stated goal of a bot that actively
trades and tries to profit.

## What "pass" means

All six criteria must be met. A result that passes five but fails one is a no-go.
If the screen fails, the recommendation is to redesign or stop the strategy before
building CoinMarketCap, news or live-trading infrastructure.

## Suggested window and markets

As proposed by Claude: 2025-01 to the latest complete month, 10–20 markets including
pairs that were later delisted. Survivorship bias must be avoided — do not select
only today's survivors.

## Constraint: one run only
The best-supported variant (from the development-window matrix) plus V0 get
**one** run on the untouched window. No tuning after seeing those results.

## What this unlocks

With all four owner decisions now recorded (variants A–F, tick-size fix, volume
drift, acceptance criteria), Codex and Claude may proceed with:
1. Implementing the harness fixes (tick-size and volume drift).
2. Implementing variants A–F behind config flags (default off).
3. Running the variant matrix on `verify-2024h1` and `practice-2022`.
4. Selecting the best-supported variant.
5. Running the untouched 2025–26 window once, against these criteria.

No live trading or removal of risk controls is authorised at any stage.
