# Paper simulation contract (schema 5)

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
| Invalid numeric/model/symbol input | Cancel all orders; latch halt; if a position is held, arm the exit so it is sold on the next valid frame | Explicit audited resume with fresh checks, once the exit has completed |
| Hard drawdown | Cancel orders; latch halt and liquidate using valid event liquidity | **Final.** Resume re-runs the risk check, and a flat account's equity cannot move, so its drawdown against `risk_high` stays at the trigger value and resume is always refused. See the note below. |
| Emergency signal | Cancel orders; latch halt and liquidate using valid event liquidity | Resumable **only while the drawdown itself is within limits**: the emergency flag is read from the resume frame, so once it clears and every other limit passes, resume succeeds. An emergency raised at or past the hard-drawdown level is final for the reason above. |
| Active capital exhausted | Cancel orders; latch halt | **Final.** Active equity is zero, so the drawdown is 1.0. The reserve is protected and resume cannot return it to the active account. |
| Saved accounting invariant failure | Abort the transaction / refuse opening the account | Investigate; resume cannot bypass corruption |

`SimulationPolicy.recovery_frames` defaults to 2 and is persisted in account
identity. Duplicate events return their recorded result without advancing the
counter. A new ineligible frame or a gap greater than
`SimulationPolicy.maximum_frame_gap_seconds` resets confirmation. The gap defaults
to 180 seconds, allowing fresh one-minute observations. This is separate from
`risk.maximum_data_age_seconds` (30 seconds), which still limits delivery age for
each quote and its strategy inputs. Slower replays must explicitly set a gap at
least as large as their observation interval; the future replay adapter must
validate that relationship. The read-only collector remains separate from this
simulator. Emergency/hard-drawdown halts never clear automatically.
**Pending change (spec v1 amendment 1, `docs/EXPERIMENT_SPEC_V1.md` §3 "Drawdown
recovery"):** once its implementation merges, a soft-drawdown episode rebases the risk
reference after a 24-hour cool-off, and a hard-drawdown halt (category `drawdown` only)
restarts automatically after 24 hours. That supersedes two statements here: the
**Final** in the hard-drawdown row, and the paragraph "A drawdown halt is final, not
merely manual" below. Everything else stands: the emergency halt's conditional resume,
the finality of capital exhaustion, the manual integrity resume, and the exact-zero
inventory rule of the manual `resume()`. The automatic restart, unlike the manual
resume, tolerates a dust residue (spec §3, restart precondition 2). This table describes
the code until then.
Risk baselines are preserved through recovery; a realised loss is not erased by
issuing resume. UTC daily baselines still carry overnight gaps into the risk check.

**A drawdown halt is final, not merely manual.** `resume()` requires the current risk
action to be `ALLOW`. Only `_settle` rescales `risk_high`, and it never runs while
halted; for a flat account active equity cannot change either. The measured drawdown is
therefore frozen at the value that triggered the halt, so every resume attempt is
refused, however long the operator waits and however far the market recovers. The same
holds for an "active capital exhausted" halt, whose drawdown is pinned at 1.0. Changing
this needs a policy decision on rebasing the reference, which is what PR #102 is
deciding; it is deliberately not a code default.

An **emergency** halt is different, and the row above says so: the emergency flag comes
from the frame passed to `resume()`, not from a frozen baseline, so a halt raised only
by that flag clears once the flag does. It is final only when the account is also at or
past the drawdown limit. Do not read "latched" as "unrecoverable" for this one case.

Pausing cancels the remainder of a partially filled buy. Its unpaired inventory
is sold conservatively on a usable frame, sharing remaining bid capacity with
other sells. Existing paired sell orders are retained, but replenishment stays
disabled until the interrupted grid has drained. Sub-minimum dust remains visible
in `unreserved_inventory`; it is not rounded away or funded using protected money.
A dust-resolution policy is still required for production operation.

Because that residue cannot be sold at all — no later frame at the same price can
satisfy the exchange's step and minimum-notional filters — no lifecycle step waits for
it. Profit settlement, opening the next grid and leaving a range exit require instead
that nothing *sellable* is held: flat, or holding only such a residue, with no resting
sell reserving it.

**`resume()` is deliberately stricter and requires exact zero inventory.** A residue is
marked to the current bid, so its value moves with price; admitting it would let a rally
lift active equity back over the soft-drawdown line and clear a hard-drawdown halt that
this document calls final. Continuing to trade with a residue is safe, because the
baselines move with it; clearing a halt on the strength of it is not. A halted account
holding only a residue therefore stays halted until a higher bid makes the residue
sellable and the exit completes.

The residue is never written off and never invented:
it stays in `inventory`, in `unreserved_inventory` and in the equity mark, and it is
excluded from the settlement base, which understates profit rather than overstating it.
Waiting for exact zero instead made a healthy account stop trading for good after any
partial fill smaller than one minimum notional.

A stored grid accumulates observed outside-range time (`outside_seconds`). Only an
interval bracketed by two consecutive valid outside-range frames no more than
`maximum_frame_gap_seconds` apart is counted. Larger gaps do not count and do not
erase time already observed. An unusable frame itself advances nothing; the
interval between valid observations on either side still counts if within the gap
limit. Only a valid frame inside the range resets the clock.
(Schema 2 reset the clock on every unusable frame, so a flapping feed
could postpone the exit indefinitely.) After six hours of accumulated time
(`SimulationPolicy.outside_range_seconds`), orders are cancelled and inventory
exits to cash with bounded liquidity.

`maximum_frame_gap_seconds` is a cadence limit (how far apart observations may be),
separate from `maximum_data_age_seconds` (how old one observation may be). Schema 3
used the 30 s freshness limit for both, so at the collector's 60 s minimum polling
interval pauses never cleared and the out-of-range exit never fired. The gap limit
must exceed the polling interval used in a run.

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
frame. Stale data never authorizes an exit. The same holds for the exit armed by a
validation halt: the invalid frame returns before the liquidation branch, so the sale
can only ever use a later frame that passed every freshness, ordering and quote check. An offline runner has no independent
watchdog: feed-loss handling for real resting orders remains separate work.

## Explicit paper resume

The public engine method is `PaperSimulator.resume(frame, event_id=..., reason=...)`.
It requires a halted, flat account with no orders, fresh valid observations,
eligible signals and passing risk limits. It logs the prior halt and operator
reason in the same transactional journal, places no order, and waits for the
normal recovery confirmations. Repeating the same command ID/payload is idempotent;
changing its payload is rejected. Inventory or outstanding liquidation must be
resolved before resume; it cannot override loss limits or restore reserve funds. A
refusal names which precondition failed, including the total inventory still held when
any is left — resume makes no distinction between an incomplete liquidation and a
residue below the minimum, because both fail the same exact-zero check — and says
plainly when a halt is final.

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
initial cash. **Only schema 5 databases are accepted; schema 1-4 are rejected, with no
implicit migration or reset.** Schema 5 (engine `exit-residue-v1`, PR #122) changed the
exit lifecycle; a schema 4 database is refused rather than silently reinterpreted.
Preserve old experiments with the old code, or start a clearly separate schema 5
experiment. Never edit identity/state to bypass risk history.
The frame-gap policy (added in 0.5.1/0.6) is part of saved identity, so experiments
without that setting are rejected. Use a new database for the new policy; retain
the original database and matching code for reviewing the old experiment.

Broad-market input quality has a separate eligibility veto. Low-quality inputs
remain reported as `TRANSITION`, but `RegimeAssessment.input_quality_ok=False`
blocks entries regardless of the configured opportunity score threshold. Healthy
transition markets retain their existing score-based eligibility.

## Verification

The original batch demo still works. New regressions exercise 50 shallow price
oscillations, recycling while other inventory remains, partial sells, reserve
isolation, invalid-frame pauses, recovery confirmation and replay, out-of-range
exit/timer gaps, audited resume, persistent transfer IDs and guarded settlement.
Version 0.5 adds a flapping-feed exit regression (it never exits on schema 2 code),
gap/inside-reset accounting and recentering with and without the cooldown.
Version 0.6 adds 60 s-cadence regressions for pause recovery, out-of-range exit and
recentering; both fail on schema 3 code.
Version 0.5.1 covers one-minute recovery, six-hour exits and 24-hour recentering,
frame-gap boundaries, persisted-policy compatibility, low-score quality vetoes,
and invalid regime configuration endpoints.
The shallow fixture produced 2 fills on the reviewed code and 100 on the corrected
code. This is a behavioural regression result, not a return forecast or backtest.

Historical strategy validation is now the next gate, ahead of universe/news
integration. See [the plan](BACKTEST_PLAN.md) and [the Claude handoff](reviews/2026-09-24-codex-response.md).
