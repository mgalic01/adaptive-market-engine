# Historical replay method (harness v1, features `price-only-v1`)

This documents exactly what the replay does, so results can be reproduced and
challenged. It implements the "first deliverable" of [BACKTEST_PLAN.md](BACKTEST_PLAN.md).
Nothing here was tuned on results; every constant below was fixed before the first
real run.

## Commands

```bash
PYTHONPATH=src python -m crypto_grid_bot.backtest fetch  --spec config/datasets/verify-2024h1.toml
PYTHONPATH=src python -m crypto_grid_bot.backtest verify --spec config/datasets/verify-2024h1.toml
PYTHONPATH=src python -m crypto_grid_bot.backtest run    --spec config/datasets/verify-2024h1.toml
```

`fetch` is the only command that uses the network: it reads public archive files from
`https://data.binance.vision` and the current exchange filters from the public data
API. `verify` and `run` are offline. `run` refuses to start unless every local file
matches the committed manifest's SHA-256. Results go to `data/backtests/<dataset>/<UTC
time>/` (`results.json` and `summary.md`), which is not committed.

## Data

- **Source:** Binance monthly spot kline archives (`data/spot/monthly/klines/<SYMBOL>/<1m|1h>/`).
- **Format** (verified 2026-09-24 on real files): one headerless 12-column CSV per zip.
  Timestamps are milliseconds up to 2024-12 and microseconds from 2025-01; both are
  normalised to milliseconds and checked to be exact candle boundaries.
- **Integrity:**
  - Every zip is checked against Binance's published `.CHECKSUM` before it is stored.
  - The dataset manifest (`config/datasets/<name>.manifest.json`, committed) records
    each file's URL, SHA-256, size, row count, missing rows, gaps, timestamp unit and
    the download date.
  - A month Binance does not publish (for example before a pair was listed) is recorded
    as `missing` and never filled in.
- **Files per dataset:** 1m klines for traded pairs cover the evaluation window only;
  1h klines for traded pairs, the market proxy and the breadth basket also cover the
  warm-up months.
- **Exchange filters** (tick size, quantity step, minimum notional) are today's values
  from the public API, applied historically. This is an approximation and is recorded
  as such in the manifest.
- **Chronology cross-check:** `verify` aggregates every traded pair's 1m bars into hours
  and compares open, high, low, close and volume exactly with Binance's own 1h archive.

## From klines to simulator quotes

Klines contain trades, not quotes. The adapter in `backtest/replay.py` is explicit:

- **Price points:**
  - Each 1m bar becomes four quotes: open, first extreme, second extreme, close. They
    are stamped at +0, +9, +19 and +29 seconds, so every quote falls within the
    engine's 30-second data-age limit.
  - `high_first` visits the high before the low; `low_first` the reverse. The true order
    is unknown, so both are run and reported.
- **Bid and ask:**
  - At the high a trade lifted the ask, so ask = high and bid is one assumed spread
    lower.
  - At the low a trade hit the bid, so bid = low and ask is one assumed spread higher.
  - Open and close are mid prices.
  - Prices round outward to the tick.
  - The assumed spread is a dataset parameter (`assumed_spread_pct`; 0.05% in
    `verify-2024h1`).
- **Crossing:** the unchanged engine still requires a limit to be crossed by the slippage
  rate. Touching a level never fills.
- **Liquidity:**
  - Taker-sell volume can fill resting buys; taker-buy volume can fill resting sells.
  - Each side's bar volume is split evenly over the four quotes, and the engine's
    participation cap (10%) applies to each share. A bar's volume is never spent twice.
- **No invented round trips:** all four quotes share one *epoch*. An order created inside
  a bar (a grid buy, a child sell or a re-entry buy) cannot fill until a later bar, so
  a buy and its child sell never both fill on an assumed favourable path inside one
  minute. A regression test fails without this rule.
- **Costs:** the fee is 0.1% per fill, charged in quote currency (Binance base rate
  without the BNB discount), plus the engine's 0.05% slippage per fill.

## Strategy inputs: hypothesis `price-only-v1`

All inputs for the minute starting at `m` use only hourly candles that closed before
`m`. A test changes every unfinished and future candle and checks that the decision
inputs are unchanged, and that changing the last completed candle does change them.

**Broad market** (market proxy `M`, BTCUSDT in `verify-2024h1`):

| Signal | Formula |
| --- | --- |
| trend | `tanh((SMA20/SMA50 − 1) / 0.02)` |
| momentum | `tanh(24h return / 0.05)` |
| breadth | `2 × share of basket markets with close > SMA50 − 1`; needs ≥ 5 fresh markets, otherwise the regime is vetoed |
| volatility_health | `−tanh(max(0, ATR%/median(ATR%, 30 d) − 1))`: 0 when volatility is at or below its 30-day median, negative when elevated |
| liquidity_health | `−tanh(2 × max(0, 1 − QV24/median(QV24, 30 d)))`: 0 when volume is normal, negative when it dries up |
| adx | Wilder ADX(14) on hourly candles |
| data_quality | share of the last 168 hours present, the lower of `M` and the traded pair; 0 when the latest candle is over 2 h old |
| news_risk | **0: component ABSENT.** There is no historical news source. Every result states this; it is not evidence that there was no news risk. |
| emergency | always false. There is no price-only emergency detector in v1. |

The health signals only ever vote *negative*. This avoids the pathology noted in
review 2: a perfectly healthy market would otherwise vote bullish and block RANGE.

**Traded pair** (`P`):

| Metric | Formula |
| --- | --- |
| range_quality | `1 − efficiency ratio(20 h)` |
| net_grid_edge | `clamp((S/K − 1) / (2 × 3 − 1))`, where `S` is the geometric spacing of an 8-level grid over `SMA20 ± 2 × ATR14` and `K` is the round-trip cost `2 × (fee + slippage) + spread` |
| liquidity_quality | `clamp(log10(24h quote volume / 100,000) / 2)` |
| downside_quality | `1 − clamp(max drawdown over 168 h / 20%)` |
| data_quality | share of the last 168 hours present; 0 when stale |
| spread_pct | the assumed spread |
| depth_multiple | `(24h quote volume / 1440) / (initial capital × 0.8 / 4)`. The engine spreads 80% of cash over the buy pairs below fair value, about half of the 8 levels (corrected after Codex's PR #9 review; it previously divided by 8 and overstated depth by ~2×) |
| fair value | SMA20 of hourly closes |
| ATR | simple ATR(14) of hourly candles |

Warm-up: the 30-day medians need 742 completed hours, so every dataset includes at
least two hourly warm-up months before `start`.

The unchanged engine then applies:
- the regime classifier;
- the opportunity scorer;
- the grid builder's rule that spacing must be at least 3× round-trip costs;
- risk limits: 3% daily pause, 8% soft and 12% hard drawdown, with hard-drawdown halts
  latched and no automatic resume;
- range exit after 6 h and re-centring after 24 h;
- the 50/50 reserve with transfers batched at 10 quote units.

## Baselines

Every run uses the same capital, window, fee, slippage and assumed spread:

- **Cash:** 0% return.
- **Buy-and-hold:**
  - buys once at the first evaluated bar's ask, plus slippage and fee;
  - is marked at each bar close at bid × (1 − slippage) × (1 − fee), i.e. what an
    exit would realise.
- **Ungated grid:**
  - identical engine, quotes and risk limits;
  - the regime and eligibility gate are removed (a quiet, fully trusted range and an
    always-eligible pair).
  - This isolates what the gate adds or costs.
  - Because the engine re-centres at every flat point, it is not a never-moved
    static grid. A true static grid baseline is still to do.

## Verification in every run

- Every file matches the manifest before the run starts.
- Aggregated 1m bars match Binance's 1h archive exactly, and no official hour inside the
  evaluation window lacks minute data (`hours_absent_from_minutes`, added after Codex's
  PR #9 review). Counts are in `results.json`.
- Exact Decimal identities between the fill journal and the final account:
  - cash = initial − buys − buy fees + sells − sell fees − secured reserve;
  - inventory = bought − sold;
  - fees match;
  - the transfer journal reconciles to the secured reserve.
- `transient_pauses` counts any frame the engine rejected as stale or out of order;
  with correct chronology it must be 0.

## Known limitations of harness v1

- **Survivorship:** `verify-2024h1` trades BTC and ADA, which still exist today. The
  expansion must include pairs that were later delisted, and must use only months the
  archive publishes.
- **Market microstructure:** 1m OHLCV hides the intrabar path, queue position and the
  real spread. Results are only as good as the stated assumptions; spread and path
  sensitivity must be reported.
- **Exchange filters and fees:** today's filters are applied historically. There is no
  BNB fee discount, and buy fees are charged in quote currency rather than in the
  asset received.
- **Single market per run:** there is no rotation between markets and no
  multi-grid portfolio.
- **Currency:** results are in quote-currency units (USDT). There is no EUR
  conversion and no hosting cost.
- **Performance:** about 200 µs per engine step, or roughly 3.5 minutes per pair,
  path and variant for six months on one core.

## Proposed acceptance criteria (NOT yet agreed; owner decision)

Proposed for the go/no-go screen on an untouched test window. Suggested window:
2025-01 to the latest complete month, 10-20 markets including later-delisted ones.
They are fixed before that window is run.

1. **Integrity:** zero accounting problems and zero chronology rejections in every run.
2. **Beats cash robustly:** the gated strategy's median return across markets is above
   0% after all costs, in *both* path modes. The worse path decides.
3. **Risk:** no market exceeds the 12% hard-drawdown limit by more than slippage, and
   the gated strategy's median max drawdown is below buy-and-hold's.
4. **The gate earns its place:** the gated strategy beats the ungated grid on
   return ÷ max drawdown in at least 60% of markets.
5. **Economics:** report the capital needed for grid profit to cover €5/month hosting.
   If that exceeds the owner's intended capital, the result is a no-go at that size,
   whatever the percentage returns.

If the screen fails, the recommendation is to change or stop the strategy before
building news, CoinMarketCap or live-trading infrastructure.
