# Read-only Binance market capture (Milestone 3a)

This increment collects auditable market observations. It does not run the
strategy, open paper orders, access accounts, read credentials, or transfer funds.
Milestone 3's complete universe/regime/news/shadow-execution gate remains open.

## Run

Python 3.12+, standard library only:

```bash
PYTHONPATH=src python -m crypto_grid_bot.app \
  --config config/default.toml --capture-market --symbol ADAUSDC \
  --database data/market-observations.db
```

For a finite foreground session, add `--samples 60 --poll-seconds 60`.
Defaults: one sample, 60-second polling. Allowed bounds: 1–120 samples and
60–3600 seconds between captures. Stop with Ctrl-C. This is not deployed hosting.
The symbol is explicit; ADAUSDC is an example, not a recommendation or a claim
that this market is currently available to a particular account or jurisdiction.

Use a separate database from the paper simulator. Databases containing unrelated
tables are rejected. Collection validates the existing paper-only configuration,
but does not use strategy thresholds to turn observations into orders.

Each successful sample prints one JSON record with `decision: observe_only`,
`orders_authorized: false`, measurements, and outstanding eligibility blockers.
Collection stops on the first feed/validation/database error; it never substitutes
old observations, synthetic data, another host, or an authenticated API.
HTTP 418 cooldowns have a conservative 48-hour minimum; HTTP 429 cooldowns have
a 60-second minimum. A longer server Retry-After extends either minimum. These
cooldowns are saved in the database and checked before another request,
including after restart. Keep the same database; do not restart against a new one
to evade exchange limits. These cooldowns are local, not a shared IP-wide limiter.
Run only one collector process per IP until coordinated rate limiting exists.

## Source and API contract

The fixed host is `https://data-api.binance.vision`, Binance's documented
unauthenticated market-data-only host. Allowed GET paths are `/api/v3/time`,
`/api/v3/exchangeInfo`, `/api/v3/klines`, and `/api/v3/depth`. There are no signed
requests, arbitrary URLs, redirect following, or automatic retries. Each capture
uses five requests: clock, metadata, candles, depth, clock. Every new capture
refreshes status and filters. The client bounds response size to 2 MB and uses
a ten-second socket timeout; it accepts only captures completed within ten seconds.
Socket timeouts are not a full wall-clock deadline against a trickling server.

Official contracts consulted on 2026-09-24:

- [Market-data-only endpoints](https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only)
- [Market data endpoints](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)
- [Exchange information and server time](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/general-endpoints)
- [Exchange filters](https://developers.binance.com/docs/binance-spot-api-docs/filters)
- [REST API limits](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/limits)

## Validation and timing

- Require the exact requested symbol, TRADING status, spot permission and LIMIT
  support. Parse price tick, quantity step/minimum/maximum, and notional bounds;
  retain the complete exchange response, including other filters.
- Fetch up to 250 completed UTC hourly candles, with at least 50 contiguous hours.
  `endTime` is fixed using the first exchange-clock response. Reject open candles,
  missing latest candles, gaps, duplicates, disorder, invalid OHLC/volume and
  non-finite or unbounded numeric values. No current incomplete candle enters a
  diagnostic, including when a capture straddles an hour boundary.
- Require clock-request round trips within two seconds, local/exchange skew
  within five seconds, and complete capture duration within ten seconds. Reject
  backwards exchange time or a discontinuity in the local wall clock.
- Require positive, strictly sorted, uncrossed book levels with valid precision.
  Reject regressing update IDs or changed levels at an already stored update ID.
- REST depth has no exchange event timestamp. Store its local request/receive
  window explicitly; this cannot prove source freshness, absence of cached data,
  or queue execution. Clock checks do not manufacture a book event timestamp.

## Diagnostics, not trade signals

All numbers are quote-asset measurements, not EUR values. Indicators use closed
candles: SMA20/50, their relative difference, 24-hour close return and quote volume,
14-period **simple mean** true range (not Wilder-smoothed ATR), and 20-period
Kaufman-style efficiency ratio. Efficiency is absolute net close movement divided
by total absolute close movement; a flat path is zero. No thresholds are tuned and
no profit probability is estimated.

Book diagnostics include midpoint-relative spread and visible quote notional
within ±0.5% of midpoint on each side. Depth is limited to the returned first
100 levels and may not cover the full band; it is a visible-depth lower bound,
not guaranteed executable liquidity. Book and candle timestamps differ by design.
A single coin's SMA relationship is not a broad-market bull/bear classification.

## Persistence and recovery

One SQLite transaction commits raw responses, source/hash/version, local and
exchange timing, normalized candles/book, diagnostics and the observe-only result.
Exact capture retries are idempotent. Changed payloads at the same capture ID,
closed-candle revisions, and out-of-order captures are rejected. Previously stored
candles/books are deduplicated across samples; a repeated book is not new volume.
A failed final write rolls back every new candle, book and capture together.
Feed/validation failures are recorded separately without being marked successful.
No paper-account state or 50/50 reserve ledger is modified.

Storage has no retention/compaction policy yet. Source revisions and clock/book
regressions require investigation; the collector does not silently rewrite history.
Schema version changes require an explicit migration rather than implicit reuse.

## Live best-price stream

`market_data/stream.py` reads the combined public stream
`wss://data-stream.binance.vision/stream?streams=<symbol>@bookTicker/...` (fixed
host, 1-10 validated symbols, one connection). Each message must name an expected
symbol and stream, carry a non-negative integer update ID and positive bounded
decimal prices/sizes, and have bid strictly below ask. A regressing update ID drops
the connection; an exact repeat is ignored.

Spot `bookTicker` messages carry no exchange event time. Freshness is therefore
measured from local receipt (`PriceBook.latest` refuses prices older than 5 s by
default), and 30 s without any message is treated as a dead connection. Every
disconnect clears all prices, so readers get fresh data or an error, never a stale
fallback.

Connection policy: 10 s open timeout, 20 s ping/pong, 16 KiB message limit,
capped jittered backoff (1 s up to 300 s, reset after a connection stays up 60 s),
at most 10 attempts per 5 minutes (Binance allows 300 per IP), planned rotation
after 23 h (Binance closes connections at 24 h), and no retry after HTTP 418/429 on
the handshake. The client uses `HTTPS_PROXY`/`NO_PROXY` and the system trust store.

Not yet done: converting stream prices into simulator frames (signals, fair value
and ATR still come from hourly candles), persisting the stream, and depth or trade
streams for fill-liquidity estimates.

## Validation status and next gate

Offline tests cover the public transport boundary, malformed and incomplete data,
known indicator values, hour rollover, bans/cooldowns, restart, exact retries,
source revisions, injected write failures and paper-database isolation. A real
ADAUSDC capture through the development workspace's HTTPS proxy succeeded on
2026-09-24: 250 closed hourly candles, book and filters passed every validation.
Earlier probes failed only because the workspace blocked the host and the client
ignored `HTTPS_PROXY`; it now tunnels through a plain `http://` CONNECT proxy while
still verifying TLS for the fixed data host. Tests use explicitly synthetic
API-format fixtures and establish software behaviour, not market performance.

Remaining work: CoinMarketCap
stable-ID universe ingestion/mapping; broad-market measurements and confirmed
regimes; news freshness/vetoes; account-specific fees/eligibility; incremental
trade/depth streams with reconnect gap handling; conservative paper execution
using those streams; historical walk-forward validation. Repeated REST snapshots
must never be passed to the existing simulator as fresh fillable volume. Live
execution and actual stablecoin transfers remain separately gated.
