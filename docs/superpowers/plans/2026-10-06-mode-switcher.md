# Mode Switcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build spec v2's spot mode switcher. Each pair, every hour, chooses Grid (v1's grid with F's block), Uptrend (one long position with a trailing stop) or Cash, under v1's unchanged risk layer, and the v2 scorer judges it.

**Architecture:**
- **The decision logic is pure:** gap-aware indicators, a three-timeframe perception and the mode selector live in `strategy/` and are tested without the simulator.
- **The uptrend engine runs inside the paper simulator behind a new policy flag,** `mode_switch`. It holds runtime-only account state, like variants E and F.
- **The replay feeds a perception snapshot on each frame.** A new scorer module applies spec v2 §8.

**Tech Stack:** Python 3.12, `decimal` (`localcontext`, precision 50), pytest, ruff, mypy, bandit. No new dependencies.

**Spec:** `docs/EXPERIMENT_SPEC_V2.md` (PR #174). This plan covers its §9 steps 3–6. Step 2, the long-window data, has its own plan, and the evaluation runs need it.

## Global Constraints

- **Paper-only.** No live trading, keys or network calls in any new code.
- **V0 and every v1 variant stay byte-identical** (spec v2 §9). All new behaviour sits behind `SimulationPolicy.mode_switch`:
  - `Frame.perception` defaults to `None` and is dropped from `Frame.payload()` when `None`;
  - the new `Account` fields are runtime-only and never saved (`to_dict`).
  - After each task, the controller's `scratchpad/runall.sh` (Claude's session scratchpad, not the repository) reproduces main's V0, A, B and C SHA-256s on its three synthetic datasets, `sb-up`, `sb-down` and `sb-nod` (Task 5, step 4). The `--structure` runs are identical apart from provenance.
- **Replay-only.** `PaperSimulator.process` refuses a paper account whose policy has `mode_switch`, as it refuses E and F.
- **Exact thresholds** (spec v2 §3–§5):

  | Where | Values |
  | --- | --- |
  | Periods | 14 (RSI, ATR, ADX, DI); SMA 20 and 50; Bollinger 20 at 2 population σ; width median over 720 widths |
  | Trend states | ADX ≥ 20 for Up and Down; < 20 for Range |
  | Grid | RSI 35 ≤ r ≤ 65; 1h ADX < 20; width ≤ median; 4 consecutive RANGE decisions |
  | Uptrend | daily RSI < 75 |
  | Uptrend engine | risk 0.04; cap 0.60; stop 3 × daily ATR; re-entry pause 86 400 s after a stop-out only |

- **Point-in-time.** A bar of length L that opens at `o` is visible only at times `t ≥ o + L`. At time `t`, the bar that should have closed last opens at `t // L * L − L`.
- **Gaps** (spec v2 §3). Indicators run over the bars that exist, skipping missing and masked bars without resetting. A timeframe is unavailable when its should-have-closed-last bar is absent, or when a needed indicator lacks its minimum bars.
- **Money:** the `Decimal` helpers of `simulation/models.py` (`floor_step`, `nonnegative`), and the fees from `MarketRules` (maker 0, taker 0.0009 in the evaluation).
- **Checks before every commit:** `ruff check .`, `ruff format --check .`, `mypy`, `bandit -q -r src scripts`, `python scripts/check_reports.py`, `pytest -q`.

## Review Focus

1. **A masked hour inside a 4h bucket, as the last hour, or inside a day.** The 4h or 1h timeframe is Unavailable, giving Cash, never a stale value. Earlier gaps are skipped, not reset. The day's daily bar stays in use as delivered, since daily bars are never masked (spec v2 §3). Pinned in Task 2, `test_masked_last_bar_is_unavailable_and_older_gaps_are_skipped` and `test_masked_hour_leaves_the_daily_state_in_use`.
2. **A run that ends while holding an uptrend position.** The run stays valid, because the position is held, not an exit owed (spec v2 §6). Pinned in Task 6, `test_run_ending_in_uptrend_is_valid_and_marked_at_exit_value`.
3. **v1's drain meeting the uptrend position.** No grid drain (an eligibility or transient pause), range exit or settlement sells it; only a risk drain does (spec v2 §6). Pinned in Task 5, `test_drain_and_range_exit_leave_the_uptrend_position_alone`.
4. **A hard stop, or a restart, mid-uptrend.** It leaves no ghost uptrend state, and the mode is re-decided at the next hour. Pinned in Task 5, `test_hard_stop_clears_uptrend_and_restart_redecides`.
5. **The daily bar missing at a daily close while holding.** No new bar arrives, so the snapshot keeps the old `d1_open_ms`. Exit 2 still fires at the day boundary (fail closed). This path is defensive: a missing daily bar excludes the pair-window (spec v2 §3), so no included run reaches it. Pinned in Task 5, `test_unavailable_daily_state_triggers_trend_fade_exit`.

---

### Task 1: Gap-aware indicators

**Files:**
- Create: `src/crypto_grid_bot/strategy/indicators.py`
- Test: `tests/test_indicators.py`

**Interfaces:**
- **Produces:**
  - `Bar(open_ms: int, high: Decimal, low: Decimal, close: Decimal)`, a frozen dataclass;
  - `sma(closes: Sequence[Decimal], length: int) -> list[Decimal | None]`;
  - `wilder_rsi(closes: Sequence[Decimal], period: int = 14) -> list[Decimal | None]`, first value at index `period`;
  - `wilder_atr(bars: Sequence[Bar], period: int = 14) -> list[Decimal | None]`, first value at index `period`, seeded with the mean of TR[1..period];
  - `wilder_adx(bars: Sequence[Bar], period: int = 14) -> tuple[list[Decimal | None], list[Decimal | None], list[Decimal | None]]`, which returns `(adx, plus_di, minus_di)`, with DI first at index `period` and ADX first at `2 × period − 1`, the same seeding as `SeriesFeatures._wilder_adx`;
  - `bollinger_width(closes: Sequence[Decimal], length: int = 20, deviations: int = 2) -> list[Decimal | None]`;
  - `rolling_median(values: Sequence[Decimal | None], size: int) -> list[Decimal | None]`, the median of the last `size` non-`None` values, which is the mean of the two middle values for an even count.
- **Contract:** callers pass only the bars that exist, in order, so gaps are skipped by construction. A true range uses the previous element's close.
- **Zero cases** (spec v2 §3): RSI is 50 when the average gain and the average loss are both 0. ±DI are 0 when the smoothed true range is 0, and DX is 0 when +DI + −DI is 0, as in `SeriesFeatures._wilder_adx`.

- [ ] **Step 1: Write the failing tests** with these exact expectations:

```python
def test_sma_values_and_warmup():
    assert sma([D(1), D(2), D(3), D(4), D(5)], 3) == [None, None, D(2), D(3), D(4)]


def test_rsi_first_value_index_and_extremes():
    rising = [D(i) for i in range(1, 17)]
    assert wilder_rsi(rising)[13] is None and wilder_rsi(rising)[14] == D(100)
    alternating = [D(10 + (i % 2)) for i in range(30)]
    rsi = wilder_rsi(alternating)
    assert rsi[14] == D(50)  # the seed: 7 gains and 7 losses of 1
    # The Wilder recursion, not a rolling mean (which would stay at 50):
    assert rsi[15].quantize(D("0.0001")) == D("53.5714")
    assert rsi[29].quantize(D("0.0001")) == D("52.4612")


def test_atr_constant_true_range():
    bars = [Bar(i, D(12), D(10), D(11)) for i in range(20)]
    assert wilder_atr(bars)[13] is None and wilder_atr(bars)[14] == D(2)


def test_adx_first_indices_and_perfect_trend():
    bars = [Bar(i, D(100 + i), D(99 + i), D("99.5") + i) for i in range(40)]
    adx, plus_di, minus_di = wilder_adx(bars)
    assert plus_di[13] is None and plus_di[14] is not None
    assert adx[26] is None and adx[27] == D(100)
    assert minus_di[30] == D(0)


def test_flat_series_zero_cases():
    assert wilder_rsi([D(5)] * 20)[14] == D(50)  # no gains and no losses
    adx, plus_di, minus_di = wilder_adx([Bar(i, D(5), D(5), D(5)) for i in range(40)])
    assert plus_di[14] == D(0) and minus_di[14] == D(0) and adx[27] == D(0)


def test_bollinger_width_zero_on_flat_closes():
    assert bollinger_width([D(5)] * 20)[19] == D(0)


def test_rolling_median_skips_none_and_averages_even_middle():
    assert rolling_median([D(1), None, D(3), D(2), D(4)], 4)[4] == D("2.5")
```

- [ ] **Step 2: Run `pytest tests/test_indicators.py -v`.** Expected: it fails, because `crypto_grid_bot.strategy.indicators` does not exist yet.
- [ ] **Step 3: Implement the functions in `strategy/indicators.py`,** inside `localcontext()` at precision 50. The Bollinger width uses the population standard deviation: (upper − lower) ÷ middle = 2 × deviations × σ ÷ SMA. Return `None` where the middle is 0.
- [ ] **Step 4: Run `pytest tests/test_indicators.py -v`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: gap-aware Wilder indicators for spec v2 perception`.

### Task 2: Perception on three timeframes

**Files:**
- Create: `src/crypto_grid_bot/strategy/perception.py`
- Test: `tests/test_perception.py`

**Interfaces:**
- **Consumes:** Task 1, and `Kline` from `backtest/klines.py`.
- **Produces:**
  - `TrendState(StrEnum)`: `UP`, `DOWN`, `RANGE`, `UNCLEAR`, `UNAVAILABLE`;
  - `four_hour_bars(hourly: Sequence[Kline]) -> list[Bar]`, with buckets at multiples of 4 h UTC, kept only when all four hours exist; high is the max, low is the min, and close is the last hour's close;
  - `trend_state(close, sma20, sma50, adx, plus_di, minus_di) -> TrendState`, where any `None` gives `UNAVAILABLE`, and the spec v2 §3 table follows with strict `>` and `<` and `adx >= 20`;
  - `DailyPoint`, a frozen dataclass: `open_ms: int`, `state: TrendState`, `close: Decimal`, `atr: Decimal | None`, which is one daily bar as it reads at its own close;
  - `Snapshot`, a frozen dataclass with these fields: `h1_available: bool`, `h1_rsi`, `h1_adx`, `h1_width`, `h1_width_median: Decimal | None`, `h4_state: TrendState`, `d1_state: TrendState`, `d1_rsi`, `d1_close`, `d1_atr: Decimal | None`, `d1_open_ms: int | None`, `d1_points: tuple[DailyPoint, ...]` and `d1_index: int | None`. `d1_points` is one tuple, shared by every snapshot, of every daily bar's point, and `d1_index` is the index of the latest one closed at the snapshot's minute. So the uptrend engine can process every close it missed in a gap (spec v2 §5);
  - `Perception(hourly: Sequence[Kline], daily: Sequence[Kline])`, which precomputes every series once, and `Perception.at(minute_ms: int) -> Snapshot`.

- [ ] **Step 1: Write the failing tests:**
  - `test_four_hour_bars_need_all_four_hours`: 8 complete hours give 2 bars with exact high, low and close; dropping hour 5 removes the second bucket.
  - `test_trend_state_boundaries`:
    - ADX exactly `D(20)` with up alignment gives `UP`;
    - `D("19.999")` gives `RANGE`;
    - `close == sma50` with ADX 25 gives `UNCLEAR`;
    - any `None` gives `UNAVAILABLE`, including ADX `D(15)` with `sma50=None`, which is `UNAVAILABLE` and not `RANGE`.
  - `test_bar_visible_only_from_its_close`: with hourly bars opening at 0 h…, `at(3 h)` reads the bar opening at 2 h, and `at(3 h − 1 ms)` reads the bar opening at 1 h. The same holds on 4h (`at(8 h)` reads the bucket at 4 h) and on 1d.
  - `test_masked_last_bar_is_unavailable_and_older_gaps_are_skipped` (Review Focus 1):
    - with hour 10 missing, `at(11 h).h1_available is False`;
    - `at(12 h)` is available, with values equal to a fresh computation over the bars that exist;
    - the 4h bucket containing hour 10 is absent, so `at(12 h).h4_state is TrendState.UNAVAILABLE`.
  - `test_daily_points_read_each_bar_at_its_own_close`: `s.d1_points[s.d1_index]` carries the same state, close and ATR as `s`'s `d1_` fields, and a snapshot two days later still exposes both earlier days' points, each as it read at its own close.
  - `test_masked_hour_leaves_the_daily_state_in_use` (Review Focus 1): with every daily bar present and one hour of the last completed day missing from the hourly bars, `at(next midnight + 1 h)` gives the same `d1_state`, `d1_close` and `d1_atr` as with no hour missing.
- [ ] **Step 2: Run `pytest tests/test_perception.py -v`.** Expected: FAIL, the module does not exist yet.
- [ ] **Step 3: Implement `perception.py`,** using `bisect` on precomputed open times, and point-in-time lookup per the Global Constraints. `h1_available` is True only when the should-have-closed-last hour exists and RSI, ADX, width and median are all non-`None`. 4h trend states use the 4h bars' SMA, ADX and DI. Daily uses the daily klines.
- [ ] **Step 4: Run `pytest tests/test_perception.py tests/test_indicators.py -v`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: three-timeframe perception snapshot for spec v2`.

### Task 3: The mode selector

**Files:**
- Create: `src/crypto_grid_bot/strategy/mode_selector.py`
- Test: `tests/test_mode_selector.py`

**Interfaces:**
- **Consumes:** `Snapshot` and `TrendState` (Task 2), and `MarketRegime` from `crypto_grid_bot.domain`.
- **Produces:**
  - `Mode(StrEnum)`: `GRID`, `UPTREND`, `CASH`;
  - the constants `GRID_RSI_LOW = D(35)`, `GRID_RSI_HIGH = D(65)`, `ADX_RANGE = D(20)`, `UPTREND_RSI_MAX = D(75)`, `RANGE_DECISIONS = 4`, `REENTRY_PAUSE_MS = 86_400_000`;
  - `select_mode(snapshot: Snapshot, regime: MarketRegime, input_quality_ok: bool, range_decisions: int, now_ms: int, stopped_at_ms: int | None) -> Mode`. `range_decisions` counts the consecutive hourly decisions, this one included, whose regime was RANGE; the caller tracks it. `input_quality_ok` is the classifier's `RegimeAssessment.input_quality_ok`. Uptrend needs it True, and needs `d1_rsi` and `d1_atr` available.

- [ ] **Step 1: Write the failing tests,** one assertion per spec v2 §4 boundary, from a base snapshot that satisfies Grid and one that satisfies Uptrend:
  - **Grid's bounds:** `h1_rsi` `D(35)` and `D(65)` give `GRID`; `D("34.99")` and `D("65.01")` give `CASH`.
  - **ADX and width:** `h1_adx` `D(20)` gives `CASH`, and `D("19.99")` gives `GRID`. Width equal to its median gives `GRID`.
  - **The RANGE count:** `range_decisions` 3 gives `CASH`, and 4 gives `GRID`.
  - **Uptrend's RSI:** `d1_rsi` `D(75)` is not `UPTREND`, and `D("74.99")` is `UPTREND`.
  - **The regime:** BEAR and STRESS block `UPTREND`. TRANSITION does not, but `input_quality_ok=False` does.
  - **Daily inputs:** `d1_atr` None blocks `UPTREND`.
  - **The pause:** `stopped_at_ms = now − 86_399_999` blocks `UPTREND`, and `now − 86_400_000` allows it.
  - **Unavailable states:** `h4_state` or `d1_state` `UNAVAILABLE` gives `CASH` from both base snapshots, and `h1_available` False gives `CASH`.
  - **Grid's states:** `h4_state` UNCLEAR and RANGE both allow `GRID`, and UP and DOWN do not. `d1_state` UP, RANGE and UNCLEAR allow `GRID`, and DOWN does not.
- [ ] **Step 2: Run `pytest tests/test_mode_selector.py -v`.** Expected: FAIL, the module does not exist yet.
- [ ] **Step 3: Implement `select_mode`,** checking Uptrend first, then Grid, otherwise Cash, exactly per spec v2 §4.
- [ ] **Step 4: Run `pytest tests/test_mode_selector.py -v`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: spec v2 mode selector with every threshold pinned`.

*Open Tasks 1–3 as one PR (spec §9 steps 3–4) to Codex and Bob.*

### Task 4: Market buy and the uptrend arithmetic

**Files:**
- Modify: `src/crypto_grid_bot/simulation/execution.py`, to add `buy_price` and `market_buy`
- Create: `src/crypto_grid_bot/simulation/uptrend.py`
- Test: `tests/test_uptrend.py`

**Interfaces:**
- **Produces, in `execution.py`:**
  - `buy_price(quote: Quote, rules: MarketRules) -> Decimal`: ask × (1 + slippage), rounded up to the tick, the same rule as `trend_benchmark.buy_price`;
  - `market_buy(account: Account, quote: Quote, rules: MarketRules, *, budget: Decimal) -> Fill | None`. Its quantity is `min(floor_step(ask_size × participation), floor_step(budget ÷ (price × (1 + taker))))`. It returns `None` when the price × quantity is below the minimum notional. The fill is applied with `_apply_fill` under order id `"uptrend/buy/" + quote.event_id` at the taker fee.
- **Produces, in `uptrend.py`:**
  - `RISK_FRACTION = D("0.04")`, `CAPITAL_CAP = D("0.60")`, `ATR_MULTIPLE = D(3)`;
  - `entry_budget(active_capital: Decimal, active_equity: Decimal, price: Decimal, stop: Decimal) -> Decimal | None`, which is `None` when the stop distance `s <= 0`;
  - `initial_stop(close: Decimal, atr: Decimal) -> Decimal`;
  - `trailed_stop(stop: Decimal, highest_close: Decimal, atr: Decimal) -> Decimal`, which is `max(stop, highest_close − 3 × atr)`;
  - `UptrendPosition`, a mutable dataclass: `budget`, `spent`, `quantity`, `stop`, `highest_close: Decimal`, `stop_day_ms: int`, `entered_at: str`, `phase: str`. The phase is one of `"entering"`, `"holding"` and `"exiting"`. `highest_close` starts at `c0`, the last completed daily close before entry, and `stop` at `initial_stop(c0, that day's ATR)` (spec v2 §5).

- [ ] **Step 1: Write the failing tests:**

```python
def test_entry_budget_risk_bound_and_cap():
    assert entry_budget(D(100), D(100), D(100), D(90)) == D(40)  # 0.04*100/0.1
    assert entry_budget(D(100), D(100), D(100), D(99)) == D(60)  # cap 0.60*100
    assert entry_budget(D(100), D(100), D(100), D(100)) is None  # s <= 0


def test_trailed_stop_never_moves_down():
    assert trailed_stop(D(95), D(100), D(2)) == D(95)  # 100-6 = 94 < 95
    assert trailed_stop(D(95), D(110), D(2)) == D(104)


def test_buy_price_matches_trend_benchmark(quote, rules):
    assert execution.buy_price(quote, rules) == trend_benchmark.buy_price(quote, rules)


def test_market_buy_bounds():
    # participation bound, budget bound, minimum notional -> None, fee = taker * notional
    ...  # assert each with a fixture Quote/MarketRules and exact quantities
```

  Write the `...` as three explicit cases with exact quantities. Use `rules.participation = D("0.10")`, `ask_size = D(5)`, `quantity_step = D("0.001")`, and a budget of 40 USDT.
- [ ] **Step 2: Run `pytest tests/test_uptrend.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement both modules.** `trend_benchmark.py` is not modified, which keeps D byte-identical.
- [ ] **Step 4: Run `pytest tests/test_uptrend.py tests/test_trend_benchmark*.py -v`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: uptrend sizing, trailing stop and a market buy`.

### Task 5: The mode switcher inside the paper simulator

**Files:**
- Modify: `src/crypto_grid_bot/simulation/runner.py`:
  - `SimulationPolicy`, `VARIANTS` and `POLICY_FLAGS`;
  - `Frame`;
  - `PaperSimulator._refuse_runtime_variants` and `PaperSimulator._step`, including its range-exit branch;
  - new methods `_decide_mode`, `_uptrend_step` and `uptrend_held`.
- Modify: `src/crypto_grid_bot/simulation/models.py`, for the runtime-only `Account` fields.
- Test: `tests/test_mode_switch_runner.py`

**Interfaces:**
- **Consumes:** Tasks 2–4.
- **Produces:**
  - **`SimulationPolicy.mode_switch: bool = False`:**
    - `__post_init__` requires `flow_block_entry=True` and every other variant flag off, raising `ValueError("spec v2's mode switcher runs with F's block and nothing else")`;
    - `variant` returns `"MS"`, and `VARIANTS` gains `"MS"`.
  - **`Frame.perception: Snapshot | None = None`,** removed in `payload()` when `None`.
  - **`Account` runtime fields,** omitted by `to_dict`:
    - `mode: str = "cash"`;
    - `range_decisions: int = 0`;
    - `decision_hour_ms: int = -1`;
    - `uptrend: UptrendPosition | None = None`;
    - `uptrend_stopped_ms: int | None = None`, set at the observation where exit 1 first triggers;
    - `risk_recovery: bool = False` and `risk_recovery_count: int = 0`. The flag is set when `_risk_action` pauses on PAUSE or REDUCE, and when `_clear_halt` restarts the account. It is cleared after `policy.recovery_frames` consecutive valid frames whose action is ALLOW, counted without V0's eligibility. Any other action, a transient frame, or a frame gap over `maximum_frame_gap_seconds` resets the count (spec v2 §7, "Recovery before a new entry");
    - `winding_down: bool = False`, set when the mode leaves Grid with grid orders open, and cleared once the grid has ended.
  - **The halt transition:** whenever `_step` reaches its halt branch with uptrend state, it ends that state before the liquidation: `account.uptrend = None`, `account.mode = "cash"` and `winding_down = False`. v1's liquidation then sells everything (spec v2 §7).
  - **`PaperSimulator._decide_mode(account, frame, regime) -> None`,** run at the first frame of each new UTC hour whenever the account is not halted, in the range-exit branch too, so that v1's re-centring cooldown holds back only new grids (spec v2 §6). It:
    - updates `range_decisions`, resetting it when the previous decision hour is not `hour − 1`;
    - holds the mode while `account.uptrend` exists;
    - otherwise sets `account.mode = select_mode(...)`, and marks this frame as a decision frame;
    - sets `winding_down` when the mode leaves Grid with grid orders open.
  - **`PaperSimulator._uptrend_step(account, frame, action) -> None`,** run on every frame while the account is not halted, after `_decide_mode` and before the branch's own selling. It updates the recovery count, then works through a held position, then the entry, in this order:
    1. **Exit 1:** `bid <= stop`, recording `uptrend_stopped_ms` at the first trigger.
    2. **Every daily close not yet processed:** each point in `d1_points` after the one at `stop_day_ms`, up to `d1_index`, in order. A point whose state is not UP exits 2 and ends the processing. Each other point sets `highest_close = max(highest_close, point.close)`, then `stop = trailed_stop(stop, highest_close, point.atr)`, and moves `stop_day_ms` to it. Usually that is one point, at the first frame after midnight. After a quote gap, it is every close the gap crossed (spec v2 §5).
    3. **Exit 2 whenever `d1_state` is UNAVAILABLE:** the daily bar due is missing, so no new point arrives, and `d1_open_ms` keeps the old value.
    4. **The entry, if no exit has started.**
       - **A new entry starts only on a decision frame** whose decision set Uptrend, with `action == RiskAction.ALLOW`, `risk_recovery` False, a non-transient frame and a flat pair. Otherwise, or when `entry_budget` is `None`, nothing starts before the next decision (spec v2 §5, "When").
       - **A started entry continues** on later quotes only while its budget lasts, the action is ALLOW and `risk_recovery` is False. Any other action ends the entry. Under a risk drain, the phase becomes `"exiting"`, so the drain sells what was bought.
    5. **On an exit,** it sets `phase = "exiting"`. v1's own selling then sells the position, since `uptrend_held` no longer holds it back: the per-frame unpaired exit, or the range-exit branch's sale.
    6. **The position ends** (`account.uptrend = None`) once what remains is below the minimum notional, leaving it as dust, as in v1.
  - **`PaperSimulator.uptrend_held(account) -> Decimal`:** the position's quantity while its phase is `"entering"` or `"holding"` and `account.risk_recovery` is False, and otherwise ZERO, so that an exit or a risk drain sells it as v1 drains. It is public, like `held_fragments`, because Task 6 reads it. It is subtracted in two places:
    - where `_step` computes `unpaired`, next to `held_fragments`;
    - in the range-exit branch, which, when `mode_switch` is on, sells `account.inventory − uptrend_held(account)` with `reduce_unreserved(..., maximum=...)` in place of `liquidate`.
    - `_resolved` still counts the position, so no harvest or settlement runs while it is held (spec v2 §6).
  - **The wind-down:** while `account.winding_down` is True, `_block_buys` runs every frame, as under F's block. Resting buys are cancelled, and `match` creates no re-entry buy.
  - **The grid gate:** `_open_grid` is reached only when `account.mode == "grid"` if `mode_switch` is on.

- [ ] **Step 1: Write the failing tests,** with frames built from stub `Snapshot`s and `Quote`s, one test per spec v2 §5–§7 rule:
  - `test_policy_mode_switch_requires_f_alone_and_is_named_ms`
  - `test_payload_without_perception_is_unchanged`, a byte-level comparison with `Frame.payload()` before the change
  - `test_cash_to_uptrend_enters_with_budget_and_initial_stop`, for example a daily close of 100, ATR 2, stop 94 and budget `min(60, 0.04 × equity ÷ 0.06)`
  - `test_entry_continues_across_quotes_under_participation`
  - `test_entry_starts_only_on_a_decision_frame`: a grid that becomes flat mid-hour enters at the next decision and not before; an attempt refused at a decision (`s <= 0`, or REDUCE) does not retry before the next one
  - `test_uptrend_enters_during_a_range_exit_cooldown_which_leaves_it_alone`
  - `test_no_entry_when_price_at_or_below_initial_stop`
  - `test_staying_in_uptrend_when_4h_turns_range`
  - `test_trailing_stop_starts_its_high_at_the_pre_entry_close`: `c0` = 100 with ATR 2 gives the stop 94. The next daily close, 99 with ATR 1, keeps the high at 100 and raises the stop to 97, where a high counted from entry only would give 96.
  - `test_trend_fade_exit_at_daily_close`
  - `test_unavailable_daily_state_triggers_trend_fade_exit` (Review Focus 5): the snapshot keeps the previous day's `d1_open_ms` with `d1_state` UNAVAILABLE, and exit 2 still fires at the first frame of the new UTC day
  - `test_daily_closes_missed_in_a_quote_gap_are_each_processed`: after a three-day quote gap whose middle day is not UP, the first quote exits 2. After a gap whose days are all UP, the stop uses the highest close within the gap.
  - `test_stop_exit_then_24h_reentry_pause`
  - `test_grid_to_uptrend_winds_down_without_reentry_and_waits_until_flat`
  - `test_grid_to_cash_winds_down_without_reentry`
  - `test_no_new_grid_unless_mode_is_grid`
  - `test_daily_loss_pause_and_soft_reduce_drain_the_uptrend_position_to_flat`
  - `test_risk_drain_ends_a_partial_entry_at_once`: a PAUSE mid-entry stops the buys on that frame, and the drain sells what was bought
  - `test_entry_waits_for_recovery_after_a_drain_and_after_a_restart`: an Uptrend decision on the first ALLOW frame after a drain, or after a hard-stop restart, starts nothing. Two consecutive ALLOW frames end the recovery, even while V0 is ineligible.
  - `test_eligibility_and_transient_pauses_do_not_sell_the_uptrend_position`
  - `test_stop_pause_runs_from_the_first_trigger`
  - `test_drain_and_range_exit_leave_the_uptrend_position_alone` (Review Focus 3)
  - `test_hard_stop_clears_uptrend_and_restart_redecides` (Review Focus 4): a halt during an entry clears `account.uptrend` and sets Cash before the liquidation. After the restart, the first decision is fresh, and no buy resumes from the old budget
  - `test_range_decisions_reset_after_a_missing_hour`
  - `test_paper_account_refuses_mode_switch`
- [ ] **Step 2: Run `pytest tests/test_mode_switch_runner.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement the fields, the policy validation and the three methods,** then hook them into `_step` as listed in Interfaces. When `mode_switch` is off, no existing line's behaviour changes.
- [ ] **Step 4: Run all the tests and the byte checks:**
  - `pytest -q`. Expected: every test passes.
  - `sh scratchpad/runall.sh <tree> ms5 sb-up:cli sb-down:cli sb-nod:cli sb-up:cli:--structure sb-down:cli:--structure sb-up:A sb-up:B sb-down:C`. Expected: each run equals main's baseline SHA-256: `sb-up:cli` `bdb47225…`, `sb-down:cli` `d70ac015…` and `sb-nod:cli` `09f6abe1…` (V0), `sb-up:A` `3001a0e9…`, `sb-up:B` `2089da3d…` and `sb-down:C` `f5c8c6b1…`. The two `--structure` runs match main's apart from provenance (`cmp163.py`).
- [ ] **Step 5: Commit** `feat: spec v2 mode switcher in the paper simulator (replay only)`.

*Open Tasks 4–5 as one PR (spec §9 step 5).*

### Task 6: Replay, reporting and the CLI

**Files:**
- Modify: `src/crypto_grid_bot/backtest/replay.py`, in `replay`, `Metrics`, `summarise` and the end-of-run `exit_state` call
- Modify: `src/crypto_grid_bot/backtest/jobs.py`, in `variant_policy` and `run_job`
- Modify: `src/crypto_grid_bot/backtest/__main__.py`, for the `--mode-switch` flag
- Modify: `.github/workflows/backtest.yml`: the `"MS"` variant choice, its description, and the case arm `MS) set -- "$@" --mode-switch ;;`. Without the arm, the run would silently be V0
- Modify: `docs/BACKTEST_METHOD.md`, with a section on the mode switcher
- Test: `tests/test_mode_switch_replay.py`, a case in `tests/test_backtest_cli.py`, and `tests/test_backtest_workflow.py`

**Interfaces:**
- **Consumes:** Task 5, `Perception` (Task 2), and the pair's hourly and daily bars that `prepare_run` already loads.
- **Produces:**
  - **In `replay()`:** when `policy.mode_switch`, it raises `ValueError("the mode switcher needs the pair's hourly and daily history")` if either is missing, builds `Perception(hourly, daily)` once, and passes `perception=perception.at(kline.open_ms)` on every frame.
  - **`Metrics` fields,** filled only for MS: `mode_minutes: Counter[str]`, `mode_switches: int`, `uptrend_trades: int`, `uptrend_stops: int`, `uptrend_fades: int`.
  - **In `summarise`:** MS rows carry `row["variant"] = "MS"` and `row["modes"] = {"minutes": {...}, "switches": n, "uptrend_trades": n, "stops": n, "fades": n, "grid_cycles": metrics.completed_cycles}`.
  - **The end of the run:** for MS, `held` is F's held fragments, as today, plus `simulator.uptrend_held(account)`. So a run ending in a blocked grid keeps F's exemption, a held position or an entry in progress is not owed, and an exit or risk drain under way is owed, as in v1 (spec v2 §6).
  - **`row["modes"]["buy_and_hold_final"]`:** `str(metrics.hold_final)`, so the scorer can end the last month exactly (Task 7).
  - **`variant_policy("MS")`** returns `SimulationPolicy(mode_switch=True, flow_block_entry=True)`. The CLI flag `--mode-switch` stores `"MS"` in `variant`, and the stamp suffix is `-variant-MS`.

- [ ] **Step 1: Write the failing tests:**
  - `test_mode_switch_cli_maps_to_policy`, in the CLI suite with the fake `run_job`.
  - `test_rising_market_enters_uptrend_and_trails_out`, on synthetic hourly, daily and minute bars, 300 days of steady rise and then a 15% drop. It asserts one uptrend trade, a stop exit, and `row["modes"]["stops"] == 1`.
  - `test_flat_market_runs_grids_in_grid_mode`, which asserts `grid_cycles > 0` and Uptrend minutes of 0.
  - `test_run_ending_in_uptrend_is_valid_and_marked_at_exit_value` (Review Focus 2), which asserts `valid`, the absence of any "incomplete" failure, and final equity = cash + quantity × the exit mark.
  - `test_run_ending_in_a_blocked_grid_keeps_f_fragments_held`: an MS run that ends in Grid mode with F fragments is not incomplete.
  - `test_run_ending_mid_exit_is_incomplete_as_in_v1`: an exit 1 whose sells the participation limit has not finished by the end leaves the run incomplete.
  - `test_every_variant_choice_maps_to_a_cli_flag`, in `tests/test_backtest_workflow.py`: it loads `backtest.yml` with `yaml`, and asserts that every `variant` choice except V0 has a case arm, and that MS's arm adds `--mode-switch`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement the wiring and the reporting,** and write the method doc's section. It covers what an MS row records, and how to run the mode switcher with `--mode-switch`.
- [ ] **Step 4: Run `pytest -q` and the byte checks of Task 5, step 4.** Expected: everything passes, with the same SHA-256s.
- [ ] **Step 5: Commit** `feat: wire the mode switcher into replay, rows and the CLI`.

### Task 7: The spec v2 scorer

**Files:**
- Create: `src/crypto_grid_bot/backtest/acceptance_v2.py`
- Test: `tests/test_acceptance_v2.py`

**Interfaces:**
- **Consumes:** `acceptance.py`'s `read_results`, `annualise`, `gate_ratio`, `certain`, `YEAR_DAYS`, `mean`, `median`, `worst_drop`, `makes_money`, `safer_than_holding`, `integrity`, `economics` (R1, reported), `window_of`, `Run` and `ScoringError`; MS rows and F rows from Task 6.
- **Produces:**
  - `SCORING = "spec-v2-section-8"`, `ROUND_TRIPS_PER_YEAR = 12`, `GATE_SHARE = Fraction(3, 5)`, and `SCORED = ("full-range-2017-2024",)`, with `REPORTED = ("practice-2022", "verify-2024h1")`;
  - `round_trips(row: dict[str, Any]) -> int`, which is `row["modes"]["grid_cycles"] + row["modes"]["uptrend_trades"]`;
  - `activity_v2(runs: Sequence[Run], trips: Mapping[str, int]) -> Criterion`, where each run's rate is `Fraction(trips[run.label]) * YEAR_DAYS / run.days` and the mean is exact;
  - `earns_its_place(ms: Sequence[Run], always_grid: Mapping[tuple[str, str], Run]) -> Criterion`:
    - a run passes only when its `return_pct` is > 0 (annualising keeps the sign) and its annualised ratio, `gate_ratio(run.annualised.value, run.max_drawdown_pct)`, beats F's, computed the same way, in the same pair and path;
    - each comparison is decided with `certain` over the interval the two `annualised.bound`s give, as C2's are;
    - a missing or invalid F run counts against. `Run.ratio` is raw, so it is not used here;
  - `upside_capture(row: dict[str, Any]) -> Fraction | None`, from `row["hourly_equity"]`, `row["initial_quote"]`, `row["final_total_equity"]` and `row["modes"]["buy_and_hold_final"]`:
    - month `m` runs from `B(m)`, the first sample at or after its start, to `B(m + 1)`;
    - the first month's `B` is `initial_quote` for both, and the last month ends at the two final values;
    - it sums over the months whose buy-and-hold return is > 0, and is `None` when there are none (spec v2 §8);
  - `role_of(row: dict[str, Any]) -> str | None`:
    - `"MS"`, the candidate;
    - `"F"`, always-grid for C6;
    - `"D"`, reported only;
    - `None` for the ungated V0 rows, which every results file carries (`__main__.py` runs the ungated baseline beside every gated policy). They are ignored;
    - any other row raises `ScoringError`;
  - `main(argv) -> int`, with the CLI `python -m crypto_grid_bot.backtest.acceptance_v2 <results...> --out <verdict.json>`, which writes C1–C6 and the reported readouts. It refuses inputs that fail v1's provenance pins, and inputs with no MS rows or no F rows.

- [ ] **Step 1: Write the failing tests:**
  - `test_activity_threshold_inclusive`: exactly 12 round trips a year passes, and 11.99 fails.
  - `test_gate_needs_positive_return_and_beats_always_grid`
  - `test_gate_uses_annualised_returns_and_counts_a_missing_or_invalid_always_grid_against`, with `days = 2192`:
    - the run returns 10% with a 5% drawdown, and F returns 20% with 9.9%;
    - the raw ratios (2.0 and 2.0202) would favour F, but the annualised ones (0.3202 and 0.3116) favour the run, so it passes;
    - a run with no F run, or with an invalid one, fails.
  - `test_upside_capture_uses_month_boundary_samples`: a move between a month's last hourly sample and the next month's first one counts in the earlier month, and the first month starts from `initial_quote`.
  - `test_gate_share_boundary`: 3 of 5 passes, and 2 of 5 fails.
  - `test_upside_capture_two_months`: buy-and-hold +10% in month 1 and −5% in month 2, the bot +4% and +1%, gives capture 0.4.
  - `test_c1_to_c4_reuse_v1_functions`: the same verdicts as `acceptance.worst_drop` and friends on shared fixtures.
  - `test_cli_scores_ms_against_f_and_ignores_the_ungated_rows`: real-shaped MS and F results files, each with its ungated V0 rows, are scored, and their D rows are reported. A file with variant A's rows is refused, and so is a set with no F rows.
  - `test_r1_is_reported_and_gates_nothing`
- [ ] **Step 2: Run `pytest tests/test_acceptance_v2.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement `acceptance_v2.py`.** `acceptance.py` is unchanged, so spec v1's scorer stays as frozen.
- [ ] **Step 4: Run `pytest -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: spec v2 scorer (C1-C6 adapted, upside capture reported)`.

*Open Tasks 6–7 as one PR (spec §9 step 6). The evaluation runs follow once the long-window data plan has delivered the dataset.*
