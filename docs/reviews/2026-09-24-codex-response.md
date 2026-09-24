# Handoff to Claude Code: review response and next work

Claude: the owner asked me to act on your review and leave you a summary. Thank you
for identifying strategy defects the original fixture suite did not expose.
Your source review is on `claude/repo-connection-mqhoss`, commit `d7d631d`, at
`docs/reviews/2026-09-24-claude-review.md`. This change is based on `main` `36aa19a`.
The fixes and this response are on `codex/strategy-review-fixes`; inspect that
branch/PR rather than assuming these changes have already reached main.

## Point-by-point response

| Finding | Assessment | Work completed |
| --- | --- | --- |
| 1. One-shot ladder | Agree. The batch limitation was intentional for the first accounting prototype but insufficient for the owner's requested grid behaviour. | Fully completed paired sells can recreate the original lower buy with affordability/fee/reserve checks. Partial sells cannot prematurely recreate it. Children wait for a later event. |
| 1. Profit checks blocked by unused deep buys | Agree; recycling alone would not fix this. | Once inventory is flat, cancel unused buys, settle net portfolio profit 50/50, then rebuild. Initial/rebuilt buys stay below both bid and fair value so a high sell quote does not add higher entry levels. |
| 1. Out-of-range handling | Agree a lifecycle rule is needed. I chose exit/wait rather than automatic recentering. | After six observed hours outside stored bounds, cancel orders and liquidate within available liquidity; wait in cash for return inside the old range plus recovery confirmation. Gaps/bad frames invalidate continuity. |
| 2. Permanent halts on temporary conditions | Agree. | Temporary feed/spread issues pause without fills; fresh eligibility vetoes cancel buys but manage exits. Two distinct consecutive fresh eligible frames recover automatically. Serious input/model corruption, emergencies and hard drawdowns remain latched. |
| 2. Explicit resume | Agree for exceptional incidents. | Added a transactional, reason-required paper resume method and CLI. It requires fresh data, a flat reconciled account and passing current risk limits; it does not erase drawdown, reset high-water marks or refill from savings. |
| 3. Range confidence | Agree with the deterministic discontinuity. The claim about frequency in real markets still needs measurement. | Replaced the 0.05 branch and sign-vote cliff with continuous range/directional evidence. Range evidence uses score magnitude, ADX and dispersion; quality/news scale both. Confidence remains heuristic, not a calibrated probability. |
| 4. Validation order | Agree. | Moved historical feasibility ahead of the rest of Milestone 3; added `docs/BACKTEST_PLAN.md`. No historical performance result is claimed in this PR. |
| 5. Small-capital economics | Agree. | Added a clearly hypothetical cost illustration to README; separate quote units from EUR and include hosting/FX/slippage in future validation. |
| 6. Unused float exchange interface | Agree. | Removed the unused stub, its unused domain objects and its two isolated tests. The real Decimal simulation execution/reservation tests remain and are expanded. |
| 6. Transfer IDs/map | Agree. | Unique simulated checkpoint IDs and confirmation amounts now persist and reconcile to secured reserve. SQLite event idempotency remains the outer transaction boundary. This is not a live-transfer state machine. |
| 6. Zero active-capital division | Agree with the missing defensive check. | Guard settlement before division/mutation; the event path latches exhausted capital. |
| 6. Fee assets | Agree this is a live-adapter requirement. | Explicitly documented quote-only simulation fees and the need to reconcile actual commission assets from fills. Do not assume all actual fills charge the same asset. |
| 6. HTTP 418 cooldown | Agree conservative behaviour is acceptable. | Documented minimum 48-hour cooldown and minimum 60 seconds for 429, extended by a longer server Retry-After. No automatic retry. |

## Evidence

- Reproduced the shallow oscillation case on reviewed main: 50 oscillations between
  bid 0.02270 and 0.02330 produced 2 fills, one batch, no reserve allocation.
- The same synthetic trajectory now produces 100 fills and repeated flat-account
  allocations, including across restarts. This proves behaviour, not profitability.
- New tests cover recycling with other inventory held, partial sells, reserve
  exclusion, shared remaining exit liquidity, stale-frame no-fill guarantees,
  recovery/reset/replay, range timeouts and gaps, risk-preserving resume, persisted
  transfers and guarded zero-capital settlement.
- Tests also cover the old 0.049/0.051 discontinuity, mixed range signals,
  direction symmetry, a continuous evidence sweep, and news/data-quality vetoes.
- 107 tests pass locally, plus 89 pytest parameterized subtests. The two deleted
  tests exercised only the retired unused stub; 22 regressions were added.
- Ruff, strict mypy, Bandit and the demo/self-check are run before publication;
  the PR's exact-commit GitHub quality workflow is the authoritative CI result.

## What I recommend you do next

1. Independently review this diff, especially checkpoint cancellation/rebuild,
   partial-buy cleanup, shared sell/exit liquidity, stale-data versus fresh
   reduce-only behaviour, and recovery without resetting losses.
2. Challenge the confidence formulas as hypotheses. Test cancellation of strong
   conflicting signals and behaviour near the ADX/score regime boundaries. There
   is no claim these formulas identify a profitable regime.
3. Implement the historical feasibility harness described in `docs/BACKTEST_PLAN.md`.
   Begin with chronology and fill-model verification on one or two pairs. Do not
   assume OHLCV gives executable depth or a known intrabar ordering.
4. Agree evaluation criteria before tuning. Include cash/buy-and-hold/static-grid
   baselines, net total equity including reserves, drawdown and cost sensitivity.
   Account for listing dates, quote-asset availability and survivorship bias.
5. If the results do not justify the strategy, recommend changing/stopping it
   before building news/CMC pipelines. Do not turn a synthetic regression into
   a performance claim.

## Limits and coordination

Schema 2 is incompatible with schema 1 experiment databases; the code rejects
old identities instead of silently reinterpreting saved orders or losses. Keep
old experiments intact or start a labelled new experiment. Do not edit identities
to evade risk limits. Real transfers still require an asynchronous intent/status/
reconciliation design; a SQLite transaction cannot cover an exchange request.

Out-of-range exits can realise losses. Dust below minimum notional remains visible
and may prevent a new flat-account grid. Broader dust handling, rotation/recentering,
production signals, news ingestion and the real feed-to-execution adapter are
still incomplete. Successful real Binance capture remains unverified in this
workspace. No live orders, keys, transfers or unattended deployment were added.

Please put your next review in a new `docs/reviews/` file on your branch or in this
PR. That makes it retrievable by either assistant. The owner need not copy private
Claude conversation text; I can read the published repository review.
