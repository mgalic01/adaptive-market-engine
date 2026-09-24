# Paper simulation contract (schema 3)

## Scope and order lifecycle

`PaperSimulator.process(Frame)` processes one timestamped quote with supplied
market signals and candidate metrics. It is a single-symbol, single-quote-currency
experiment, without exchange accounts, credentials or real transfers. The CLI
demo remains a constructed batch test; it does not establish profitability.

The simulator starts in cash, budgeting up to 80% of unprotected cash including
buy fees. Passive initial buys are below both the current bid and the supplied
fair value. The fair-value ceiling prevents a profitable checkpoint from adding
higher buy levels merely because the latest sell quote is higher.

A fully filled buy creates a paired sell. A fully filled paired sell recreates
the buy at the original lower price, subject to funds, fees, precision and minimum
notional checks. A partial sell does not create a full replacement buy. Every
child order waits for a later event; IDs do not grow into an unbounded nested
chain. Other inventory may remain held while a completed level recycles.
`Frame.allow_new_grid=False` disables both new grids and replacement buys, but
allows existing orders to finish. This is how the original synthetic batch demo
continues to close each batch deliberately.

Whenever inventory becomes flat after sales, unused/recreated buys are cancelled
and net portfolio profit is settled before rebuilding. Thus shallow oscillations
do not leave deeper unfilled buys blocking the 50/50 checkpoint forever. Harvesting
remains deferred while inventory is held: profitable legs are not automatically
new net portfolio profit if other holdings have depreciated.

## Execution assumptions

- Prices, quantities, balances, reservations and fees use Decimal. The unused
  float-based exchange stub was removed; it is not a future live adapter contract.
- A buy requires ask strictly below its limit after slippage; a sell requires bid
  strictly above its limit after slippage. Touching a limit is insufficient.
- Limit fills receive the order limit without favourable price improvement.
  Reducing unpaired inventory and forced exits use bid minus slippage, tick-rounded.
- All fills on one side share that event's participation-limited liquidity. A
  later residual sale deducts liquidity already consumed by matched sells.
- Fees are modelled in quote currency on both sides. Actual commission assets,
  base-fee deductions and fee-token discounts require fill-level reconciliation
  before any live adapter; this model is not an exchange commission guarantee.
- Each distinct quote assumes new usable liquidity. Repeated REST snapshots and
  candle volume are not interchangeable with incremental depth/trade events.
- Signals and candidate metrics are supplied fixtures. Quote validity, freshness,
  spread and execution liquidity are checked independently. There is still no
  production news or broad-market signal pipeline.

## Pauses, halts and recovery

| Condition | Response | Recovery |
| --- | --- | --- |
| Stale/future/out-of-order quote or signal, backward receive clock, excessive spread | Cancel buys; retain sells; no fills or marking from this frame | Two distinct, consecutive fresh eligible observations |
| Fresh frame with news/candidate veto | Cancel buys, stop replenishment, allow reduce-only sells | Same confirmation rule after eligibility returns |
| Daily-loss limit or soft drawdown | Cancel buys, manage sells, block new exposure | Risk limits must pass, then confirmed recovery |
| Invalid numeric/model/symbol input | Cancel all orders; latch halt | Explicit audited resume with fresh checks |
| Emergency or hard drawdown | Cancel orders; latch halt and liquidate using valid event liquidity | Explicit resume; current risk limits must still pass |
| Saved accounting invariant failure | Abort the transaction / refuse opening the account | Investigate; resume cannot bypass corruption |

`SimulationPolicy.recovery_frames` defaults to 2 and is persisted in account
identity. Duplicate events return their recorded result without advancing the
counter. A new ineligible frame or a gap greater than the configured maximum data
age resets confirmation. Emergency/hard-drawdown halts never clear automatically.
Risk baselines are preserved through recovery; a realised loss is not erased by
issuing resume. UTC daily baselines still carry overnight gaps into the risk check.

Pausing cancels the remainder of a partially filled buy. Its unpaired inventory
is sold conservatively on a usable frame, sharing remaining bid capacity with
other sells. Existing paired sell orders are retained, but replenishment stays
disabled until the interrupted grid has drained. Sub-minimum dust remains visible
in `unreserved_inventory`; it is not rounded away or funded using protected money.
A dust-resolution policy is still required for production operation.

A stored grid accumulates observed outside-range time (`outside_seconds`). Only an
interval bracketed by two consecutive valid outside-range frames no more than
`maximum_data_age_seconds` apart is counted. Gaps and unusable frames pause the
clock without erasing time already observed; only a valid frame inside the range
resets it. (Schema 2 reset the clock on every unusable frame, so a flapping feed
could postpone the exit indefinitely.) After six hours of accumulated time
(`SimulationPolicy.outside_range_seconds`), orders are cancelled and inventory
exits to cash with bounded liquidity.

After the exit the account waits in cash. It leaves that state once flat, risk
limits pass and the candidate is eligible, and either price is back inside the old
band or, with `recenter_after_exit=True` (default), `recenter_cooldown_seconds`
(default 24 h) have passed since the exit. The normal recovery confirmations then
apply, and the next grid is built around the current fair value. With
`recenter_after_exit=False` the account deliberately waits until price re-enters the
old band. That can mean waiting indefinitely after a genuine breakout; the report
reason says "recentering disabled". Both settings are hypotheses to measure in
[BACKTEST_PLAN.md](BACKTEST_PLAN.md), not validated choices.

If risk triggers after normal matching, liquidation waits for a later usable
frame. Stale data never authorizes an exit. An offline runner has no independent
watchdog: feed-loss handling for real resting orders remains separate work.

## Explicit paper resume

The public engine method is `PaperSimulator.resume(frame, event_id=..., reason=...)`.
It requires a halted, flat account with no orders, fresh valid observations,
eligible signals and passing risk limits. It logs the prior halt and operator
reason in the same transactional journal, places no order, and waits for the
normal recovery confirmations. Repeating the same command ID/payload is idempotent;
changing its payload is rejected. Inventory or outstanding liquidation must be
resolved before resume; it cannot override loss limits or restore reserve funds.

The operator CLI reopens the saved rules/policy and additionally checks freshness
against the real UTC clock. `fresh-frame.json` must contain `Frame.payload()` with
Decimal values encoded as strings and full quote/signal/candidate inputs:

```bash
PYTHONPATH=src python -m crypto_grid_bot.app --config config/default.toml \
  --resume-paper --database data/paper-v2.db --resume-frame fresh-frame.json \
  --event-id incident-001 --reason "Verified incident resolved"
```

This is a paper control for exceptional incidents, not a normal per-trade approval
step. The project still lacks a production source for the complete input frame.

## Accounting and persistence

`available_quote = cash - pending_reserve - fee_inclusive_buy_reservations`.
Sell reservations never exceed inventory. Active equity marks inventory at bid
less slippage/sell fees and excludes pending savings; total equity includes both
pending and secured savings. Neither reserve category can fund new orders.

At a flat checkpoint, the high-water-mark ledger allocates only new net profit
50/50 and batches simulated transfers. Recovering a loss does not create new
profit. Earmarks adjust risk/daily baselines proportionally. An exhausted active
account is guarded before division; no settlement can divide by zero.

Each simulated transfer has a unique checkpoint ID. The confirmation map persists
in account state and must sum to secured reserve. Events, orders, fills, allocations,
confirmation IDs and account state commit atomically using SQLite WAL/FULL and
`BEGIN IMMEDIATE`. Failures roll back the complete event. This does not solve real
asynchronous transfer reconciliation: live transfers will need durable intents,
exchange IDs, statuses and recovery after uncertain responses.

Saved identity includes schema, policy, configuration, market assumptions and
initial cash. **Schema 1 and 2 databases are rejected by version 0.5; no implicit
migration or reset occurs.** Preserve old experiments with the old code, or start a
clearly separate schema 3 experiment. Never edit identity/state to bypass risk history.

## Verification

The original batch demo still works. New regressions exercise 50 shallow price
oscillations, recycling while other inventory remains, partial sells, reserve
isolation, invalid-frame pauses, recovery confirmation and replay, out-of-range
exit/timer gaps, audited resume, persistent transfer IDs and guarded settlement.
Version 0.5 adds a flapping-feed exit regression (it never exits on schema 2 code),
gap/inside-reset accounting and recentering with and without the cooldown.
The shallow fixture produced 2 fills on the reviewed code and 100 on the corrected
code. This is a behavioural regression result, not a return forecast or backtest.

Historical strategy validation is now the next gate, ahead of universe/news
integration. See [the plan](BACKTEST_PLAN.md) and [the Claude handoff](reviews/2026-09-24-codex-response.md).
