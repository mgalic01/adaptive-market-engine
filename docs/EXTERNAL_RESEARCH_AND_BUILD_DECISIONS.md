# External research and build decisions

Consolidated 2026-10-06 from the owner's strategy/product research chat.
Status: planning reference in draft PR #169; no platform adoption or merge.
Parent: [High-performance crypto strategy roadmap](HIGH_PERFORMANCE_CRYPTO_STRATEGY_ROADMAP.md).
Main refreshed for publication: `e9279aeff6b8b0138f387e10443be321869394ee`.
The engineering comparison below inspected main `7c5a472ea52b72fb48c591325f9d5b258c79eb1f`;
it is not an audit of subsequent main changes. Recheck gaps before implementation.

## Purpose and decision standard

Build a competitive spot and futures long/short product that maximizes compounded
net return within a defined drawdown and ruin-risk budget. Favorable 10–20%+ months
may occur; they are not guaranteed monthly targets. Productive risk takes priority
over loosening limits. Effort and feature count do not establish competitiveness.

Engineering improvements can be justified without proof of higher trading returns:
preventing duplicate orders, preserving evidence and making losses explainable have
direct value. Signal changes still require preregistered, cost-aware evaluation.
Every proposed addition must close a demonstrated gap or support a specific test.
At roughly EUR 100 starting capital, operating/model costs and minimum order sizes
matter. Trading profits are not a dependable near-term development budget.

Current spec v2 remains authoritative and frozen. These proposals do not change its
acceptance rules, authorize reserved 2025-onward market data, or enable live orders.
The original roadmap covers adaptive grid spacing, capital utilization, rotation,
hybrid trend/grid, composite spot and futures leverage/funding/OI/margin/portfolio
risk in detail; this document consolidates external evidence without duplicating it.

## Coverage and evidence limits

The survey covered accessible recent/all-time-top subreddit listings, indexed older
posts and selected discussions, followed by primary repository inspection. Reddit's
bulk JSON listing failed. This was not a complete subreddit scrape or archive;
deleted/private/unindexed content and every comment on every post were not covered.
Promotional claims and community anecdotes were not treated as verified returns.

Three independent read-only agents inspected Jesse, MDRAP and Fenix source/tests.
Upstream code and tests were not executed, dependencies were not installed, and no
trading account was connected. Static findings are not runtime reproductions or
whole-project security certifications. Existing historical result exports used by
the earlier OpenTraderWorld probe were development artifacts, not new strategy runs.

| Project | Inspected commit | Decision |
| --- | --- | --- |
| OpenTraderWorld | `a3383baff1b5bb6d78c349437c45fbbe32cd4836` | Keep UI/research concepts; no platform dependency |
| trend-switcher | `e59282d6232e541b944ab4a8930333379283ba2c` | Bounded exit/re-entry questions in Addendum A |
| CacheCarti/Crypto-Strategies | `f8e32599c192b823dbe7aea77a2b9341c6114527` | Hypothesis library, not validated profitable strategies |
| Jesse | `417f8765225e3bfc12043d4b712f19fe15a3c078` | Adapt research visualization and testing designs |
| MDRAP | `b614bf86b54c2933ddf5c971e0edbcb0c0c316a2` | Selective data/replay tests; do not integrate platform |
| FenixAI | `bd7373d59bee48addea51989796df27f69193a34` | Adapt execution safeguards and visibility concepts |

## Existing research retained

### OpenTraderWorld and trend-switcher

OpenTraderWorld is a separate product. Its example strategies overlap our trend and
regime ideas but are not its author's demonstrated profitable strategy package.
Addendum B records the EMA reclaim, SMA200, RSI momentum/reversion and two-sided
fade comparisons. Its demo saved-run statistics are fixed seeded values, not measured
backtests: [builder](https://github.com/G-OTW/OpenTraderWorld/blob/a3383baff1b5bb6d78c349437c45fbbe32cd4836/core/otw-core/src/demo_seed.rs#L846).
That is a demo limitation, not evidence of fraud. Its FSL license must be considered
before any commercial source reuse; no such reuse is proposed.

[PR #177](https://github.com/mgalic01/adaptive-market-engine/pull/177) preserves the
separate evaluation and standard-library offline export probe. It retained original
result bytes and provenance; the plain HTML preview was not a full trading dashboard
or an installed OpenTraderWorld instance. The richer graphs/tables the owner wants
are a separate proposed viewer below. No upstream application dependency was added.

The [OpenTraderWorld Reddit discussion](https://www.reddit.com/r/ai_trading/comments/1wvlmtc/how_i_automated_strategy_research_and_discovery/)
raised immutable experiment identity, journal history and permission revocation.
Use those as review questions. History and permissions require source/runtime checks,
not assumptions from an attractive UI. The earlier evaluation in PR #177 retains
the detailed source observations and their limitations.

The [trend-switcher project](https://github.com/dimonb19a/trend-switcher/tree/e59282d6232e541b944ab4a8930333379283ba2c)
motivates continuous-state exit/re-entry testing, not a performance expectation.
Addendum A defines isolated L0/L1/L2 comparisons; mandatory risk exits stay unchanged.

### Reddit engineering discussion

The [strategy-is-not-the-hardest-part discussion](https://www.reddit.com/r/algotradingcrypto/comments/1wusjlq/building_an_algorithmic_trading_bot_the_strategy/)
adds no reproducible alpha. Retain reconciliation before new exposure, realistic
costs, partial fills, and separate execution-correctness and economic-quality gates.
Do not adopt unsupported fixed backtest-to-live performance ratios or endlessly
retune failed ideas. Unknown exchange state is not flat state. Protective actions
must remain possible subject to valid execution/reconciliation safeguards.

### The 416-strategy collection

[Source and cards](https://github.com/CacheCarti/Crypto-Strategies/tree/f8e32599c192b823dbe7aea77a2b9341c6114527)
contain useful hypotheses, but all ten published passed cards report negative OOS
returns. Every one records stages_passed=2 while its note claims seven-stage success.
This is an unresolved reporting inconsistency, not proof of fraud. The complete
validation engine and imported domains.strategy_contract are not included.

| Published passed file stem | Reported OOS return (bps) | Trades |
| --- | ---: | ---: |
| asia_drift_btc_v2 | -155.76 | 9 |
| asia_drift_btc_v3 | -165.26 | 8 |
| asia_drift_btc_v9 | -176.87 | 4 |
| crash_recovery_eth_v3 | -169.13 | 7 |
| ema_pullback_eth_v7 | -562.98 | 52 |
| gap_fade_btc_v8 | -372.46 | 49 |
| monday_drift_sol_v4 | -273.34 | 8 |
| rel_strength_eth_v3 | -302.97 | 10 |
| scalp_btclead_sol_v3 | -325.08 | 37 |
| vol_burst_sol_v2 | -243.55 | 86 |

These are copied reported metrics, not independently reproduced outcomes; 100 bps
equals one percentage point. Selection among hundreds of related trials and short
evaluation histories requires multiple-testing and uncertainty treatment.

Keep session timing as a candidate incremental filter, relative strength within
rotation/directional research, and BTC-to-altcoin lead/lag as a deferred hypothesis.
Do not execute all 416 or select on these cards. The
[relative-strength file](https://github.com/CacheCarti/Crypto-Strategies/blob/f8e32599c192b823dbe7aea77a2b9341c6114527/passed/rel_strength_eth_v3.py)
trades ETH long/short, not portfolio rotation, and defaults missing return features
to zero. Independently specify feature units, lookbacks, availability and missingness.
Any trial uses our own frozen costs and accounting; the MIT label is not validation.

## Jesse: adapt research visibility, not futures accounting wholesale

Persisted candle/order/indicator payloads and route-specific retrieval are useful
references for a local viewer over our immutable run records:
[saved payload](https://github.com/jesse-ai/jesse/blob/417f8765225e3bfc12043d4b712f19fe15a3c078/jesse/modes/backtest_mode.py#L231),
[retrieval](https://github.com/jesse-ai/jesse/blob/417f8765225e3bfc12043d4b712f19fe15a3c078/jesse/controllers/backtest_controller.py#L268).
Show equity/drawdown, fills, fees, regimes, rejected entries and open inventory.
Do not invent candle/trade detail absent from an existing artifact: show unavailable
fields and extend future permitted exports separately. Preserve zero-trade runs.

Its [rule-significance implementation](https://github.com/jesse-ai/jesse/blob/417f8765225e3bfc12043d4b712f19fe15a3c078/jesse/research/rule_significance_testing/rule_significance.py#L158)
uses centered stationary block-bootstrap rule returns. It is not the random-entry
comparison described in the README and not a full costs/exits/sizing backtest.
Borrow a seeded, preregistered diagnostic design with explicit null, horizon, block
length, finite-simulation p-value and multiple-testing treatment. Genuine random-entry
controls would need separate matched constraints in our engine.

Borrow run-isolation and simulator-parity test ideas:
[isolation](https://github.com/jesse-ai/jesse/blob/417f8765225e3bfc12043d4b712f19fe15a3c078/tests/test_isolated_backtest.py#L410).
Do not replace our adverse/favorable intrabar comparisons with a single assumed path.
Backtests set funding to zero and mark price to current price; isolated liquidation
uses fixed maintenance assumptions and cross liquidation returns NaN:
[Position.py](https://github.com/jesse-ai/jesse/blob/417f8765225e3bfc12043d4b712f19fe15a3c078/jesse/models/Position.py#L32).
Our futures engine requires venue-specific funding, marks and margin tiers.

Public code is MIT. The full stack includes PostgreSQL/Redis, FastAPI, Ray, Optuna
and native components: [dependencies](https://github.com/jesse-ai/jesse/blob/417f8765225e3bfc12043d4b712f19fe15a3c078/requirements.txt).
Live/paper plugin terms and [pricing](https://jesse.trade/pricing) are separate and
changeable. No subscription or migration is recommended for these narrow features.

## MDRAP: adapt failure tests, avoid duplicate infrastructure

Real exchange parsers exist, but a bounded WS queue evicts its oldest event on
overflow: [queue path](https://github.com/Aryan-20-04/mdrap/blob/b614bf86b54c2933ddf5c971e0edbcb0c0c316a2/src/ws_feed.py#L676).
The synchronous recovery callback discards returned recovered packets while state
advances: [recovery path](https://github.com/Aryan-20-04/mdrap/blob/b614bf86b54c2933ddf5c971e0edbcb0c0c316a2/src/recovery.py#L249).
These are static observations; upstream tests were read, not run. Do not transplant
that recovery engine. Generic sequence handling also does not substitute for each
venue's update-ID rules. Distinct venues' valid prices must not be merged into one
execution truth merely because one source has a higher reliability score.

Our existing PriceStream already invalidates books on disconnect/bad data, and
StateStore already commits state/events atomically and rejects changed duplicate
payloads. Incremental value is conservation testing, arrival-time replay, data-quality
reasons and an injected clock. Accepted events must be persisted or explicitly
rejected/quarantined; a recovered event cannot count as delivered when discarded.
Never sort away arrival-order failures when simulating live behavior.

An [audit test](https://github.com/Aryan-20-04/mdrap/blob/b614bf86b54c2933ddf5c971e0edbcb0c0c316a2/tests/test_phase1_card5_audit_tamper.py#L12)
demonstrates why a self-consistent hash chain needs an independently retained anchor
to detect tail truncation. Consider this only if our existing manifests are insufficient.
Its nanosecond figures concern synthetic in-process stages, not exchange-to-durable
storage latency. C/shared-memory/FPGA optimizations do not address our current need.
MIT, optional extras beyond the base package; no new dependency recommended.

## FenixAI: adapt order safety, defer learning-memory integration

The wired executor reconciles ambiguous submissions using the same client order ID:
[submission](https://github.com/Ganador1/FenixAI_tradingBot/blob/bd7373d59bee48addea51989796df27f69193a34/src/trading/executor.py#L740).
It verifies protection and attempts reduce-only emergency closing when protection
cannot be confirmed: [protection](https://github.com/Ganador1/FenixAI_tradingBot/blob/bd7373d59bee48addea51989796df27f69193a34/src/trading/executor.py#L827).
Adapt these with a durable intent ledger spanning restarts; a close request is not
proof of a closed position. Unknown state must block opening exposure, with alerts
and reconciliation. Its verified snapshot API distinguishes failed queries from
flat state; do not use legacy empty-on-error behavior.

The deterministic risk manager is wired before entries, but availability is optional
after import failure: [import](https://github.com/Ganador1/FenixAI_tradingBot/blob/bd7373d59bee48addea51989796df27f69193a34/src/trading/engine.py#L76).
Our governor must be mandatory and distinguish risk reduction from opening shorts.
Do not build a second spot risk engine; extend the existing one for futures budgets.
[Fault tests](https://github.com/Ganador1/FenixAI_tradingBot/blob/bd7373d59bee48addea51989796df27f69193a34/tests/test_fault_injection.py#L40)
cover one submission plus reconciliation. The protection test mocks the close helper,
so it does not prove exchange-side closure. Fees alone are not complete funding,
margin, liquidation or fee-asset accounting.

Its [memory retrieval](https://github.com/Ganador1/FenixAI_tradingBot/blob/bd7373d59bee48addea51989796df27f69193a34/src/memory/reasoning_bank.py#L385)
has no historical as-of cutoff and favors successful outcomes; historical replay
would need outcome-availability timestamps, immutable fold snapshots and a controlled
clock. This is leakage risk, not proof that a published result leaked. An advertised
advanced regime module is a [disabled legacy shim](https://github.com/Ganador1/FenixAI_tradingBot/blob/bd7373d59bee48addea51989796df27f69193a34/src/system/advanced_market_regime_detector.py#L1),
not a working detector to adopt. Keep our causal classifier and frozen mode rules.

Useful UI concept: decision → filter/risk verdict → order → fill → reconciliation,
backed by durable event IDs rather than only a transient screen feed. Paper-run
isolation of state, memory and logs is also useful; add our provenance/clock controls.
Apache-2.0 public code, with a substantial Torch/Transformers/LangGraph/database
stack and local/cloud model options. Local inference does not mean zero operating
complexity. No AI/model dependency is recommended in the baseline.

## Other survey leads and exclusions

[CryptoHFTData](https://www.cryptohftdata.com/) advertises order books, trades,
funding, marks and OI. Published history begins in 2025, varying by venue, so it
does not fill our permitted pre-2025 development-data needs. No dataset was fetched;
coverage, quality and future pricing remain to be audited if separately authorized.
Older Discord futures bots and the Kenny1941 ML bot were only preliminary leads,
not deeply audited recommendations. Freqtrade was a framework mention, not an
approved dependency; existing no-GPL/AGPL policy remains binding. No additional
platform, API account, paid service or external runtime was added through this work.

## Bounded implementation sequence and completion criteria

### Follow-up: validation and portfolio admission (2026-10-07)

The owner requested that the following two assessments join this planning reference.
They add reporting and risk-design requirements, not new strategy parameters or
changes to the frozen experiment.

The [ML pipeline post-mortem](https://www.reddit.com/r/algotradingcrypto/comments/1wzhi3g/research_i_spent_6_months_building_an_ml_pipeline/)
is useful as a warning about aggregate metrics and directional bias. Its title calls
the 71% loss a production result, while the body attributes it to a holdout test;
without supporting records it is not a verified live loss. No reproducible code or
complete experiment record was supplied in the inspected post. Do not adopt its
unsupported universal train/test Sharpe-gap thresholds as acceptance criteria.

Expanding-window training is not inherently invalid or leaky; rolling-window
training is not automatically stricter. Choose the training/retraining policy before
outcomes and match deployment information availability. If comparing policies, count
them as registered trials. [TimeSeriesSplit documentation](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
describes chronological splitting with expanding training sets and optional gaps.
Fit preprocessing and feature selection within each training fold, as explained in
the [leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html).

For future ML, enforce outcome-availability timestamps: a 12-hour return label may
enter training only when that outcome is complete and available at the fit cutoff.
Purge training labels overlapping the evaluation boundary; derive the separation
from actual label intervals and data delays rather than a universal bar count.
Use common chronological cutoffs across assets, and retain trial/model/data identity.
Neither a small Sharpe gap nor a high hit rate establishes profitability.

Proposed reporting addition: for each predefined chronological period and regime,
show net return, drawdown, trade count, turnover/costs, time invested, long/short
exposure and each side's P&L contribution. Compare cash, buy-and-hold, the relevant
frozen baseline and exposure-aware controls on identical periods. Mark small samples
and uncertainty. Diagnostic hindsight regime labels must never become decision-time
features. Display aggregate and period results together so a favorable interval
cannot conceal persistent losses or an effectively always-long strategy.

The [portfolio-risk discussion](https://www.reddit.com/r/algotradingcrypto/comments/1wzqx2q/how_do_you_manage_portfoliolevel_risk_when/)
raises correlated altcoin signals, BTC sensitivity and the risk of overfitting an
overlay. No answers were visible when inspected; it is a research question, not a
validated solution. Our proposed response is a portfolio admission check extending
the roadmap's shared spot/futures supervisor.

Before admitting an order, evaluate the portfolio after worst-case pending fills:

1. Combined spot/futures gross and net exposure using consistent equity denominators.
2. Same-asset and correlated-group concentration, including correlated long positions
   that appear diversified only because their symbols differ.
3. Incremental portfolio loss under predefined price, spread, funding and liquidity
   stresses; stops are not guaranteed execution prices during gaps.
4. Remaining collateral, maintenance requirements and liquidation buffers. Low net
   exposure does not remove gross, basis, funding or venue risk.
5. Freshness and reconciliation of account, order and market state. Unknown state
   blocks new exposure; risk-reducing actions retain their explicit safe workflow.

Reserve risk capacity atomically when accepting intents so concurrent signals cannot
each consume the same remaining budget. Release or reconcile reservations on fills,
cancellation and restart; include partial fills. A reported flat state must be verified.

Start with transparent fixed caps and predefined stress scenarios. Introduce BTC-beta
or covariance-based allocation only under a bounded comparison against that simple
baseline. Estimate using information available then, define insufficient-history and
stale-estimate fallbacks, and stress correlations rising together. An uncertain low
correlation estimate must not automatically justify extra leverage. Predeclare numeric
limits and scenario severity rather than tuning them to selected historical crashes.

Acceptance fixtures should cover correlated entries across symbols, spot plus a
same-asset futures long, offsetting positions with large gross exposure, concurrent
pending intents, partial fills, stale accounts, funding shocks and gap-through-stop
events. Reports must reconcile to the ledger. Evaluate risk reduction together with
net return, rejected opportunities and utilization, avoiding a trivial always-flat
overlay. These requirements belong in the future multi-asset/futures design and
research reporting; they do not assert that today's single-asset engine implements
them or authorize a new ML subsystem, data access, live trading or wider loss limits.

### Delivery order

This supplements Addendum B's strategy sequence. Infrastructure does not need to
wait for an alpha result when it directly supports the experiment; optional UI
must not delay the frozen v2 build. Tasks below remain proposals for assignment.

| Order | Deliverable | Acceptance evidence |
| --- | --- | --- |
| 1 | Audit existing exports and define a read-only run bundle | Code/config/data identity, exact decimals, zero-trade/open-position handling; no invented fields |
| 2 | Local results viewer using that bundle | Equity/drawdown and tables reconcile exactly; regime/trade annotations where recorded; clear missing-data labels; no remote runtime/assets required by default |
| 3 | Fill specific replay/failure-test gaps | Repeat/run-order invariance; restart and duplicate handling; explicit queue-loss detection; accepted-event conservation; stale data cannot open risk |
| 4 | Simulated durable order-intent/reconciliation state machine | Timeout after acceptance plus restart cannot duplicate an order; partial fills/cancel races reconcile; unknown is distinct from flat |
| 5 | Futures ledger and protection fixtures | Signed funding/fees/P&L reconcile; venue margin/mark/liquidation rules; reduce-only and unconfirmed-protection states; combined spot/futures exposure enforced |
| 6 | Registered signal diagnostics and strategy trials | Frozen null/trial budget/costs; no future data or memory; independent long/short attribution; existing risk gates retained |

Tasks 1–3 can be isolated from strategy changes. Tasks 4–5 initially use synthetic
exchange fixtures, not live credentials. Task 6 follows the frozen experiment and
reviewed next research specification; session timing does not silently enter v2.
The engineering writer owns implementation; a different reviewer verifies the
exact resulting commit. No owner or reviewer is assigned by implication to Claude.

Rough scoping only: bundle 3–5 developer-days; viewer 5–10; targeted failure tests
1–3; durable reconciliation 3–5 plus integration review. These estimates overlap,
exclude discovered gaps and are not delivery promises. Futures accounting needs
venue/data scoping before a credible estimate. Stop optional work if it duplicates
existing behavior or cannot improve a concrete research/operational decision.

Success is measured in correct accounting, reproducible research, fewer unexplained
failures and net risk-adjusted performance—not feature count or a world-best claim.
No platform adoption, performance result, live readiness or profit guarantee follows
from this document. Retain upstream notices if any source is later reused; verify
that exact dependency set and license before integration.
