# V4.0 Step 3: The Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the V4 engine. It replays one cell (an arm, a capital and a cost level) over
the step-2 packs, hour by hour, on one shared spot and USDT-M futures account. It writes
hash-chained records, a self-verified `summary.json` and an HTML page.

**Architecture:** This is a new package, `src/crypto_grid_bot/v4/engine/`, with one module per
responsibility:
- arms and costs;
- the market view of the packs;
- signals and sizing;
- pending decisions;
- the ledger and leg orders;
- the spot-first allocation;
- safety;
- lifecycles;
- records;
- the hour loop, the hold arms and the summary;
- a one-cell CLI, `scripts/v4_cell.py`.

The pure parts (signals, sizing, allocation, safety factors) are tested on their own. The hour
loop composes them.

Everything that touches market data is guard-free: V3's stateful code refuses every month
after 2024-12, so the V3 math V4 needs is copied into `v4/engine/`, with differential tests
against the V3 originals on pre-2025 data.

**Tech Stack:** Python 3.12, standard library only (`decimal`, `fractions`, `array`, `json`,
`hashlib`, `html`), pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-17-v4-design.md`. The sections are "Signals",
"Sizing", "Account and execution", "Safety", "Versions in the run" (the arm table, the
neighbour lookbacks and the hold arms), "Pass rule" (the common measure the summary must
support), "Records", "Reports", "Engineering", "Verification" and "Delivery" item 3. The
input is the step-2 packs: their layout and the contract for this step are in the module
docstring of `src/crypto_grid_bot/v4/data/pack.py`, and `docs/RUN_ARCHIVE.md` says where
they are stored.

## Global Constraints

- Paper simulation only. There are no orders, no keys, and no network access in the engine.
- Never edit `src/crypto_grid_bot/simulation/`, `trend/`, `strategy/`, `backtest/` or
  `combined/`. Import only these guard-free names (the step-3 audit, 2026-10-20):
  - `combined.assessment.daily_bars`
  - `strategy.indicators.sma`
  - `trend.metrics` (`maximum_drawdown`, `cagr`, `sharpe`, `sample_returns`)
  - `trend.sizing.DailyReturn`
  - `backtest.klines` (`Kline`, `INTERVAL_MS`, `month_bounds_ms`)
  - `combined.execution` (`VenueRules`, `floor_quantity`)
  - `combined.driver.venues.cost_profile`
  - `combined.artifacts` (`_canonical`, `_digest`)
  - the `v4.data` modules

  Never call `trend.signals`, `trend.sizing.size_portfolio`/`daily_returns`,
  `trend.pending`, `trend.account`, `trend.execution`, `combined.engine` or
  `combined.account` from engine code. Those reach a 2024 guard or the 2025-01-01 literal.
  Tests may call them only as differential oracles on pre-2025 data.
- One Decimal context for all Decimal arithmetic: `CONTEXT = Context(prec=60,
  rounding=ROUND_HALF_EVEN)` in `v4/engine/numbers.py`, as V3 §4-§6 compute. The ledger
  keeps exact `Fraction`s internally, as V3.1's does.
- Costs come from `cost_profile(multiple, venue)`. Normal is multiple 1: spot fee 0.001,
  futures fee 0.0005, slippage 0.0005 on both. Doubled is multiple 2.
- **Arms:** `v4_main`, `v4_long_only`, `v4_vol25`, `v4_vol60`, `v4_faster`, `v4_slower`,
  `hold_universe`, `hold_btc`. Capitals are 1000 and 10000 USDT; cost multiples are 1 and 2.
  `v3_as_built` is out of scope here (Ruling R1).
- **The reserved window (v4-d03):** no test, and nothing run while building this step, reads
  the real packs. They hold 2025+ data, which only the registered run (step 5) may execute.
  All engine tests use synthetic packs.
- The owner's rule against CPU-heavy work on their PC: run only each task's focused test
  modules locally. Before pushing, also run the repo-wide gates, `python -m ruff format
  --check .`, `python -m ruff check .` and `python -m bandit -q -r src scripts`. The full
  suite runs in CI.
- Ruff, mypy (strict) and bandit clean. Commit trailer:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Rulings this plan makes** (the spec leaves these open; each one is cheap to change):

- **R1:** the `v3_as_built` cell (V3's frozen runner plus a `summary.json` built from V3's
  records) belongs to step 4, with the comparisons and the cells matrix. Step 3 covers the
  six V4 arms and the two hold arms.
- **R2, futures margin bookkeeping:**
  - there is no collateral bucket, so cash is the wallet's USDT;
  - backing = cash + futures unrealised P&L, which equals V3.1's free cash + collateral +
    unrealised P&L;
  - the initial margin that the room formula and the cash clip use is
    `|futures notional at the current open| / 3`. It is computed, never booked. (V3.1's
    ledger books 1/2 of entry notional, and a booked 1/3 does not terminate in decimals.)
- **R3, fill prices:** `open x (1 + side x slippage)`, not rounded to the tick (V3 §6 fills
  "at the open with slippage"). The fee is `quantity x fill price x fee rate`. A synthetic
  close uses the penalised price and the fee with no slippage (spec "Safety").
- **R4, returns:** daily returns are V3's: close to close between consecutive UTC days only,
  never across a missing day (`trend.sizing.daily_returns`' rule).
- **R5, units:** the ledger and the orders work in each venue's own units: coins on spot,
  contracts on the perpetual, whose prices and filters the pack already holds in contract
  units. A coin's position and every target are compared in USDT notional, so the multiplier
  appears only in records.
- **R6, best unrealised profit:** a lifecycle's best unrealised profit and profit given back
  are measured on hourly open marks, the same marks as the common measure.
- **R7, symbols:** V4 code validates symbols with the V4 data layer's pattern (2-30
  characters of `[A-Z0-9]`), never with `market_data.parsing.symbol_name`, which allows 24.

## Review Focus

1. **A coin with spot and perpetual of the same name holds both legs at once** (BTCUSDT spot
   and BTCUSDT futures). V3.1's ledger refuses this, so V4's ledger keys positions by venue
   and symbol. Pinned in Task 6, `test_one_coin_holds_a_spot_and_a_futures_leg_under_one_name`.
2. **A multiplier perpetual** (1000SHIBUSDT for SHIBUSDT): targets in notional must become
   contracts at the contract price, and funding must use contract quantity times the
   contract price. Pinned in Task 8,
   `test_a_multiplier_perpetual_is_sized_in_contracts_from_notional`.
3. **A masked bar at the 00:00 decision or the 01:00 fill hour.** The order defers to the
   coin's next usable hour, and a newer 00:00 decision replaces it. Pinned in Task 5,
   `test_midnight_decision_replaces_a_deferred_order`.
4. **An empty universe month, or a window whose first months hold coins without a
   perpetual:** targets are zero or spot-only, and nothing divides by zero. Pinned in Task 12,
   `test_an_empty_universe_month_holds_cash_and_trades_nothing`.
5. **A cell that stops early** (liquidation or an unrestorable limit) must still write a full
   summary up to the stop, with the spec's nulls. Pinned in Task 14,
   `test_a_liquidated_cell_writes_a_full_summary_to_the_stop`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/crypto_grid_bot/v4/engine/__init__.py` | Package marker |
| `v4/engine/numbers.py` | `CONTEXT`, exact helpers (`to_fraction`, `to_decimal`), `INF` handling for the margin ratio |
| `v4/engine/arms.py` | `Lookbacks`, `ArmSpec`, `CellSpec`, the eight arm definitions, cost rates |
| `v4/engine/market.py` | `SeriesStore` (compact hourly bars), `Market` (packs to per-coin views, daily bars, eligibility, funding) |
| `v4/engine/signals.py` | Per-coin signal state: SMA, EMA, Donchian 55/20, downtrend, speeds, L, S, s |
| `v4/engine/sizing.py` | Daily returns, sigma, covariance, full-strength scale, caps, the band |
| `v4/engine/pending.py` | Pending decisions: deferral, the 00:00 rule, no-bar, mandatory exits, replacement buys |
| `v4/engine/ledger.py` | The shared-account ledger: FIFO lots by (venue, symbol), cash, funding, marks, audit |
| `v4/engine/orders.py` | Leg orders: step rounding, min/max quantity and notional, splits, reduce-only, dust, fill price and fee |
| `v4/engine/allocation.py` | Spot-first split and the cash clip (pure) |
| `v4/engine/safety.py` | Margin ratio, liquidation, cushion and ceiling cuts, dead markets, funding-month exits, window end |
| `v4/engine/lifecycle.py` | Per coin and side lifecycles across venues |
| `v4/engine/records.py` | Hash-chained record writer and reader, the bundle receipt |
| `v4/engine/run.py` | The hour loop for the V4 arms |
| `v4/engine/hold.py` | `hold_universe` and `hold_btc` |
| `v4/engine/summary.py` | `summary.json`, the HTML page, self-verification |
| `scripts/v4_cell.py` | Run one cell from a data directory into an output directory |
| `tests/test_v4_engine_*.py` | One module per source module, plus `tests/v4_synthetic.py` (synthetic pack builder) |

---

### Task 1: Arms, costs and the number helpers

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/__init__.py`, `v4/engine/numbers.py`, `v4/engine/arms.py`
- Test: `tests/test_v4_engine_arms.py`

**Interfaces:**
- Produces:
  - `numbers.CONTEXT: Context` (prec 60, `ROUND_HALF_EVEN`), `to_fraction(value: Decimal) -> Fraction`, and `to_decimal(value: Fraction) -> Decimal`, which is exact and raises on a non-terminating value.
  - `Lookbacks(fast: int, ema_fast: int, ema_slow: int, donchian_entry: int, donchian_exit: int, slow: int, trend_sma: int, trend_slope: int, trend_window: int)`, frozen.
  - `ArmSpec(name: str, family: Literal["v4", "hold"], vol_target: Decimal | None, long_only: bool, lookbacks: Lookbacks | None)`, frozen.
  - `ARMS: Mapping[str, ArmSpec]`, holding the eight arms.
  - `CellSpec(arm: str, capital: int, cost_multiple: int)`, frozen, with `cell_id -> str` (`"v4_main-10000-1x"`) and `costs(venue) -> Costs`, which delegates to `cost_profile`.
  - Fixed sizing constants: `SIGMA_RETURNS = 60`, `COVARIANCE_DAYS = 60`, `MIN_COMMON_DAYS = 40`, `COIN_CAP = Decimal("0.30")`, `TOTAL_CAP = Decimal("2.7")`, `BAND_RELATIVE = Decimal("0.25")`, `BAND_ABSOLUTE = Decimal("0.01")`, `CEILING = Decimal(3)`, `CEILING_TARGET = Decimal("2.7")`, `CUSHION_FLOOR = 3`, `CUSHION_TARGET = 4`, `MAINTENANCE_RATE = Decimal("0.01")`, `INITIAL_MARGIN_DIVISOR = 3`, `COST_RESERVE = Decimal("0.02")`, `DEAD_MARKET_HOURS = 168`, `DEAD_MARKET_PENALTY = Decimal("0.10")`, `HOLD_INVESTED = Decimal("0.99")`.

- [ ] **Step 1: Write the failing tests**
  - `test_main_lookbacks_are_the_specs` checks `(20, 21, 55, 55, 20, 200, 50, 10, 20)`.
  - `test_neighbour_lookbacks_are_the_specs_table`: faster is `(15, 16, 41, 41, 15, 150, 38, 8, 15)` and slower is `(25, 26, 69, 69, 25, 250, 62, 12, 25)` (spec "Versions in the run").
  - `test_vol_targets_and_long_only_flags`: main, long-only, faster and slower are 0.40, vol25 is 0.25, vol60 is 0.60, and only `v4_long_only` is long-only; the hold arms have `vol_target=None` and `lookbacks=None`.
  - `test_cells_are_two_capitals_by_two_cost_levels` checks `cell_id` for all 32 cells.
  - `test_costs_are_the_v31_profile_and_double`.
  - `test_to_decimal_refuses_a_non_terminating_fraction`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** No logic beyond the data and the two converters.
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: arms, costs and exact number helpers`.

### Task 2: The market view of the packs

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/market.py`, `tests/v4_synthetic.py`
- Test: `tests/test_v4_engine_market.py`

**Interfaces:**
- Consumes: `pack.read_canonical`, the pack formats (pack docstring), `combined.assessment.daily_bars`, `backtest.klines.Kline`.
- Produces:
  - `SeriesStore.from_rows(rows: Sequence[Sequence[str | int]], masked: Iterable[int]) -> SeriesStore`.
    - It keeps the unmasked rows only. A missing open counts as masked, per the pack contract.
    - Storage: `open_ms` goes in `array("q")`. `open`, `high`, `low` and `close` are each `array("q")` scaled by `10**d`, where d is the series' most decimals after `normalize()`.
    - Methods:
      - `bar(open_ms) -> HourBar | None`;
      - `last_close_before(ms) -> Decimal | None`;
      - `last_open_at_or_before(ms) -> int | None`;
      - `first_open_ms -> int | None`;
      - `opens() -> Sequence[int]`.
  - `Perpetual(symbol: str, multiplier: int, store: SeriesStore, funding: tuple[tuple[int, Decimal], ...], months: Mapping[str, str], rules: VenueRules)`.
  - `Coin(symbol: str, spot: SeriesStore, spot_rules: VenueRules, perpetual: Perpetual | None)`.
  - `Market.load(data_dir: Path) -> Market`:
    - It reads `data.json`, verifies the daily pack and the index by their pins, then every coin pack by its index pin.
    - It refuses a format other than the three pack formats.
  - `Market` attributes and methods:
    - `window_start_ms`: 00:00 UTC of the first universe month.
    - `window_end_ms`: the last hour's open of `end_month`.
    - `universe(month: str) -> tuple[str, ...]`, which is `()` for a month without a universe.
    - `coin(symbol) -> Coin`.
    - `daily(symbol) -> tuple[Kline, ...]`: `daily_bars` over the coin's unmasked spot hours, computed once and cached.
    - `perpetual_eligible(symbol, decision_ms) -> bool`. True only when all three hold (spec "Universe", point in time):
      - the perpetual's first bar is at or before `decision_ms`;
      - it has a bar in the 168 hours before `decision_ms`;
      - the funding month of `decision_ms` is `"complete"`.
    - `funding_events(hour_open_ms) -> tuple[tuple[str, int, Decimal], ...]`: (perpetual, time_ms, rate) for records with `hour_open_ms <= time_ms < hour_open_ms + 3_600_000`, in time order.
    - `funding_month(symbol, month) -> str | None`.
- `tests/v4_synthetic.py` builds valid packs from simple price paths through `pack.py`'s own builders. Later tasks use it for synthetic worlds.

- [ ] **Step 1: Write the failing tests**
  - `test_store_keeps_only_unmasked_rows_and_treats_a_gap_as_masked`.
  - `test_store_round_trips_every_price_exactly` (Decimal equality, trailing zeros included).
  - `test_store_is_compact`: 100,000 bars use under 64 bytes per bar, measured with `sys.getsizeof` over the arrays.
  - `test_market_verifies_every_pin_and_refuses_a_tampered_coin_pack`.
  - `test_daily_bars_follow_the_20_of_24_rule_and_skip_masked_hours`.
  - `test_perpetual_eligibility_is_point_in_time`: before the first bar → False; a 169-hour gap → False; an incomplete funding month → False; otherwise True.
  - `test_funding_events_fall_in_their_hour_in_time_order`.
  - `test_window_runs_from_the_first_universe_month_to_end_month`.
  - `test_reading_far_beyond_2024_never_calls_the_2024_guard` (spy pattern from `tests/test_v4_data_bars.py`).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** `daily_bars` takes `Kline`, so the adapter is `Kline(open_ms, open, high, low, close, Decimal(0), Decimal(0), Decimal(0))`; the engine needs prices only.
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: compact market view of the packs`.

### Task 3: Signals

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/signals.py`
- Test: `tests/test_v4_engine_signals.py`

**Interfaces:**
- Consumes: `Lookbacks`, `Kline` daily bars, `strategy.indicators.sma` (optional).
- Produces:
  - `SignalReading`, a frozen dataclass:
    - `day_ms`, `close`;
    - `sma_fast`, `sma_slow`, `ema_fast`, `ema_slow`;
    - `donchian: int | None`;
    - `sma_trend`, `sma_trend_lagged`;
    - `high_recent`, `high_prior`, `low_recent`, `low_prior`;
    - `fast`, `medium`, `slow`: each `Literal[1, -1] | None`, where `None` is warming up or a tie;
    - `downtrend: bool | None`;
    - `L: Decimal`, `S: Decimal`, `s: Decimal`, `s_long_only: Decimal`.

    The Decimal fields are `| None` while warming up.
  - `CoinSignals(lookbacks: Lookbacks)` with `update(bar: Kline) -> SignalReading`. Bars must be strictly increasing UTC days, and a missing day is simply not passed.

Rules, each pinned by a test (spec "Signals"):
- Every window is the last n available bars.
- An EMA starts at bar n as the simple mean of the first n closes, then follows `a x close + (1 - a) x previous` with `a = 2/(n+1)`.
- Donchian is V3's R3 state machine with the arm's entry and exit lookbacks. "Prior n" means the n bars ending the bar before. It starts flat and needs `entry + 1` bars. The rule text is V3 spec §4's R3 row, and the reference is `trend/signals.py:83-95`.
- **Fast:** up if `close > SMA(fast)`, down if below.
- **Medium:** the mean of the EMA vote (+1, -1, or 0 when equal) and the Donchian state. Up if greater than 0, down if less than 0. It is warm only when both votes are.
- **Slow:** as fast, with `slow`.
- **Downtrend:** all four of
  - `close < SMA(trend_sma)`;
  - `SMA(trend_sma)` below its value `trend_slope` bars earlier;
  - the high of the last `trend_window` bars below the high of the `trend_window` bars before them;
  - the low of the last `trend_window` bars below the low of the `trend_window` bars before them.
- **S** = 0 unless medium is down and the downtrend is confirmed. Otherwise `(0.5 if fast down else 0.25) x (2 if slow down else 1)`.
- **L** = the count of speeds up divided by 3.
- **s** = `-S` if S > 0, else L. `s_long_only` = L.

- [ ] **Step 1: Write the failing tests**
  - `test_ema_seeds_with_the_simple_mean_then_recurses`.
  - `test_donchian_enters_exits_and_reverses_as_v3_r3`.
  - `test_a_missing_day_adds_no_observation_and_resets_nothing`.
  - `test_short_fraction_values_0_25_0_5_and_1`.
  - `test_a_fast_rally_halves_a_short_and_medium_up_closes_it`.
  - `test_long_fraction_counts_speeds_up`.
  - `test_warming_speeds_count_as_neither`.
  - `test_neighbour_lookbacks_change_only_the_windows`.
  - `test_matches_v3_on_pre_2025_bars`: on a seeded random walk of 400 daily bars in 2021, with main lookbacks, `ema_fast`, `ema_slow` and `donchian` equal V3's `SignalPoint.ema21`, `.ema55` and `.rule("R3")`, and `sma_trend` equals `.sma50` bar by bar (`trend.signals.signal_series` as the oracle).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** Keep deques or running sums so that `update` is O(window), never O(history). V3's per-bar list rebuild is O(n²) and must not be copied.
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: three speeds, downtrend and the net signal`.

### Task 4: Sizing and the band

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/sizing.py`
- Test: `tests/test_v4_engine_sizing.py`

**Interfaces:**
- Consumes: Task 1 constants, `trend.sizing.DailyReturn`, `Kline`.
- Produces:
  - `daily_returns(bars: Sequence[Kline]) -> tuple[DailyReturn, ...]`, under Ruling R4.
  - `CoinSizing(sigma: Decimal | None, raw: Decimal, full: Decimal, scaled: Decimal, after_coin_cap: Decimal, after_total_cap: Decimal)`, frozen.
  - `SizingResult(weights: Mapping[str, Decimal], coins: Mapping[str, CoinSizing], scale: Decimal | None, common_days: int)`, frozen.
  - `size_book(signals: Mapping[str, Decimal], returns: Mapping[str, Sequence[DailyReturn]], day_ms: int, *, vol_target: Decimal, coin_cap: Decimal = COIN_CAP, total_cap: Decimal = TOTAL_CAP) -> SizingResult`.
  - `band_trades(target: Decimal, current: Decimal) -> bool`.

Rules (spec "Sizing", steps 1-3, and the band):
- sigma is the sample standard deviation (n-1) of the last 60 returns at or before `day_ms`, times √365. A coin with fewer than 60 returns, or sigma 0, gets 0.
- `full = sign(s) / sigma`, and `raw = s / sigma`.
- The common days are the calendar days among the last 60 ending at `day_ms` on which every coin with a nonzero `full` has a return. With fewer than 40, all weights are 0.
- Sigma is the sample covariance over the common days, times 365.
- `c = vol_target / sqrt(full' Sigma full)`. If the quadratic form is 0, all weights are 0.
- `weight = c x raw`, then each |weight| is capped at `coin_cap`, then the book is scaled proportionally to `sum |w| <= total_cap`.
- The band trades when the target's sign differs from the current's, when the target is 0 with a position open, or when `|target - current| > max(0.25 |target|, 0.01)`.

- [ ] **Step 1: Write the failing tests**
  - `test_returns_never_bridge_a_missing_day`.
  - `test_short_history_or_zero_sigma_gets_zero`.
  - `test_fewer_than_40_common_days_flattens_the_book`.
  - `test_agreement_sets_the_size`: with two coins at s=1 and s=1/3, the second's weight is exactly a third of its full-strength weight (v4-d12).
  - `test_full_strength_book_hits_the_vol_target_before_caps`.
  - `test_coin_cap_then_total_cap`.
  - `test_band_cases`: sign change, zero target, inside the band, outside the band, and the 0.01 floor.
  - `test_matches_v3_size_portfolio_when_every_signal_is_full`: on pre-2025 random-walk data with every |s| = 1, `size_book(..., vol_target=0.40, coin_cap=0.20, total_cap=1.60)` equals `trend.sizing.size_portfolio(..., multiple=2)` coin by coin (V3 m = 2).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** under `CONTEXT`.
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: volatility sizing from the full-strength book, caps and band`.

### Task 5: Pending decisions

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/pending.py`
- Test: `tests/test_v4_engine_pending.py`

**Interfaces:**
- Produces:
  - `Pending(coin: str, decision_ms: int, target: Decimal)` and `Exit(coin: str, venue: Literal["spot", "futures"], reason: str, after_ms: int)`.
  - `PendingBook` with:
    - `decide(decision_ms: int, targets: Mapping[str, Decimal]) -> tuple[Pending, ...]`. It records new targets made at a 00:00 decision and returns the pending orders they replaced (cancelled). A coin absent from `targets` (a no-bar coin) keeps its pending order.
    - `due(hour_ms: int, ready: Callable[[str], bool]) -> tuple[Pending, ...]`. These are the orders that may fill at `hour_ms`: `hour_ms >= decision_ms + 3_600_000` and `ready(coin)` is True. Once returned, an order is removed.
    - `cancel(coin: str) -> Pending | None`.
    - `schedule_exit(exit: Exit)`.
    - `due_exits(hour_ms: int, has_bar: Callable[[str, str], bool]) -> tuple[Exit, ...]`. Each leg exits on its own venue's first bar at or after `after_ms`.
    - `schedule_replacement(coin: str, after_ms: int)` and `due_replacements(hour_ms, has_spot_bar) -> tuple[str, ...]`. A replacement spot buy waits for its futures close and is superseded by a newer target from a 00:00 decision (spec "Sizing", the last paragraph).

Copy the semantics of V3's `PendingDecisions` (`trend/pending.py`), minus the walk-forward pick logic, and port its three tests.

- [ ] **Step 1: Write the failing tests**
  - `test_midnight_decision_replaces_a_deferred_order` (Review Focus 3).
  - `test_no_bar_day_keeps_the_pending_order`.
  - `test_each_coin_waits_for_its_own_first_ready_hour`.
  - `test_a_new_decision_cannot_fill_in_its_own_hour`.
  - `test_mandatory_exit_legs_close_independently_per_venue`.
  - `test_replacement_buy_waits_for_the_futures_close_and_a_newer_target_cancels_it`.
  - `test_a_no_bar_midnight_keeps_the_replacement_pending`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: pending decisions, mandatory exits and replacement buys`.

### Task 6: The ledger

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/ledger.py`
- Test: `tests/test_v4_engine_ledger.py`

**Interfaces:**
- Consumes: `numbers`.
- Produces:
  - `Venue = Literal["spot", "futures"]`.
  - `Fill(timestamp_ms: int, venue: Venue, symbol: str, side: int, quantity: Decimal, price: Decimal, fee: Decimal, reason: str)`.
  - `Mark(equity: Decimal, cash: Decimal, spot_value: Decimal, futures_upnl: Decimal, backing: Decimal, maintenance: Decimal, ratio: Decimal | None, gross_notional: Decimal, gross: Decimal | None)`. A `None` ratio means no futures position, which the engine treats as +infinity. A `None` gross means equity at or below zero.
  - `Audit(wallet_residual: Decimal, quantity_residuals: Mapping[tuple[Venue, str], Decimal], equity_residual: Decimal)`.
  - `Ledger(initial_cash: Decimal)` with:
    - `fill(f: Fill) -> Decimal`, which returns the realised P&L.
    - `funding(timestamp_ms: int, perpetual: str, amount: Decimal) -> None`.
    - `quantity(venue, symbol) -> Decimal` (signed for futures, non-negative for spot).
    - `mark(prices: Mapping[tuple[Venue, str], Decimal]) -> Mark`.
    - `audit(prices) -> Audit`.
    - `cash -> Decimal`.

Rules:
- Positions are FIFO lots keyed by `(venue, symbol)` (Review Focus 1).
- **Spot:** a buy spends `qty x price + fee`; a sell adds `qty x price - fee` and may not exceed the held quantity.
- **Futures:** a fill moves cash by its realised P&L minus its fee (Ruling R2). A fill that would cross zero is refused, so the caller splits a flip.
- **Funding:** `amount` is added to cash. The caller computes `-quantity x rate x price` (spec "Shorts on futures").
- `backing = cash + futures_upnl`, `maintenance = 0.01 x sum |qty x mark|` over futures, and `ratio = backing / maintenance` when maintenance > 0.
- `gross_notional = sum |spot qty x mark| + sum |futures qty x mark|`, and `gross = gross_notional / equity`.
- **Audit:**
  - `wallet_residual = cash - (initial - spot buys + spot sells - fees + realised futures P&L + funding)`;
  - `quantity_residuals` per position = held - (sum of buys - sum of sells);
  - `equity_residual = equity - (initial + realised + unrealised - fees + funding)`.

  The wallet and quantity residuals must be exactly 0, and the equity residual must be at most `1e-18` in absolute value.

- [ ] **Step 1: Write the failing tests**
  - `test_one_coin_holds_a_spot_and_a_futures_leg_under_one_name` (Review Focus 1).
  - `test_spot_buy_and_sell_move_cash_by_notional_and_fee`.
  - `test_futures_open_reduce_close_realise_fifo_pnl`.
  - `test_a_futures_fill_crossing_zero_is_refused`.
  - `test_funding_moves_cash_only`.
  - `test_backing_excludes_spot_and_ratio_is_none_without_futures`.
  - `test_gross_counts_spot_and_futures_notional`.
  - `test_audit_identities_hold_exactly_over_a_random_fill_sequence` (seeded, 500 fills).
  - `test_matches_v31_funding_cashflow_sign_convention`: the caller-side formula equals `combined.execution.funding_cashflow` for a long and a short.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** with `Fraction` internally and exact `Decimal` at the boundary.
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: shared spot and futures ledger keyed by venue and symbol`.

### Task 7: Leg orders

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/orders.py`
- Test: `tests/test_v4_engine_orders.py`

**Interfaces:**
- Consumes: `VenueRules`, `floor_quantity`, `Costs`.
- Produces:
  - `Order(side: int, quantity: Decimal, reduce_only: bool)`.
  - `LegPlan(orders: tuple[Order, ...], refusal: str | None, dust: Decimal)`.
  - `plan_leg(venue: Venue, held: Decimal, target: Decimal, price: Decimal, rules: VenueRules) -> LegPlan`. Quantities are in venue units, and `price` is the unslipped open.
  - `fill_price(open_price: Decimal, side: int, costs: Costs) -> Decimal`.
  - `fee(quantity: Decimal, price: Decimal, costs: Costs) -> Decimal`.

Rules (spec "Exchange filters" and "Reductions are never refused for size"):
- Round toward zero to the step.
- An opening or increasing order below `min_qty` or `min_notional` (at the unslipped open) is not made, and `refusal` names which.
- An order above `max_qty` is split into the fewest orders.
- **Futures reductions** are reduce-only and ignore `min_notional`. One below `min_qty` is raised to it, or to the whole position. One that would leave less than `min_qty` closes the whole position.
- **Spot sales:** a remainder below `min_qty` or `min_notional` is not sold and is returned as `dust`.
- A flip is a closing order then an opening order, two orders.
- `fill_price = open x (1 + side x slippage)` (Ruling R3).

- [ ] **Step 1: Write the failing tests**
  - `test_rounds_toward_zero_to_the_step`.
  - `test_opening_order_refused_below_min_qty_or_notional_with_reason`.
  - `test_large_order_splits_into_the_fewest_orders`.
  - `test_futures_reduction_raised_to_min_qty_or_whole_and_ignores_notional`.
  - `test_reduction_leaving_less_than_min_qty_closes_the_whole_position`.
  - `test_spot_remainder_below_filters_becomes_dust`.
  - `test_flip_is_close_then_open`.
  - `test_fill_price_and_fee_follow_the_cost_profile`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: leg orders with filters, splits, reduce-only and dust`.

### Task 8: The spot-first allocation and the cash clip

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/allocation.py`
- Test: `tests/test_v4_engine_allocation.py`

**Interfaces:**
- Produces:
  - `CoinState(coin: str, target_notional: Decimal, spot_notional: Decimal, dust_notional: Decimal, futures_notional: Decimal, eligible: bool, keeps_legs: bool, exiting_legs: frozenset[Venue])`.
  - `LegTargets(spot: Decimal, futures: Decimal)`.
  - `allocate(equity: Decimal, coins: Sequence[CoinState]) -> Mapping[str, LegTargets]`, in notional.
  - `clip_increases(increases: Sequence[tuple[str, Venue, Decimal]], cash: Decimal, open_initial_margin: Decimal, backing: Decimal, maintenance: Decimal, costs: Mapping[Venue, Costs]) -> tuple[tuple[str, Venue, Decimal], ...]`.

Rules (spec "Longs on spot first, coin by coin", taken literally):
- **Fixed holdings:**
  - coins with `keeps_legs` (deferred, no-bar, band-kept) keep their legs, and sum into S_K (spot, dust excluded) and F_K (|futures|);
  - a leg in `exiting_legs` counts as 0;
  - D is every coin's `dust_notional`.
- `residual = target - dust`. A spot-only coin's negative residual becomes 0.
- E holds positive residuals with `eligible`, and N holds the spot-only positive residuals.
- `G_E`, `G_N` and `G_L = G_E + G_N` are their sums, and `G_S` sums the |negative residuals|.
- `R = 0.98 x equity - S_K - D - F_K / 3`.
- `s_max = max(0, min(G_L, 1.5 x (R - (G_L + G_S) / 3)))`.
- If `s_max >= G_N`: N is fully on spot, E gets `s_max - G_N` of spot pro rata, and the rest is on futures.
- Otherwise E is fully on futures and N is scaled by `k = max(0, R - (G_E + G_S)/3) / G_N`, capped at 1.
- **Cash clip:**
  - increases are taken in the order given (alphabetical, spot before futures within a coin);
  - free cash = `min(cash - open_initial_margin, backing - 4 x maintenance)`, updated after each increase;
  - a spot buy needs notional plus fee, and a futures increase needs notional/3 plus fee;
  - an increase is cut to what free cash pays for.

  The caller rounds the result to the step and skips any increase that is now below the filters.

- [ ] **Step 1: Write the failing tests**, each with hand-computed numbers from the spec's formulas:
  - `test_room_formula_counts_fixed_holdings_dust_and_futures_margin`.
  - `test_spot_only_coins_fill_spot_first_then_eligible_coins_share_the_rest`.
  - `test_when_spot_capacity_is_short_eligible_coins_go_to_futures_and_spot_only_scale`.
  - `test_targets_are_net_of_dust_and_a_short_beside_dust_shorts_more`.
  - `test_exiting_legs_count_as_zero`.
  - `test_cash_clip_never_takes_the_margin_ratio_below_4`.
  - `test_cash_clip_order_is_alphabetical_spot_before_futures`.
  - `test_a_multiplier_perpetual_is_sized_in_contracts_from_notional` (Review Focus 2: the caller converts `futures notional / contract price`; tested here through a helper `to_venue_quantity(notional, price) -> Decimal`).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** as pure functions under `CONTEXT`.
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: spot-first allocation and the cash clip`.

### Task 9: Safety

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/safety.py`
- Test: `tests/test_v4_engine_safety.py`

**Interfaces:**
- Consumes: `Mark`, `Ledger`, Task 1 constants.
- Produces:
  - `liquidated(mark: Mark) -> bool`, which is True when `maintenance > 0 and backing <= maintenance`.
  - `adverse_prices(held: Mapping[tuple[Venue, str], Decimal], bars: Mapping[tuple[Venue, str], HourBar | None], carried: Mapping[tuple[Venue, str], Decimal]) -> Mapping[tuple[Venue, str], Decimal]`. A long takes the low and a short the high; a masked leg takes its carried mark.
  - `cushion_factor(backing: Decimal, untradable_maintenance: Decimal, tradable_maintenance: Decimal) -> Decimal | None`. It returns `k`, or `None` when no futures position can trade. A k at or below 0 means close every tradable futures position.
  - `ceiling_factor(equity: Decimal, untradable_gross: Decimal, tradable_gross: Decimal) -> Decimal | None`, which returns `k'`.
  - `DeadMarkets` with:
    - `observe(hour_ms: int, venue: Venue, symbol: str, has_bar: bool) -> None`;
    - `due(hour_ms: int) -> tuple[tuple[Venue, str], ...]`, the legs whose venue has had no bar for 168 consecutive hours before `hour_ms`.
  - `penalised_price(last_close: Decimal, side_held: int) -> Decimal`, which gives `last_close x (1 - 0.10)` for a long and `x (1 + 0.10)` for a short.
  - `funding_exit_hour(market: Market, coin: str, month: str) -> int | Literal["synthetic"]`. It is the 01:00 open of the previous month's last day if the perpetual has a bar there, else the next perpetual bar before the month starts. If none exists, it returns `"synthetic"`, a close at 00:00 of the month's first day (spec "Data").

Rules (spec "Safety"):
- `k = (backing / 4 - untradable maintenance) / tradable maintenance`.
- `k' = (2.7 x equity - untradable gross) / tradable gross`.
- When the limit cannot be restored, the outcome is `limit_unrestorable`, with reason `ceiling`, `margin_cushion` or `required_fill`.
- Synthetic closes due at one instant form one batch. Liquidation is checked once at all their penalised prices together, then they are booked together. Equity at or below zero after the batch means liquidated.

- [ ] **Step 1: Write the failing tests**
  - `test_liquidation_at_backing_at_or_below_maintenance`.
  - `test_adverse_extremes_all_at_once_masked_legs_at_carried_marks`.
  - `test_cushion_factor_restores_ratio_4_before_fees`.
  - `test_cushion_with_no_tradable_futures_is_unrestorable`.
  - `test_ceiling_factor_cuts_to_2_7_and_counts_untradable_gross`.
  - `test_dead_market_after_168_hours_per_venue`.
  - `test_penalised_price_is_10_percent_against_the_holder`.
  - `test_funding_exit_hour_falls_back_to_a_synthetic_midnight_close`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: margin cushion, 3x ceiling, liquidation and dead markets`.

### Task 10: Lifecycles

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/lifecycle.py`
- Test: `tests/test_v4_engine_lifecycle.py`

**Interfaces:**
- Produces:
  - `Lifecycle(coin, side, entry_ms, exit_ms, exit_reason, gross_pnl, fees, funding, best_unrealised, given_back, holding_hours, censored: bool, venues: Mapping[Venue, Mapping[str, Decimal]])`.
  - `Lifecycles` with:
    - `after_batch(hour_ms, coin, signed_notional, spot_qty, futures_qty, dust_only: bool, fills, reason) -> Lifecycle | None`;
    - `funding(coin, amount)`;
    - `mark(hour_ms, coin, unrealised)`;
    - `censor(hour_ms, reason) -> tuple[Lifecycle, ...]`.

Rules (spec "Records", the lifecycle bullet):
- A lifecycle is per coin and side. It opens when the signed position over both venues leaves zero, and ends when that position changes sign or both legs are flat.
- Dust keeps a lifecycle open until it is sold or censored, and so does a futures leg offsetting dust.
- Tests run after a whole batch of fills, never between them.
- Venue transfers stay inside the lifecycle.
- Best unrealised profit and give-back are measured on hourly open marks (Ruling R6).
- Exit reasons: `signal`, `universe exit`, `funding-month exit`, `margin cut`, `ceiling cut`, `delisting`, `window end`, `window end (dust)`, `liquidation`, `limit_unrestorable`.

- [ ] **Step 1: Write the failing tests**
  - `test_full_spot_to_futures_move_stays_one_lifecycle`.
  - `test_sign_change_ends_one_and_opens_the_other`.
  - `test_dust_keeps_the_lifecycle_open_until_sold`.
  - `test_best_unrealised_and_given_back_on_open_marks`.
  - `test_censoring_at_window_end_and_at_a_stop`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: per coin and side lifecycles across venues`.

### Task 11: Records and the bundle

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/records.py`
- Test: `tests/test_v4_engine_records.py`

**Interfaces:**
- Consumes: `combined.artifacts._canonical` and `_digest`.
- Produces:
  - `RECORD_SCHEMA = "v4-cell-1"` and `RECEIPT_SCHEMA = "v4-receipt-1"`.
  - `RecordWriter(path: Path)`, which creates `records.jsonl` exclusively, with:
    - `append(kind: str, record: Mapping[str, object]) -> str`. It returns the record's hash.
    - `close() -> Receipt`.
  - `Receipt(records_sha256: str, record_count: int, final_chain_hash: str, kinds: Mapping[str, int])`.
  - `read_records(path: Path, receipt: Receipt) -> Iterator[tuple[str, dict]]`, which verifies the chain and the receipt.

Rules (spec "Records", "Integrity"):
- Every record is one line, `{"kind", "record", "schema", "previous_hash", "hash"}`. The hash is `sha256(canonical({"kind", "record", "schema", "previous_hash"}))`, the seed is `"0" x 64`, and every kind goes in the one chain, so all records are chained.
- **Kinds:**
  - `daily_coin`: each speed's values and vote, the downtrend parts, L, S and s, sigma, raw, every sizing step, the band result, the split, and the order or the reason none was made;
  - `fill`;
  - `funding`;
  - `lifecycle`;
  - `monthly`: the universe record and the funding-month validation;
  - `hourly`: equity, gross, margin ratio and the open mark with its completeness flag;
  - `event`: deferrals, refusals, cuts and synthetic closes;
  - `outcome`.
- Values are exact JSON (Decimals as `str`), and floats are refused, as in the packs.

- [ ] **Step 1: Write the failing tests**
  - `test_every_record_is_chained_and_the_receipt_binds_the_file`.
  - `test_a_tampered_line_breaks_the_chain`.
  - `test_floats_are_refused`.
  - `test_existing_records_file_is_refused`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: hash-chained records and the receipt`.

### Task 12: The hour loop for the V4 arms

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/run.py`
- Test: `tests/test_v4_engine_run.py`

**Interfaces:**
- Consumes: every task above.
- Produces:
  - `CellResult(outcome: str, reason: str | None, stop_ms: int | None, open_marks: tuple[tuple[int, Decimal, bool], ...], final_equity: Decimal, equity_2025: Decimal | None, final_after_close: Decimal | None, audit: Audit, receipt: Receipt)`.
  - `run_v4_cell(market: Market, cell: CellSpec, out_dir: Path) -> CellResult`.

The hour loop, for every hour from `window_start_ms` to `window_end_ms`, in exactly the spec's order of events:
1. The synthetic closes due at this instant (dead markets, synthetic funding-month closes), as one batch.
2. The open mark (recorded with its completeness flag), then the pre-fill liquidation check.
3. At 00:00, before the fills: on the 1st, the month's universe, plus a `monthly` record with the universe and each perpetual's funding-month validation. Then the decision for each coin in the universe or held:
   - signals from completed daily bars;
   - sizing;
   - targets, which are 0 for a universe exit;
   - a coin without an eligible perpetual at the decision (`Market.perpetual_eligible`) uses `max(s, 0)`, because it is spot-only and long-only;
   - the funding-month exit schedule for the next month;
   - the no-bar rule: a coin with no daily bar for the day just closed keeps its signal and takes no new target.

   A universe exit and a funding-month exit override the no-bar rule and cancel any pending order of the coin (`PendingBook.cancel`, then `schedule_exit`). Then `PendingBook.decide`, and a `daily_coin` record per coin.
4. The fills due this hour (`due`, `due_exits`, `due_replacements`). For each coin, the band test runs at this hour's opens. Deferrals are decided first, then the allocation, then the leg orders. Reductions go first, then the clipped increases, all alphabetical. Then the lifecycle `after_batch`.
5. The post-fill mark: liquidation check, then the cushion check and cut, then the ceiling check and cut. Each cut fills at this open and is followed by a new mark.
6. Each funding event in time order, each followed by a mark, the liquidation check, the cushion check and the ceiling check.
7. The liquidation check at the adverse extremes.
8. The audit at the end of the hour. A failure stops the cell with `accounting_failure`.

At `window_end_ms` (the last hour), every position closes at that hour's close (the carried mark if it has no bar), with costs. Unsellable dust stays and is censored. A liquidation or an unrestorable limit stops the cell as spec "Safety" says. An exception becomes `engine_error`.

- [ ] **Step 1: Write the failing tests**, on small synthetic worlds from `tests/v4_synthetic.py`:
  - `test_a_steady_uptrend_goes_long_on_spot_first` (one coin, no perpetual needed).
  - `test_a_confirmed_downtrend_shorts_on_futures`.
  - `test_leaving_the_top_10_exits_at_the_next_open`.
  - `test_an_empty_universe_month_holds_cash_and_trades_nothing` (Review Focus 4).
  - `test_funding_is_charged_on_the_held_quantity_at_the_open`.
  - `test_a_crash_at_3x_cuts_or_liquidates_as_specified`.
  - `test_a_perpetual_that_dies_is_closed_after_168_hours_with_the_penalty`.
  - `test_an_incomplete_funding_month_moves_the_long_to_spot_before_it_starts`.
  - `test_window_end_closes_everything_with_costs_and_censors_dust`.
  - `test_the_audit_holds_every_hour` (equity residual ≤ 1e-18 throughout).
  - `test_long_only_and_vol_variants_change_only_their_parameters`.
  - `test_the_engine_never_calls_a_2024_guard_on_2026_data`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** `run.py` orchestrates and holds no rule of its own; every rule lives in the modules above. Write every record through `RecordWriter`.
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: the hour loop for the V4 arms`.

### Task 13: The hold arms

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/hold.py`
- Test: `tests/test_v4_engine_hold.py`

**Interfaces:**
- Produces `run_hold_cell(market: Market, cell: CellSpec, out_dir: Path) -> CellResult`.

Rules (spec "Versions in the run", the hold comparisons):
- Each hold arm is a spot-only account.
- `hold_universe` rebalances at each month's first 00:00 decision, filling at 01:00:
  - each of n coins gets `0.99 x equity / n`, from equity at that open before the fills;
  - a coin that left gets 0, and an empty month gives 0 for all;
  - there is no band;
  - sells go before buys, each alphabetical;
  - a buy is cut to the cash available, fee included, and rounded down;
  - an order below the filters is skipped and recorded, and an unsellable remainder is dust.
- `hold_btc` buys BTCUSDT at the window's first fill hour with `0.99 x equity`, under the same cash rule.
- Masked fill hours defer the order, and the dead-market rule and the window-end close apply.
- There is no funding, no ceiling and no liquidation check.

- [ ] **Step 1: Write the failing tests**
  - `test_hold_universe_targets_0_99_equity_over_n`.
  - `test_buys_are_cut_to_cash_fee_included`.
  - `test_empty_month_sells_what_it_can`.
  - `test_hold_btc_buys_once_and_holds_to_the_window_end`.
  - `test_hold_arms_write_the_same_record_and_summary_shapes`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement**, reusing the ledger, orders, records and dead-market code.
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: the hold comparisons`.

### Task 14: The summary, the page and self-verification

**Files:**
- Create: `src/crypto_grid_bot/v4/engine/summary.py`
- Test: `tests/test_v4_engine_summary.py`

**Interfaces:**
- Consumes: `CellResult`, the records, `trend.metrics`.
- Produces:
  - `SUMMARY_FORMAT = "v4-summary-1"`.
  - `build_summary(cell: CellSpec, result: CellResult, records_path: Path) -> dict`.
  - `verify_summary(summary: dict, records_path: Path, receipt: Receipt) -> None`, which rebuilds from the records and requires equality.
  - `render_page(summary: dict) -> str`.
  - `write_cell_outputs(out_dir: Path, summary: dict, page: str) -> str`, which writes `summary.json` and `report.html` exclusively and returns the summary's SHA-256.

`summary.json` fields (spec "Reports"):
- `format`, `cell`, `outcome`, plus `reason` and `stop_ms` where they apply;
- `initial_equity`, `final_equity`, `equity_2025` (the open mark at 2025-01-01 00:00, or null), `final_after_close` (null for an early stop);
- `max_drawdown` and `compounded_return`, on the hourly open marks plus the final equity;
- `open_marks`: rows `[open_ms, equity, complete]` for every hour;
- `eras`: the window start to 2020-12-31, 2021-01-01 to 2024-12-31, and 2025-01-01 to the end;
- `years`;
- `liquidations`, `accounting_residual` and `receipt_sha256`.

A failure summary (`accounting_failure`, `engine_error`) holds only `format`, `cell`, `outcome` and the failure's details.

The page is self-contained HTML with no script. It holds the outcome, the headline numbers, the eras, the years and an equity sparkline as inline SVG, and states that a pass means "promising", not "proven".

- [ ] **Step 1: Write the failing tests**
  - `test_full_summary_has_every_field_with_exact_decimals`.
  - `test_a_liquidated_cell_writes_a_full_summary_to_the_stop` (Review Focus 5: `equity_2025` null if the stop was earlier, `final_after_close` null).
  - `test_failure_summaries_hold_the_failure_only`.
  - `test_verify_summary_rebuilds_and_detects_a_changed_number`.
  - `test_open_marks_carry_the_completeness_flag`.
  - `test_page_has_no_script_and_states_promising_not_proven`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: summary, page and self-verification`.

### Task 15: The one-cell CLI and the synthetic world

**Files:**
- Create: `scripts/v4_cell.py`
- Test: `tests/test_v4_cell_cli.py`

**Interfaces:**
- Produces `main(argv: Sequence[str] | None = None) -> int`, with `run --data D --arm A --capital {1000,10000} --costs {1,2} --out O`.
  - It writes `O/<cell_id>/`: `records.jsonl`, `receipt.json`, `summary.json` and `report.html`.
  - It runs `verify_summary` before finishing, and prints counts only (cell id, outcome, records, hours).
  - It returns 0 whenever a summary was written, whatever the outcome. It returns 1 only when nothing could be written.

- [ ] **Step 1: Write the failing tests**
  - `test_cli_runs_every_arm_on_the_synthetic_world`. The world has three coins over 26 months, with:
    - a delisting;
    - a crash that tests the 3x ceiling;
    - a coin leaving the top 10;
    - a multiplier perpetual;
    - a masked day;
    - an incomplete funding month.

    It asserts a written, verified summary for each of the eight arms at one capital and cost level.
  - `test_cli_output_prints_no_prices`.
  - `test_cli_refuses_a_data_dir_with_a_bad_pin`.
  - `test_cli_writes_a_failure_summary_on_engine_error`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 engine: the one-cell CLI on a synthetic world`.

- [ ] **Step 5: Push and open the PR.** CI runs the full suite. The PR follows the standing review bar: a claim, Bob, Codex, CI and the automated review. Step 4 (the cells matrix, `v3_as_built`, the verdict step, the synthetic rehearsal and the timing run) builds on this.
