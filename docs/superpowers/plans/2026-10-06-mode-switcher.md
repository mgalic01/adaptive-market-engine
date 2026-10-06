# Mode Switcher Implementation Plan

> **How this plan runs:** task by task, each with a fresh implementer and then a fresh reviewer, and a whole-branch review at the end. That is the subagent-driven execution the owner chose on 2026-10-06. Steps use checkbox (`- [ ]`) syntax for tracking.

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
  - After each task, `python scripts/byte_identity.py check` (Task 0) reproduces main's baseline SHA-256s for V0, the two `--structure` runs, and every registered v1 variant, including the full stack. It runs on three synthetic datasets built from a fake archive, with no network, so any reviewer can run it.
- **Replay-only.** `PaperSimulator.process` refuses a paper account whose policy has `mode_switch`, as it refuses E and F.
- **Exact thresholds** (spec v2 §3–§5):

  | Where | Values |
  | --- | --- |
  | Periods | 14 (RSI, ATR, ADX, DI); SMA 20 and 50; Bollinger 20 at 2 population σ; width median over 720 widths |
  | Trend states | ADX ≥ 20 for Up and Down; < 20 for Range |
  | Grid | RSI 35 ≤ r ≤ 65; 1h ADX < 20; width ≤ median; 4 consecutive RANGE decisions |
  | Uptrend | daily RSI < 75 |
  | Uptrend engine | risk 0.04; cap 0.60; stop 3 × daily ATR; re-entry pause 86 400 000 ms (24 h, exactly 24 h allowed) after a stop-out only |

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

### Task 0: The byte-identity check, in the repository

**Files:**
- Create: `scripts/byte_identity.py`
- Create: `scripts/byte_identity_baseline.json`
- Test: `tests/test_byte_identity_script.py`

**Interfaces:**
- **Produces:** `python scripts/byte_identity.py check`, which prints one line per run (`<run> <sha256> IDENTICAL|DIFFERENT`), then `ALL IDENTICAL` or `SOME DIFFER`, and exits 0 only when all match. `python scripts/byte_identity.py record` rewrites the baseline file from the current tree.
- **The runs** (the controller's scratchpad harness, `strat_bytecheck.py` with `btmerge_bytecheck.py`'s `FakeArchive`, ported):
  - **three synthetic datasets,** built through `dataset.fetch_dataset` from a fake archive, with no network, in a temporary directory. The price is the harness's random walk × `exp(drift × days since the start)`. `up` has drift 0, `down` has drift −0.004 per day, and `nod` has drift 0 and no daily history;
  - **deterministic archives and manifests:** each zip entry gets a fixed `ZipInfo` date (1980-01-01 00:00:00), and `fetch_dataset` gets a fixed clock, `now=lambda: datetime(2024, 3, 1, tzinfo=UTC)`. Its default clock would stamp the manifest's `created_at`, and so every CLI `results.json`'s `manifest_created_at`. The scratchpad's `FakeArchive` stamps the wall-clock time, so its archives, manifests and `results.json` change with every build;
  - **the CLI runs:** `main()` in-process, with the process pool replaced by an inline executor, on `up`, `down` and `nod`, and with `--structure` on `up` and `down`. The `up` and `down` V0 runs add `--trend-benchmark`, so variant D is checked too;
  - **the variant runs:** every registered v1 variant, so that a change to a shared path cannot pass unseen. A, B, E, F, G, H, C+G and C+H run on `up`; C runs on `down`; and the full stack (`C+F+G+H` with the structure features) runs on `up`. Each goes through `run_job(policy=jobs.variant_policy(name, structure=...))` for all four path and gated cases. `results` maps `<variant>-<path>-<gated|ungated>` to the row, with its `"variant"` key dropped;
  - **funding for G:** G, C+G and the full stack refuse a manifest without BTCUSDT's funding archive for an evaluation month from 2020-01 (`load_funding`). So the fake archive adds one synthetic funding month, 2024-01, in the format `load_funding` reads, and the datasets' manifests list it;
  - **the hashes cover the engine's output only:** SHA-256 over `json.dumps(document, sort_keys=True, default=str)`, with the identity keys `spec_sha256`, `manifest_sha256`, `config_sha256`, `code_commit` and `code_sha256` set aside wherever they appear.
- **The baseline:** recorded with `record` from main, at the commit this task branches from, before any v2 code. If main moves before the PR merges, it is re-recorded on the new merge base. The controller also checks once that the port's engine output equals the scratchpad harness's on main, with the same keys set aside. The scratchpad's own whole-file hashes (`bdb47225…` and the rest) cannot carry over, because its archives were stamped at build time.

- [ ] **Step 1: Write the failing test** `test_byte_identity_dataset_builder_is_deterministic`: building the `nod` dataset twice in two temporary directories gives byte-identical archives and manifests.
- [ ] **Step 2: Run it.** Expected: FAIL, the script does not exist yet.
- [ ] **Step 3: Port the harness** into `scripts/byte_identity.py`. It must pass `ruff`, `mypy` and `bandit` like the rest of `scripts/`.
- [ ] **Step 4: Run `python scripts/byte_identity.py record` on main's code, then `check`.** Expected: `ALL IDENTICAL`. The controller then compares the port's engine output with the scratchpad harness's on main (the step above).
- [ ] **Step 5: Commit** `test: byte-identity check for V0 and the v1 variants, in the repository`.

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
  - `wilder_adx(bars: Sequence[Bar], period: int = 14) -> tuple[list[Decimal | None], list[Decimal | None], list[Decimal | None]]`, which returns `(adx, plus_di, minus_di)`, with DI first at index `period` and ADX first at `2 × period − 1`, the same seeding as `SeriesFeatures._wilder_adx`. That function computes nothing for a series of `2 × period` bars or fewer (`features.py:154`). This one gives ADX from the 28th bar, as spec v2 §3's minimum-bars table says, and on longer series the values match;
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

*Open Tasks 0–2 as one PR (spec §9 step 3, perception, with the byte check it relies on), to Codex and Bob. Spec v2 §9 makes each build step its own PR.*

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

*Open Task 3 as its own PR (spec §9 step 4), to Codex and Bob.*

### Task 4: Market buy and the uptrend arithmetic

**Files:**
- Modify: `src/crypto_grid_bot/simulation/execution.py`, to add `buy_price` and `market_buy`
- Create: `src/crypto_grid_bot/simulation/uptrend.py`
- Test: `tests/test_uptrend.py`

**Interfaces:**
- **Produces, in `execution.py`:**
  - `buy_price(quote: Quote, rules: MarketRules) -> Decimal`: ask × (1 + slippage), rounded up to the tick, the same rule as `trend_benchmark.buy_price`;
  - `market_buy(account: Account, quote: Quote, rules: MarketRules, *, budget: Decimal) -> Fill | None`. Its quantity is `min(floor_step(ask_size × participation), affordable)`, where `affordable = floor_step(budget ÷ (price × (1 + taker)))`, lowered one `quantity_step` at a time while `affordable × price × (1 + taker) > budget`. That is `trend_benchmark.entry_quantity`'s guard against a quotient rounded up at the last digit. It returns `None` when the price × quantity is below the minimum notional. The fill is applied with `_apply_fill` under order id `"uptrend/buy/" + quote.event_id` at the taker fee.
- **Produces, in `uptrend.py`:**
  - `RISK_FRACTION = D("0.04")`, `CAPITAL_CAP = D("0.60")`, `ATR_MULTIPLE = D(3)`;
  - `entry_budget(active_capital: Decimal, active_equity: Decimal, price: Decimal, stop: Decimal) -> Decimal | None`, which is `None` when the stop distance `s <= 0`;
  - `initial_stop(close: Decimal, atr: Decimal) -> Decimal`;
  - `trailed_stop(stop: Decimal, highest_close: Decimal, atr: Decimal) -> Decimal`, which is `max(stop, highest_close − 3 × atr)`;
  - `UptrendPosition`, a mutable dataclass: `budget`, `spent` (the USDT paid, taker fees included, which the budget bounds, as `market_buy`'s affordability guard counts them), `exit_reason: str` ("" until an exit begins; Task 5), `quantity`, `stop`, `highest_close: Decimal`, `stop_day_ms: int`, `entered_at: str`, `phase: str`. The phase is one of `"entering"`, `"holding"` and `"exiting"`. `highest_close` starts at `c0`, the last completed daily close before entry, and `stop` at `initial_stop(c0, that day's ATR)` (spec v2 §5).

- [ ] **Step 1: Write the failing tests:**

```python
def test_entry_budget_risk_bound_and_cap():
    assert entry_budget(D(100), D(100), D(100), D(90)) == D(40)  # 0.04*100/0.1
    assert entry_budget(D(100), D(100), D(100), D(99)) == D(60)  # cap 0.60*100
    assert entry_budget(D(100), D(100), D(100), D(100)) is None  # s <= 0


def test_trailed_stop_never_moves_down():
    assert trailed_stop(D(95), D(100), D(2)) == D(95)  # 100-6 = 94 < 95
    assert trailed_stop(D(95), D(110), D(2)) == D(104)


RULES = MarketRules(
    symbol="BTCUSDT",
    tick_size=D("0.01"),
    quantity_step=D("0.001"),
    minimum_notional=D("5"),
    fee_rate=D("0"),
    slippage_rate=D("0"),
    participation=D("0.10"),
    taker_fee_rate=D("0.0009"),
)
T0 = "2024-01-01T00:00:00+00:00"


def quote(ask_size):
    return Quote("e1", "BTCUSDT", T0, T0, D("99.99"), D("100"), D(5), ask_size)


def test_buy_price_matches_trend_benchmark():
    rules = replace(RULES, slippage_rate=D("0.00033"))  # 100.033 rounds up to 100.04
    assert execution.buy_price(quote(D(5)), rules) == trend_benchmark.buy_price(quote(D(5)), rules)


def test_market_buy_bounds():
    # The price is 100 and the all-in unit cost 100.09.
    # Participation: 2 x 0.10 = 0.2 is below the budget's 40 / 100.09 -> 0.399.
    fill = execution.market_buy(Account.start(D(100)), quote(D(2)), RULES, budget=D(40))
    assert (fill.price, fill.quantity, fill.fee) == (D(100), D("0.2"), D("0.018"))
    # Budget: 5 x 0.10 = 0.5 is above 0.399.
    fill = execution.market_buy(Account.start(D(100)), quote(D(5)), RULES, budget=D(40))
    assert (fill.quantity, fill.fee) == (D("0.399"), D("0.03591"))
    # Minimum notional: 4 / 100.09 -> 0.039, and 0.039 x 100 = 3.9 < 5.
    assert execution.market_buy(Account.start(D(100)), quote(D(5)), RULES, budget=D(4)) is None


def test_market_buy_never_spends_more_than_its_budget():
    # 1E-55 below 0.4 x 100.09: the quotient rounds up to 0.4 at precision 50,
    # and 0.4 would cost 40.036, so the guard lowers it to 0.399.
    with localcontext() as context:
        context.prec = 80
        budget = D("40.036") - D("1E-55")
    fill = execution.market_buy(Account.start(D(100)), quote(D(5)), RULES, budget=budget)
    assert fill.quantity == D("0.399")
```
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
  - `PaperSimulator._resolved`, for the uptrend position;
  - new methods `_decide_mode`, `_uptrend_step`, `_finish_uptrend` and `uptrend_held`.
- Modify: `src/crypto_grid_bot/backtest/replay.py`, in `order_requests` only, which counts `uptrend/` buys.
- Modify: `src/crypto_grid_bot/simulation/models.py`, for the runtime-only `Account` fields.
- Modify: `tests/test_trend_switch.py`: its `test_unset_switch_leaves_identity_state_journal_and_reports_unchanged` pins `SimulationPolicy`'s fields, so `"mode_switch": False` joins its `unset` dict.
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
    - `risk_recovery: bool = False` and `risk_recovery_count: int = 0`. The flag is set when `_risk_action` pauses on PAUSE or REDUCE, and when `_clear_halt` restarts the account. It is cleared after `policy.recovery_frames` consecutive valid frames whose action is ALLOW, counted without V0's eligibility (spec v2 §7, "Recovery before a new entry"). `_uptrend_step` adds to the count on ALLOW and resets it on any other action. The other two resets sit where `_step` already sees those events, since `_uptrend_step` runs too late for them: the TransientFrame branch, beside `episode_count = 0`, and the frame-gap test, beside `recovery_count = episode_count = 0`;
    - `winding_down: bool = False`, set when the mode leaves Grid with grid orders open. It is cleared once the grid has ended, or when a decision sets the mode back to Grid first, which lifts the wind-down as F's block lifts (spec v2 §6, "Returning to Grid before it ends").
  - **The halt transition:** on every frame that reaches `_step`'s halt branch, before the liquidation, `account.mode = "cash"` and `winding_down = False`, whether or not a position exists. Otherwise a halt in Grid mode would keep Grid through the restart, and a grid could open before any decision (spec v2 §7: "While halted, the mode is Cash"). A position's phase becomes `"exiting"`, so it never buys again. v1's liquidation then sells everything, and `_finish_uptrend`, which also runs in the halt branch after the liquidation, ends the position only once the liquidation has sold it. `_restart` requires a finished liquidation, so no position survives a restart.
  - **A risk drain ends the position:** when `_risk_action` starts a drain (PAUSE or REDUCE) while a position exists, its phase becomes `"exiting"`, whatever it was. The drain's unpaired exit then sells it, and `_finish_uptrend` ends it. Without this, a sold position would stay `"holding"`, hold the mode, and keep `_resolved` False for good.
  - **Exit 3's label:** a risk drain or a halt sets `report["uptrend_exit"] = "risk"` only when no uptrend exit has started yet. A stop or fade whose own sale trips the post-fill risk check keeps its label, and the drain still sells whatever remains.
  - **`_step`'s main branch extends `report["fills"]`** with `match`'s fills, where it assigns them today, so the uptrend buys appended earlier in the frame survive. The list is empty at that point in every v1 run, so nothing changes there, as the byte check confirms.
  - **`PaperSimulator._decide_mode(account, frame, regime) -> None`,** run at the first valid frame at or after each UTC hour boundary, whenever the account is not halted (spec v2 §4). A transient frame returns from `_step` before this hook, so it neither decides nor touches `range_decisions` or `decision_hour_ms`. The hook runs in the range-exit branch too, so that v1's re-centring cooldown holds back only new grids (spec v2 §6). It:
    - updates `range_decisions`, resetting it when the previous decision hour is not `hour − 1`;
    - holds the mode while `account.uptrend` exists;
    - otherwise sets `account.mode = select_mode(...)`, and marks this frame as a decision frame;
    - sets `winding_down` when the mode leaves Grid with grid orders open, and clears it when a decision returns to Grid before the grid has ended.
  - **`PaperSimulator._uptrend_step(account, frame, action, report) -> None`,** run on every frame while the account is not halted, after `_decide_mode` and before the branch's own selling. Each uptrend buy is appended to `report["fills"]` as `asdict(fill)`, so replay's `_record_fills`, the accounting reconciliation and the journal see it as they see any fill. An exit that triggers sets `report["uptrend_exit"]` to `"stop"`, `"fade"` or `"risk"`. It updates the recovery count, then works through a held position, then the entry, in this order:
    1. **Exit 1:** `bid <= stop`, recording `uptrend_stopped_ms` at the first trigger.
    2. **Every daily close not yet processed, one at a time:** each point in `d1_points` after the one at `stop_day_ms`, up to `d1_index`, in order. A point whose state is not UP exits 2. Each other point sets `highest_close = max(highest_close, point.close)`, then `stop = trailed_stop(stop, highest_close, point.atr)`, and moves `stop_day_ms` to it. The quote's bid is then checked against that stop (exit 1) before the next point. The first exit ends the processing, so a stop raised by an earlier missed close is not lost to a later fade (spec v2 §5, "Daily closes missed in a gap"). Usually that is one point, at the first frame after midnight. After a quote gap, it is every close the gap crossed.
    3. **Exit 2 whenever `d1_state` is UNAVAILABLE:** the daily bar due is missing, so no new point arrives, and `d1_open_ms` keeps the old value.
    4. **The entry, if no exit has started.**
       - **A new entry starts only on a decision frame** whose decision set Uptrend, with `action == RiskAction.ALLOW`, `risk_recovery` False, a non-transient frame and a flat pair. Flat is spec v2 §6's definition: no resting order (`not account.orders`), and nothing marketable once F's held fragments are set aside. The test is `marketable(unpaired_inventory(account) − held_fragments(account), quote, rules) == 0`, so dust does not block it, nor do several fragments whose sum exceeds the minimum, as v1's unpaired exit exempts them. Otherwise, or when `entry_budget` is `None`, or when the quote's bid is at or below the initial stop, nothing starts before the next decision (spec v2 §5, "When"). The bid test matters because `s` uses the buy price, which is above the bid by the spread and slippage.
       - **A started entry continues** on later quotes only while its budget lasts, the action is ALLOW and `risk_recovery` is False. Any other action ends the entry. Under a risk drain, the phase is already `"exiting"` (above), so the drain sells what was bought.
    5. **On an exit,** it sets `phase = "exiting"`. v1's own selling then sells the position, since `uptrend_held` no longer holds it back: the per-frame unpaired exit, or the range-exit branch's sale. The position stores its reason, `exit_reason`, set once when the exit begins (`"stop"`, `"fade"` or `"risk"`). Every sale of it, over as many quotes as the participation limit needs, is journaled as `"uptrend_" + exit_reason` in `_record_exit`, not as a grid's `"drain"` or `"range_exit"`, until `_finish_uptrend` ends the position. So `realised_exit_pnl_by_reason` keeps the two apart, and `report["uptrend_exit"]` is set only on the frame where the exit begins, so each exit counts once.
  - **`PaperSimulator._finish_uptrend(account, quote, report) -> None`,** run at the end of every `_step` that reaches a branch, after that branch's selling (the unpaired exit, the range-exit sale, or the halt's liquidation). When the phase is `"exiting"` and what remains is zero or below the minimum notional, it ends the position (`account.uptrend = None`) and leaves any remainder as dust, as in v1. It sets `report["uptrend_ended"] = True` when the position bought something (`spent > 0`), and `report["uptrend_abandoned"] = True` when it bought nothing, which is not a trade (spec v2 §5). So a sale that completes on a frame, the last frame of a run included, ends the position in that frame.
  - **`PaperSimulator.uptrend_held(account) -> Decimal`:** the position's quantity while its phase is `"entering"` or `"holding"`, and otherwise ZERO, so that an exit or a risk drain (which sets `"exiting"`) sells it as v1 drains. It is public, like `held_fragments`, because Task 6 reads it. It is subtracted in two places:
    - where `_step` computes `unpaired`, next to `held_fragments`;
    - in the range-exit branch. When `mode_switch` is on and `uptrend_held(account)` is positive, the branch sells `bound = account.inventory − uptrend_held(account)` with `reduce_unreserved(..., maximum=bound)`, and only while `bound` is positive. Otherwise it calls `liquidate` exactly as v1. `reduce_unreserved` raises on a bound of zero, and the bound is zero whenever the account holds nothing but the position.
  - **`_resolved` is False while an uptrend position is entering or holding,** whatever its size, when `mode_switch` is on. Today's `_resolved` is True when the unreserved inventory is below the sellable minimum, so a dust-sized live position would otherwise let the harvest settle and move the reserves while it is held (spec v2 §6). Dust completion applies only in phase `"exiting"` (`_finish_uptrend`).
  - **A halted position's trade counts only after its liquidation:** `_finish_uptrend` reports `uptrend_ended` when the liquidation has sold the position, not at the halt. A run that ends before the liquidation finishes is incomplete, as in v1, and counts no trade.
  - **`replay.order_requests`** counts each fill whose id starts with `uptrend/` as one off-book request, as it counts `exit/` fills, so `max_order_requests_per_day` sees every entry buy. No other run has such fills, so their counts do not change.
  - **The wind-down:** while `account.winding_down` is True, `_block_buys` runs every frame, as under F's block. Resting buys are cancelled, and `match` creates no re-entry buy.
  - **The grid gate:** `_open_grid` is reached only when `account.mode == "grid"` if `mode_switch` is on.

- [ ] **Step 1: Write the failing tests,** with frames built from stub `Snapshot`s and `Quote`s, one test per spec v2 §5–§7 rule:
  - `test_policy_mode_switch_requires_f_alone_and_is_named_ms`
  - `test_payload_without_perception_is_unchanged`, a byte-level comparison with `Frame.payload()` before the change
  - `test_cash_to_uptrend_enters_with_budget_and_initial_stop`, for example a daily close of 100, ATR 2, stop 94 and budget `min(60, 0.04 × equity ÷ 0.06)`
  - `test_entry_continues_across_quotes_under_participation`
  - `test_uptrend_buys_are_in_the_report_and_reconcile`: a two-quote entry puts both buys in `report["fills"]`, and replay's accounting check passes with their notional and fees counted
  - `test_uptrend_buys_count_as_order_requests`: a three-quote entry adds three requests to that day's count
  - `test_dust_sized_held_position_blocks_the_harvest`: a holding position whose value marks below the minimum notional keeps `_resolved` False, so no settlement runs
  - `test_exit_completing_on_a_frame_ends_the_position_there`: when the frame's unpaired exit sells the whole position, `_finish_uptrend` ends it in that frame and sets `report["uptrend_ended"]`
  - `test_entry_starts_only_on_a_decision_frame`: a grid that becomes flat mid-hour enters at the next decision and not before; an attempt refused at a decision (`s <= 0`, or REDUCE) does not retry before the next one
  - `test_uptrend_enters_during_a_range_exit_cooldown_which_leaves_it_alone`
  - `test_no_entry_when_price_at_or_below_initial_stop`
  - `test_no_entry_when_the_spread_straddles_the_initial_stop`: the buy price is above the stop and the bid at it, so nothing is bought, and no pause starts
  - `test_staying_in_uptrend_when_4h_turns_range`
  - `test_trailing_stop_starts_its_high_at_the_pre_entry_close`: `c0` = 100 with ATR 2 gives the stop 94. The next daily close, 99 with ATR 1, keeps the high at 100 and raises the stop to 97, where a high counted from entry only would give 96.
  - `test_trend_fade_exit_at_daily_close`
  - `test_unavailable_daily_state_triggers_trend_fade_exit` (Review Focus 5): the snapshot keeps the previous day's `d1_open_ms` with `d1_state` UNAVAILABLE, and exit 2 still fires at the first frame of the new UTC day
  - `test_daily_closes_missed_in_a_quote_gap_are_each_processed`: after a three-day quote gap whose middle day is not UP, the first quote exits 2. After a gap whose days are all UP, the stop uses the highest close within the gap.
  - `test_stop_exit_then_24h_reentry_pause`
  - `test_stop_before_any_fill_ends_the_entry_and_starts_the_pause`: the report has `uptrend_abandoned`, not `uptrend_ended`, and the 24-hour pause runs
  - `test_transient_first_frame_defers_the_decision`: a transient frame at the top of the hour decides nothing, and leaves `range_decisions` and `decision_hour_ms` as they were. The next valid frame in that hour decides
  - `test_flat_ignores_dust_and_fragments_but_not_resting_orders`, including two held fragments whose sum exceeds the minimum notional
  - `test_grid_to_uptrend_winds_down_without_reentry_and_waits_until_flat`
  - `test_grid_to_cash_winds_down_without_reentry`
  - `test_return_to_grid_lifts_the_wind_down`: after one hour out of Grid and a return, a filled sell creates its re-entry buy again, and the buys cancelled during the wind-down are not restored
  - `test_no_new_grid_unless_mode_is_grid`
  - `test_daily_loss_pause_and_soft_reduce_drain_the_uptrend_position_to_flat`, which also asserts `account.uptrend is None` once the drain has sold it, and a held phase that turned `"exiting"` at the drain's frame
  - `test_halt_in_grid_mode_sets_cash_and_no_grid_opens_before_a_decision`
  - `test_range_exit_branch_with_only_the_position_does_not_crash`: on frames whose account holds nothing but the position, inside a range exit, the bound is zero, so the branch makes no sale call and raises nothing, and the position's quantity and `account.inventory` are unchanged. `liquidate` would sell the position, so it is not called while one is held
  - `test_uptrend_exit_pnl_has_its_own_labels`: a stop's sale is journaled as `"uptrend_stop"`, not `"drain"`
  - `test_risk_drain_ends_a_partial_entry_at_once`: a PAUSE mid-entry stops the buys on that frame, and the drain sells what was bought
  - `test_entry_waits_for_recovery_after_a_drain_and_after_a_restart`: an Uptrend decision on the first ALLOW frame after a drain, or after a hard-stop restart, starts nothing. Two consecutive ALLOW frames end the recovery, even while V0 is ineligible. A frame gap between the two restarts the count.
  - `test_eligibility_and_transient_pauses_do_not_sell_the_uptrend_position`
  - `test_stop_pause_runs_from_the_first_trigger`
  - `test_drain_and_range_exit_leave_the_uptrend_position_alone` (Review Focus 3)
  - `test_hard_stop_clears_uptrend_and_restart_redecides` (Review Focus 4): a halt during an entry sets Cash and the position's phase to `"exiting"` before the liquidation. The position ends, with `uptrend_ended`, only once the liquidation has sold it. After the restart, the first decision is fresh, and no buy resumes from the old budget
  - `test_halt_before_any_fill_abandons_the_entry`: a halt during an entry that bought nothing ends it with `uptrend_abandoned` and no trade, and clears `account.uptrend`
  - `test_raised_stop_is_checked_on_the_same_quote`: the first quote after a daily close is above the old stop but below the raised one. Exit 1 fires on that quote
  - `test_missed_closes_recheck_the_stop_after_each`: after a gap whose first missed close is UP and raises the stop above the bid, and whose second is not UP, the quote exits 1 (a stop, with its 24-hour pause), not 2
  - `test_exit_reason_labels_every_sale_until_the_end`: a stop whose sale takes three quotes, the bid recovering above the stop in between, is journaled as `"uptrend_stop"` on all three, and `uptrend_stops` counts 1
  - `test_stop_reason_survives_a_post_fill_drain`: a stop whose sale trips the daily-loss pause keeps `uptrend_exit == "stop"`
  - `test_range_decisions_reset_after_a_missing_hour`
  - `test_paper_account_refuses_mode_switch`
- [ ] **Step 2: Run `pytest tests/test_mode_switch_runner.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement the fields, the policy validation and the three methods,** then hook them into `_step` as listed in Interfaces. When `mode_switch` is off, no existing line's behaviour changes.
- [ ] **Step 4: Run all the tests and the byte checks:**
  - `pytest -q`. Expected: every test passes.
  - `python scripts/byte_identity.py check` (Task 0). Expected: `ALL IDENTICAL`, meaning that every V0, `--structure`, A, B and C run equals main's recorded baseline.
- [ ] **Step 5: Commit** `feat: spec v2 mode switcher in the paper simulator (replay only)`.

*Open Tasks 4–5 as one PR (spec §9 step 5).*

### Task 6: Replay, reporting and the CLI

**Files:**
- Modify: `src/crypto_grid_bot/backtest/replay.py`, in `replay`, `Metrics`, `summarise` and the end-of-run `exit_state` call
- Modify: `src/crypto_grid_bot/backtest/jobs.py`, in `variant_policy` and `run_job`
- Modify: `src/crypto_grid_bot/backtest/__main__.py`, for the `--mode-switch` flag
- Modify: `.github/workflows/backtest.yml`: the `"MS"` variant choice, its description, and the case arm `MS) set -- "$@" --mode-switch ;;`. Without the arm, the run would silently be V0. The `trend_benchmark` input's description also says that v2's scorer reads D from the MS run, where v1's reads it from the V0 run
- **Where D's rows come from:** v2's evaluation adds `--trend-benchmark` to the MS runs only, one per window. Task 7 refuses D rows in a V0 file, whose gated rows it does not accept, and refuses a second D row for a key, so D on both the MS and the F run would be refused
- Modify: `docs/BACKTEST_METHOD.md`, with a section on the mode switcher
- Test: `tests/test_mode_switch_replay.py`, a case in `tests/test_backtest_cli.py`, and `tests/test_backtest_workflow.py`

**Interfaces:**
- **Consumes:** Task 5, `Perception` (Task 2), and the pair's hourly and daily bars that `prepare_run` already loads.
- **Produces:**
  - **In `replay()`:** when `policy.mode_switch`, it raises `ValueError("the mode switcher needs the pair's hourly and daily history")` if either is missing, builds `Perception(hourly, daily)` once, and passes `perception=perception.at(kline.open_ms)` on every frame.
  - **`Metrics` fields,** filled only for MS: `mode_ms: Counter[str]`, `mode_switches: int`, `uptrend_trades: int`, `uptrend_stops: int`, `uptrend_fades: int`.
    - `mode_ms` is weighted by elapsed time. Each quote adds the time from its own observation to the next replayed quote's to the mode in force after that quote's step:
      - within a minute, that is its own span (`POINT_SPANS_MS`, the replay's 9, 10, 10 and 31 seconds);
      - across a masked or missing span, it is the whole gap, because the mode held before a gap stays in force through it;
      - **at the run's two ends,** the span from the evaluation's start to the first replayed quote goes to Cash, the mode every account starts in, and the span from the last replayed quote to the evaluation's end goes to the last mode. This covers a masked prefix or suffix.
      So a change of mode within a minute, a halt's included, is weighted by the time it held. The modes' times sum to the registered window's length (`REGISTERED_DAYS` × 86,400,000 ms), and the share of time in each mode (spec v2 §8) is computed from them.
    - `mode_switches` counts each change of `account.mode` from one value to another, whatever causes it: a decision, or a halt's Cash. The run's initial Cash is not a switch, and neither is a decision that keeps the mode.
    - `uptrend_trades` counts completed round trips for C5 (spec v2 §8): one for each frame whose report has `uptrend_ended`, never `uptrend_abandoned`. `_finish_uptrend` sets it when an exit's sale, a risk drain's or a halt's liquidation has sold a position that bought something (dust included; Task 5). A position still held or entering at the end is not counted, and neither is one whose halt liquidation is unfinished. An exit that completes on the run's last frame is counted.
    - `uptrend_stops` and `uptrend_fades` count the reports whose `uptrend_exit` is `"stop"` or `"fade"`. They are reported only.
  - **In `summarise`:** MS rows carry their own strategy, `row["strategy"] = MODE_SWITCH_STRATEGY` (a new constant, `"mode switcher (spec-v2)"`), never v1's `gated grid (...)` label. They also carry `row["variant"] = "MS"` and `row["modes"] = {"time_ms": {...}, "switches": n, "uptrend_trades": n, "stops": n, "fades": n, "grid_cycles": metrics.completed_cycles}`.
  - **The end of the run:** for MS, `held` is F's held fragments, as today, plus `simulator.uptrend_held(account)`. So a run ending in a blocked grid keeps F's exemption, a held position or an entry in progress is not owed, and an exit or risk drain under way is owed, as in v1 (spec v2 §6).
    - **The row's exit fields leave the held position out.** `exit_state` values all unpaired inventory, so a held position would show as `final_exit_blocked: "dust"`, with its whole value as `final_unsellable_notional`. For MS rows, those two fields are computed on the unpaired inventory without `uptrend_held(account)`: `""` and 0 when nothing else is unpaired. The position goes in `row["modes"]["held_at_end"] = {"quantity": ..., "value": ...}`, at the exit mark.
  - **`row["modes"]["buy_and_hold_final"]`:** `str(metrics.hold_final)`, so the scorer can end the last month exactly (Task 7).
  - **`variant_policy("MS")`** returns `SimulationPolicy(mode_switch=True, flow_block_entry=True)`. The CLI flag `--mode-switch` stores `"MS"` in `variant`, and the stamp suffix is `-variant-MS`.

- [ ] **Step 1: Write the failing tests:**
  - `test_mode_switch_cli_maps_to_policy`, in the CLI suite with the fake `run_job`.
  - `test_rising_market_enters_uptrend_and_trails_out`, on synthetic hourly, daily and minute bars: 300 days of a rise with down days, alternating +3% and −1.5% a day so that the daily RSI stays below 75, then a 15% fall spread over several UTC days, at most 4% a day. A steady rise would hold the daily RSI at 100 and never allow Uptrend. A one-day drop would trip the 3% daily-loss pause before the stop, which sits about 6% down: at the 60% cap a fall of 5% loses 3%. So the slow fall lets exit 1 sell. It asserts one uptrend trade, a stop exit, `row["modes"]["stops"] == 1`, and `accounting_problems == []`.
  - `test_flat_market_runs_grids_in_grid_mode`, which asserts `grid_cycles > 0` and no Uptrend time.
  - `test_mode_time_is_weighted_by_quote_spans`: a mode change during the third quote's step of a minute adds 19 seconds (9 + 10) to the old mode and 41 seconds (10 + 31) to the new one.
  - `test_mode_time_counts_a_masked_gap_to_the_mode_before_it`: a three-hour masked span adds three hours to the mode in force before it, and the modes' times sum to the run's elapsed time.
  - `test_mode_time_covers_masked_spans_at_both_ends`: a masked first hour counts to Cash, and a masked last hour to the last mode.
  - `test_mode_switches_count_each_change_of_mode`: Cash → Grid → Uptrend → Cash counts 3; a decision that keeps Grid counts 0.
  - `test_run_ending_in_uptrend_is_valid_and_marked_at_exit_value` (Review Focus 2), which asserts `valid`, the absence of any "incomplete" failure, final equity = cash + quantity × the exit mark, `row["modes"]["uptrend_trades"] == 0`, `final_exit_blocked` empty, and the position in `held_at_end`.
  - `test_run_ending_in_a_blocked_grid_keeps_f_fragments_held`: an MS run that ends in Grid mode with F fragments is not incomplete.
  - `test_run_ending_mid_exit_is_incomplete_as_in_v1`: an exit 1 whose sells the participation limit has not finished by the end leaves the run incomplete.
  - `test_exit_completing_on_the_last_quote_counts_the_trade`: a stop whose sale completes on the run's final quote gives `uptrend_trades == 1` and a valid run.
  - `test_entry_that_bought_nothing_counts_no_round_trip`: an entry whose quotes were all below the minimum notional, then stopped, adds 0 to `uptrend_trades`.
  - `test_ms_rows_carry_their_own_strategy`: gated MS rows say `MODE_SWITCH_STRATEGY`, and the ungated baseline rows keep their v1 label.
  - `test_every_variant_choice_maps_to_a_cli_flag`, in `tests/test_backtest_workflow.py`: it loads `backtest.yml` with `yaml`, and asserts that every `variant` choice except V0 has a case arm, and that MS's arm adds `--mode-switch`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement the wiring and the reporting,** and write the method doc's section. It covers what an MS row records, and how to run the mode switcher with `--mode-switch`.
- [ ] **Step 4: Run `pytest -q` and `python scripts/byte_identity.py check`.** Expected: everything passes, and `ALL IDENTICAL`.
- [ ] **Step 5: Commit** `feat: wire the mode switcher into replay, rows and the CLI`.

### Task 7: The spec v2 scorer

**Files:**
- Create: `src/crypto_grid_bot/backtest/acceptance_v2.py`
- Test: `tests/test_acceptance_v2.py`

**Interfaces:**
- **Consumes:** `acceptance.py`'s `read_results`, `annualise`, `gate_ratio`, `certain`, `YEAR_DAYS`, `mean`, `median`, `worst_drop`, `makes_money`, `safer_than_holding`, `integrity`, `economics` (R1, reported), `window_of`, `document_problems`, `primary_problems`, `code_problems`, `pinned`, `MINIMUM_PAIRS`, `thin_windows`, `REGISTERED_DAYS`, `evaluation_window`, `Run` and `ScoringError`; MS rows and F rows from Task 6.
- **The same input checks as v1's scorer,** since `acceptance.runs_of` cannot build MS runs (`variant_of` raises on them):
  - `document_problems` on every input: engine, features, integrity rules, and `valid` agreeing with `failures`;
  - `primary_problems` on every MS and F row: maker 0, taker 0.0009, slippage, participation, spread and capital, and no fill trigger. A run at other fees is refused, not scored;
  - each `Run`'s problems built as `runs_of` builds them, with the file's general failures, so a file-level failure makes its runs invalid (C4);
  - **one comparison mask per window,** as v1's `assess` requires: every input file for a named window must produce the identical `Window` from `window_of`, or the input set is refused before any matrix is built;
  - **exactly one row per key:** one row per role (MS, F, D) × window × pair × path. A duplicate is refused, as v1's `assess` refuses one, so overlapping files cannot overweight a pair;
  - the pins: `code_problems`, and `pinned` for the config and for each `SCORED` and `REPORTED` window's spec and manifest. `read_frozen`'s `INVOCATIONS` are v1's stages, so they are not used;
  - **the registered windows,** which `read_frozen` would otherwise check: each `SCORED` and `REPORTED` window's spec must have its registered evaluation months and length. `full-range-2017-2024` runs 2019-01 to 2024-12, `practice-2022` 2022-06 to 2023-01, and `verify-2024h1` 2024-01 to 2024-06. The day counts come from v1's `REGISTERED_DAYS` (2,192, 245 and 182), and `evaluation_window` must reproduce them. A spec whose hash matches but whose window differs is refused, never scored under the registered name.
- **`MODE_SWITCH_STRATEGY` must not start with "gated grid":** `feature_problems` refuses gated rows whose strategy starts with it but is not V0's.
- **Produces:**
  - `SCORING = "spec-v2-section-8"`, `ROUND_TRIPS_PER_YEAR = 12`, `GATE_SHARE = Fraction(3, 5)`, and `SCORED = ("full-range-2017-2024",)`, with `REPORTED = ("practice-2022", "verify-2024h1")`;
  - `round_trips(row: dict[str, Any]) -> int`, which is `row["modes"]["grid_cycles"] + row["modes"]["uptrend_trades"]`;
  - **the expected matrix, which must be whole:** every included pair of the scored window (`window_of`) × both paths. The CLI refuses the input set unless every key has its MS, F and D rows. A gap is refused, never scored, as v1's final verdict refuses one (`acceptance.py`, "the final verdict needs both stages' whole matrices"). So a results file left out by mistake cannot end v2 with a false fail. C6's rule for an F run that is present but invalid stands: it counts against;
  - **the reported windows too:** each `REPORTED` window needs the same whole MS, F and D matrix, or the input set is refused. So spec v2 §8's sanity runs and its D comparator cannot silently drop out, though neither gates anything;
  - **registered windows only:** an input from a window outside `SCORED` and `REPORTED` is refused, as v1's `read_frozen` refuses one;
  - **minimum evidence:** a scored window that keeps fewer than `MINIMUM_PAIRS` (2) included pairs gives "insufficient evidence", never a pass, through v1's `thin_windows` (spec v1 §5, carried over in full by spec v2 §2);
  - `activity_v2(runs: Sequence[Run], trips: Mapping[str, int]) -> Criterion`, where each run's rate is `Fraction(trips[run.label]) * YEAR_DAYS / run.days` and the mean is exact;
  - `earns_its_place(ms: Sequence[Run], always_grid: Mapping[tuple[str, str, str], Run]) -> Criterion`, keyed by `Run.key`, which includes the window, so that the same pair and path in another window can never stand in:
    - a run passes only when its `return_pct` is > 0 (annualising keeps the sign) and its annualised ratio, `gate_ratio(run.annualised.value, run.max_drawdown_pct)`, beats F's, computed the same way, in the same pair and path;
    - each comparison is decided with `certain` over the interval the two `annualised.bound`s give, as C2's are;
    - a missing or invalid F run counts against. `Run.ratio` is raw, so it is not used here;
  - `upside_capture(row: dict[str, Any]) -> Fraction | None`, from `row["hourly_equity"]`, `row["initial_quote"]`, `row["final_total_equity"]` and `row["modes"]["buy_and_hold_final"]`:
    - month `m` runs from `B(m)`, the first sample at or after its start, to `B(m + 1)`;
    - the first month's `B` is `initial_quote` for both, and the last month ends at the two final values;
    - it sums over the months whose buy-and-hold return is > 0, and is `None` when there are none (spec v2 §8);
  - `role_of(row: dict[str, Any]) -> str | None`, which checks the strategy and the variant together:
    - `"MS"`, the candidate, only with `row["strategy"] == MODE_SWITCH_STRATEGY` (Task 6). An MS variant under another strategy raises;
    - `"F"`, always-grid for C6, only with v1's gated-grid strategy, as `acceptance.variant_of` reads it;
    - `"D"`, reported only;
    - `None` for the ungated V0 rows, which every results file carries (`__main__.py` runs the ungated baseline beside every gated policy). They are ignored;
    - any other row raises `ScoringError`;
  - `main(argv) -> int`, with the CLI `python -m crypto_grid_bot.backtest.acceptance_v2 <results...> --out <verdict.json>`, which writes C1–C6 and the reported readouts. It follows v1's `main`:
    - it refuses an `--out` that is one of the inputs;
    - it writes a "not scored" verdict first, then, on a `ScoringError`, a "refused" verdict with the reasons and exit status 2. So a stale verdict never survives a refused run;
    - the verdict records every input as `acceptance.verdict_json` does: path, SHA-256, dataset, the spec, manifest and config hashes, and the code commit and hash. It also carries v1's `C7_NOTE`, since the reserved window stays closed until C7 is settled or waived (spec v2 §8).

- [ ] **Step 1: Write the failing tests:**
  - `test_activity_threshold_inclusive`: exactly 12 round trips a year passes, and 11.99 fails.
  - `test_a_missing_run_is_refused`: a results set with the scored window's MS file, or its F file, left out is refused with the missing keys named, not scored as a fail. So is an input from an unregistered window.
  - `test_refused_scoring_overwrites_a_stale_verdict`: a run whose inputs fail the pins writes "refused" over an earlier verdict and exits 2, and an `--out` among the inputs is refused.
  - `test_reported_windows_must_be_complete`: an input set with complete full-range files but no `verify-2024h1` rows, or with no D rows in either the scored or a reported window, is refused.
  - `test_inconsistent_comparison_masks_are_refused`: an MS file and an F file of the same window whose cross-checks exclude different pairs are refused.
  - `test_duplicate_rows_are_refused`: two MS rows for one window, pair and path are refused.
  - `test_a_wrong_window_is_refused`: a `full-range-2017-2024` spec that starts in 2019-02, and so lasts 2,161 days, is refused.
  - `test_one_included_pair_is_insufficient_evidence`: a scored window whose data checks leave one included pair gives "insufficient evidence", even when that pair's MS runs would pass C1–C6.
  - `test_gate_needs_positive_return_and_beats_always_grid`
  - `test_gate_uses_annualised_returns_and_counts_a_missing_or_invalid_always_grid_against`, with `days = 2192`:
    - the run returns 10% with a 5% drawdown, and F returns 20% with 9.9%;
    - the raw ratios (2.0 and 2.0202) would favour F, but the annualised ones (0.3202 and 0.3116) favour the run, so it passes;
    - a run with no F run, or with an invalid one, fails.
  - `test_upside_capture_uses_month_boundary_samples`: a move between a month's last hourly sample and the next month's first one counts in the earlier month, and the first month starts from `initial_quote`.
  - `test_gate_share_boundary`: 3 of 5 passes, and 2 of 5 fails.
  - `test_upside_capture_two_months`: buy-and-hold +10% in month 1 and −5% in month 2, the bot +4% and +1%, gives capture 0.4.
  - `test_c1_to_c4_reuse_v1_functions`: the same verdicts as `acceptance.worst_drop` and friends on shared fixtures.
  - `test_cli_scores_ms_against_f_and_ignores_the_ungated_rows`: real-shaped MS and F results files, each with its ungated V0 rows, are scored, and the D rows, which ride on the MS files only, are reported. A file with variant A's rows is refused, and so are a set with no F rows and a row with variant MS under v1's gated-grid strategy.
  - `test_r1_is_reported_and_gates_nothing`
- [ ] **Step 2: Run `pytest tests/test_acceptance_v2.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement `acceptance_v2.py`.** `acceptance.py` is unchanged, so spec v1's scorer stays as frozen.
- [ ] **Step 4: Run `pytest -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: spec v2 scorer (C1-C6 adapted, upside capture reported)`.

*Open Tasks 6–7 as one PR (spec §9 step 6). The evaluation runs follow once the long-window data plan has delivered the dataset.*
