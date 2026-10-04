# Meta-Strategy Architecture: Adaptive Variant Selection System

**Document type:** Technical design document — shared knowledge base  
**Intended readers:** Codex, Claude (and the owner)  
**Status:** Draft — open for discussion and brainstorming  
**Date:** 2026-10-02  
**Branch context:** `bob/audit-remediation-2026-09-30`

---

## 1. Project Overview and Goal

The adaptive crypto grid bot was originally built as a single-variant system: choose one
`SimulationPolicy` configuration, run it against historical data, score it on the C1–C6
criteria, and accept or reject it. Eleven variants have now been implemented under spec v1.

The core insight driving this document is that **no single variant is expected to dominate
across all market conditions**. Each variant was designed to protect against a specific class
of loss:

- Trend-adverse entries in a falling market → Variant A (trend switch)
- Inventory overextension in a volatile market → Variant B (inventory cap)
- Breakout-fail range exits driven by noise → Variant E (volume confirmation)
- Entries into adverse order-flow → Variant F (flow block)
- Entries when funding rates signal overheated longs → Variant G (funding gate)
- Grid placement during cycle peak overextension → Variant H (halving cycle context)

Each of these failure modes is regime-specific. A grid bot running in a healthy ranging
market with neutral funding is fine with V0. A grid bot running into the peak of a halving
cycle with strongly positive funding and adverse flow is exposed on all of the above axes
simultaneously. The variants are not competing strategies — they are **regime-specific
protection modules**.

The ultimate objective of this project is therefore a **meta-strategy**: a regime-adaptive
system that observes the current market state and dynamically selects or blends the best
`SimulationPolicy` configuration for that state, rather than committing to a single variant
for the entire lifetime of the bot.

This document captures the full current state of the project, all eleven variants in detail,
the architecture of the proposed meta-strategy, and the open questions that Codex, Claude,
and the owner must resolve before implementation begins.

---

## 2. Current Experiment Setup

### Exchange and Assets

| Parameter | Value |
|---|---|
| Exchange | Binance (spot) |
| Assets | BTC/USDT, ETH/USDT, XRP/USDT |
| Fee model (primary) | Revolut X: maker 0 / taker 0.0009 |
| Fee model (sensitivity) | 0.001 maker / 0.001 taker |

### Date Windows

| Parameter | Value |
|---|---|
| Data fetch start (warmup) | 2018-05 |
| Evaluation start | 2019-01 |
| Evaluation end | 2024-12 |
| `DEVELOPMENT_END` hard lock | 2024-12 (enforced in `window.py`) |
| Spec name | `full-range-2017-2024` |

> **Note on naming:** The spec is named `full-range-2017-2024` for historical reasons; the
> actual data starts from 2018-11 (BTC) and 2018-05 (warmup). The 2019-01 evaluation start
> guarantees at least 200 completed daily bars for SMA200 initialisation before the first
> evaluated minute bar.

### Binding Acceptance Windows (not yet run)

| Spec | Assets | Purpose |
|---|---|---|
| `verify-2024h1` | ADA + BTC | C1–C6 binding acceptance window 1 |
| `practice-2022` | BTC + XRP + SOL | C1–C6 binding acceptance window 2 |

These are the **held-out one-use windows**. They must not be inspected until a winner is
selected on the development data, and they must not be used for tuning under any
circumstances. The `full-range-2017-2024` window is the development/research window.

### Compute Infrastructure

| Parameter | Value |
|---|---|
| Cores available | 4 |
| Max parallel processes | 4 |
| Time per path (12 paths × 3 assets × 2 gate configs) | ~128 minutes |
| Time per full variant run | ~25 hours |
| Total for all 11 variants | ~2–3 days wall time |

Variant runs are orchestrated by `scripts/run_parallel_variants.py`, which launches up to 4
concurrent subprocesses, each writing to its own log file (`data/run-{x}.log`), and
auto-starts the next variant when a slot frees.

### V0 Results on `full-range-2017-2024` (known)

| Asset | Gated result | Grids | Range exits | Halt |
|---|---|---|---|---|
| BTC | +2.09% | 22 | 16 | None |
| ETH | −4.2% to −5.4% | 70–72 | 35 | None |
| XRP | −31% to −38% | 149–151 | 76 | 2021 or 2024 |

Ungated baseline always halts and loses 44–52%. This confirms that the cycle gate is load-bearing
even in V0, and that ETH/XRP are structurally much harder to trade on a grid over this window.

---

## 3. All 11 Variants — Full Reference

### Variant table

| ID | CLI flag | Policy field | Core mechanism | Selection eligibility |
|---|---|---|---|---|
| V0 | *(none)* | defaults | Plain grid + cycle gate (gated vs ungated baseline) | ✅ Eligible |
| A | `--variant-a` | `trend_switch=True` | Daily SMA50/SMA200 state machine; pauses new grids and liquidates on Down | ✅ Eligible |
| B | `--variant-b` | `inventory_cap=Decimal("0.40")` | Caps committed crypto exposure at 40% of prospective active equity per buy | ✅ Eligible |
| C | `--variant-c` | `trend_switch=True` + `inventory_cap` | A and B together | ✅ Eligible |
| D | `--trend-benchmark` | *(not a grid)* | Pure trend-follow benchmark; no grid, no risk controls; reference only | 🔒 Not selectable |
| E | `--variant-e` | `volume_exit=True` | Volume-confirmed range exit: 6h outside-range timer extends to 12h when bar volume < 2× median 720h volume × 6 | ⏳ Pending Codex review |
| F | `--variant-f` | `flow_block_entry=True` | Order-flow entry block: new buys blocked when taker-buy share < 0.40 over last 15 completed 1m bars; unblocked at ≥ 0.45; fails closed | ⏳ Pending Codex review |
| G | `--variant-g` | `funding_gate=True` | Funding-rate gate: no new grid when signal unavailable or all three of the last three settlements > +0.0005 | ⏳ Pending Codex review |
| H | `--variant-h` | `cycle_gate=True` | Bitcoin halving cycle context: H2 phase [18,30) with C > 1.60×SMA200 → no new grid, 2h exit threshold; H3 phase [30,48) with C < 0.50×ATH → score minimum −0.10 | ⏳ Pending Codex review |
| C+G | `--variant-cg` | `trend_switch` + `inventory_cap` + `funding_gate` | A + B + G combined | ⏳ Pending Codex review |
| C+H | `--variant-ch` | `trend_switch` + `inventory_cap` + `cycle_gate` | A + B + H combined | ⏳ Pending Codex review |

### Variant A — Trend Switch (detail)

Implemented in [`simulation/trend_switch.py`](../src/crypto_grid_bot/simulation/trend_switch.py).

The daily state machine produces one of five states per UTC day:

| State | Meaning |
|---|---|
| `up` | Two consecutive closes above SMA200; full grid operation permitted |
| `recovering` | One close above SMA200 after a non-Up state; grid permitted |
| `middle` | Close between SMA50 and SMA200; grid permitted |
| `down` | Close below SMA50; triggers Down sequence: cancel resting buys, liquidate within 24h |
| `unavailable` | No daily bar or SMA undefined; treated conservatively |

A new grid requires state `up` or `recovering` and no active Down sequence. A Down sequence
started by a `down` classification cancels all resting buys immediately and forces a
liquidation exit within `DOWN_DEADLINE_SECONDS` (86,400 s). Requires `daily_warmup_start`
in the spec and at least 200 completed daily bars before the first evaluated minute.

The signal is read from the bar of the previous UTC day only. A bar from two days ago or
older is treated as `unavailable` (stricter than the doc note in audit finding H6).

### Variant B — Inventory Cap (detail)

Implemented inline in [`simulation/runner.py`](../src/crypto_grid_bot/simulation/runner.py)
via `capped_quantity()` from [`simulation/inventory_cap.py`](../src/crypto_grid_bot/simulation/inventory_cap.py).

Before creating a new buy order, the engine computes prospective active equity (cash +
mark-to-market inventory) and refuses to create an order that would push committed
crypto exposure above `inventory_cap` (default 40%) of that figure. Existing grids and
exits are unaffected. This does not liquidate; it simply blocks new grids when loaded.

### Variant E — Volume-Confirmed Range Exit (detail)

Policy field: `volume_exit`. Signals arrive on `Frame` as `e_threshold` and `e_bar_volume`.

When the price has been outside the grid range for the 6h timer period, V0 would exit
immediately. Variant E extends the timer to 12h if the accumulated bar volume in the
outside-range window is below `e_threshold = 2 × median(last 720 completed 1h base volumes) × 6`.
The intent is to avoid exiting on low-volume noise breakouts that resolve quickly.

### Variant F — Order-Flow Entry Block (detail)

Policy field: `flow_block_entry`. Signal arrives on `Frame` as `f_share`.

Measures taker-buy share = taker-buy base volume ÷ total base volume over the last 15
completed consecutive 1m bars. The gate is hysteretic: blocks entry when share < 0.40,
unblocks when share ≥ 0.45. Starts in the blocked state (fails closed). Signal is `None`
when F is off or when a bar is missing or has zero aggregate volume.

### Variant G — Funding-Rate Gate (detail)

Policy field: `funding_gate`. Signal arrives on `Frame` as `g_blocks`.

Blocks new grid creation when: (a) the funding signal is unavailable (fails closed), or
(b) all three of the last three 8-hourly settlement rates exceed +0.0005. Existing grids
and exits are unaffected. On the `full-range-2017-2024` window, no funding-rate data was
fetched, so G will produce 0 grids on that window — this is expected and correct per the
spec's fail-closed design.

### Variant H — Bitcoin Halving Cycle Context (detail)

Policy field: `cycle_gate`. Implemented in [`backtest/cycle.py`](../src/crypto_grid_bot/backtest/cycle.py).

Uses fixed historical halving timestamps (2016-07-09, 2020-05-11, 2024-04-20). Computes
phase `m` = whole calendar months since the most recent halving.

| Band | Phase | Condition | Effect |
|---|---|---|---|
| H1 | [0, 18) | Always | No additional restriction |
| H2 | [18, 30) | Close > 1.60 × SMA200 | Block new grid; reduce outside-range threshold to 2h |
| H3 | [30, 48) | Close < 0.50 × ATH since halving | Lower opportunity score minimum by 0.10 |

SMA200 and ATH are computed from completed daily bars at observation time (no lookahead).
H3 does not activate if ATH data does not reach back to the halving.

---

## 4. Why Individual Variants Are Insufficient

Each variant addresses exactly one dimension of market risk. The market, however, can
present multiple unfavourable conditions simultaneously.

Consider late 2021 (BTC cycle peak, XRP exit losses in V0): funding rates are elevated,
the halving cycle is in H2, order flow is sell-dominated, and the trend is technically
still Up but stalling. In this state:

- V0 runs freely and accumulates inventory into a reversal.
- A holds off new grids once the daily close drops below SMA200, but by then inventory
  is already on board.
- G blocks new grids due to funding, but does nothing about existing inventory.
- H blocks new grids in H2, but the 2h outside-range threshold may trigger exits at
  loss while a deeper correction continues.
- B limits inventory growth but doesn't react to cycle phase or funding.

No individual variant handles all of this. The combination C+G or C+H comes closer, but
it is still a static combination — it cannot distinguish a benign H2 phase with low
funding from a dangerous one with all signals aligned bearish.

More fundamentally: running all 11 variants over the full 6-year window on V0 will
show that **the ranking of variants reverses across market regimes**. A variant that
destroys value in a ranging market (e.g. G when funding is always neutral) may save
the entire account in a trending/overheated market. Picking one variant for all time
is equivalent to picking one tool from a toolkit and discarding the rest.

The 6-year run is therefore **research data**, not a deployment decision. Its value is
the per-regime performance profile it produces for each variant — the calibration data
for a router that selects the right variant for the current market state.

---

## 5. Meta-Strategy Architecture

### 5.1 Conceptual Layers

The meta-strategy sits above the existing `PaperSimulator` / `SimulationPolicy` stack.
It does not replace those components; it drives them. Conceptually it has four layers:

```
┌─────────────────────────────────────────────┐
│  4. Feedback loop                           │  Live performance → regime mapping update
├─────────────────────────────────────────────┤
│  3. Selection / blending decision           │  Hard-switch or weighted allocation
├─────────────────────────────────────────────┤
│  2. Variant scoring layer                   │  Expected performance given regime state
├─────────────────────────────────────────────┤
│  1. Regime detection layer                  │  Current market state classification
└─────────────────────────────────────────────┘
         ↓ emits SimulationPolicy
┌─────────────────────────────────────────────┐
│  Existing PaperSimulator stack              │  Unchanged
└─────────────────────────────────────────────┘
```

### 5.2 Layer 1 — Regime Detection

The regime detection layer already partially exists. [`strategy/regime.py`](../src/crypto_grid_bot/strategy/regime.py)
implements a `RegimeClassifier` that classifies `MarketSignals` into one of:

| Regime | Meaning |
|---|---|
| `RANGE` | Low ADX, low score magnitude, low dispersion |
| `BULL` | High ADX, strong positive directional evidence |
| `BEAR` | High ADX, strong negative directional evidence |
| `TRANSITION` | Between states or below quality floor |
| `STRESS` | Emergency flag active |

The classifier uses a weighted vote across six signals:

| Signal | Weight | Source |
|---|---|---|
| `trend` | 0.25 | SMA cross / daily bars |
| `breadth` | 0.20 | Market breadth across basket |
| `momentum` | 0.15 | Price momentum |
| `volatility_health` | 0.15 | ATR / historical vol |
| `liquidity_health` | 0.15 | Spread / depth |
| `structure_alignment` | 0.10 | Multi-timeframe structure |

**What the existing classifier does not capture** (and the meta-strategy needs):

| Signal | Variant relevance | Currently available |
|---|---|---|
| Funding rate level | G | On `Frame.g_blocks` |
| Halving cycle phase | H | On `Frame.h2_active`, `Frame.h3_active` |
| Order flow direction | F | On `Frame.f_share` |
| Volume character (range exit noise) | E | On `Frame.e_bar_volume`, `Frame.e_threshold` |
| Inventory load (exposure %) | B | Computable from account state |

The meta-strategy's regime detection layer must **extend** the existing classifier to
incorporate these signals, producing a richer regime descriptor that is sufficient to
distinguish when each variant's protection is warranted.

A candidate extended regime descriptor might look like:

```python
@dataclass(frozen=True)
class ExtendedRegime:
    broad: MarketRegime          # RANGE / BULL / BEAR / TRANSITION / STRESS
    trend_state: str             # up / recovering / middle / down / unavailable
    cycle_phase: int             # months since halving (0–47+)
    h2_active: bool
    h3_active: bool
    funding_elevated: bool       # all 3 of last 3 settlements > 0.0005
    flow_adverse: bool           # taker-buy share < 0.40
    inventory_loaded: bool       # committed exposure > threshold
    volume_thin: bool            # bar volume below E threshold
```

### 5.3 Layer 2 — Variant Scoring

Given an `ExtendedRegime`, the scoring layer maps each variant to an expected performance
delta relative to V0. This mapping is the core output of the 6-year variant runs.

The expected form of this data (post-runs) is a table of the type:

```
regime_key → {V0: score, A: score, B: score, C: score, ..., C+H: score}
```

where `regime_key` is a discretised representation of the `ExtendedRegime` and `score`
is derived from the C1–C6 acceptance criteria (described in section 5.6).

**Key design constraint:** The scoring table must be derived from the development data
(`full-range-2017-2024`) only, and must be **frozen before** the binding acceptance
windows (`verify-2024h1`, `practice-2022`) are inspected. This is the same startup rule
that governs individual variant selection: no tuning after seeing held-out results.

### 5.4 Layer 3 — Selection vs Blending

Two strategies exist for using the scoring table at runtime:

**Hard selection:** At each regime transition, the meta-strategy switches the active
`SimulationPolicy` to the highest-scoring variant for the detected regime. Simple to
reason about; clean audit trail; no capital splitting required.

**Proportional blending:** Allocate capital across multiple variants simultaneously,
weighted by their expected performance scores. This requires running multiple
`PaperSimulator` instances in parallel and routing capital between them. Significantly
more complex; risks portfolio drift; harder to audit.

The current codebase has no infrastructure for parallel simulator instances or capital
routing. Hard selection is the natural first target. Blending is a longer-term option
that should only be considered if hard selection proves insufficient on the acceptance
windows.

### 5.5 Layer 4 — Feedback Loop

In live operation, actual trade outcomes will diverge from the historical performance
profile (because the market changes). The feedback loop updates the regime-to-variant
mapping weights based on recent realised performance.

This is the highest-risk component of the meta-strategy. If the feedback loop is too
sensitive, it will overfit to short-term noise and constantly switch variants at the
worst moment (chasing the last regime rather than the current one). If it is too slow,
it degrades to static selection.

**Design constraint:** The feedback loop must be subject to the same no-tuning rule.
Its update frequency and sensitivity parameters must be set before any live data is seen
and must not be changed based on live results.

### 5.6 Scoring System — C1 Through C6

The C1–C6 criteria are the frozen acceptance criteria agreed by the owner on 2026-09-24
(see [`docs/reviews/2026-09-24-owner-decisions-confirmed.md`](2026-09-24-owner-decisions-confirmed.md)).

| Criterion | Description |
|---|---|
| C1 | Total equity return over the evaluation window (fees included) |
| C2 | Maximum drawdown (peak-to-trough, mark-to-market) |
| C3 | Sharpe-like risk-adjusted return |
| C4 | Number of forced range exits (proxy for regime-hostility) |
| C5 | Halt frequency (hard drawdown halts per year) |
| C6 | Performance vs buy-and-hold and vs cash baseline |

For the meta-strategy, C1–C6 should be computed on the **combined** output of the
meta-strategy (as if it were a single variant), not on any individual variant in isolation.
The meta-strategy's acceptance on the binding windows is what matters, not the individual
variant scores.

---

## 6. What the 6-Year Run Gives Us

The `full-range-2017-2024` run across all 11 variants will produce, for each variant:

1. **Per-path results** (3 assets × 4 path types = 12 paths per variant):
   - Total equity return (gated and ungated)
   - Grid count, range exit count, halt count
   - Forced exit losses broken down by exit reason

2. **Regime period analysis** (post-processing required):
   - The 6-year window spans multiple clear regimes: 2019 ranging, 2020 bull, 2021 peak,
     2022 bear, 2023 recovery, 2024 bull. By slicing each variant's results by calendar
     period aligned to these known regimes, we get the per-variant per-regime performance
     profile.

3. **Signal activation frequency**:
   - How often did each variant's gate fire? (G: how often was funding elevated? H: how
     many bars spent in H2/H3? F: how often was flow adverse?)
   - This tells us whether a variant is regime-specific (fires rarely, high precision) or
     pervasive (fires constantly, potentially blunting the strategy).

4. **Variant failure modes**:
   - E.g. Variant G will show 0 grids on this window because no funding data was fetched.
     This is expected. It confirms the fail-closed design but means G's performance on
     this window is not informative for the meta-strategy scoring table.
   - Variant H in H2 phase: did the 2h exit threshold cause premature exits in 2021?

5. **Correlation between variants**:
   - Do A and G tend to activate simultaneously (both triggered by downtrends with high
     funding)? Or independently? High correlation means blending them provides little
     diversification; low correlation means they protect different scenarios.

6. **Calibration data for regime boundaries**:
   - By examining which regime descriptor values (trend state, cycle phase, funding level)
     correlate with each variant outperforming V0, we can set empirical thresholds for the
     regime detection layer — rather than guessing them in advance.

---

## 7. Open Questions and Brainstorming Agenda

The following questions are unresolved and require discussion between Codex, Claude, and
the owner before the meta-strategy can be designed in detail.

### 7.1 Regime Definition and Detection

- **How granular should the regime descriptor be?** A 5-state broad classifier (RANGE /
  BULL / BEAR / TRANSITION / STRESS) combined with 5 binary flags (h2, h3, funding, flow,
  volume) produces 5 × 32 = 160 possible states. Most will be rare or empty in the
  6-year data. Should we collapse this into a smaller taxonomy of named regimes (e.g.
  "bull accumulation", "cycle peak", "bear capitulation", "ranging low-vol")?

- **Should regime detection be rule-based or ML-based?** The existing `RegimeClassifier`
  is fully rule-based and explainable. ML-based detection (HMM, clustering) could find
  emergent regimes not captured by the current taxonomy — but at the cost of
  explainability and a much higher overfitting risk. Given the small dataset (6 years,
  daily granularity), rule-based is almost certainly safer.

- **How to handle the TRANSITION regime?** The classifier returns TRANSITION when it
  cannot confidently classify. In those periods, should the meta-strategy default to V0,
  hold the last regime, or use a defensive variant (e.g. B alone)?

### 7.2 Switching Frequency and Transition Handling

- **How frequently should the meta-strategy re-evaluate the regime?** Daily (after each
  daily bar closes)? Per 8h funding settlement window? Per minute bar? Switching too
  frequently produces thrash; switching too infrequently misses regime changes.

- **What happens to open grids during a variant switch?** If the meta-strategy switches
  from C+H (which blocked a new grid) to V0 (which would allow it), does it immediately
  open a grid? Or does it wait for a clean slate? This is the most dangerous transition
  because it can create entry at a regime boundary — exactly where regime classifiers are
  least reliable.

- **Should there be a hysteresis buffer on regime transitions?** Analogous to the
  taker-buy share hysteresis in Variant F (block < 0.40, unblock ≥ 0.45), the regime
  classifier could require N consecutive bars agreeing on a new regime before switching.

### 7.3 Overfitting Prevention

- **The regime-to-variant mapping is calibrated on the same 6-year window the variants
  were developed on.** The only protection against overfitting is:
  (a) using a small number of regime buckets (fewer degrees of freedom),
  (b) requiring each regime bucket to have a minimum number of observations,
  (c) applying a significance threshold (variant must outperform V0 by at least X% to
  be preferred in that regime),
  (d) freezing the mapping before looking at the binding acceptance windows.
  What thresholds are appropriate? This is a key design decision.

- **Walk-forward validation:** Before running on the binding windows, the meta-strategy
  should be validated on a walk-forward split of the `full-range-2017-2024` data — e.g.
  calibrate the regime mapping on 2019–2022, validate on 2023–2024. This does not consume
  the held-out windows and provides an early overfitting signal.

### 7.4 Capital Allocation in Blending Mode

- **If blending is pursued**, how is capital split? Equal weight? Score-proportional?
  Min-variance? Note that the individual simulators are not independent — they all trade
  the same underlying asset, so "portfolio diversification" between them is illusory at
  the asset level. The diversification is only in the decision rules, not in the exposure.

- **Can two variants simultaneously have open grids on the same symbol?** With the current
  architecture, each `PaperSimulator` manages one account. Running two simulators on the
  same symbol would require two separate accounts with split capital, which the current
  codebase does not support.

### 7.5 Meta-Strategy Backtesting

- **The meta-strategy must be backtested as a combined system** before deployment. This
  means implementing a backtesting harness that: (a) runs all relevant variants in
  parallel on the same bar sequence, (b) at each bar evaluates the regime detector and
  selects the active variant, (c) routes the "active" variant's decisions to the account,
  and (d) records the combined equity curve as if a single strategy had been running.

- **This is a new piece of infrastructure** that does not currently exist. It is
  significantly more complex than the existing per-variant backtest runner. It must be
  built, reviewed, and tested to the same standard as the existing simulator before it
  can be used for acceptance decisions.

### 7.6 Live Operation Constraints

- **Regime switches in live operation** must not cause contradictory open orders. The
  current `PaperSimulator` can have resting buy orders. A regime switch that would
  invalidate those orders (e.g. switching to Variant A Down state) must trigger the same
  Down sequence behaviour as if the variant had been running all along.

- **Signal availability:** In live operation, G and F require real-time data (funding
  rate settlements, 1m trade data). H requires daily bars. A requires daily bars. These
  have different latency and availability characteristics. The meta-strategy must degrade
  gracefully when any signal is unavailable — defaulting to the most conservative
  applicable variant, not to V0.

---

## 8. Longer-Term Vision

The end state of this project, if the meta-strategy is successfully validated on the
binding acceptance windows, is a single deployed bot that:

1. **Continuously classifies the market regime** using the extended regime descriptor,
   updating on each daily bar close and on each 8h funding settlement.

2. **Selects the active `SimulationPolicy`** from a frozen regime-to-variant lookup
   table calibrated on the 6-year development window, with a hysteresis buffer to
   prevent rapid switching.

3. **Manages open grids through transitions** without creating contradictory orders —
   respecting the Down sequence protocol if A/C is activated, the H2 exit threshold
   protocol if H is activated, and the flow block if F is activated.

4. **Reduces forced-exit losses** by blocking grid creation during the regimes most
   hostile to grid strategies (cycle peaks, adverse flow, elevated funding), while
   remaining active and profitable during the regimes where grid strategies have
   demonstrated positive returns.

5. **Improves cycle-phase awareness** beyond the binary gated/ungated distinction of V0,
   using the four-band halving cycle model (H1/H2/H3/post-H3) to modulate both grid
   creation and exit thresholds.

6. **Outperforms any individual variant** across all market conditions — not by being
   the best at any one regime, but by never being badly wrong in any regime. The goal is
   a strategy that survives the full cycle, not one that wins one phase and blows up in
   another.

The `full-range-2017-2024` run currently in progress is the first concrete step toward
this goal. Its output — per-variant, per-regime performance profiles — is the calibration
dataset that makes the meta-strategy possible.

---

## 9. File and Code Reference Map

| Component | File |
|---|---|
| Variant A implementation | [`simulation/trend_switch.py`](../src/crypto_grid_bot/simulation/trend_switch.py) |
| Variant H cycle logic | [`backtest/cycle.py`](../src/crypto_grid_bot/backtest/cycle.py) |
| All variant flags (`SimulationPolicy`) | [`simulation/runner.py`](../src/crypto_grid_bot/simulation/runner.py) |
| Frame signal fields (E/F/G/H) | [`simulation/runner.py`](../src/crypto_grid_bot/simulation/runner.py) L180–232 |
| CLI variant flags | [`backtest/__main__.py`](../src/crypto_grid_bot/backtest/__main__.py) |
| Existing regime classifier | [`strategy/regime.py`](../src/crypto_grid_bot/strategy/regime.py) |
| Market signal and regime domain types | [`domain.py`](../src/crypto_grid_bot/domain.py) |
| Parallel variant runner | [`scripts/run_parallel_variants.py`](../scripts/run_parallel_variants.py) |
| Full-range spec | [`config/datasets/full-range-2017-2024.toml`](../config/datasets/full-range-2017-2024.toml) |
| Binding window 1 | [`config/datasets/verify-2024h1.toml`](../config/datasets/verify-2024h1.toml) |
| Binding window 2 | [`config/datasets/practice-2022.toml`](../config/datasets/practice-2022.toml) |
| C1–C6 criteria (owner record) | [`reviews/2026-09-24-owner-decisions-confirmed.md`](2026-09-24-owner-decisions-confirmed.md) |
| Spec v1 (draft) | [`docs/EXPERIMENT_SPEC_V1.md`](../EXPERIMENT_SPEC_V1.md) |
| Roadmap | [`ROADMAP.md`](../ROADMAP.md) |
| Second audit plan | [`reviews/2026-09-30-bob-second-audit-plan.md`](2026-09-30-bob-second-audit-plan.md) |

---

*This document was produced by Bob on 2026-10-02 as a shared design briefing for Codex
and Claude. It should be treated as a living document: update it as design decisions are
made, open questions are resolved, and results from the current runs become available.*
