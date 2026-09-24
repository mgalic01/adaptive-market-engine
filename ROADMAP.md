# Delivery gates

## 1. Decision-core foundation (merged)

Paper-only configuration, heuristic regime classification, candidate scoring,
indicative grid sizing, rotation policy, risk recommendations, settled 50/50
reserve accounting, order stub, tests, and CI. No claim of strategy profitability.

## 2. Reproducible end-to-end paper simulator (merged)

- Feed deterministic, timestamped synthetic quotes through one risk-gated decision loop.
- Model cash and inventory reservations, fees, spread, conservative fills,
  partial fills, cancellations, and exchange quantity/price/notional filters.
- Persist orders, fills, equity, and reserve events transactionally in SQLite.
- Verify replay determinism, restart recovery, duplicate events, balance
  invariants and reserve-adjusted baselines. External deposits/withdrawals
  remain unsupported and have no public mutation API.
- Ensure protected reserve cannot be submitted as order capital.
- Simulate the 50/50 profit loop, losses, interrupted transfers, and recovery.

Gate: replay/restart/failure tests pass; no network trading endpoint exists.
Scope is one simulated symbol per account, cash-start grids, quote-asset fees,
and flat-account reserve checkpoints. Version 0.4 adds grid recycling and confirmed
recovery of temporary pauses; hard halts require reviewed resume. Rotation execution,
live order reconciliation and real transfers remain separate work.

## Next gate: strategy feasibility before expanding integrations

The external review found that the original grid did not recycle and transient
conditions permanently halted it. Version 0.4 fixes recycling/flat checkpoints,
recovery controls and regime-confidence discontinuities. These are software fixes,
not evidence of a trading edge. See [the handoff](docs/reviews/2026-09-24-codex-response.md).
Version 0.5 aligns regime decisions with the configured limits, makes the
outside-range exit robust to a flapping feed and adds optional recentering; see
[Claude fixes](docs/reviews/2026-09-24-claude-fixes.md).

**Do the historical feasibility spike described in section 4 next**, ahead of the
remaining section 3 work. Start with a small verified replay harness, then expand
across regimes/pairs and held-out windows. See [BACKTEST_PLAN.md](docs/BACKTEST_PLAN.md).
Continue broader infrastructure only if the results justify it.

## 3. Read-only market-data shadow mode (partly implemented; expansion deferred)

Milestone 3a adds a GET-only public-data collector, validated closed hourly candles,
book/filter snapshots, descriptive indicators, and atomic observation storage.
No execution occurs in capture mode. Fixture tests pass, and a real ADAUSDC
capture succeeded on 2026-09-24. See
[MARKET_DATA.md](docs/MARKET_DATA.md). The following full-stage gates remain:

- Refresh CoinMarketCap top 100 plus NIGHT using stable identifiers, then map
  to actually available eligible Binance spot pairs. Membership is not an order.
- Exclude stablecoin-to-stablecoin grids, leveraged products, duplicate exposures,
  unavailable markets, and assets that fail liquidity/history checks.
- Ingest exchange candles, spread/depth and filters; compute indicators without
  look-ahead. Implement regime confirmation and news freshness/veto handling.
- Start with one affordable grid; remain in cash if costs or minimums fail.
- Handle disconnects, API limits, clock skew, stale feeds, delistings, and outages.
- Log every recommendation and veto with its inputs, timestamp, and config version.

Gate: read-only shadow run demonstrates correct recovery and accounting.

## 4. Strategy validation

Walk-forward tests across multiple regimes with fees, slippage, inventory
mark-to-market losses, delistings, and point-in-time universes. Compare cash,
buy-and-hold and static-grid baselines. Report total equity including reserve,
drawdown, turnover, costs and uncertainty. Do not optimize solely for win rate
or realized grid profit while ignoring inventory losses. News cannot create
orders or override risk controls. Revisit heuristic thresholds using held-out data.

Gate: documented results and failure tests; no guaranteed return assumptions.

## 5. Explicitly approved, limited live pilot

Only after the preceding gates: separately review regional exchange/stablecoin
availability, deployment costs, keys, reserve segregation and transfer permissions.
Use bounded initial capital, spot-only trading, monitoring, a kill switch and
operator incident instructions. Keep live execution disabled until approved.

The EUR budget must be converted using actual rates and fees, not treated as
an equal number of USDT/USDC. Hosting is a separate decision and cost.
Trading can be automated, but outages, security incidents and tax records still
require human oversight. Codex development tasks are not 24/7 bot hosting.
