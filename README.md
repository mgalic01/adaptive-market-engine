# Adaptive Crypto Grid Bot

Development prototype for a planned automated **spot** grid-trading system.
Version 0.4 added repeating grid levels, automatic recovery from temporary pauses
and audited paper resume. Version 0.5 makes the configured regime limits the real
decision boundaries, stops a flapping feed from postponing the outside-range exit
and adds optional recentering after that exit. Version 0.6 separates frame cadence
from data freshness, so pauses clear and range exits fire at 60 s polling. Historical strategy validation is
the next gate; profitable operation is not established.
It cannot submit live Binance orders, access an account, or move real funds.

## Agreed operating rules

These are project requirements, not claims that all features work today.
The numeric thresholds are initial hypotheses, not validated trading advantages.

- Monitor CoinMarketCap's top 100 assets plus Midnight (`NIGHT`).
- Trade only Binance spot markets; no leverage, futures, or martingale.
- Classify the broad market as range, bull, bear, transition, or stress.
- Trade only when market regime, coin suitability, liquidity, costs, and news
  risk all pass deterministic checks.
- Start with one affordable active grid. Five slots are a future maximum, not a
  requirement.
- Rotate only when a replacement remains at least 20% better for two scoring
  cycles and its expected improvement exceeds three times switching costs.
- Split every confirmed net portfolio profit 50/50: lock half for the protected
  stablecoin reserve and compound the other half.
- Never refill active trading capital from the protected reserve.
- Fail closed on stale data, unknown order state, balance mismatch, or exchange
  errors.

## Current milestone

Implemented:

- typed domain model;
- TOML configuration and validation;
- explainable market-regime classifier;
- coin opportunity scoring;
- geometric-grid viability checks;
- rotation hysteresis;
- drawdown and daily-loss circuit breakers;
- high-water-mark profit-vault ledger;
- single-market cash-start grid replay with recycling buy/sell levels;
- Decimal balances, fee reservations, tick/quantity/minimum-notional checks;
- conservative spread/slippage-aware fills with shared liquidity limits;
- automatic settled-profit allocation and simulated reserve transfers;
- SQLite atomic state/event persistence, duplicate protection and recovery;
- recoverable pauses, persistent hard halts, audited paper resume and bounded exits;
- flat-inventory profit checkpoints and persistent simulated transfer IDs;
- public Binance candle/book/filter capture with strict validation;
- descriptive closed-candle indicators and isolated SQLite observation storage;
- automated unit tests and a GitHub Actions security/quality workflow.

Not yet implemented:

- Binance live adapter or API-key handling;
- CoinMarketCap universe refresh;
- streamed market-data ingestion and full market-regime inputs;
- live queue/latency modelling and complete order-filter enforcement;
- multi-market orchestration and automatic rotation execution;
- regime confirmation across distinct observations and persistent cooldowns;
- verified news/event ingestion;
- external deposits/withdrawals and live account reconciliation;
- backtesting and walk-forward validation;
- protected subaccount transfer adapter;
- monitoring dashboard and alerts.

See [ROADMAP.md](ROADMAP.md) for the next delivery gates and
[SECURITY.md](SECURITY.md) for operational boundaries.

## Capture public market data

```bash
PYTHONPATH=src python -m crypto_grid_bot.app \
  --config config/default.toml --capture-market --symbol ADAUSDC \
  --database data/market-observations.db
```

This finite, read-only collector needs no API key and reports observations only.
It does not place paper/live orders or interpret missing news as safe. A real
ADAUSDC capture succeeded on 2026-09-24 (250 closed hourly candles plus book and
filters, all validations passing). The collector honours a standard `HTTPS_PROXY`
(plain `http://` CONNECT proxy) and `NO_PROXY`. See [Market data](docs/MARKET_DATA.md) for validation, repeat collection,
source contracts and remaining Milestone 3 gates.

## Run the offline paper demo

```bash
PYTHONPATH=src python -m crypto_grid_bot.app \
  --config config/default.toml \
  --paper-demo --database data/paper-demo-v2.db
```

This replays 30 deliberately constructed price cycles for a fictitious
`DEMOUSDT` market, starting with 100 simulated quote units. It exercises partial
fills, fee accounting, compounding and reserve batching. **It is a software
test, not a backtest, EUR conversion, forecast or evidence of profitability.**
It reads no credentials and needs no network. Running the same command again
reuses recorded results without duplicating trades or savings. A different
database path starts a separate simulation; changed account settings are
rejected against an existing database. Version 0.6 uses schema 4 and rejects old
schema 1-3 experiments; no implicit migration or resetting of losses occurs.

See [Paper simulation](docs/PAPER_SIMULATION.md) for accounting, fill assumptions,
recovery behaviour and remaining limits.

## Run the self-check

Requires Python 3.12 or newer and no runtime dependencies.

```bash
PYTHONPATH=src python -m crypto_grid_bot.app \
  --config config/default.toml \
  --self-check
```

Run tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Development checks (in a virtual environment):

```bash
python -m pip install -r requirements-dev.lock
python -m pip install -e . --no-deps
ruff check .
ruff format --check .
mypy src
pytest
bandit -q -r src
pip-audit
```

## Profit reserve accounting

The prototype ledger uses `Decimal` and only accepts settled quote cash after
fees, with all positions closed and no outstanding orders. Input cash includes
pending reserve and excludes reserve already transferred. Pending reserve is
deducted before calculating new profits, so repeated balance checks cannot
allocate the same profit twice. Recoveries below the adjusted high-water mark
are not new profits. Transfer confirmations are idempotent by transfer ID.

Example in quote-currency units (not an assumed EUR/USD exchange rate):

| Event | Active capital | Pending reserve | Secured reserve |
| --- | ---: | ---: | ---: |
| Start | 100 | 0 | 0 |
| Settle at 200; allocate | 150 | 50 | 0 |
| Confirm transfer of 50 | 150 | 0 | 50 |
| Later settle active account at 180; allocate | 165 | 15 | 50 |

This implements the latest 50/50 compounding rule, not the earlier fixed-100
capital proposal. A transfer threshold batches small amounts; earmarked funds
are unavailable for trading even below that threshold. `confirm_transfer` is
only a ledger operation, not an exchange API call. The offline simulator performs
allocation, simulated transfer, order updates and event recording in one SQLite
transaction. A real transfer requires a separate asynchronous reconciliation design.
External deposits/withdrawals are not supported by this ledger yet. Production
allocation with open positions requires additional realized-P&L accounting.

## Safety boundary

`mode = "paper"` is mandatory in the current version. Configuration validation
rejects any other mode. No secret belongs in source control; `.env.example`
contains names only.

The simulator applies risk results to simulated orders. Invalid numeric/model
inputs latch a halt. Stale/spread/order-of-arrival issues cancel buys and pause
without fills. Fresh hard-drawdown or emergency
inputs can trigger simulated liquidation, bounded by available liquidity;
unfilled inventory or dust remains visible. Daily-loss and soft-drawdown pauses cancel buy entries and manage exits. Temporary
pauses recover after consecutive eligible observations; hard halts require the
audited paper resume checks. Resume cannot erase losses. Savings earmarks adjust
risk baselines proportionally and cannot fund orders.

The strategy suggests float-based levels; the simulator converts and rounds
them to Decimal ticks and rechecks costs, quantities and affordability. Actual
exchange rules and fee-asset handling still require a separately tested adapter.
Regime confidence is a heuristic score, not a probability of making money.
There is no background process, deployment, or real fund protection in this version.

### Regime decision boundaries

The `[regime]` limits in `config/default.toml` are the actual boundaries, and
input quality (`data_quality * (1 - news_risk)`) is a veto rather than a
multiplier on the confidence gate:

| Regime | Requires (defaults) |
| --- | --- |
| range | quality >= 0.70, \|score\| <= 0.25, ADX <= 22, mean \|signal\| <= 0.50 |
| bull / bear | quality >= 0.70, ADX > 22, score >= 0.35 / <= -0.35 with fully coherent votes; conflicting votes need a larger score |
| stress | emergency flag |
| transition | everything else, including any quality veto |

Evidence equals `minimum_confidence` exactly on each boundary and is continuous.
Only range (and exceptional bull candidates) can pass the opportunity score, so
a quality veto means no new grid. These limits are untested hypotheses.

This software is experimental and does not guarantee profit. Backtests and
paper results do not predict future performance.

## Validation priority and small-capital economics

The [Codex response](docs/reviews/2026-09-24-codex-response.md),
[Claude review #2](docs/reviews/2026-09-24-claude-review-2.md) and
[Claude fixes](docs/reviews/2026-09-24-claude-fixes.md) record the behavioural
defects and fixes. The [historical feasibility plan](docs/BACKTEST_PLAN.md)
now comes before further universe/news infrastructure.

For illustration only: a 20-quote-unit purchase with 1% price spacing and a 0.1%
fee on each side yields about 0.16 quote units before slippage. A hypothetical
5-quote-unit monthly hosting cost alone would require roughly 32 such completed
round trips. Inventory losses, unsuccessful trades and other costs are additional.
These are assumed inputs, not observed fees, returns or hosting prices. A €100
budget is not automatically 100 USDC/USDT; FX and conversion costs matter.
