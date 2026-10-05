# High-Performance Crypto Strategy Roadmap

## V2 Expansion and V3 Futures Long/Short Architecture

Status: planning proposal, 2026-10-05. Named writer: Codex Desktop.
Branch: `codex/high-performance-crypto-strategy-roadmap`.
Repository baseline: `c4cfb87c3560131c5b14d0165f6b026c215f9a2d`.

This document preserves the strategy roadmap from the owner's “PR 159/160
Clearance” conversation and adds implementation and evaluation details in §22–§26.
The conversation retrieval provided the roadmap through Stage 11; its remaining
ending was truncated. The concluding stages and added details below are an editorial
completion based on the requested scope, not a verbatim transcript.

All parameter ranges below are candidate research settings, not approved production
defaults or evidence of profitability. Statements about the “current” strategy in
the preserved brief describe its discussion-time baseline and must be reconciled
with the pinned implementation before preregistration.

### Relationship to existing policy

[START_HERE.md](START_HERE.md), [EXPERIMENT_SPEC_V1.md](EXPERIMENT_SPEC_V1.md)
and the existing [delivery roadmap](../ROADMAP.md) remain authoritative for the
current experiment. C1's acceptance ceiling is **10% maximum drawdown on both
total and active equity**, and any hard-drawdown halt fails it. The **12% runtime
hard stop is a separate emergency control**, not a replacement acceptance bar.
All C1–C6 criteria remain binding; R1 economics is reported, not gated.

This roadmap neither changes those criteria nor authorizes reserved-window access,
new market-data downloads, live orders, exchange credentials, or deployment.
Future strategy families need their own reviewed preregistration and explicit
policy decisions where they differ from existing constraints. The project remains
paper-only. A successful historical result does not itself authorize a live pilot.

Source: [original strategy discussion](https://chatgpt.com/c/6ac28eee-c644-83ed-bfe9-3b8e5999c3a1)
(access depends on account permissions).

### Purpose

The project should no longer be framed as merely building a conservative grid bot that survives crypto volatility.

The objective should be:

> **Maximize compounded return from crypto market volatility while operating inside a clearly defined portfolio drawdown and ruin-risk budget.**

Crypto offers a fundamentally different opportunity set from traditional equities. Large directional moves, rapid volatility expansion, strong momentum persistence, cross-asset dispersion and repeated range/trend regime changes create opportunities that a defensive spot-only grid cannot fully exploit.

A strategy producing roughly 5% annually would not justify the complexity, operational burden and crypto-specific risk of this system. The system should instead be designed to capture substantial upside during favorable conditions while protecting capital during hostile regimes.

This does **not** mean forcing a fixed return such as 20% every calendar month. It means designing the system so that **10–20%+ months are possible when crypto conditions genuinely provide that opportunity**, while avoiding the catastrophic losses that usually destroy aggressive crypto strategies.

---

# 1. Strategic Architecture

The bot should become a **multi-regime trading engine**, not a single strategy forced to operate under every market condition.

The intended long-term architecture is:

| Market state | Primary behavior |
|---|---|
| Strong RANGE | High-turnover adaptive spot grid |
| Weak RANGE | Wider / lower-exposure grid |
| Strong BULL | Directional long exposure |
| Strong BEAR | Directional short exposure |
| TRANSITION | Reduced exposure or flat |
| STRESS | Flatten leveraged exposure and protect capital |

The existing regime classifier, structure engine, opportunity scorer, risk system and data integrity framework provide much of the foundation.

The next development stage should concentrate on turning those components into **capital-allocation decisions**, rather than merely using them as reasons not to trade.

---

# 2. Development Principle: Productive Risk, Not Blind Risk

We should distinguish between two types of additional risk.

**Productive risk** increases exposure when expected edge is stronger.

Examples include allocating more capital when regime, liquidity, momentum and structure all agree; selecting the strongest asset from the universe; tightening grids in genuine ranges; or using moderate futures exposure during strongly directional conditions.

**Unproductive risk** simply permits larger losses.

Examples include immediately increasing the hard-drawdown threshold from 12% to 20%, deploying 100% of capital regardless of signal quality, adding high leverage without evidence, or averaging into losing leveraged positions.

The project should aggressively investigate the first category before changing the second.

---

# 3. Phase 0 — Finish the Current Foundation

Before introducing new strategic behavior, complete the current corrective sequence.

The discussion identified PR #165 as the foundation dependency. GitHub now records
[#165](https://github.com/mgalic01/adaptive-market-engine/pull/165) as merged on
2026-10-05 at `396041f70f9428608723d9b558287cd7327e54f8`.
Do not reopen that historical instruction as new work. Before strategy experiments,
verify its resulting baseline and evidence: E's wall-clock timing, F fragment
protection, H3's new-grid-only behavior, required diagnostics and funding-manifest
verification. Merge status alone does not establish experimental readiness.

After integration, the clean baseline should contain:

| Component | Status required |
|---|---|
| True V0 | Reproducible and unchanged when optional mechanisms are disabled |
| V2 structure | No lookahead, frozen/preregistered |
| A/B/C | Working |
| E/F/G/H | Correct and measurable |
| P8 funding/daily data | Verified and usable |
| Risk engine | Current D1–D21 owner decisions |
| Provenance | Exact commit/config/data identity |
| CI | Green |

Only after this should the next strategy family be evaluated.

---

# 4. Variant I — Regime-Adaptive Grid

This should be the first major profitability experiment.

The current grid geometry is relatively static:

- 6–8 levels;
- 2.0 ATR range multiplier;
- minimum spacing of 3× expected round-trip cost;
- 80% grid capital budget.

That configuration is unlikely to be optimal across all volatility regimes.

The new hypothesis is:

> **A high-quality sideways market should trade a tighter grid and recycle capital frequently, while increasingly directional or unstable markets should use wider spacing or stop opening grids.**

A first registered parameter family could be:

| Condition | Indicative behavior |
|---|---|
| Exceptional RANGE | tight grid, approximately 1.0–1.25 ATR |
| Normal RANGE | approximately current 2.0 ATR |
| Weak / unstable RANGE | 2.5–3.0 ATR or lower exposure |
| BULL/BEAR | no ordinary range grid |
| STRESS | no new exposure |

These values should be preregistered before results are observed and treated as research parameters rather than presumed optimal values.

The minimum fee/cost spacing rule remains mandatory.

The primary objective is to increase:

**completed profitable cycles per unit of capital and per unit of drawdown.**

Important measurements include cycles/day, grid P&L, forced-exit P&L, turnover, time deployed, maximum drawdown and net return.

---

# 5. Variant J — Confidence-Weighted Capital Deployment

The fixed 80% grid budget should eventually be challenged.

The current system can allocate roughly the same percentage of capital to a barely acceptable setup and an exceptional one.

Instead, exposure should become a function of expected opportunity quality.

A first research mapping could resemble:

| Opportunity quality | Capital utilization |
|---|---:|
| Marginal qualified setup | 50–60% |
| Normal qualified setup | 70–80% |
| Very strong setup | 85–90% |
| Exceptional multi-signal alignment | up to 95% |
| Invalid / uncertain | 0% |

Inputs can include:

- opportunity score;
- regime confidence;
- structure alignment;
- liquidity quality;
- spread;
- volatility;
- depth;
- relative strength.

No leverage is required for this experiment.

The purpose is to determine whether selective aggression improves return materially without causing disproportionate forced exits.

---

# 6. Variant K — Cross-Asset Opportunity Rotation

This may ultimately produce a larger improvement than adjusting the grid itself.

The repository currently contains universe and rotation configuration, but those settings are intentionally inert. The engine still effectively trades one pair.

That means the system may be spending considerable effort optimizing a mediocre ADA, BTC or XRP opportunity while a substantially better setup exists elsewhere.

The future engine should evaluate a qualified crypto universe and assign its active risk budget to the strongest opportunity.

Conceptually:

**Candidate ranking = expected grid/trend edge × regime quality × liquidity × structure × execution quality**

Only one active grid could remain initially, keeping portfolio-level risk comparable with today's system.

Rotation should require meaningful superiority to prevent churn. For example, the challenger may need to remain 15–20% better for several confirmations before capital moves.

A cooldown should prevent rapid switching.

The rotation experiment should explicitly measure:

- return improvement over fixed-pair execution;
- turnover cost;
- false rotations;
- time spent in the highest-ranked asset;
- post-rotation performance;
- maximum drawdown.

---

# 7. Variant L — Hybrid Spot Trend + Grid

Research extension: [Addendum A — Trend exits and recovery participation](#addendum-a--trend-exits-and-recovery-participation) defines a bounded comparison within L, to be registered when this development stage is reached.

This is the most important conceptual shift.

The system should stop assuming that a grid is always the correct profit engine.

In a strong bull trend, repeatedly selling inventory for small grid gains may substantially underperform the underlying move.

Therefore:

| Regime | Engine |
|---|---|
| RANGE | Adaptive V2 grid |
| BULL | Directional spot trend position |
| TRANSITION | Reduced exposure / wait |
| BEAR | Cash initially |
| STRESS | Flat |

The directional spot component should use existing trend, momentum, structure and regime information.

A BULL allocation might initially use 30–60% of capital and employ a trailing exit rather than fixed grid targets.

This strategy should be compared against:

- V2 grid;
- buy-and-hold;
- Variant D trend benchmark;
- cash.

A key metric should be **bull-market upside capture**.

If the underlying asset rises 80% while our bot earns only 10–15%, that should be considered a strategic weakness even if the bot made money.

---

# 8. Variant M — Aggressive Composite Spot Strategy

Once I, J, K and L have been tested independently, their useful components can be combined.

Variant M would potentially consist of:

**adaptive spacing + dynamic capital utilization + asset rotation + directional spot BULL mode**

The combined system should not be evaluated until the individual components have been measured, because otherwise it becomes impossible to identify which mechanism creates improvement or damage.

Variant M becomes the final spot-only candidate before futures are introduced.

---

# 9. V3 — Futures Long/Short Engine

Futures should be implemented as a separate strategy family rather than as a small V2 extension.

The objective is to allow the system to profit directly from both major bullish and bearish crypto trends.

Initial V3 behavior:

| Regime | Futures behavior |
|---|---|
| Strong BULL | Long |
| Strong BEAR | Short |
| RANGE | No directional futures position; grid owns the opportunity |
| TRANSITION | Flat or minimal exposure |
| STRESS | Flatten immediately |

Futures and spot exposure must share a single portfolio risk layer.

---

# 10. Futures Signals

The futures engine should not use regime direction alone.

It should combine multiple independent dimensions.

### Existing signals

The current system already provides useful information from:

- trend;
- momentum;
- breadth;
- ADX;
- liquidity;
- volatility;
- multi-timeframe structure;
- support/resistance;
- opportunity scoring.

### Additional crypto-specific features

The V3 research set should investigate:

**BTC master regime.**

Altcoins behave differently depending on BTC's direction and volatility.

**Cross-asset relative strength.**

Long the strongest qualified asset rather than an arbitrary coin; short structurally weak assets.

**Funding rate.**

Unlike spot Variant G, funding becomes both a signal and an actual cash-flow component.

**Open interest.**

Price moves accompanied by rising OI can represent new positioning; falling OI can signal liquidation/position closure.

**Price/OI/funding divergence.**

Examples:

- rising price + rising OI + extreme positive funding;
- rising price + falling OI;
- falling price + rising OI;
- falling price + collapsing OI.

These situations should not be treated identically.

**Realized volatility / ATR regime.**

Position size should fall as volatility increases.

**Perpetual basis.**

Useful for detecting crowded directional positioning.

Liquidation information can be investigated later, but should not be required for the first implementation.

---

# 11. Long/Short Asymmetry

Shorting should not simply invert the long strategy.

Crypto crashes frequently occur faster than rallies, while bull trends can continue for much longer.

Therefore the engines should be independently parameterized.

A long strategy may use:

- slower trailing exits;
- pyramiding only after favorable movement;
- longer holding periods.

A short strategy may require:

- faster confirmation;
- tighter invalidation;
- faster profit realization;
- stronger volatility controls;
- stricter leverage constraints.

No short averaging-down mechanism should be allowed.

---

# 12. Futures Position Sizing and Leverage

Initial futures research should deliberately avoid extreme leverage.

The first registered leverage scenarios should be:

**1.0×, 1.5× and 2.0× effective exposure.**

Only after those results are understood should 3× be considered.

5×, 10× or higher should not be part of the first experiment.

Position size should be volatility-adjusted.

A conceptual sizing rule is:

**position exposure ∝ risk budget / expected volatility**

Therefore a highly volatile asset automatically receives less notional exposure than a quiet one.

Leverage should be an output of the risk model, not a number chosen because the exchange allows it.

---

# 13. Liquidation Safety

The strategy must never depend on exchange liquidation as a risk-control mechanism.

For every futures position the engine should calculate:

- entry;
- maintenance margin;
- estimated liquidation price;
- strategy invalidation/stop;
- distance from stop to liquidation.

The internal exit must occur substantially before liquidation becomes possible.

If the liquidation buffer is insufficient, the position is not allowed.

This requirement should be enforced at order creation.

---

# 14. Portfolio-Level Exposure

Spot and futures positions cannot be risk-managed independently.

For example:

80% spot ADA + 2× ADA futures long

can represent vastly more directional exposure than intended.

The portfolio engine should therefore track:

**gross exposure**

and

**net directional exposure.**

An illustrative future limit could be:

| State | Maximum effective directional exposure |
|---|---:|
| RANGE | ~0.8–1.0× |
| Strong BULL | ~1.0–1.5× initially |
| Exceptional BULL experiment | ≤2× |
| BEAR short | similar risk budget, independently tested |
| TRANSITION | low |
| STRESS | 0 |

Exact limits should be preregistered before testing.

---

# 15. Risk Controls for V3

Futures require a second layer of controls beyond the existing risk engine.

The initial rules should include:

**No martingale.**

Never increase leverage simply because a position moved against us.

**No uncontrolled averaging down.**

Additional entries require improved evidence, not a lower price alone.

**Position-risk budget.**

Each position may lose only a defined percentage of account equity before strategy exit.

**Portfolio-drawdown circuit breaker.**

Existing daily, soft and hard account limits remain.

**Funding-cost ceiling.**

A position may be reduced or refused when expected funding materially erodes expected edge.

**Volatility shock breaker.**

Extreme short-term volatility reduces leverage or closes directional exposure.

**Exchange/API/data failure.**

Leveraged positions fail toward reduced exposure, not continued trading.

---

# 16. Profit Vault Reconsideration

The current 50% profit-vault reserve is intentionally conservative.

Once positive expectancy is demonstrated, this should become another registered experiment.

Potential scenarios:

| Reserve fraction | Interpretation |
|---|---|
| 50% | Current conservative mode |
| 40% | Moderate compounding |
| 30–35% | Aggressive compounding |

A dynamic version could eventually secure more profit during drawdowns and compound more aggressively during strong equity growth.

This should be tested only after the underlying strategy demonstrates sustainable profitability.

---

# 17. Risk Limits Should Be Tested Last

The current approximate limits are:

- 3% daily pause;
- 8% soft drawdown;
- 12% hard drawdown.

We should not raise them merely because desired return is higher.

After the more intelligent mechanisms above are tested, analyze every hard-stop event.

If a meaningful percentage of stops occur shortly before profitable recovery, then a registered sensitivity can compare:

**12% / 15% / 18% hard drawdown**

and possibly modified soft limits.

The analysis must measure how much additional return is obtained for each additional unit of maximum drawdown.

A change is justified only if the return increase clearly compensates for the extra capital risk.

---

# 18. Evaluation Framework

Annual return alone is insufficient.

Every strategy should report at least:

| Metric | Purpose |
|---|---|
| CAGR | Long-term compounded performance |
| Monthly return distribution | Shows high-return and poor-return months |
| Maximum drawdown | Capital risk |
| Return / max drawdown | Efficiency of risk-taking |
| Recovery time | How long capital remains impaired |
| Upside capture | How much of bull markets the bot captures |
| Downside capture | How much of bear declines the bot experiences |
| Profitable-month percentage | Consistency |
| Time deployed | Detects excessive cash inactivity |
| Capital utilization | How aggressively capital is used |
| Completed cycles | Grid productivity |
| Grid P&L | Core grid edge |
| Forced-exit P&L | Main historical loss source |
| Trend P&L | Directional engine performance |
| Long P&L / short P&L | Futures attribution |
| Funding P&L | Actual derivatives carrying cost |
| Turnover | Execution burden |
| Fees/slippage | Execution cost |
| Liquidation-distance minimum | Futures safety |

---

# 19. Performance Objective

The bot should not have an artificial monthly return requirement.

Instead, the desired behavior is:

**Quiet/bad market:** preserve capital.

**Normal favorable market:** compound steadily.

**Strong crypto bull/bear regime:** exploit the opportunity aggressively enough that 10–20%+ months are possible.

The long-term design target should be materially above passive conventional-market returns.

A useful strategic benchmark is:

- below ~10% annualized: likely not worth the complexity;
- ~15–25%: potentially useful but not compelling for this project;
- ~30–50% CAGR: genuinely interesting;
- >50% annualized with controlled drawdowns: highly successful;
- exceptional crypto-cycle years may be substantially higher.

These are research objectives, not promises.

---

# 20. Research Discipline

This remains essential.

We should define the hypotheses **before seeing the new clean results**.

Otherwise every improvement risks becoming retrospective curve-fitting.

Therefore the proposed future trial registry should include:

**I — Adaptive grid spacing**

**J — Confidence-weighted exposure**

**K — Cross-asset rotation**

**L — Hybrid spot trend/grid**

**M — Composite aggressive spot strategy**

**V3-LONG/SHORT — futures directional engine**

The first parameter sets and acceptance rules should be written down before their corresponding backtests.

Changing them after results are observed creates a new registered trial rather than silently replacing the previous one.

---

# 21. Recommended Development Sequence

The development order should be:

**Stage 1 — Complete current work**

Verify the merged #165 foundation against current main, establish a clean E/F/G/H baseline, and run only the already-authorized clean variant comparison. Register future hypotheses before inspecting new outcomes that could influence their design.

**Stage 2 — Register future hypotheses**

Before examining those results in a way that would influence these ideas, write the I–M/V3 research registration and initial parameter families.

**Stage 3 — Build adaptive grid**

Implement Variant I first.

**Stage 4 — Dynamic exposure**

Implement J on top of the proven grid foundation.

**Stage 5 — Universe and rotation**

Activate the currently inert universe/rotation architecture as K.

**Stage 6 — Directional spot engine**

Implement L and compare its BULL performance against the grid and buy-and-hold.

**Stage 7 — Composite spot engine**

Build M only after I/J/K/L results can be attributed independently.

**Stage 8 — Futures data layer**

Add perpetual futures market data, mark/index price, funding, OI and required integrity checks.

**Stage 9 — V3 long/short engine**

Implement direction, sizing, leverage, stops, funding accounting and liquidation protection.

**Stage 10 — Futures leverage experiment**

Run 1× / 1.5× / 2× first.

**Stage 11 — Integrated portfolio engine**

Allow spot grid, spot trend and futures strategies to share one capital/risk allocator.

**Stage 12 — Compounding and risk sensitivities (planning completion)**

Only after useful strategy edge is established, compare profit-vault settings and
then hard-stop sensitivities in separate registered experiments. Preserve current
acceptance policy until the owner explicitly adopts any replacement.

**Stage 13 — Paper validation and deployment decision (planning completion)**

Validate replay-to-paper consistency, operational failure handling and portfolio
risk enforcement. Produce a go/no-go report. Any live-capital pilot remains a
separate owner decision under the existing delivery roadmap.

## 22. Implementation contracts for V2 research

### Shared decision flow

Use an explicit flow: point-in-time market snapshot → feature validity → regime
and confidence → candidate ranking → engine selection → capital request →
portfolio risk approval → simulated order execution → accounting and diagnostics.
Risk approval is authoritative and can reduce or refuse any strategy request.
All decisions record their timestamp, source snapshot and rejection reason.

Define confidence thresholds, confirmation counts, stale-data rules, minimum dwell
times and transition exits before runs. A regime switch must cancel obsolete entry
orders, reconcile fills and inventory, and resolve the previous engine's exposure
before admitting replacement exposure. Count pending orders and partial fills
against budgets. Never let grid and trend independently spend the same cash.

### I: adaptive geometry

Specify whether the ATR multiplier sets full grid width or half-width, how width
maps to level count, and when recentering is allowed. Preserve the original candidate
ranges in §4; they are width hypotheses, not a claim that each adjacent interval is
one ATR. After tick rounding, enforce the minimum adjacent spacing against expected
round-trip fees, spread and slippage. If geometry cannot meet the cost floor,
reject the setup rather than silently tightening below it.

Initially apply new geometry to newly opened grids; register any in-flight
reconfiguration separately. Attribute apparent gains to completed net-profitable
cycles, inventory mark-to-market and forced exits, not gross fill count alone.

### J: capital allocation

Define utilization as allocated active trading capital divided by eligible active
equity, excluding protected vault funds. Also report utilization against total
equity so changing the denominator cannot create apparent improvement. Reserve
cash for fees, pending orders and operational buffers; “95%” is a proposal ceiling,
never an instruction to exhaust available balances.

Calibrate confidence only on training data. Correlated inputs such as momentum,
trend and relative strength do not constitute three independent confirmations.
Compare J alone against the fixed-budget baseline before combining it with I.

### K: asset rotation

Construct the tradable universe using only listings, liquidity and information
available at each historical decision time. Include delistings and unavailable
periods; never select today's survivors retrospectively. Align candidate timestamps
and score normalization, and exclude stale or invalid assets.

The 15–20% superiority hypothesis requires a defined positive score scale;
otherwise use a preregistered absolute improvement threshold. Require superiority
net of exit, entry and slippage costs, multiple confirmations and a cooldown.
Start with one active grid. Define whether normal completion or immediate
liquidation transfers capital; charge all stranded-inventory and exit costs.
A failed candidate entry must not leave an untracked old position or duplicate
budget reservation.

### L and M: engine ownership and attribution

L needs an explicit trend entry, invalidation, trailing exit, timeout and regime
transition policy. Begin with the 30–60% spot allocation hypothesis. Range grids
and directional spot positions use separate attribution but one inventory ledger.

Test I, J, K and L as independent additions to a frozen common baseline. Then test
selected combinations and M with component-removal ablations. “J on top of the
grid foundation” in the development sequence does not mean its only comparison
is an already-improved I configuration. Report interaction effects and negative
results. Retain the simplest configuration if added complexity has no robust gain.

## 23. V3 data, execution and liquidation contracts

### Point-in-time data

Require trade prices, mark prices, index prices, contract specifications,
maintenance-margin tiers, funding settlements and instrument metadata for any
leveraged simulation. OI is an optional registered signal until coverage is
demonstrated; missing OI must not silently become zero. Record units (contracts,
base units or quote notional), publication delays, revisions, gaps and venue.

Funding has two distinct roles: a lagged feature available at decision time and
an actual signed cash flow at settlement. Do not use the realized future funding
rate as an earlier signal. Model the exchange's actual settlement schedule;
do not assume a universal eight-hour cadence. Basis and price/OI/funding patterns
are hypotheses, not deterministic interpretations or automatic entries.

### Sizing and leverage definitions

Let E be active account equity eligible for risk, r the preregistered fraction at
risk, and d the fractional stop distance including conservative execution costs.
For a simple linear contract, a first sizing upper bound is N_stop = E × r / d.
Combine it with a volatility-target cap, liquidity cap, margin cap, asset cap and
remaining portfolio cap; take the smallest permissible notional and round down.
Reject invalid or zero distances. Contract-specific sizing is required for inverse
or nonlinear contracts.

“1× / 1.5× / 2×” means futures notional divided by active equity for the registered
isolated experiment, not the exchange's margin leverage setting. In an integrated
portfolio, the tighter combined exposure limit always wins. Report gross futures,
combined gross and combined net exposure separately. The 3× scenario requires a
new research decision; it is not unlocked automatically by a profitable backtest.

Choose contract and margin mode explicitly before testing. Model isolated and
cross-margin behavior separately if both are studied. A protected vault is not
available collateral. Volatility expansion must reduce permitted exposure even
when an exchange would allow additional leverage.

### Liquidation buffer and realistic exits

Use the venue's mark-price trigger, maintenance tiers, fees, funding and collateral
rules to estimate liquidation. For a long require a stop above liquidation by a
positive safety buffer; for a short require a stop below liquidation by a positive
buffer. Define that buffer in volatility and price-gap terms before testing.
Recheck after fills, size changes, funding settlement, equity changes and margin
tier changes, not only at initial entry.

A stop order cannot guarantee its fill price through gaps, outages or insufficient
liquidity. Stress the path between stop trigger and execution; reject positions
whose modeled stressed exit approaches liquidation. Liquidation remains a
recorded failure even if terminal simulated equity is positive. The absence of
liquidation in historical tests is not proof of zero ruin risk.

### Order and failure state

Test reduce-only exits, duplicate event handling, partial fills, rejected orders,
cancel/replace races, restart reconciliation, stale prices and disconnects.
An exit must not accidentally open the opposite position. On impaired data, stop
new risk and retain protective exits. If the exchange is unavailable, record that
flattening is requested but unconfirmed; do not report a flat position until
execution and reconciliation confirm it. Paper simulation must model that delay.

## 24. Portfolio budget and risk hierarchy

Define gross exposure as the sum of absolute marked spot and futures notionals
divided by eligible equity. Define net exposure as signed notionals divided by
that same equity. Cash and vault balances are not directional positions.
Track per-asset and correlated-group exposure as well as the aggregate; a low
net number can hide large gross and basis risk.

For example, 0.8E of spot plus 2E of same-asset futures long is 2.8× combined
directional exposure when both use the same E denominator. It must be refused
if the portfolio cap is 1.5×, regardless of each engine's standalone request.

The hierarchy is: data integrity and operational availability; liquidation and
margin constraints; account circuit breakers; portfolio and correlated-group
caps; per-position risk; strategy allocation request. A lower layer cannot override
a refusal above it. Enforce caps against filled exposure plus worst-case pending
fills. Maintain independent long/short diagnostics and a portfolio-wide kill switch.

Before any experiment, record numerical position-risk, daily-loss, soft/hard
drawdown, funding-cost, volatility-shock, gross/net, correlation and liquidity
limits, along with recovery/re-enable rules and who can change them. Define
“ruin” operationally (for example an equity floor or forced liquidation), its
evaluation horizon and a tolerated modeled exceedance probability. Those values
remain open research decisions; this document does not invent approved limits.

Evaluate tail scenarios, clustered losses, correlated market crashes, spread
expansion, adverse funding and venue interruption together. Report uncertainty
in estimated ruin probability; finite samples cannot certify a zero probability.
Pyramiding uses favorable movement plus renewed signal/risk approval. No
martingale or adding to losing shorts; no increase justified merely by losses.

## 25. Evaluation and research record

### Required trial record

For every trial store hypothesis, variant ID, parent baseline, code SHA, immutable
configuration, data manifest and hashes, allowed dates, feature availability lags,
cost model, random seeds, split boundaries, all tried parameters, primary metric,
risk constraints and selection rule. Register changes as new trials and preserve
failed trials. Do not retune against a held-out result.

Use chronological development and walk-forward splits with suitable warm-up and
separation for overlapping observations. Fit transforms only on the training
portion. Respect the existing reserved-window restriction: neither this document
nor its publication authorizes access to 2025-01 or later market data.
Correct for the number of tried strategies when interpreting apparent improvement.
Block resampling can test path sensitivity but does not create independent unseen
market history. Require robustness across assets, regimes, cost assumptions and
nearby parameters rather than selecting one narrow optimum.

### Comparable measurements

- Compute CAGR from net equity over the actual elapsed time; do not extrapolate
  short exceptional windows into a claimed sustainable annual return.
- Report calendar monthly returns, median, tails, best/worst months and profitable
  month share, including months in cash. Show frequencies of 10% and 20% months
  without treating them as acceptance quotas.
- Measure peak-to-trough drawdown and recovery duration on both total and active
  equity. Record unrecovered drawdowns at the end of a run.
- Use the same dates and capital convention for cash, buy-and-hold, frozen V0,
  clean V2 and the D trend benchmark. D retains its existing benchmark-only status.
- Define upside/downside capture on fixed benchmark-positive/negative periods,
  and report undefined ratios when denominators are zero or unstable. A strategy
  can warrant lower upside capture if the preregistered risk tradeoff supports it.
- Separate realized grid cycles, inventory changes, forced exits, spot trend,
  futures long/short, funding, fees and slippage; reconcile their sum to equity.
  Avoid double counting mark-to-market and subsequent realized gains.
- Report cycle counts/rates, turnover, mean and peak utilization, cash time,
  gross/net exposures, minimum liquidation distance, margin violations, rejected
  allocations, signal validity and data exclusions.
- Include minimum order sizes, rounding, liquidity and operating costs for the
  project's approximately EUR 100 starting-capital context. R1 remains reporting
  only. Compare complexity and operating cost alongside returns.

### Promotion and rejection

A candidate advances only after correctness and data-integrity checks, the
preregistered risk gates, and net out-of-sample improvement over its stated
baseline are satisfied. Record uncertainty and regime dependence. No winner is
an acceptable result. Absolute return aspirations in §19 express owner preference,
not a validated forecast, replacement acceptance criteria or a reason to hide
risk failures. Any new V2/V3 acceptance policy must be explicitly reviewed and
approved before selection under that policy.

## 26. Concrete handoff for the next development session

| Step | Deliverable | Gate |
|---|---|---|
| Foundation reconciliation | Pinned baseline and E/F/G/H, P8, V0-equivalence evidence checklist | Existing corrections and diagnostics verified; no claim based on merge status alone |
| Preregistration | Separate I/J/K/L/M/V3 trial definitions and unresolved decision register | Hypotheses and selection rules fixed before relevant outcome inspection |
| I and J | Geometry and utilization experiments with isolated baselines | Net gains survive costs and current risk controls |
| K and L | Point-in-time universe, rotation state machine and trend engine | Switching costs and upside/downside attribution independently visible |
| M | Composite with component-removal comparisons | Interactions do not erase isolated gains or breach risk constraints |
| Futures foundation | Contract-aware accounting, mark/index/funding data and integrity tests | Reconciliation and liquidation/stress fixtures pass before strategy comparison |
| V3 | Separate long and short experiments at 1×, 1.5× and 2× | Portfolio supervisor exists from the first futures test |
| Integrated allocation | Grid, spot trend and futures share one budget | Combined and pending-order limits enforced in replay and paper simulation |
| Later sensitivities | Vault first, risk-limit sensitivity last | New registered trials and explicit policy decisions |
| Paper validation | Failure drills, parity evidence and go/no-go report | Existing delivery gates; live deployment separately authorized |

Implementation ownership is assigned at the start of each approved task. The
portfolio supervisor is a prerequisite for V3 even though fuller multi-engine
allocation is Stage 11; it must not be deferred until after leveraged tests.

Outstanding decisions are the venue/contract/margin model, precise risk and ruin
budgets, score calibration, turnover thresholds, feature availability standards,
trial count and statistical selection method, and any future change to acceptance
policy. Record them before execution rather than filling gaps after seeing results.

Publication scope: documentation only. No strategy code, configuration, acceptance
policy, market data or trading behavior is changed by this roadmap.

## Addendum A — Trend exits and recovery participation

Added 2026-10-05 at the owner's request. **Status: proposed research within Variant L.** Recording this proposal does not authorize implementation, experiments, reserved-data access, changed risk limits or live trading. It does not interrupt the development sequence in §21 and §26.

### Purpose and rationale

Test whether better exit and re-entry rules improve compounded return within the approved drawdown and ruin-risk budget. Avoiding a decline must be assessed alongside recovery missed, switching costs and time in cash. These transitions are already part of the planned hybrid spot strategy, so a bounded comparison belongs within L rather than a new strategy family.

The external [trend-switcher article](https://dimonb19a.hashnode.dev/holding-eth-through-the-2022-crash-lost-52-this-free-bot-ended-at-0-9) and [repository snapshot](https://github.com/dimonb19a/trend-switcher/tree/e59282d6232e541b944ab4a8930333379283ba2c) motivate questions, not performance expectations. Its separate-start windows, stochastic model judgments, unpublished raw ledgers and differences between replay and live halt recovery prevent treating its headline results as validation for our system. Its later continuous-path reconstruction is not a single continuous replay. We are not adopting its code, AI services, execution platform or parameter values through this proposal.

### A1. Verify protective-exit behavior

Before adding strategy logic, trace how existing controls distinguish opening or increasing exposure, cancelling entry orders, reducing exposure and handling uncertain execution or invalid market data.

A restriction on new exposure must not inadvertently block an otherwise valid protective exit. This is not permission to bypass execution safeguards: unresolved orders, stale prices and unknown fills may require reconciliation before another order is safe. Define each halt's permitted actions explicitly.

Deliver a documented state-transition check. If a defect is demonstrated, add targeted regression tests and handle the correction through its own reviewed change. Do not presume a defect or redesign the risk engine without evidence.

### A2. Register a bounded deterministic comparison

Use one frozen baseline, the same eligible data and starting capital, and identical cost and account-risk policies. The L0/L1/L2 labels below are local research labels within Variant L; they do not replace existing variant identifiers.

| Arm | Question | Controlled change |
| --- | --- | --- |
| L0 — Planned deterministic trend baseline | How well does the proposed trend engine exit and recover? | Frozen baseline entry, exit and re-entry rules |
| L1 — Confirmed exit | Does price confirmation reduce false exits enough to compensate for later crash protection? | Change the discretionary trend exit only; retain L0 re-entry |
| L2 — Recovery-aware re-entry | Does a separate recovery signal improve participation without excessive churn? | Retain L0 exit; change re-entry only |

Evaluate L1 and L2 independently against L0 before registering a combined arm. Emergency and mandatory account-risk exits remain unchanged: confirmation must never delay them.

Candidate mechanisms include a volatility-scaled break of recent structure and persistence across completed bars. A recovery signal may permit entry below the previous sale price; otherwise a prolonged recovery can remain inaccessible. The external rule that buys back only above the last sale can be a separately registered diagnostic comparator, not our default.

Freeze exact thresholds, confirmation periods, warm-up, signal timestamps, the primary objective, allowed tradeoffs and maximum trial count before examining outcomes. Do not import the external 0.9% threshold as an optimum. Repeated judgments on nearly identical inputs are not independent confirmation.

### A3. Require continuous, stateful evaluation

Evaluate permitted development periods continuously across declines, ranges and recoveries. Carry forward inventory, cash, protected profits, equity peaks, risk halts, outstanding orders and strategy state. Segment results by regime for diagnosis, but do not reset into the favorable starting position for each segment or combine separate-start returns as one portfolio.

Use only completed bars available at decision time, realistic execution delays and costs, and the same halt/re-enable policy planned for paper operation. If a replay approximates operator intervention, register and disclose that approximation rather than silently resetting halts. The existing restriction on reserved data remains binding.

### A4. Measure both protection and recovery

Report net compounded return, maximum drawdown on active and total equity, recovery duration, and unrecovered drawdowns. Include bull participation, losses during declines, time in cash after exits, delay to re-entry, switching frequency, fees, slippage and forced-exit losses.

Compare L0/L1/L2 with the relevant frozen grid baseline and buy-and-hold using consistent dates and capital conventions. Check nearby parameter values and higher execution costs under the registered trial budget. Use a fixed, preregistered definition of recovery for diagnostics; do not label turning points retrospectively as signals available to the strategy.

Existing acceptance criteria remain binding. New acceptance policy for a future strategy family requires a separate explicit decision; this addendum does not replace C1–C6 or relax account limits.

### A5. Promotion, rejection and scope

Advance a mechanism only after correctness checks and applicable risk gates pass, and the preregistered objective improves across multiple permitted periods without relying on one fortunate crash exit. Quantify uncertainty and missed upside; do not call an apparent gain robust solely because the aggregate return is higher.

Reject or defer a mechanism if realistic costs erase its advantage, recovery participation deteriorates beyond the registered tolerance, or added complexity brings no reliable benefit. Negative results are retained. An AI component, futures, leverage, cross-chain execution and wider loss limits are outside this comparison.

### A6. Next development handoff

1. Complete and verify the existing foundation before this experiment.
2. Assign a writer to the protective-exit state-transition check; record evidence and any actual gaps.
3. When Variant L is scheduled, incorporate L0–L2 into its reviewed preregistration, including numeric gates and the trial budget.
4. Implement and run only the authorized comparison, preserving continuous state and reproducible provenance.
5. Keep only mechanisms supported by the evidence; consider a combined arm afterward under a new registered trial.

**Recommendation:** retain this as a scoped addition to Variant L's plan. Its expected benefit is a clearer test of safe exits versus recovery participation, not a promise of higher returns or a reason to accelerate deployment.
