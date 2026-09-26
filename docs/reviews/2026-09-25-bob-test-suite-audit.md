# Test-Suite Audit: isolation, order, hash seeds, warnings, gaps

- **Task file:** `docs/tasks/2026-09-25-bob-test-suite-audit.md`
- **Author:** IBM Bob (task run), 2026-09-25
- **Commit:** `876f7ce9d3a32b4a31bc558a0eb038a462c1472e`
- **Python:** 3.12.14
- **Working outputs:** `data/t-baseline.log`, `data/t-alone-*.log`, `data/t-reverse.log`, `data/t-hashseeds.log`, `data/t-warnings-as-errors.log`, `data/t-durations.log`, `data/t-flakiness.log`, `data/untested.py` (SHA-256: `db563af487b88c11c7f5cc9875e16745989aa81e5cffd88c665a05454ab0c17f`), `data/spot_check.py` (SHA-256: `65dd777956b29b08db4827a6de0c505b9ee6d35e6c47790362065616e8db7e32`)

**Stop condition check:** `git status --porcelain --untracked-files=all` returned empty (working tree clean, `data/` is gitignored). No stop conditions were triggered. All steps completed.

---

## Step 0 — Environment

| Item | Value |
|------|-------|
| Commit | `876f7ce9d3a32b4a31bc558a0eb038a462c1472e` |
| Python version | Python 3.12.14 |

Command: `git rev-parse HEAD && python --version`

---

## Steps 1–7 — Results Table

| Step | Mode | Passed | Failed | Skipped | Subtests | Exit |
|------|------|--------|--------|---------|----------|------|
| 1 — Baseline | `pytest` | 314 | 0 | 0 | 449 | 0 |
| 1 — self-check | `python -m crypto_grid_bot.app --self-check` | pass | — | — | — | 0 |
| 1 — paper-demo | `python -m crypto_grid_bot.app --paper-demo` | pass | — | — | — | 0 |
| 2 — Each file alone | 18 files, all pass | 314 | 0 | 0 | — | 0 (all) |
| 3 — Reverse order | `pytest $(ls tests/test_*.py \| sort -r)` | 314 | 0 | 0 | 449 | 0 |
| 4 — PYTHONHASHSEED=0 | full suite | 314 | 0 | 0 | 449 | 0 |
| 4 — PYTHONHASHSEED=1 | full suite | 314 | 0 | 0 | 449 | 0 |
| 4 — PYTHONHASHSEED=2 | full suite | 314 | 0 | 0 | 449 | 0 |
| 4 — PYTHONHASHSEED=4242 | full suite | 314 | 0 | 0 | 449 | 0 |
| 4 — PYTHONHASHSEED=random | full suite | 314 | 0 | 0 | 449 | 0 |
| 5 — Warnings as errors | `-X dev -W error -m pytest` | 314 | 0 | 0 | 449 | 0 |
| 6 — Durations | `pytest --durations=25` | 314 | 0 | 0 | 449 | 0 |
| 7 — Flakiness run 1 | full suite | 314 | 0 | 0 | 449 | 0 |
| 7 — Flakiness run 2 | full suite | 314 | 0 | 0 | 449 | 0 |
| 7 — Flakiness run 3 | full suite | 314 | 0 | 0 | 449 | 0 |
| 7 — Flakiness run 4 | full suite | 314 | 0 | 0 | 449 | 0 |
| 7 — Flakiness run 5 | full suite | 314 | 0 | 0 | 449 | 0 |

**All 18 test files pass alone** (step 2 exit codes all 0). No file depends on another file's state.

**No isolation, order, or hash-seed failures.** No flaky tests found across 7 total full runs (including baseline).

**Step 1 baseline output (key lines):**
```
314 passed, 449 subtests passed in 8.96s
configuration: valid
mode: paper
universe: top 100 plus NIGHT
sample regime: range (80% confidence)
live trading: unavailable by design
{"cash":"116.6135835750000000000000000000000","cycles":30,"fees":"5.12704835","fills":270,...}
```

**Step 5 — No warnings-as-errors failures.** `python -X dev -W error -m pytest -q -p no:cacheprovider` exited 0 with `314 passed, 449 subtests passed in 9.86s`. No warnings were elevated to errors.

---

## Step 6 — Slowest 25 Tests

Command: `pytest -q -p no:cacheprovider --durations=25`, exit code 0.

| Duration (s) | Test |
|-------------|------|
| 1.52 | `tests/test_strategy_recovery.py::StrategyRecoveryTests::test_minute_cadence_exits_after_six_hours_and_recenters_after_a_day` |
| 1.08 | `tests/test_backtest_replay.py::ReplayTests::test_replay_accounting_identities_hold_for_both_paths` |
| 0.88 | `tests/test_backtest_replay.py::DegenerateHistoryTests::test_already_invested_account_crosses_into_degenerate_history` |
| 0.57 | `tests/test_backtest_replay.py::MeasurementTests::test_completed_cycles_count_fully_filled_grid_sells` |
| 0.49 | `tests/test_backtest_replay.py::MeasurementTests::test_range_exit_losses_are_labelled_and_reconcile` |
| 0.32 | `tests/test_backtest_replay.py::ReplayTests::test_rejected_frames_do_not_inflate_the_range_exit_count` |
| 0.21 | `tests/test_backtest_replay.py::MeasurementTests::test_hard_drawdown_liquidation_is_labelled_and_fails_the_halt_veto` |
| 0.18 | `tests/test_backtest_replay.py::FeatureChronologyTests::test_unfinished_and_future_candles_cannot_change_a_decision` |
| 0.18 | `tests/test_simulation_runner.py::SimulatorTests::test_demo_loops_and_is_repeatable` |
| 0.17 | `tests/test_strategy_recovery.py::StrategyRecoveryTests::test_fifty_shallow_oscillations_keep_trading_and_harvesting` |
| 0.13 | `tests/test_simulation_runner.py::SimulatorTests::test_cash_and_fees_reconcile_to_journal_and_profit_split` |
| … (remaining 14 all ≤ 0.12 s) | — |

The longest test (`1.52 s`) runs 30 minutes of 1-second simulation frames. The top-5 slowest are all integration-style tests in `test_strategy_recovery.py` and `test_backtest_replay.py`. No single test is unreasonably slow; the suite total (~9 s) is well within CI limits.

---

## Step 8 — Coverage by Reading

**Method:** Listed every public function, class and method (no leading underscore) under `src/crypto_grid_bot/`. Grepped `tests/` for each name with word boundaries. For names with no grep hit, I read the source to determine whether the function is reached indirectly through a tested function.

`data/untested.py` (SHA-256: `db563af487b88c11c7f5cc9875e16745989aa81e5cffd88c665a05454ab0c17f`) contains the full list of 148 public names checked.

### `crypto_grid_bot.config`

| Name | Test file | Notes |
|------|-----------|-------|
| `ConfigurationError` | `test_config.py` | Directly imported |
| `BotConfig` | — (grep: 0 direct hits) | **Reached indirectly**: constructed by `load_config()` which is tested by `test_config.py` and used as a fixture in every integration test. Reached by `test_config.py::ConfigLoaderTests`. |
| `load_config` | `test_config.py`, `test_backtest_replay.py`, `test_simulation_runner.py`, `test_strategy_recovery.py`, `test_backtest_cli.py` | Directly tested |

### `crypto_grid_bot.market_data.parsing`

| Name | Test file | Notes |
|------|-----------|-------|
| `DataError` | Multiple | Directly imported |
| `symbol_name` | — | **Reached indirectly**: called inside `parse_instrument`, `parse_candles`, `parse_book`, `amount` (all tested). Also called in `Collector.capture` which is tested. Not named in any test directly. |
| `integer` | — | **Reached indirectly**: called inside `parse_candles`, `parse_book` (both tested in `test_market_data.py`). |
| `amount` | `test_market_data.py` (imported directly) | Directly tested |
| `Candle` | — | **Reached indirectly**: `parse_candles` returns `tuple[Candle, ...]`; its fields are accessed in `diagnostics` tests. The dataclass itself is never named in a test, but its construction and field access are covered via `parse_candles`. |
| `Instrument` | — | **Reached indirectly**: `parse_instrument` returns an `Instrument`; its fields are accessed in `Collector.capture` test. Never directly imported in tests. |
| `Book` | — | **Reached indirectly**: `parse_book` returns a `Book`; its `midpoint`, `spread_pct` properties are exercised via `diagnostics`. Never directly imported in tests. |
| `parse_instrument` | `test_market_data.py` | Directly tested |
| `parse_candles` | `test_market_data.py` | Directly tested |
| `parse_book` | `test_market_data.py` | Directly tested |
| `diagnostics` | `test_market_data.py` | Directly tested |

**Gap:** `symbol_name`, `integer` have no direct test; validation edge cases (e.g. symbol with non-ASCII or `integer` with `type(value) is not int`) are not independently exercised. They are only tested as side effects of `parse_*` tests.

### `crypto_grid_bot.market_data.client`

| Name | Test file | Notes |
|------|-----------|-------|
| `FeedError` | `test_market_data.py`, `test_price_stream.py` | Directly tested |
| `Response` | `test_market_data.py` | Imported; used to construct test doubles |
| `Transport` | — | Protocol class; used implicitly via `PublicClient(transport=...)` in tests. No direct import needed. **Reached indirectly.** |
| `https_proxy` | `test_market_data.py` | Directly tested |
| `https_connection` | — | **Reached indirectly**: called by `public_get` and `archive_get`. Tested through proxy tests (`test_https_proxy_tunnels_*`) which exercise the connection construction via mocked sockets. |
| `public_get` | `test_market_data.py` | Directly tested |
| `PublicClient` | `test_market_data.py` | Directly tested |

### `crypto_grid_bot.market_data.collector`

| Name | Test file | Notes |
|------|-----------|-------|
| `encode` (collector) | `test_market_data.py` | Imported (`from crypto_grid_bot.market_data.collector import Collector, encode`) |
| `server_time` | — | **Reached indirectly**: called inside `Collector.capture()`, which is tested by `test_capture_uses_closed_candles_and_never_authorizes_orders` and several other tests in `test_market_data.py`. The function's error path (`missing exchange server clock`) is not independently tested. |
| `Collector` | `test_market_data.py` | Directly tested |

**Gap:** `server_time` error path (when `payload` lacks `"serverTime"`) has no dedicated test.

### `crypto_grid_bot.market_data.store` (ObservationStore)

| Name | Test file | Notes |
|------|-----------|-------|
| `ObservationStore` | `test_market_data.py` | Directly tested (multiple tests: restart, rollback, ban, collision, etc.) |

### `crypto_grid_bot.market_data.stream`

| Name | Test file | Notes |
|------|-----------|-------|
| `BookTick` | — | **Reached indirectly**: returned by `parse_book_ticker` (tested). The `on_tick` lambda in `PriceStream` tests receives `BookTick` objects. Not directly imported. |
| `stream_url` | `test_price_stream.py` | Directly tested |
| `parse_book_ticker` | `test_price_stream.py` | Directly tested |
| `PriceBook` | `test_price_stream.py` | Directly tested |
| `StreamStats` | — | **Reached indirectly**: `PriceStream.run()` returns a `StreamStats`, whose fields are accessed in multiple stream tests via `stats.connects`, `stats.ticks`, etc. Never directly imported. |
| `NoRedirectConnect` | `test_price_stream.py` (via `stream_module.NoRedirectConnect`) | Tested via module reference |
| `default_connector` | `test_price_stream.py` (via `stream_module.default_connector`) | Tested via module reference |
| `PriceStream` | `test_price_stream.py` | Directly tested |
| `summarize` | — (grep: 0 hits) | **UNTESTED**: The module-level `summarize()` function aggregates a `PriceStream`'s tick history into a summary dict. It is called by `run_stream()` (also untested). No test directly invokes either. |
| `run_stream` | — (grep: 0 hits as module function) | **UNTESTED**: The module-level `run_stream()` wraps `PriceStream.run()` with an `asyncio.run()` and calls `summarize()`. Only tested via the CLI integration test for `--stream-prices`, which is in `test_backtest_cli.py` — verified below. |

**Clarification for `run_stream`:** `test_backtest_cli.py` tests the CLI mode `--stream-prices`; let me confirm it reaches `run_stream`:
```
grep -n "stream_prices\|run_stream\|stream-prices" tests/test_backtest_cli.py
```
Result (verified by reading `test_backtest_cli.py`): the CLI integration test patches at the `app` module level and does not call `run_stream` directly. The function `run_stream` is reachable from `app.main()` when `--stream-prices` is passed, but the test patches `run_stream` out with a mock, so the real `summarize` + `run_stream` logic is **not exercised** by any test.

### `crypto_grid_bot.portfolio.profit_vault`

| Name | Test file | Notes |
|------|-----------|-------|
| `ProfitVaultState` | `test_profit_vault.py` | Directly used (imported or constructed) |
| `ProfitAllocation` | — | **Reached indirectly**: `ProfitVault.allocate()` returns a `ProfitAllocation`. Its fields are accessed in `test_profit_vault.py` tests. Never directly imported. |
| `ProfitVault` | `test_profit_vault.py` | Directly tested |

### `crypto_grid_bot.risk.engine`

| Name | Test file | Notes |
|------|-----------|-------|
| `RiskEngine` | `test_risk.py` | Directly tested |

### `crypto_grid_bot.strategy.grid`

| Name | Test file | Notes |
|------|-----------|-------|
| `GridNotViable` | `test_grid.py` | Directly imported/tested |
| `GridBuilder` | `test_grid.py` | Directly tested |

### `crypto_grid_bot.strategy.opportunity`

| Name | Test file | Notes |
|------|-----------|-------|
| `OpportunityScorer` | `test_opportunity.py` | Directly tested |

### `crypto_grid_bot.strategy.regime`

| Name | Test file | Notes |
|------|-----------|-------|
| `RegimeThresholds` | `test_regime.py` | Directly used |
| `thresholds_from_config` | — | **Reached indirectly**: called in `PaperSimulator.__init__()` which is used by simulation tests. Reads config thresholds and returns `RegimeThresholds`. Not independently tested. |
| `RegimeClassifier` | `test_regime.py` | Directly tested |

### `crypto_grid_bot.strategy.rotation`

| Name | Test file | Notes |
|------|-----------|-------|
| `RotationState` | `test_rotation.py` | Directly used |
| `RotationPolicy` | `test_rotation.py` | Directly tested |

### `crypto_grid_bot.simulation.models`

| Name | Test file | Notes |
|------|-----------|-------|
| `decimal` | — | **Reached indirectly**: called by `Account.from_dict()` which is called by `StateStore.read()`. Tested via simulation tests that read/write accounts. |
| `nonnegative` | — | **Reached indirectly**: called by `Account.validate()`, `place()`, `match()`, etc., all tested. |
| `floor_step` | — | **Reached indirectly**: used extensively in `execution.py` and `runner.py`; all paths exercised by simulation tests. |
| `seconds_between` | — | **Reached indirectly**: called in `PaperSimulator._track_range()`. Exercised by `test_strategy_recovery.py` outside-range tests. |
| `MarketRules` | `test_simulation_execution.py`, `test_backtest_replay.py` | Directly used |
| `Quote` | `test_simulation_execution.py`, `test_backtest_replay.py` | Directly used |
| `LimitOrder` | `test_simulation_execution.py`, `test_backtest_replay.py` | Directly used |
| `Fill` | — | **Reached indirectly**: returned by `place()`, `match()`, etc. Accessed via `asdict(fill)` in runner. Its fields are read in tests but the class is never directly imported. |
| `Account` | `test_simulation_execution.py`, `test_backtest_replay.py` | Directly used |
| `timestamp` | — | **Reached indirectly**: used in validation and tracking; exercised through simulation tests. |

### `crypto_grid_bot.simulation.execution`

| Name | Test file | Notes |
|------|-----------|-------|
| `place` | `test_simulation_execution.py`, `test_backtest_replay.py` | Directly tested |
| `cancel` | `test_simulation_execution.py` | Directly tested |
| `match` | `test_simulation_execution.py`, `test_backtest_replay.py` | Directly tested |
| `reduce_unreserved` | `test_simulation_execution.py` | Directly tested |
| `liquidate` | `test_simulation_execution.py` | Directly tested |

### `crypto_grid_bot.simulation.runner`

| Name | Test file | Notes |
|------|-----------|-------|
| `TransientFrame` | — | **Reached indirectly**: raised by `_validate_frame()`, caught in `_step()`. Exercised by stale-quote tests in `test_strategy_recovery.py`, but the exception class itself is never directly imported in tests. |
| `SimulationPolicy` | `test_strategy_recovery.py` | Directly tested |
| `Frame` | `test_simulation_runner.py`, `test_backtest_replay.py`, `test_strategy_recovery.py` | Directly used |
| `PaperSimulator` | `test_simulation_runner.py`, `test_backtest_replay.py`, `test_strategy_recovery.py` | Directly tested |

### `crypto_grid_bot.simulation.store`

| Name | Test file | Notes |
|------|-----------|-------|
| `encode` (sim_store) | `test_simulation_runner.py` | Used via `PaperSimulator` (indirectly) |
| `StateStore` | — | **Reached indirectly**: used by `PaperSimulator.__init__()`. The `StateStore.transact`, `StateStore.read`, `StateStore.close` methods are all exercised through simulation tests. Never directly imported in tests. |

### `crypto_grid_bot.simulation.control`

| Name | Test file | Notes |
|------|-----------|-------|
| `decode_frame` | `test_strategy_recovery.py` | Directly tested |
| `resume_paper` | `test_strategy_recovery.py` | Directly tested |

### `crypto_grid_bot.simulation.demo`

| Name | Test file | Notes |
|------|-----------|-------|
| `demo_frames` | `test_simulation_runner.py`, `test_strategy_recovery.py` | Directly tested |
| `run_demo` | `test_simulation_runner.py` | Directly tested |

### `crypto_grid_bot.backtest.klines`

| Name | Test file | Notes |
|------|-----------|-------|
| `Kline` | `test_backtest_data.py`, `test_backtest_replay.py` | Directly used |
| `FileStats` | — | **Reached indirectly**: returned by `parse_rows` and `read_archive`. Tests in `test_backtest_data.py` call `parse_rows` and inspect the returned stats via the tuple second member, but never import `FileStats` directly. |
| `month_bounds_ms` | — | **Reached indirectly**: called by `parse_rows`, `read_archive`, `load_spec`, etc. All tested indirectly through archive parsing tests. |
| `parse_rows` | `test_backtest_data.py` | Directly tested |
| `read_archive` | `test_backtest_data.py` | Directly tested |
| `read_member` | — | **Reached indirectly**: called by `read_archive` (tested) and `read_funding_archive` (tested). |
| `aggregate` | `test_backtest_data.py`, `test_backtest_replay.py` | Directly tested |

### `crypto_grid_bot.backtest.features`

| Name | Test file | Notes |
|------|-----------|-------|
| `SeriesFeatures` | `test_backtest_replay.py` | Directly used |
| `Inputs` | — | **Reached indirectly**: returned by `FeatureEngine.at()`. Fields accessed in replay tests. Never directly imported in tests. |
| `FeatureEngine` | `test_backtest_replay.py` | Directly tested |

### `crypto_grid_bot.backtest.funding`

| Name | Test file | Notes |
|------|-----------|-------|
| `FundingRecord` | `test_funding.py` | Directly used |
| `FundingState` | — | **Reached indirectly**: returned by `FundingSignal.state()`. Fields are accessed in funding tests (`.available`, `.blocks`, `.reason`). Never directly imported. |
| `parse_funding_rows` | `test_funding.py` | Directly tested |
| `read_funding_archive` | `test_funding.py` | Directly tested |
| `FundingSignal` | `test_funding.py` | Directly tested |

### `crypto_grid_bot.backtest.dataset`

| Name | Test file | Notes |
|------|-----------|-------|
| `BasketExclusion` | — | **Reached indirectly**: constructed by `load_spec()` when `basket_exclusions` are present in a spec. `test_backtest_data.py` exercises `load_spec` with basket exclusions. The `BasketExclusion` dataclass itself is never directly imported. |
| `DatasetSpec` | — | **Reached indirectly**: returned by `load_spec()` which is tested in `test_backtest_data.py`. Methods like `.months()`, `.required()` are called in dataset tests via the returned spec. |
| `fee_rate` | — | **Reached indirectly**: called inside `load_spec()`. Exercised by valid and invalid spec tests. |
| `load_spec` | `test_backtest_data.py` | Directly tested |
| `archive_path` | `test_backtest_data.py` | Directly tested |
| `local_path` | `test_backtest_data.py` | Directly tested |
| `archive_get` | — | **UNTESTED**: The real `archive_get` (HTTPS download from Binance) is never called in tests; `test_backtest_data.py` uses a `FakeArchive` callable. The real network function is not tested (expected: no live network in test). |
| `exchange_filters` | — | **UNTESTED**: The real `exchange_filters` (live Binance API call via `PublicClient`) is never called in tests; `fetch_dataset` is exercised with a lambda stub. |
| `sha256_file` | — | **Reached indirectly**: called inside `fetch_file()` to verify cached archives. `test_backtest_data.py::test_cached_file_is_not_refetched_when_checksum_matches` exercises this path (the test creates a real temp file with a matching hash). Verified by reading the test. |
| `fetch_file` | `test_backtest_data.py` | Directly tested |
| `fetch_dataset` | `test_backtest_data.py` | Directly tested |
| `write_manifest` | — | **Reached indirectly**: called from `fetch_dataset` in some paths, but most tests use `load_manifest` directly. `test_backtest_data.py::test_manifest_round_trip_preserves_all_fields` calls `write_manifest` explicitly. Verified by reading the test. Actually tested. |
| `load_manifest` | `test_backtest_data.py` | Directly tested |
| `verify_dataset` | `test_backtest_data.py` | Directly tested |

**Correction after reading:** `write_manifest` IS directly called in `test_backtest_data.py`. `archive_get` and `exchange_filters` are the two truly untested network functions (by design: no live network in tests).

### `crypto_grid_bot.backtest.replay`

| Name | Test file | Notes |
|------|-----------|-------|
| `RunConfig` | `test_backtest_replay.py` | Directly used |
| `bar_quotes` | `test_backtest_replay.py` | Directly tested |
| `reason_key` | `test_backtest_replay.py` | Directly tested |
| `depth_multiple` | `test_backtest_replay.py` | Directly tested |
| `signals_for` | `test_backtest_replay.py` | Directly tested |
| `candidate_for` | `test_backtest_replay.py` | Directly tested |
| `Metrics` | `test_backtest_replay.py` | Directly used |
| `RequestCountingOrders` | `test_backtest_replay.py` | Directly used |
| `order_requests` | `test_backtest_replay.py` | Directly tested |
| `replay` | `test_backtest_replay.py` | Directly tested |
| `check_accounting` | `test_backtest_replay.py` | Directly tested |
| `load_hourly` | — | **UNTESTED**: Reads from local `.zip` archives and is not exercised in tests (requires local data files). |
| `load_daily` | — | **UNTESTED**: Same as above. |
| `cross_check_daily` | `test_backtest_replay.py` | Directly tested |
| `load_minutes` | — | **UNTESTED**: Generator over local archives; not exercised in tests. |
| `compare_bars` | `test_backtest_replay.py` | Directly tested |
| `cross_check_hourly` | `test_backtest_replay.py` | Directly tested |
| `check_hourly_series` | `test_backtest_replay.py` | Directly tested |
| `summarise` | — | **UNTESTED**: Formats a `Metrics` result dict. Never imported or called in any test. |
| `rules_for` | — | **UNTESTED**: Constructs `MarketRules` from instrument dict. Called by the CLI (`backtest/__main__.py`) but not exercised in any test. |

### Summary of truly untested or network-only functions

The following public functions are NOT reached by any test (directly or indirectly) and are not network-only:

| Module | Function | Reason |
|--------|----------|--------|
| `market_data.stream` | `summarize` | No test imports or calls it; `run_stream` is patched in CLI tests |
| `market_data.stream` | `run_stream` | Real function never called; mock is used in CLI test |
| `backtest.dataset` | `archive_get` | Network-only by design; `FakeArchive` replaces it |
| `backtest.dataset` | `exchange_filters` | Network-only by design; lambda stub replaces it |
| `backtest.replay` | `load_hourly` | Requires local archive files; no test data available |
| `backtest.replay` | `load_daily` | Same |
| `backtest.replay` | `load_minutes` | Same |
| `backtest.replay` | `summarise` | Never called in any test |
| `backtest.replay` | `rules_for` | Only in CLI path; no test reaches it |

The following are "weakly tested" (no dedicated tests; only reached indirectly):
`symbol_name`, `integer`, `server_time` error path, `thresholds_from_config`, `TransientFrame` class identity.

---

## Step 9 — Fail-Closed Spot Check

Script: `data/spot_check.py` (SHA-256: `65dd777956b29b08db4827a6de0c505b9ee6d35e6c47790362065616e8db7e32`). Command: `python data/spot_check.py`. Exit code: 0. All five checks printed `OK:`.

### 1. `ProfitVault.confirm_transfer` — amount > pending_reserve

**Function:** `portfolio/profit_vault.py`, `ProfitVault.confirm_transfer()`, line 113.
**Dangerous input:** `state.pending_reserve = Decimal("5")`, `amount = Decimal("10")`.
**Expected behaviour:** `ValueError("transfer amount is not pending")`.
**What the code does:** Line 113 explicitly checks `if amount > state.pending_reserve: raise ValueError(...)`. **Correctly fails closed.**
**Observed:** `OK: confirm_transfer rejects amount > pending: transfer amount is not pending`.

### 2. `amount()` — extreme negative exponent

**Function:** `market_data/parsing.py`, `amount()`, lines 40–43.
**Dangerous input:** `"1E-9999"` (a valid Decimal string, but exponent −9999).
**Expected behaviour:** `DataError("unsupported decimal precision")`.
**What the code does:** After constructing the `Decimal`, checks `not -18 <= exponent <= 18`. Extreme exponents from Binance responses could cause downstream `Decimal` operations to exhaust memory or run for unreasonably long. **Correctly fails closed.**
**Observed:** `OK: amount() rejects 1E-9999: unsupported decimal precision`.

### 3. `ObservationStore.save` — `orders_authorized=True`

**Function:** `market_data/store.py`, `ObservationStore.save()`, line 80.
**Dangerous input:** observation dict with `orders_authorized=True`.
**Expected behaviour:** `DataError("only current observe-only records can be saved")`.
**What the code does:** After parsing the JSON, checks `item["orders_authorized"] is not False` before any write. This prevents any accidentally authorized observation from being persisted. **Correctly fails closed.**
**Observed:** `OK: save() rejects orders_authorized=True: only current observe-only records can be saved`.

### 4. `parse_candles` — unclosed (future) candle

**Function:** `market_data/parsing.py`, `parse_candles()`, line 148.
**Dangerous input:** 50 closed hourly candles followed by one whose `close_ms >= server_ms` (i.e., not yet closed by the exchange).
**Expected behaviour:** `DataError("candle is unclosed or not a UTC hourly candle")`.
**What the code does:** Checks `end >= server_ms` per candle. A candle from the in-progress hour would have been delivered prematurely and could contain incorrect OHLC. **Correctly fails closed.**
**Observed:** `OK: parse_candles rejects unclosed candle: candle is unclosed or not a UTC hourly candle`.

### 5. `RiskEngine.evaluate` — negative active_equity

**Function:** `risk/engine.py`, `RiskEngine.evaluate()`, line 30.
**Dangerous input:** `PortfolioSnapshot(active_equity=-1.0, day_start_equity=100.0, high_water_mark=100.0, data_age_seconds=0)`.
**Expected behaviour:** `RiskDecision(PAUSE, 0.0, ("invalid portfolio equity",))`.
**What the code does:** First line of evaluation checks `any(not isfinite(value) or value < 0 for value in equities)`. A negative equity (from a bug or race condition) triggers PAUSE immediately, never proceeding to drawdown calculations. **Correctly fails closed.**
**Observed:** `OK: RiskEngine.evaluate rejects negative equity: pause ('invalid portfolio equity',)`.

---

## Ideas and Proposals

Ordered by risk (highest first). Each proposal names the function, a concrete input, and the expected behaviour precisely enough to write the test.

### P1 — `symbol_name` edge cases (risk: medium-high; parsing gateway)

**Why:** `symbol_name` is the gateway for every external symbol from Binance. A bypass could cause SQL injection, path traversal (in archive paths) or downstream mismatches. It has no dedicated test.
**Function:** `market_data/parsing.py::symbol_name`.
**Tests to add:**
- Input `"ADA USDT"` (space): expect `DataError("symbol must contain 2-24 uppercase...")`.
- Input `"A"` (too short): expect `DataError`.
- Input `"A" * 25` (25 chars, too long): expect `DataError`.
- Input `"adausdc"` (lowercase): expect `DataError`.
- Input `"ADAUSDC123"` (valid): expect `"ADAUSDC123"` returned.

### P2 — `integer` edge cases (risk: medium-high; parsing gateway)

**Why:** `integer` validates Binance's numeric fields (update IDs, trade counts). The check `type(value) is not int` catches JSON floats (e.g. `1.0` from a lenient parser). No dedicated test exists.
**Function:** `market_data/parsing.py::integer`.
**Tests to add:**
- Input `1.0` (float): expect `DataError("expected a bounded non-negative integer")`.
- Input `"5"` (string): expect `DataError`.
- Input `-1` (negative): expect `DataError`.
- Input `10**16 + 1` (too large): expect `DataError`.
- Input `0` (valid zero): expect `0`.

### P3 — `server_time` missing-key path (risk: medium; clock coherence)

**Why:** `server_time` is called twice per capture. If the exchange sends a malformed time response (e.g. `{}` or `{"serverTime": "abc"}`), the capture should fail rather than proceed with a wrong clock. The error path is exercised only incidentally by `Collector.capture` mock tests.
**Function:** `market_data/collector.py::server_time`.
**Tests to add:**
- Input `{}` (no `serverTime` key): expect `DataError("missing exchange server clock")`.
- Input `{"serverTime": "not-an-int"}` (wrong type): expect `DataError` (from `integer`).
- Input `{"serverTime": 1704067200000}` (valid): expect `1704067200000`.

### P4 — `stream.summarize` correctness (risk: medium; CLI output integrity)

**Why:** `summarize` is the only function that assembles the `--stream-prices` JSON output. It currently has no test at all. A bug there (e.g. division by zero when `ticks=0`, or a missing key) would silently corrupt the CLI output.
**Function:** `market_data/stream.py::summarize`.
**Tests to add:**
- Call with a `PriceStream` whose `stats` has zero ticks and no recorded ticks: verify `"ticks": 0`, `"max_gap_ms": None`, `"last_bid": None` for each symbol.
- Call after simulating two ticks for one symbol: verify `"ticks": 2`, `max_gap_ms` equals the ms difference, bid/ask match the last tick.
- Verify `"orders_authorized": False` is always present.

### P5 — `replay.summarise` correctness (risk: medium; replay report integrity)

**Why:** `summarise` formats the entire replay result dict. Bugs (wrong field name, missing key, wrong Decimal-to-float conversion) would corrupt every replay report silently.
**Function:** `backtest/replay.py::summarise`.
**Tests to add:**
- Call with a known `RunConfig`, `Metrics` and `Account` (e.g. from the existing replay test fixture): verify that `"return_pct"`, `"max_drawdown_pct"` are correct floats, `"final_total_equity"` is a string Decimal, `"accounting_problems"` matches what `check_accounting` returned, `"news_component"` contains `"ABSENT"`.
- Verify `"orders_authorized"` is absent from the output (it is not in the current summary; confirm no accidental authorization field appears).

### P6 — `thresholds_from_config` round-trip (risk: low-medium; config/strategy boundary)

**Why:** `thresholds_from_config` bridges `BotConfig` to `RegimeThresholds`. If a config field name changes (e.g. a rename), the function would silently pass the wrong value. No test checks the mapping.
**Function:** `strategy/regime.py::thresholds_from_config`.
**Test to add:**
- Load the default config with `load_config("config/default.toml")`, pass to `thresholds_from_config`, assert that `result.bull == config.bull_threshold`, `result.bear == config.bear_threshold`, and all other fields match their `BotConfig` counterparts.

---

*End of report.*
