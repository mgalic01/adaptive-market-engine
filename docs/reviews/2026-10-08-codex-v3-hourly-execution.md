# V3 hourly execution and deferred decisions

Index: V3 execution primitives implement mandatory reductions, leverage checkpoints,
hourly event order and pending decision replacement; synthetic validation only.

Purpose: faithfully simulate the frozen V3 exposure and costs before judging its
returns. These modules do not establish profitability or authorize replay.

`plan_reduction` shares minimum/dust/split rules with daily order planning but
has no turnover band. `leverage_checkpoint` checks liquidation before reducing,
accounts for masked gross exposure, plans one alphabetical reduction batch and
checks the post-cost book. Invalid outcomes are explicit.

`execute_hour` takes supplied open/carried prices, unmasked extremes and filters,
ready targets and complete raw-timestamp funding groups. It retains the pre-fill
open sample, executes reductions before increases using common pre-batch equity,
checks the post-fill book, applies funding groups in time order with risk checks,
then checks simultaneous adverse extremes without simulated liquidation fills.

`PendingDecisions` replaces old targets before midnight processing, retains absent
coins' pending targets, starts each new decision at 01:00 and dispatches at the
coin's first supplied tradable hour. Cancellations and decision timestamps remain
available for the future decision/lifecycle reporter.

Validation: 120 synthetic execution, pending, reduction, account, order, sizing and
signal tests pass. New API tests failed before implementation. Ruff, formatting
and mypy pass. External review and full CI are pending.

Outstanding: a continuous runner must supply complete hourly coverage and carried
marks, stop on terminal/invalid results, enforce the strict accounting audit, retain
the true peak and statistics, handle excluded-month forced closures, and generate
decision and lifecycle evidence. These APIs alone do not enforce those obligations.
The accounting tolerance proposal remains unapproved; no tolerance is adopted.
No historical data accessed, no fetch or replay, no dependencies or live trading.

Named writer: Codex Desktop. Branch is stacked on the account PR; do not merge into
that dependency. All future scheduler work must preserve the frozen event ordering.
