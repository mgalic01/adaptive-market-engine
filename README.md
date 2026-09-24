# Adaptive Crypto Grid Bot

Offline prototype for a planned automated **spot** grid-trading system.
Milestone 2 adds a deterministic single-market paper simulator with fee-aware
partial fills, reserved balances, a persistent journal, and restart recovery.
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
- single-market cash-start grid replay with paired buy/sell orders;
- Decimal balances, fee reservations, tick/quantity/minimum-notional checks;
- conservative spread/slippage-aware fills with shared liquidity limits;
- automatic settled-profit allocation and simulated reserve transfers;
- SQLite atomic state/event persistence, duplicate protection and recovery;
- persistent risk halts and liquidity-limited simulated emergency exits;
- automated unit tests and a GitHub Actions security/quality workflow.

Not yet implemented:

- Binance live adapter or API-key handling;
- CoinMarketCap universe refresh;
- market-data ingestion and indicator calculation;
- live queue/latency modelling and exchange filter discovery;
- multi-market orchestration and automatic rotation execution;
- regime confirmation across distinct observations and persistent cooldowns;
- verified news/event ingestion;
- external deposits/withdrawals and live account reconciliation;
- backtesting and walk-forward validation;
- protected subaccount transfer adapter;
- monitoring dashboard and alerts.

See [ROADMAP.md](ROADMAP.md) for the next delivery gates and
[SECURITY.md](SECURITY.md) for operational boundaries.

## Run the offline paper demo

```bash
PYTHONPATH=src python -m crypto_grid_bot.app \
  --config config/default.toml \
  --paper-demo --database data/paper-demo.db
```

This replays 30 deliberately constructed price cycles for a fictitious
`DEMOUSDT` market, starting with 100 simulated quote units. It exercises partial
fills, fee accounting, compounding and reserve batching. **It is a software
test, not a backtest, EUR conversion, forecast or evidence of profitability.**
It reads no credentials and needs no network. Running the same command again
reuses recorded results without duplicating trades or savings. A different
database path starts a separate simulation; changed account settings are
rejected against an existing database.

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

The simulator applies risk results to simulated orders. Invalid/stale inputs
cancel resting paper orders and latch a halt. Fresh hard-drawdown or emergency
inputs can trigger simulated liquidation, bounded by available liquidity;
unfilled inventory or dust remains visible. Daily pause and soft drawdown
cancel orders and stop trading; soft drawdown uses a conservative full pause
instead of partial resizing. Halts survive restart and have no automatic resume
yet. Savings earmarks adjust risk baselines proportionally and cannot fund orders.

The strategy suggests float-based levels; the simulator converts and rounds
them to Decimal ticks and rechecks costs, quantities and affordability. Actual
exchange rules and fee-asset handling still require a separately tested adapter.
Regime confidence is a heuristic score, not a probability of making money.
There is no background process, deployment, or real fund protection in this version.

This software is experimental and does not guarantee profit. Backtests and
paper results do not predict future performance.
