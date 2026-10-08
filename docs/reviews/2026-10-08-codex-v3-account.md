# V3 account primitives and exact accounting audit

Index: Codex implemented futures fill/funding/mark/liquidation primitives and exact ledger audits; owner decision on a demonstrated PnL rounding conflict remains pending.

Branch: `codex/v3-account`, following order-planning PR #215.
Spec: `docs/EXPERIMENT_SPEC_V3.md` §6 and §8 accounting-failure handling.

## Implemented

`src/crypto_grid_bot/trend/account.py` implements `FuturesAccount`, immutable
position/fill/funding-event records, mark snapshots and terminal liquidation.
It uses fixed normal or double costs and fresh Decimal60 ROUND_HALF_EVEN contexts.

- Opening futures moves only fees, never the notional. Adds update weighted entry;
  reductions realize signed long/short PnL and preserve the remaining entry price.
  Flips require separate reduction and opening intents. Invalid intents fail before
  account or clock mutation.
- Funding is a complete timestamp group, sorted by symbol. All amounts are computed
  before balances change, so a failed item cannot partly charge the account.
  Positive payments are debits, negative payments credits. Duplicate funding groups
  and backward/reserved timestamps are rejected.
- Wallet is evaluated from initial capital and accumulated ledger totals in the
  spec's written order. Marks use sorted positions and supplied prices; the future
  scheduler must supply open, carried or adverse prices as required.
- Liquidation uses equity <=1% of gross notional, skipping a flat book. It stores
  the terminal mark without fees or closing fills and refuses later fills/funding.
- The audit reconstructs wallet and quantities from records and reports the exact
  equity-change/PnL residual. No tolerance, balancing entry or PnL adjustment exists.

## Numerical specification conflict

The [separate proposal](2026-10-08-codex-v3-accounting-rounding-proposal.md) provides
an independently reproduced ordinary fill sequence whose exact PnL identity differs
by -1e-59 USDT due to the mandated arithmetic. The owner has been asked whether to
adopt a narrowly scoped 1e-18 USDT audit tolerance. Until that answer, the strict
audit remains false for this fixture and no replay is authorized. Passing unit tests
means this behavior is correctly detected, not that the conflict is resolved.

This PR also corrects the sizing handoff: negative computed covariance variance is
an engine/numerical issue to stop and diagnose, not a strategy-invalid outcome to
exclude from rule selection. No sizing formula changed.

## Evidence and boundaries

20 account tests pass, including hand-calculated long/short costs/PnL, weighted
entry, funding, boundary liquidation, gap liquidation, timestamp validation,
atomic failures, ledger corruption detection and hostile ambient Decimal settings.
Initial missing APIs produced14 failures before implementation; a separate hostile
constructor context test exposed and fixed contextual absolute-value rounding.

Independent review at bec9371d965a4e8cf060f21cb1bd7217daed2d16 found no substantive
primitive defect and ran additional signed-short, clock-atomicity, terminal and
Decimal-trap cases. Its review did not approve a rounding tolerance. The later
order-planner dependency correction adds unrounded attempt diagnostics; account
code does not consume OrderPlan and still uses unchanged OrderIntent.

Hourly scheduling, pre/post-fill ordering, delevering, masked marks, deferred orders,
trade lifecycles, WFO and evaluation are still required. The class does not enforce
those missing runner responsibilities. No market archives, replay runs, new
libraries, live routes or altered frozen trading rules. External exact-head review
and full CI remain pending.
# Follow-up audit safeguards

Cloud identified three reproducible evidence/validation defects at a5003f7.
The quantity audit now checks the union of position and fill symbols, so a lost
position cannot disappear from reconciliation. Marks retain prices in an immutable
mapping. Empty funding groups are refused before either clock or ledger changes.
Three regressions failed on the earlier implementation and pass after these fixes;
all23 account tests pass, along with Ruff, formatting and mypy. No arithmetic,
funding rates, costs, liquidation threshold or proposed tolerance changed.

