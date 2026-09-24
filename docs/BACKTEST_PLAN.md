# Next gate: historical strategy feasibility

Do this before broadening CMC/news infrastructure. The objective is to determine
whether the proposed strategy merits further work after costs, not to produce an
attractive backtest chart. No historical result has been produced by this change.

## First deliverable

Build a reproducible, offline replay harness with checksummed Binance bulk input
files and a data manifest (source URL, pair/quote asset, period, units, missing data,
checksum, download date). Verify the current official archive format before
implementation, including millisecond/microsecond timestamp differences. Start
with one or two pairs to verify chronology/accounting, then expand to roughly
10-20 markets across available periods in 2022-2026. Do not invent USDC/NIGHT
history before a pair was listed or select only today's survivors.

Derive inputs exclusively from completed candles available before each decision.
Use a clear warm-up period and separate training, validation and untouched test
windows. Define broad-market signals as well as coin-level metrics; do not feed
always-range/always-eligible fixtures into a claimed strategy backtest. Missing
historical news must be identified as an absent model component, not a fabricated
"safe" signal. Evaluate a documented price-only strategy hypothesis first.

## Fill uncertainty

One-minute OHLCV does not reveal the order of intrabar prices, spread or queue
position. Never spend an entire candle's volume separately at each level. Share
volume budgets, charge fees and slippage, and prevent a buy and its newly created
sell from using an invented favourable intrabar path. Use conservative chronological
bar rules, compare both plausible OHLC paths where useful, and report fill/cost
sensitivity. Do not directly reinterpret klines as the simulator's fresh bid/ask
quotes without an explicit tested adapter and its limitations.

## Comparisons and output

- Same initial capital, quote currency, window and costs for cash, buy-and-hold,
  static grid and the adaptive candidate. Document reserve allocation treatment
  consistently when comparing total wealth and active risk.
- Total equity including reserves and unsold inventory, maximum drawdown,
  turnover, fees/slippage, inventory exposure, time in cash, number of trades,
  loss/return distribution, and sensitivity to hosting costs.
- Clearly separate quote-currency results from EUR purchasing power; conversions
  require observed FX rates and costs.
- Include range, trend and crash periods, unavailable markets, gaps and missed
  fills. Report negative results and the effect of selection/survivorship bias.

## Lifecycle and regime parameters to measure

Report results for these as explicit, pre-registered variants rather than tuning
them on the test window:

- `recenter_after_exit` on/off and `recenter_cooldown_seconds` (e.g. 6 h, 24 h, 72 h);
  record time in cash after exits and losses realised by out-of-range exits.
- `outside_range_seconds` (e.g. 2 h, 6 h, 24 h), with `maximum_frame_gap_seconds`
  set above the replay's frame spacing.
- `minimum_input_quality`, `range_dispersion_limit` and the range score/ADX box;
  report how often each regime and each veto occurs per market and period.

Agree on acceptance criteria before tuning. An exploratory replay is a go/no-go
screen, not evidence sufficient for live deployment. No production development,
capital increase or removal of risk controls is justified by one profitable window.

## Follow-on only if justified

Complete CMC stable-ID mapping, verified news/event risk, incremental streams and
recovery, prolonged live-data paper runs, operational alerts, region/account
eligibility, actual commission assets and protected transfer reconciliation.
Live trading remains separately gated and unavailable in the current code.
