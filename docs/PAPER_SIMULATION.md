# Paper simulation contract

## What runs

`PaperSimulator.process(Frame)` processes one timestamped quote plus supplied
market signals and candidate metrics. It validates freshness and symbol, checks
the regime and eligibility, evaluates portfolio risk, matches pre-existing orders,
checks risk again, settles profits if flat, and optionally opens a new grid.
The CLI demo uses a fictitious symbol and entirely synthetic prices. No network
endpoint, API key, scheduler, hosting or real money is involved.

The simulation starts in cash. Only passive buy levels below the current bid
are funded; each fully filled buy creates a sell at the next higher grid level.
The new sell waits for a later quote. Partially filled buys retain inventory
and reserve the unfilled cash remainder. It opens another batch only after
every order and position is closed. A batch can stay open indefinitely in an
unfavourable market; there is no promise to "finish" a trade at a profit.

One database represents one symbol and one quote currency. The top-100-plus-NIGHT
configuration is a future universe requirement, not a live feed in this version.

## Fill assumptions

- Prices, quantities, balances and fees use Decimal. Synthetic market filters
  define price tick, quantity step and minimum notional. They are not Binance data.
- Up to 80% of unprotected cash funds a grid, including buy fees. The rest stays
  available; there is no borrowing or short inventory.
- Quote ask must cross strictly below a buy limit after the slippage allowance;
  bid must cross strictly above a sell limit. Touching a limit is insufficient.
- Limit fills occur at the order limit without favourable price improvement.
  Emergency sales use bid minus slippage, rounded down to the tick.
- Only a configured fraction of each quote's available bid/ask size can fill.
  All orders on that side share the budget. Partial fills are supported.
- Fees are charged in quote currency on both sides. Base-asset fees, fee-token
  discounts and actual exchange queue position are not modelled.
- This is a conservative approximation, not a calibrated fill model. Each
  distinct quote assumes fresh usable liquidity; real replay feeds will need
  incremental trade/depth accounting to avoid reusing static order-book size.
- Supplied candidate metrics and signals are test inputs. Only quote freshness,
  spread, execution liquidity and numerical validation are independently checked.
  Production indicators, news provenance and liquidity scoring are later work.

## Accounting invariants

`cash` includes pending savings but excludes savings already transferred in the
simulation. `available_quote = cash - pending - buy_reservations`, where each buy
reservation includes the maximum fee at its limit. Sell reservations cannot
exceed actual inventory. Negative balances and oversubscription abort a transaction.

Active equity is cash minus pending savings plus inventory marked at bid less
slippage and estimated sell fee. Total equity adds pending and secured savings
back to active equity. Reporting only grid sales without unrealized inventory
losses is deliberately avoided.

When flat with no orders, the existing high-water-mark vault splits new net
profit 50/50. Pending savings are never rebudgeted, even below the transfer
threshold. At the threshold, a simulated transfer reduces cash and pending
savings and increases secured savings in the same transaction. This does not
represent a request to an exchange or provide real custody protection.

Earmarking scales daily and risk-high baselines by the remaining-active-capital
fraction. It does not create an artificial drawdown or a negative baseline after
large gains. A new UTC day uses the last recorded active equity as its opening
baseline, so an overnight gap is included in the next risk check. Deposits and
withdrawals are unsupported; no external balance mutation endpoint is exposed.

## Risk and failure handling

Invalid, stale, future-dated or out-of-order inputs cancel simulated resting
orders and latch a halt. Candidate/news vetoes do the same. The actual quote
spread is checked even if supplied candidate metrics claim a tighter spread.
Daily-loss and soft-drawdown actions pause completely; soft partial resizing
and automatic resume are not implemented. Existing inventory remains marked.

A fresh hard-drawdown or emergency event cancels orders and starts liquidity-
limited simulated liquidation. If risk trips after normal matching, liquidation
starts on the next valid event, avoiding double use of that quote's liquidity.
Sub-minimum inventory remains visible as dust. Stale input cannot authorize an
exit. A stopped feed produces no events; this offline runner is not a watchdog.

Halts persist across restarts. Do not restart with a fresh database to conceal
losses; a fresh database is a distinct experiment. Human incident review and a
tested automatic recovery policy are required before unattended live use.

## Persistence and replay

SQLite uses WAL, full synchronous writes and `BEGIN IMMEDIATE`. State changes,
fills in the event result, reserve changes and the event record commit together.
An exception rolls the entire event back. Event IDs are unique; an exact retry
returns the saved result, while the same ID with different content fails.
Separate simulator instances serialize through SQLite's writer lock.

The saved identity includes schema version, all bot config, market assumptions
and initial cash. Reopening with different settings fails. A saved account is
validated on reads and restarts. This detects invalid balances/order reservations,
not malicious tampering with an otherwise internally consistent database.

SQLite atomicity models a local simulated transfer only. A real exchange call
cannot share the transaction: it will require pending/confirmed/failed states,
exchange transfer IDs, reconciliation and retry recovery before live operation.

## Verification

Tests exercise exact fee and cash conservation, partial fills, shared liquidity,
minimums and precision, no same-event child fills, reserved-profit isolation,
news/spread/freshness vetoes, bounded emergency exits, overnight gaps, duplicate
IDs, changed settings, invalid saved balances, restarts during partial orders,
and injected failure during execution and reserve confirmation. Full replay
and interrupted replay produce the same account and event outcomes.

Passing these tests verifies the stated software model. Historical walk-forward
performance, live market suitability and profitability remain untested.
