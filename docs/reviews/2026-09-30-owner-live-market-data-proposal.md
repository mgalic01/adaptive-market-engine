# Owner proposal: live market data layer for real-time trading decisions

Index: 2026-09-30 owner direction. Live order book, real-time structure, buy/sell pressure, on-chain signals. What already exists, what is missing, what to build. Owner decisions required before implementation.

- **Recorded by:** Bob (IBM Bob, owner's desktop session), 2026-09-30
- **Status:** Proposal. Not a spec amendment. Owner decisions required (listed at the end).

---

## What already exists (do not rebuild these)

The codebase already has a solid, production-quality live data foundation:

| Component | File | What it does |
|-----------|------|-------------|
| **WebSocket price stream** | `market_data/stream.py` | Connects to Binance `@bookTicker` WebSocket — live best bid/ask for up to 10 symbols simultaneously. Reconnects automatically, rotates connections every 23h, handles backoff. |
| **REST client** | `market_data/client.py` | Authenticated GET-only to Binance's public data API. Fetches klines, order book depth snapshot (`/api/v3/depth`), exchange info. Rate-limit aware (respects 418/429). |
| **Data collector** | `market_data/collector.py` | Orchestrates fetch + store of historical klines. |
| **Paper simulator** | `simulation/runner.py` | Full paper trading engine. Accepts live `Frame` objects. Already connected to the strategy layer. |

**The WebSocket stream is already streaming live bid/ask.** The order book depth endpoint is already on the allowlist. The paper simulator already runs on live data. The infrastructure is there — it just needs the intelligence layer on top.

---

## What is missing

### M1 — Real-time order book depth (buy/sell pressure)

**What it is:** the current stream only gives best bid/ask (top of book). Real pressure comes from the full order book — how much volume is stacked on the buy side vs sell side within 1-2% of current price.

- **Bid depth** = total quote volume in buy orders within 1% of mid price → buyer conviction
- **Ask depth** = total quote volume in sell orders within 1% of mid price → seller resistance
- **Imbalance ratio** = bid_depth / (bid_depth + ask_depth). > 0.6 = buyers dominating. < 0.4 = sellers dominating.

The `/api/v3/depth` endpoint is already on the client allowlist (`client.py` line 22). It returns up to 5000 levels. **This needs wiring, not building from scratch.**

**What to build:** a `LiveOrderBook` class that:
1. Fetches a depth snapshot every 60 seconds via the REST client
2. Computes bid/ask imbalance within ±1% of mid price
3. Exposes `imbalance: float` (0–1) and `bid_depth_usd: float`, `ask_depth_usd: float`
4. Feeds into `Inputs.buy_pressure` (proposed in P1a of the position trading proposal)

---

### M2 — Real-time kline stream (live candle formation)

**What it is:** currently the bot uses completed hourly candles from archives. In live trading it needs the **forming candle** — what is happening right now, not what happened an hour ago.

Binance provides `@kline_1h` and `@kline_1m` WebSocket streams that push updates every second as each candle forms.

**What to build:** extend `stream.py` to subscribe to `@kline_1m` and `@kline_1h` streams alongside `@bookTicker`. The forming candle's OHLCV updates the `FeatureEngine` inputs in near-real-time instead of waiting for the hourly close.

**Impact:** the regime classifier currently lags by up to 59 minutes (it waits for a completed hourly candle). With live kline streaming, regime decisions update every minute based on the partially-formed candle. This significantly reduces entry/exit lag.

---

### M3 — Taker volume ratio (aggressor pressure)

**What it is:** already described in proposal P1a. The `taker_buy_base_asset_volume` field in each completed 1-minute kline gives the fraction of that minute's volume that was buyer-initiated (aggressive market buys). This is the single clearest signal of short-term directional pressure.

**Current state:** `Kline.taker_buy_base` is already parsed and stored in the archive. In the backtest it is available. In live mode it comes from the kline stream (field `V` in the kline WebSocket message).

**What to build:** wire `taker_buy_base` ratio into `Inputs.buy_pressure` in `features.py`. No new data source — just computation on already-available data.

---

### M4 — Live structure analysis (real-time swing detection)

**What it is:** `structure.py` already detects swing points, S/R zones, and FTA levels from historical candles. In live trading, this runs on the same hourly candle buffer but updated every time a new hourly candle closes.

**Current state:** the `_structure_cache` in `FeatureEngine` already caches structure per completed hourly candle index `p`. This means structure updates automatically every hour in the live bot — **no change needed here.**

**What is missing:** a way to see the structure output in real time for monitoring (a dashboard or log line showing current swing zones, FTA resistance, and alignment score). This is an observability item, not a logic item.

---

### M5 — External sentiment and on-chain signals (new data sources)

These require new data sources beyond Binance:

| Signal | Source | What it tells you | Complexity |
|--------|--------|-------------------|------------|
| **Fear & Greed Index** | alternative.me API (free, public) | Crowd sentiment: extreme fear = buy zone, extreme greed = sell zone. Historically very accurate at cycle extremes. | Low — one JSON endpoint, daily update |
| **Funding rate** | Binance futures public API | Whether perpetual futures traders are long-heavy (positive funding = crowded longs, price likely to drop) or short-heavy (negative funding = shorts squeezed, price likely to rise) | Low — already partially built (`backtest/funding.py`) |
| **Exchange inflows/outflows** | CryptoQuant, Glassnode (paid) or on-chain data | Large BTC moving TO exchanges = selling pressure incoming. Large BTC moving FROM exchanges = holding / accumulation. | Medium-High — requires API key or on-chain node |
| **Open interest** | Binance futures public API | Rising OI + rising price = trend confirmation. Rising OI + falling price = shorts piling in. | Low — public endpoint |
| **Dominance** | CoinGecko public API | BTC dominance rising = altcoin season ending, rotate to BTC. Dominance falling = altcoin season, grid bots work better on alts. | Low — public endpoint |

**Recommended starting point (free, no API keys):**
1. Fear & Greed Index — `https://api.alternative.me/fng/` — one call per day, returns 0-100 score
2. Funding rate — Binance public futures endpoint — already partially in the codebase
3. Open interest — Binance public futures endpoint — no auth required

---

### M6 — Live monitoring dashboard

**What it is:** right now the bot is a black box. To trade confidently you need to see:
- Current regime for each pair (RANGE/BULL/BEAR/TRANSITION)
- Live structure: current swing zones, FTA resistance price, structure alignment score
- Order book imbalance (buy vs sell pressure right now)
- Current taker volume ratio (last 15 minutes)
- Fear & Greed score
- Funding rate for each pair
- Cycle phase (ACCUMULATION / EARLY_BULL / LATE_BULL / DISTRIBUTION / BEAR)
- Any open grids: entry price, current P&L, time open

**What to build:** a simple terminal dashboard (Python `rich` library) or a lightweight web page served locally. Reads from the live data layer and the paper simulator's account state. Updates every 30 seconds.

---

## What the full live data stack looks like

```
Binance WebSocket ──→ PriceStream (exists) ──→ live bid/ask
                 └──→ KlineStream (M2) ──────→ forming candles
Binance REST ────────→ DepthClient (M1) ──────→ order book imbalance
alternative.me ─────→ FearGreedClient (M5) ──→ sentiment score
Binance Futures ────→ FundingClient (M5) ─────→ funding rate + OI

All feeds ──→ LiveFeatureEngine ──→ Inputs (same as backtest)
                                       ↓
                               RegimeClassifier
                                       ↓
                               OpportunityScorer
                                       ↓
                               PaperSimulator (exists)
                                       ↓
                               Live orders (paper only until forward test passes)
```

The key insight: **the backtest and live paths share the same `Inputs` dataclass and `FeatureEngine`**. Adding a new signal to `Inputs` automatically makes it available to both the backtester and the live bot. The architecture is already correct.

---

## Build order (what to do first)

| Step | What | Effort | Impact |
|------|------|--------|--------|
| **1** | Wire `taker_buy_base` ratio → `Inputs.buy_pressure` | 1 day | Immediate: buy/sell pressure in every backtest and live decision |
| **2** | `LiveOrderBook` from existing `/api/v3/depth` client | 2 days | Order book imbalance — the single clearest short-term pressure signal |
| **3** | Fear & Greed Index client | 0.5 days | Free, no auth, daily sentiment signal |
| **4** | Funding rate + open interest from Binance futures public API | 1 day | Already partially built; complete the wiring |
| **5** | Live kline stream (`@kline_1m`) to reduce regime lag | 2 days | Eliminates 59-minute decision lag |
| **6** | Monitoring dashboard | 2 days | Observability — see what the bot is doing and why |

**Total to a fully observable live paper trading bot: ~8–10 working days.**

---

## What this does NOT include

- **Live order placement** — this remains paper-only until the forward test passes (S5 in the v2 backlog). No exchange API keys. No real orders.
- **On-chain data** (exchange inflows, whale alerts) — requires paid API. Out of scope until the free signals are measured.
- **Social sentiment** (Twitter/X, Reddit) — noisy, expensive, legally complex. Not recommended.
- **Price prediction / ML models** — not proposed. The bot uses rule-based signals grounded in price/volume/structure.

---

## Owner decisions required

- [ ] **LD-1:** Approve adding `buy_pressure` (taker volume ratio) to `Inputs` — this changes the `Inputs` dataclass and affects all future backtest reproducibility. Confirm before Claude/Codex implement.
- [ ] **LD-2:** Approve `LiveOrderBook` using the existing `/api/v3/depth` endpoint. Confirm the 60-second refresh frequency is acceptable (more frequent = more API calls, risk of rate limiting).
- [ ] **LD-3:** Approve Fear & Greed Index as an input signal. It is a third-party API (alternative.me). Do you trust it as a signal source?
- [ ] **LD-4:** Approve funding rate + open interest as input signals. These come from Binance futures — a different product from spot. Confirm this is appropriate for a spot grid bot.
- [ ] **LD-5:** Set the priority: should live data be built now (before Variant A backtest), or after the backtest results confirm the strategy direction?

— IBM Bob (owner's desktop session)
