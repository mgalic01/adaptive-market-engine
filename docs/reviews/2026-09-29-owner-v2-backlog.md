# V2 backlog: owner-confirmed research items and open directions

Index: 2026-09-29: Consolidated list of v2 research questions, open directions, and
missing capabilities confirmed by the owner during the 2026-09-29 session with Bob
(owner's desktop session). Not a spec, not registered trials — these are hypotheses
to validate before any strategy or infrastructure change is made.

- **Recorded by:** Bob (owner's desktop IBM Bob session), 2026-09-29.
- **Status:** Living document. Add rows as new items are confirmed. Remove rows only
  when a measured backtest result or owner decision closes them.

---

## Strategy research items

### S1 — Regime-adaptive grid spacing
**Source:** Owner conversation, 2026-09-29. Detail: `docs/reviews/2026-09-29-owner-regime-adaptive-grid-spacing.md`

In a sideways (RANGE) market, tight grid spacing (~1–2%) harvests frequent small
oscillations. In a trending market (BULL/BEAR), wide spacing or a pause avoids the
grid being blown through by a directional move. Currently spacing is fixed at grid-open
time regardless of regime changes.

**Questions to answer:**
- What spacing targets are right for each regime (needs backtest measurement)?
- How fast should the grid rebuild on a regime change?
- Does adaptive spacing interact with drawdown recovery (amendment 1)?

**Owner decisions needed:**
- [ ] Schedule as formal Bob task or hold until v1 comparison is complete?
- [ ] Which regime-to-spacing mapping to test first?

---

### S2 — Market structure perception and FTA sell targets
**Source:** Owner conversation + Luka Hranjec Jeri's analysis, 2026-09-29.
Detail: PRs #147, #148, #150 (open, not yet merged).

The bot needs to independently detect market structure (swing highs/lows, support/
resistance zones, multi-timeframe trend alignment) and use the FTA (First Trouble Area)
as sell targets rather than fixed geometric spacing. PR #147 implements the perception
module; PR #148 wires FTA into GridBuilder; PR #150 adds structure_alignment to the
regime classifier. A backtest comparison task is in PR #149.

**Questions to answer (via PR #149 backtest):**
- Do FTA-aware sell targets improve fill rate and per-cycle return vs geometric targets?
- Does structure_alignment as a regime signal reduce false RANGE classifications?
- What is the right weight for structure_alignment vs the other regime signals?

**Owner decisions needed:**
- [ ] Approve PRs #147–#150 for merge once reviewed by Claude/Codex.

---

### S3 — Monte Carlo / out-of-sample validation
**Source:** Community best-practice advice relayed by owner, 2026-09-29.

Backtest results on development datasets are hypotheses, not proof. Before any capital
or strategy decision, results need:
1. **Monte Carlo simulation** — randomise entry timing and order within the backtest
   period; check that results hold across many path realisations, not just the single
   historical path.
2. **Out-of-sample (reserved window) test** — run on data the strategy was never
   optimised against. The reserved window (2025-01 onwards) is already set aside for
   this. Owner must give explicit go before any reserved-window data is opened.

**What needs building:**
- A Monte Carlo wrapper around the existing replay engine (randomise bar order within
  windows, re-run N times, report distribution of outcomes).
- A protocol for opening the reserved window: owner decision + documented rationale.

**Owner decisions needed:**
- [ ] When to open the reserved window for out-of-sample validation (after v1 is stable)?
- [ ] How many Monte Carlo runs are required before a strategy is considered validated?

---

### S4 — Counterfactual logging ("log the setups you skipped")
**Source:** Community best-practice advice relayed by owner, 2026-09-29.

Currently the bot logs what it trades. It does not log why it chose *not* to open a
grid on a given symbol or time — the regime was wrong, the opportunity score was too
low, the drawdown limit was hit, etc. Without this, it is impossible to know whether
skipped setups were actually good opportunities that were wrongly filtered.

**What needs building:**
- A "near-miss" log: for each evaluation that resulted in no action, record the symbol,
  the regime score, the opportunity score, and what threshold it failed.
- Track outcome of near-misses alongside actual trades to measure whether the filters
  are calibrated correctly.

**Owner decisions needed:**
- [ ] Where should counterfactual logs be stored (repo, separate file, database)?
- [ ] Retention policy (30/60 days as suggested, or full history)?

---

### S5 — Forward test period before any live capital
**Source:** Community best-practice advice relayed by owner, 2026-09-29.

Paper trading catches what backtesting misses (partial fills, slippage, connectivity).
The recommendation is 30+ days of uninterrupted paper trading across at least one
regime change before going live with any real capital.

**What needs building:**
- A sustained paper-trading deployment (not just backtest runs): the bot running against
  live market data, paper-only, for 30+ days with full logging.
- A pass/fail checklist: what metrics must hold for the forward test to count as passed?

**Owner decisions needed:**
- [ ] When to start the forward test period (after v1 spec comparisons complete)?
- [ ] What are the pass/fail criteria (e.g. no drawdown halt triggered, positive return,
  fill rate within X% of backtest)?

---

### S6 — Indicator expansion: what's built, what's missing, what to add
**Source:** Community discussions relayed by owner, 2026-09-29.

The community consensus (and your bot's own design) is: mix indicator *categories*
(trend + momentum + volatility + volume), not redundant copies of the same signal.
Below is the full set of commonly-used indicators mapped against what your bot
already computes vs what is missing.

| Indicator | Category | Already in bot? | Notes |
| --- | --- | --- | --- |
| **SMA/EMA** | Trend direction | ✅ SMA20, SMA50, SMA200 | Used in regime score and trend_switch |
| **ADX** | Trend strength | ✅ ADX14 | Core to BULL/BEAR vs RANGE decision |
| **ATR** | Volatility / risk | ✅ ATR14 | Used for grid sizing and S/R zone clustering |
| **Volume indicators** | Market confirmation | ✅ 24h quote volume, volume vs baseline | Used in liquidity_health signal |
| **MACD** | Trend confirmation | ❌ Not built | Derived from EMA12 - EMA26; adds confirmation of trend transitions. Lower priority — SMA ratio covers similar ground |
| **RSI** | Momentum | ❌ Not built | Relative Strength Index (14-period). Useful as overbought/oversold filter. Currently covered approximately by `momentum` signal (24h return tanh-scaled) |
| **Bollinger Bands** | Volatility | ❌ Not built | Upper/lower bands at ±2σ around SMA20. Useful for detecting price extremes and squeeze setups. ATR covers volatility sizing but not band position |
| **Stochastic** | Momentum | ❌ Not built | %K/%D oscillator. Redundant with RSI — adding both adds no new information. Low priority |
| **VWAP** | Price/volume | ❌ Not built | Volume-weighted average price. Intraday reference for whether buyers or sellers dominate. Genuinely different from existing signals — worth adding to opportunity scorer |
| **Ichimoku Cloud** | Trend analysis | ❌ Not built | Multi-component system (cloud, conversion/base lines, lagging span). High complexity, partially redundant with SMA-based trend. Low priority |

**Key lesson from community:** adding RSI + Stochastic + CCI is the same signal three
times — it feels like more confidence but adds no information. Real diversification
comes from mixing categories. Your bot already has the right categories covered;
the gaps are MACD (trend confirmation), RSI (momentum extremes), Bollinger Bands
(volatility position), and VWAP (intraday volume reference).

**Recommended additions for v2 (in priority order):**
1. **RSI(14)** — add as overbought/oversold filter on entry (skip longs if RSI > 70,
   skip shorts if RSI < 30). Low implementation cost, genuine new signal category.
2. **VWAP** — add to opportunity scorer as intraday price/volume reference.
3. **Bollinger Band position** — add as volatility squeeze detector (tight bands
   precede large moves; wide bands mean expansion already happening).
4. **MACD** — add as trend confirmation once the above are measured.

**What needs building:** extend `SeriesFeatures` in `backtest/features.py` with RSI,
VWAP, and Bollinger Band calculations. Add to `Inputs` dataclass. Measure impact via
backtest before wiring into any decision.

**Owner decisions needed:**
- [ ] Confirm priority order above or reorder.
- [ ] Schedule as a formal Bob task once PRs #147–#150 are merged and measured.

---

### S7 — Regime as filter not gate (entry in TRANSITION with tighter risk)
**Source:** Community discussion relayed by owner, 2026-09-29.

Currently regime is a binary gate: the bot only opens a new grid in RANGE. In
TRANSITION (unclear signal), no new grid opens regardless of how strong the
individual signals are. The community pattern of "2–3 core indicators for entry,
rest as filters" suggests a softer approach: allow entry in TRANSITION if core signals
are sufficiently strong, but apply tighter risk rules (smaller capital allocation,
tighter drawdown threshold, smaller grid).

**This is a meaningful behaviour change and needs measurement before implementation.**

**Questions to answer:**
- How often is the market in TRANSITION, and what fraction of profitable grid
  opportunities occur during TRANSITION?
- If entries are allowed in TRANSITION with 50% capital allocation, does total return
  improve or does drawdown increase?

**Owner decisions needed:**
- [ ] Is this worth investigating, or keep the binary gate as a simplicity principle?

---

## Infrastructure items

### I1 — Reliable 24/7 hosting (VPS or homelab)
**Source:** Community best-practice advice relayed by owner, 2026-09-29.

Free-tier or sleeping hosts break 24/7 market monitoring. For the forward test and
any live deployment, the bot needs a process that never sleeps. Issue #121 (deploy
two remote Codex reviewers) is related infrastructure but does not address the trading
bot's hosting.

**Owner decisions needed:**
- [ ] VPS provider, or homelab server?
- [ ] This is not needed until the forward test starts. Low priority until then.

---

## Closed / addressed items

*(Move items here when a backtest result or owner decision resolves them.)*

None yet.

— IBM Bob (owner's desktop session)
