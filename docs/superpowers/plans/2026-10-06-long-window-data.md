# Long-Window Data Implementation Plan

> **How this plan runs:** task by task, each with a fresh implementer and then a fresh reviewer, and a whole-branch review at the end. That is the subagent-driven execution the owner chose on 2026-10-06. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `full-range-2017-2024` replayable under spec v1 §5's frozen data rules, so that spec v2 can be judged on it, and leave every v1 stage-1 result identical.

**Architecture:**
- **A repairing reader** returns an archive's bars and statistics together with the hours it could not trust, instead of rejecting the whole archive.
- **A pure masking module** decides, month by month, which hours enter the replay: rules 1, 2 and 5, the 17% coin-month rule, and the days that rule 3 skips.
- **Every consumer gets the masks:** a mask phase computes one mask per symbol before the cross-checks, and the CLI passes the whole `{symbol: mask}` map to the checks and to every run. `prepare_run` applies it to the pair, the proxy and every basket series, and variant D's minutes use it too.
- **The CLI** computes the comparison mask before the first job, writes it into `results.json`, and applies XRP's actual-quotes test.
- **The data:** the frozen dataset specs, Bob's re-fetch with a compact digest, the manifest, and a stage-1 identity check before any v2 run.

**Tech Stack:** Python 3.12, `decimal`, pytest, ruff, mypy, bandit. No new dependencies.

**Spec:** `docs/EXPERIMENT_SPEC_V2.md` §9, step 2, which applies `docs/EXPERIMENT_SPEC_V1.md` §5 (the post-mask expected set; rules 1–5 and 8; the 17% rule) and §4 (the two long-window definitions). Plan 1 (`2026-10-06-mode-switcher.md`) covers steps 3–6.

## Global Constraints

- **Paper-only.** No live trading or keys. Tests use no network. Bob's fetch (Task 9) is the only network step, on `data.binance.vision` alone.
- **Nothing after 2024-12** is fetched, read or replayed (spec v1 §7).
- **Stage-1 identity** (decision 18, spec v1 §6). Re-running stage 1 must give `results.json` files identical to stage 1's, except `code_commit` and `code_sha256`. Spec v1 §6 lets only the mask-report fields of §5 rule 1 differ, and only as empty or zero. So:
  - every new field is written only when it is non-empty or non-zero;
  - a load without a mask behaves exactly as today, with the strict reader;
  - this plan does not touch `config/datasets/practice-2022.*`, `config/datasets/verify-2024h1.*`, `config/default.toml`, `replay.INTEGRITY_RULES` or `ENGINE_VERSION`.
- **Order with Plan 1:**
  - Plan 1's Task 0, the byte check, merges first, because this plan's checks use it.
  - This plan applies masks inside `prepare_run`, so Plan 1's `Perception` reads post-mask hourly bars without any change to Plan 1.
  - Whichever plan merges second rebases onto the other in `replay.py`, `jobs.py`, `__main__.py` and `.github/workflows/backtest.yml`.
  - MS rows carry this plan's per-run mask fields, like every row.
- **Byte identity:** `python scripts/byte_identity.py check` (Plan 1, Task 0) stays `ALL IDENTICAL` after every task.
- **Exactness:** `Decimal` throughout; `drift-tolerance-v1` (`replay.compare_bars`) for matches, and `Decimal(0)` for any hour holding a repaired row.
- **Imports:** `masking.py` may import from `replay.py`, and `replay.py` never imports `masking.py`, which would be circular. `audit.py` imports `replay.py`, so the replay path never imports `audit.py`. Helpers that both need move into `masking.py`.
- **Memory:** masks are computed month by month, streaming. Hours and pair-months never cross a month, and only sets of masked hours are kept. A whole window of 1m `Kline`s would take about 3 GB per pair.
- **Checks before every commit:** `ruff check .`, `ruff format --check .`, `mypy`, `bandit -q -r src scripts`, `python scripts/check_reports.py`, `pytest -q`.

## Review Focus

1. **A truncated close followed by an adjacent row.** It is repaired, as rule 1's refined rule says, and admitted on an exact match. Only an unaligned open, or a next row opening before `open + step`, stays unrepaired and masks its hour. Pinned in Task 1, `test_repair_rule_matches_the_refined_rule`.
2. **A repaired hour that matches only within the volume drift.** It is masked, because a repaired hour needs an exact match. Pinned in Task 2, `test_repaired_hour_needs_an_exact_match`.
3. **Masks reaching every consumer.** A masked proxy hour, a masked basket hour and a masked minute are absent from every pair's features and from variant D. Pinned in Task 3, `test_masks_reach_the_proxy_the_basket_and_variant_d`.
4. **A pair-month around 17%, and the listing hours.** Above 17% real defects masks the month; exactly 17% keeps it; open-only hours and hours before listing do not count. Pinned in Task 2, `test_seventeen_percent_rule_boundary_listing_and_open_only`.
5. **XRP's spread.** One synthesized quote above 0.15% in the replayed, post-mask minutes excludes XRP's pair-window for every variant; a pass writes nothing into `results.json`. Pinned in Task 6, `test_one_wide_quote_excludes_xrp_and_a_pass_writes_nothing`.

---

### Task 1: The repairing reader

**Files:**
- Modify: `src/crypto_grid_bot/backtest/klines.py`
- Test: `tests/test_klines_repaired.py`

**Interfaces:**
- **Produces:**
  - `RepairedRead`, a frozen dataclass:
    - `bars: list[Kline]`;
    - `stats: FileStats`, as `parse_rows` computes them, over the kept rows; equal to the strict parser's when nothing is repaired or dropped;
    - `repaired: frozenset[int]`, the opens of repaired rows;
    - `masked_hours: frozenset[int]`, the opens of the hours with an untrusted row;
    - `unreadable: str`, "" when the archive could be read, else the reason;
  - `parse_rows_repaired(text: str, interval: str, month: str) -> RepairedRead`, for `1m` and `1h` only;
  - `read_archive_repaired(path: Path, symbol: str, interval: str, month: str) -> RepairedRead`. An archive that `read_member` cannot open or decode, or that holds a row whose open cannot be read (below), gives `unreadable`, with no bars.
- **The repair rule,** exactly as spec v1 §5 rule 1 and `audit.fix_closes`'s refined rule (`audit.py:186-188`). A row gets close `open + step − 1`, in memory only, when:
  - its close is off the step boundary;
  - its open is aligned (`open % step == 0`);
  - and it is the file's last row, or its next row in file order opens at `open + step` or later, an adjacent row included.
- **Untrusted rows:** a row that would make `parse_rows` raise for any other reason masks the hour its open falls in, and is dropped. That covers a duplicated open, an open not after the previous row's (both rows' hours are masked), an unaligned open, a close whose next row opens before `open + step`, a malformed field other than the open, and a row outside the month. **A row whose open cannot be read** (a missing column 0, or a value that is not an integer timestamp) has no hour to mask: it makes the whole archive `unreadable`, with the reason. Its hours are then absent, masked, and counted toward the 17% rule (spec v1 §5 rule 1, "The reader").
- **Daily archives** keep the strict `read_archive`: daily bars are never masked, and a missing or duplicated daily bar stays fatal (spec v1 §5).
- **The strict path is unchanged.** `parse_rows`, `read_archive` and `fetch_file` keep their behaviour, which `audit_run._fetch` and `tests/test_backtest_audit.py` rely on.

- [ ] **Step 1: Write the failing tests:**
  - `test_valid_archive_reads_the_same_both_ways`: for every archive the existing `tests/test_backtest_data.py` fixtures accept, `parse_rows_repaired` returns the same bars and the same `FileStats` as `parse_rows`, with nothing repaired or masked.
  - `test_repair_rule_matches_the_refined_rule` (Review Focus 1). Three rows are repaired: a last row with close `open + step − 2`, a row whose next row opens exactly `open + step`, and a row whose next row opens two steps later. Two are not, and each masks its hour: an unaligned open, and a row whose next row opens before `open + step`. The cases mirror `tests/test_backtest_audit.py`'s refined-rule cases (2019-06 and 2021-12).
  - `test_duplicate_and_out_of_order_rows_mask_only_their_hours`: a 1m archive with one duplicated minute and one out-of-order minute masks exactly those minutes' hours, and keeps every other bar.
  - `test_unreadable_archive_has_no_bars`: a zip with two members gives `unreadable` and no bars.
  - `test_malformed_open_makes_the_archive_unreadable`: a row with a non-numeric open, and a row with too few columns, each give `unreadable` with a reason and no bars; a row with a malformed close masks only its hour.
- [ ] **Step 2: Run `pytest tests/test_klines_repaired.py -v`.** Expected: FAIL, the functions do not exist yet.
- [ ] **Step 3: Implement** `RepairedRead`, `parse_rows_repaired` and `read_archive_repaired`, reusing `parse_rows`'s field checks row by row.
- [ ] **Step 4: Run the new tests and `pytest -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: a repairing kline reader for spec v1 section 5's long-window rules`.

### Task 2: The mask, month by month

**Files:**
- Create: `src/crypto_grid_bot/backtest/masking.py`
- Modify: `src/crypto_grid_bot/backtest/audit.py`, to import the moved helpers from `masking.py`
- Test: `tests/test_masking.py`

**Interfaces:**
- **Consumes:** Task 1's `RepairedRead`; `replay.compare_bars` and `replay.VOLUME_DRIFT_TOLERANCE`.
- **Produces:**
  - `expected_hours`, `hour_statuses` and `differing_fields`, moved from `audit.py` unchanged;
  - `MonthMask`, a frozen dataclass for one symbol-month:
    - `month: str`;
    - `expected: frozenset[int]`: the month's hours minus the symbol's documented exclusion ranges (`[[basket_exclusions]]`), which also cover the hours before listing (spec v1 §4: "Each listing exclusion ends at the symbol's first candle");
    - `masked: frozenset[int]` and `reasons: dict[int, str]`;
    - `defects: frozenset[int]`: the real defects, the masked hours other than `open_only`, as found before the 17% rule. `apply_seventeen_percent` leaves it unchanged when it masks the whole month, so an excluded month still reports the share that excluded it;
    - `repaired: frozenset[int]`;
    - `open_only: frozenset[int]`: the masked hours whose two bars are complete and whose `differing_fields(aggregated, official, tol) == ("open",)`, where `tol` is `VOLUME_DRIFT_TOLERANCE`, or `Decimal(0)` for a repaired hour, as the eligibility record measured. Hourly-only months have none;
    - `excluded: bool`, set by the 17% rule;
  - `traded_month_mask(minutes: RepairedRead, hourly: RepairedRead, month: str, exclusions: Sequence[BasketExclusion]) -> MonthMask`, for a traded pair's evaluation month (rules 1 and 2). An expected hour enters only if:
    - it is in neither read's `masked_hours` (an untrusted row, Task 1). Such an hour is masked first, with the reason "untrusted row", because the reader keeps one copy of a duplicated or out-of-order row;
    - exactly one 1h bar exists;
    - exactly one 1m bar exists at each of its 60 minute opens, and none elsewhere in it;
    - and the aggregated minutes match the 1h bar under `drift-tolerance-v1`, or exactly (`Decimal(0)`, prices and volume) when either archive repaired a row in that hour.
    Every other expected hour is masked, with its reason;
  - `hourly_only_month_mask(hourly: RepairedRead, month: str, exclusions: Sequence[BasketExclusion]) -> MonthMask`, for untraded basket symbols, an untraded proxy, and traded pairs' hourly warm-up months (rule 1, "Hours with no minute data", and rule 5). An expected hour enters only if it is not in `masked_hours`, exactly one 1h bar exists and it is not a repaired row;
  - `SEVENTEEN = Fraction(17, 100)`, and `apply_seventeen_percent(month: MonthMask) -> MonthMask`. A month is excluded when its real defects, its masked hours other than `open_only`, are more than 17% of its expected hours. An excluded month has all its expected hours masked;
  - `real_defect_share(month: MonthMask) -> Fraction | None`: `len(defects)` ÷ the expected hours, unchanged by an exclusion, or `None` when the month has no expected hours. A whole month inside documented exclusions has none, such as SOLUSDT's months before 2020-08, or DOGEUSDT 2020-02 (rule 5). Such a month counts nothing toward the 17% rule and is never excluded; any bars its archives hold are dropped by the loaders as a documented absence (Task 3), not masked. `apply_seventeen_percent` compares the share with `SEVENTEEN` only when it is not `None`, so nothing divides by zero;
  - `masked_days(masked: Iterable[int]) -> frozenset[int]`, the UTC day opens that contain a masked hour (rule 3).
- **Hours inside a documented exclusion** are neither expected nor fed to the features. A loader given a mask also drops every bar inside the symbol's `[[basket_exclusions]]` ranges (Task 3), so DOGEUSDT 2020-02's bars, its repaired hour included, never reach the breadth features. Those hours are not masked hours: they stay out of the 17% count and out of the comparison mask. Today's loaders feed every bar of an `ok` archive; the listing exclusions are absent today only because no bars exist before a listing, and no stage-1 spec has an exclusion.

- [ ] **Step 1: Write the failing tests:**
  - `test_clean_hour_enters_and_incomplete_hour_is_masked`: 60 matching minutes enter; 59 minutes mask the hour (rule 2).
  - `test_repaired_hour_needs_an_exact_match` (Review Focus 2): a repaired hour whose volume differs by 0.05% is masked, and the same hour unrepaired enters as drift.
  - `test_extra_minute_or_second_hourly_bar_masks_the_hour`, built through `parse_rows_repaired`, not hand-built reads: a duplicated minute and a duplicated hourly row each mask their hour, although the reader kept one copy of each.
  - `test_hourly_only_symbol_masks_repaired_hours` (rule 5)
  - `test_seventeen_percent_rule_boundary_listing_and_open_only` (Review Focus 4):
    - in a 700-hour expected month, 119 real defects (exactly 17%) keep it, and 120 exclude it; the excluded month has all 700 hours masked, `defects` of 120 hours, and a reported share of 120/700;
    - open-only hours do not count toward either;
    - in SOLUSDT 2020-08, the 246 hours before listing are not expected, so they do not count.
  - `test_month_with_no_expected_hours_is_kept`: SOLUSDT 2019-03, wholly before listing, and DOGEUSDT 2020-02, wholly inside rule 5's exclusion, each have no expected hours, a share of `None`, no masked hour, and are not excluded. DOGEUSDT 2020-02's bars are dropped by the loader (Task 3), not masked.
  - `test_open_only_hours_are_identified`
  - `test_masked_days_cover_each_masked_hours_day`
  - `test_audit_still_uses_the_same_helpers`: `audit`'s outputs on its existing fixtures are unchanged.
- [ ] **Step 2: Run `pytest tests/test_masking.py -v`.** Expected: FAIL.
- [ ] **Step 3: Implement `masking.py`,** and point `audit.py` at the moved helpers.
- [ ] **Step 4: Run `pytest -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: spec v1 section 5's hour mask and 17% rule, month by month`.

### Task 3: Masks for every consumer, and the post-mask expected set

**Files:**
- Modify: `src/crypto_grid_bot/backtest/replay.py`: `load_candles`, `load_minutes`, `cross_check_hourly`, `cross_check_daily` and `check_hourly_series`
- Modify: `src/crypto_grid_bot/backtest/jobs.py`: `prepare_run`, `run_job` and `cross_check_job`, and a new `mask_job`
- Modify: `src/crypto_grid_bot/backtest/trend_benchmark.py`: `trend_job`, which passes the masks through
- Test: `tests/test_backtest_masked_checks.py`

**Interfaces:**
- **Consumes:** Tasks 1 and 2.
- **Produces:**
  - **`load_candles(..., mask: frozenset[int] | None = None, excluded: Sequence[tuple[int, int]] = ())` and `load_minutes(..., mask=..., excluded=...)`.** `excluded` is the symbol's documented exclusion ranges in ms, as `cross_check_job` already builds them from `spec.basket_exclusions`:
    - with `mask=None`, exactly today's strict loading, which refuses an archive with repaired or dropped rows, and drops nothing. So only callers carrying a mask admit repaired data, and every stage-1 run reads as before;
    - with a mask, they read 1m and 1h archives with `read_archive_repaired`, drop every bar in a masked hour, and drop every bar inside `excluded`, a documented absence (spec v1 §4), so DOGEUSDT 2020-02's bars never load. Neither stage-1 spec has an exclusion;
    - **fail-closed, as today:** an archive the manifest lists as `ok` that reads as unreadable raises `DataError` (`tests/test_backtest_loaders.py:115-131`). Only manifest status `"unreadable"` (Task 7) gives no bars, which `_archive_months` already ensures;
  - **the three cross-checks** take the masked hours and remove them from the expected set (spec v1 §5, "The post-mask expected set"). `cross_check_daily` takes the masked days from its caller, skips each, and counts it in `daily_days_skipped_for_masks`, a key it writes only when non-zero (rule 3);
  - **`mask_job(spec_path: Path, data_dir: Path, symbol: str) -> SymbolMask`,** a new job in `jobs.py`, which the CLI runs for every checked symbol before the cross-checks: the pair, the proxy and each basket member. It reads the symbol's 1m and 1h archives with the repaired reader, month by month (Task 2). `SymbolMask` is a frozen dataclass:
    - `symbol: str`;
    - `mask: frozenset[int] | None`: `None` when the symbol's repaired reads repair, drop and mask nothing and no hour is masked; otherwise every masked hour;
    - `months: tuple[MonthMask, ...]`: the per-month table, for the comparison mask and `mask-report` (Task 5).
  - **`cross_check_job(..., mask: frozenset[int] | None = None)` keeps its return value:** the same record as today, which the CLI writes whole under `hourly_cross_checks`. With a mask, the record's checks run on the post-mask expected set. The record gains only `daily_days_skipped_for_masks`, and Task 6's `tick_limit_quotes`, each written only when non-zero. No mask and no per-month table ever enter the record;
  - **`run_job(..., masks: Mapping[str, frozenset[int] | None] | None = None)` and `trend_job(..., masks=...)`.** `prepare_run` applies each symbol's mask to the pair's hourly bars, to the proxy's series and to every basket member's series. So `prepared.hourly` is post-mask, which Plan 1's `Perception` reads. `run_job` also passes the pair's mask and exclusion ranges to the `load_minutes` call that feeds the grid replay (`jobs.py:237`), and `trend_job` to D's (`trend_benchmark.py:273`), so no masked minute reaches any replay, grid or D. D's rows carry Task 4's fields;
  - **`None` and an empty mask differ:**
    - a symbol mapped to `None`, or absent, loads with today's strict reader;
    - a symbol mapped to a set, even an empty one, loads with the repaired reader and drops the set's hours.
    Task 5's CLI passes each `SymbolMask.mask` as it is. A clean symbol gets `None`, so stage-1 runs take today's exact path, and Task 10's re-run proves it. Only a symbol with a masked hour, a repaired row or a dropped row gets a set.
- **With no masks,** every function behaves byte for byte as today.

- [ ] **Step 1: Write the failing tests:**
  - `test_no_mask_changes_nothing`: each check and loader with no mask equals today's on the existing fixtures. On a clean window, every `SymbolMask.mask` is `None`, and every cross-check record equals today's, keys and values.
  - `test_masked_hour_leaves_the_expected_set`: a masked hour with no minutes fails no check.
  - `test_daily_check_skips_and_counts_masked_days`: the day is skipped and counted, and its official 1d bar stays in use.
  - `test_masks_reach_the_proxy_the_basket_and_variant_d` (Review Focus 3)
  - `test_grid_run_omits_masked_minutes`: a V0 run with one masked evaluation hour processes no quote and fills no order inside it, and the same run with no mask does.
  - `test_documented_exclusion_bars_are_dropped_with_a_mask`: DOGEUSDT 2020-02's bars, its repaired hour included, are absent from every pair's breadth series, February counts no masked hour, and with `mask=None` the same archive loads whole, as today.
  - `test_ok_archive_that_is_unreadable_still_raises`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `pytest -q` and `python scripts/byte_identity.py check`.** Expected: PASS, and `ALL IDENTICAL`.
- [ ] **Step 5: Commit** `feat: masks reach every consumer; checks on the post-mask expected set`.

### Task 4: Reporting masked spans in each run

**Files:**
- Modify: `src/crypto_grid_bot/backtest/replay.py`: `Metrics`, `replay` and `summarise`; and `trend_benchmark.py`'s rows
- Test: `tests/test_backtest_masked_runs.py`

**Interfaces:**
- **Consumes:** `replay(..., masked: frozenset[int] = frozenset())` and `trend_benchmark`'s run gain this parameter, holding the pair's own mask, which `run_job` and `trend_job` take from the `masks` map (Task 3). The proxy's and the basket's masks shape the features and are not reported per run. Plan 1 rebases onto this signature.
- **Produces,** on every row, D's and MS's included, each field written only when non-zero (spec v1 §5 rule 1, "Each run reports"):
  - `masked_hours`: the number of hours in `masked` inside the evaluation window `[start, end)`;
  - `days_skipped_for_masks`: `masked_days(masked)` inside the daily check's hourly window (rule 3);
  - `fills_after_masked_span`: fills on the first replayed minute whose previous replayed minute is separated from it by a masked hour (rule 4). A gap from feature warm-up (`features.at` returning None) is not a masked span. Orders stay open across the span, and the engine's own gap rules apply unchanged.

- [ ] **Step 1: Write the failing tests:** `test_fill_after_a_masked_span_is_flagged`, and `test_unmasked_run_rows_gain_no_field`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `pytest -q` and `python scripts/byte_identity.py check`.** Expected: PASS, and `ALL IDENTICAL`.
- [ ] **Step 5: Commit** `feat: runs report masked hours, skipped days and fills after a masked span`.

*Open Tasks 1–4 as one PR.*

### Task 5: The comparison mask, written before scoring

**Files:**
- Modify: `src/crypto_grid_bot/backtest/__main__.py`: the cross-check phase that `verify` and `run` share, and a new `mask-report` command
- Test: `tests/test_backtest_cli.py`, `tests/test_backtest_acceptance.py`

**Interfaces:**
- **Produces:**
  - **`results.json["comparison_mask"]`,** computed before the first job is submitted, printed by `verify`, and included in the single `results.json` the CLI writes at the end (`__main__.py` writes it once, after every run; no early file), only when its content is non-empty: a masked hour, an excluded month or a breach of XRP's test. It holds, per symbol, the masked hours as merged `[from, to)` ISO ranges with their reasons, and the excluded pair-months, built from the `SymbolMask`s (Task 3). The CLI runs `mask_job` for every checked symbol first, then passes each symbol's mask to its cross-check and the `{symbol: mask}` map to every run. `verify` shares this phase, and prints the comparison mask under the same rule;
  - **`python -m crypto_grid_bot.backtest mask-report --spec X --data-dir data`,** which prints JSON without replaying:
    - the comparison mask, and per symbol whether its mask is `None`, with its repaired, dropped and masked counts (Task 10 reads these);
    - for each symbol-month: the expected hours, the masked hours, the open-only hours, the real-defect share (`null` for a month with no expected hours), and whether it is excluded;
    - XRP's test statistic, the widest quote spread found, whether or not it breaches.
- **`acceptance.py`'s code is unchanged,** as Plan 1 also requires. Task 6 updates one docstring and one comment there, and nothing else.
  - Masked hours never exclude a pair-window. The one exclusion these rules add, XRP's (Task 6), reaches the scorer through the cross-checks that `window_of` already reads.
  - No criterion uses Task 4's per-run mask fields. Spec v1 §5 asks each run to report them (rules 1 and 4), and `results.json` carries them. So `runs_of` and `run_json` stay as they are, and Plan 1's `acceptance_v2` does not read them either.

- [ ] **Step 1: Write the failing tests:**
  - `test_mask_is_computed_before_the_first_job_and_written_only_when_non_empty`: with the fake pool, the comparison mask exists before `run_job` is first called, and a clean window writes no `comparison_mask` key;
  - `test_mask_report_prints_shares_without_replaying`;
  - `test_window_of_is_unchanged_without_the_new_keys`, a synthetic `window_of` test on cross-checks that carry none of the new keys. The real stage-1 check is Task 10: stage 1's files are not in the repository, and the scorer pins its own code.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `pytest -q` and `python scripts/byte_identity.py check`.** Expected: PASS, and `ALL IDENTICAL`.
- [ ] **Step 5: Commit** `feat: the comparison mask in results.json, and mask-report`.

### Task 6: XRP's actual-quotes test

**Files:**
- Modify: `src/crypto_grid_bot/backtest/masking.py`; `jobs.cross_check_job`, which gains `config_path: Path` (the CLI passes `args.config`, and `mask-report` takes `--config`), since it has no config today; `__main__.py`'s `integrity_failures`
- Modify: `src/crypto_grid_bot/backtest/acceptance.py`: `data_rule_exclusions`'s docstring and the comment in `runs_of`, nothing else
- Test: `tests/test_masking.py`, `tests/test_backtest_cli.py`, `tests/test_backtest_acceptance.py`

**Interfaces:**
- **Produces:** `widest_spread_pct(minutes: Iterable[Kline], symbol: str, spread: Decimal, tick: Decimal) -> Decimal`, the largest spread in percent over every quote that `replay.bar_quotes(kline, symbol, "high_first", spread, tick)` synthesizes. Both paths give the same four quotes, so one path suffices. Beside it, `tick_limit_quotes(minutes, symbol, spread, tick, limit: Decimal) -> int`, the number of those quotes with a spread above `limit`, which the cross-check record carries. Both are computed only when `symbol == "XRPUSDT" and symbol in spec.traded`; in `verify-2024h1` XRP is a basket member only, with no minutes, and nothing is computed. `load_minutes` returns a one-shot iterator, which `cross_check_hourly` exhausts, so `cross_check_job` computes the statistic in a second `load_minutes(...)` call, with the pair's mask, after the cross-check. The two functions take an `Iterable` and iterate it once; the tests pass a one-shot iterator, not a list, so a function that iterates twice fails.
- **Units and arithmetic, as the replay and the engine already use them:**
  - `spread` is `RunConfig.spread`, the fraction `spec.assumed_spread_pct / 100` that `jobs.prepare_run` computes (`jobs.py:170`) and the replay passes to `bar_quotes`. `tick` is `run.rules.tick_size`, as `replay.py:734` passes it;
  - each quote's spread is `(quote.ask - quote.bid) / quote.ask * 100`, in that order, as `src/crypto_grid_bot/simulation/runner.py:590` computes it;
  - the limit is `Decimal(str(config.maximum_spread_pct))`, as `PaperSimulator` converts the float (`src/crypto_grid_bot/simulation/runner.py:336`);
  - a breach is a spread `> limit`, the engine's own condition (`_validate_frame`, `runner.py:591`). A quote exactly at the limit passes.
- **The rule** (spec v1 §5 rule 8, decision 16): for XRPUSDT only, over the window's replayed minutes, which are the evaluation months after masking, with the dataset's assumed spread, the manifest's tick and `config/default.toml`'s `maximum_spread_pct`. It is computed month by month, like the masks: `cross_check_job` computes it for XRPUSDT on the minutes that XRP's mask leaves, and `mask-report` prints the same statistic.
- **Only a breach writes anything** into `results.json`. A pass writes nothing, so `practice-2022`, whose XRP passes, keeps its stage-1 identity. A breach excludes XRP's pair-window for every variant, through the existing machinery:
  - XRP's cross-check record gains `tick_limit_quotes`, the number of quotes above the limit, written only when non-zero;
  - `__main__.py` gains `QUOTE_INTEGRITY_FIELDS = ("tick_limit_quotes",)`, which `integrity_failures` reads on a traded pair's check with `check.get(field, 0)`. The existing `INTEGRITY_FIELDS`, `SERIES_INTEGRITY_FIELDS` and `DAILY_INTEGRITY_FIELDS` keep their direct `check[field]` lookups, so a stage-1 record missing one of those fields still raises, as today. `scoped_failures` makes `tick_limit_quotes` XRP's own failure, since XRP is traded and is not the market proxy. `excluded_pairs["XRPUSDT"]` then names it, and `acceptance.window_of` excludes the same pair-window, with `acceptance.py`'s code unchanged;
  - the comparison mask records the breach.
- **`acceptance.py`'s two stale texts are updated.** `data_rule_exclusions`'s docstring, and the comment in `runs_of`, foresaw this PR naming the fields. They now say:
  - rule 8 reaches the scorer through the cross-check record's `tick_limit_quotes` and `scoped_failures`, so `data_rule_exclusions` stays empty;
  - the per-run mask fields are reported in each row and scored by no criterion.
  `data_rule_exclusions` still returns `[]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_one_wide_quote_excludes_xrp_and_a_pass_writes_nothing` (Review Focus 5). Warm-up minutes do not count. It runs through `cross_check_job` with `load_minutes` patched to return one-shot iterators and count its calls: the cross-check's counts and the XRP statistic are both right, from two calls;
  - `test_quotes_at_the_limit_pass`: the limit comes from the engine itself, a `PaperSimulator`'s `_maximum_spread_pct` built from `config/default.toml`. A bar whose widest quote equals it exactly passes, and one tick lower on the bid breaches;
  - `test_stage_1_checks_still_need_every_existing_field`: a pair check missing `hours_missing` still raises `KeyError` in `integrity_failures`, and one missing `tick_limit_quotes` does not;
  - `test_practice_2022_xrp_passes`, on a synthetic copy of its tick and spread;
  - `test_scorer_excludes_the_same_xrp_window`: `acceptance.window_of` on a results file with `tick_limit_quotes` excludes XRP's pair-window, and no XRP run is then expected. It replaces `test_the_long_window_data_rules_are_not_applied_yet` (`tests/test_backtest_acceptance.py:604-618`), whose name and comment would otherwise be false.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `pytest -q` and `python scripts/byte_identity.py check`.** Expected: PASS, and `ALL IDENTICAL`.
- [ ] **Step 5: Commit** `feat: XRP's actual-quotes test (spec v1 section 5 rule 8)`.

### Task 7: Repairable and unreadable archives in a fetch

**Files:**
- Modify: `src/crypto_grid_bot/backtest/dataset.py`: `fetch_dataset`, `verify_dataset` and `_validate_manifest`
- Test: `tests/test_backtest_data.py`

**Interfaces:**
- **Produces:** for 1m and 1h archives, a fallback in `fetch_dataset`, not in `fetch_file`, which `audit_run._fetch` and `tests/test_backtest_audit.py:258-283` rely on to raise `ArchiveParseError`. When `fetch_file` raises it after the archive downloaded and verified against its checksum, `fetch_dataset` reads the stored file with `read_archive_repaired`:
  - an unreadable archive gets status `"unreadable"`, with its reason;
  - any other archive gets status `"ok"`, with the repaired read's `FileStats`. #156's manifest of this window lists 108 such archives, from 2018-07 to 2023-03, and the first is the sixth file `required()` lists.
- **`_validate_manifest`** accepts status `"unreadable"` beside `ok` and `missing` (`dataset.py:545-546` refuses any other status today); `sha256` is required for `ok` and `unreadable`, and a non-empty `reason` for `unreadable`. It runs inside `load_manifest` (`dataset.py:487-493`), which `verify`, `prepare_run` and `cross_check_job` all call, so without this no consumer could load the new manifest.
- **`verify_dataset`** accepts `"unreadable"` with its SHA-256. The loaders give no bars for it, so its hours are absent, then masked, and they count toward the 17% rule (spec v1 §5 rule 1, "The reader").
- **A strictly valid archive's entry is unchanged,** so refetching a stage-1 window gives the same manifest.

- [ ] **Step 1: Write the failing tests:**
  - `test_truncated_close_archive_is_fetched_as_ok_with_repaired_stats`;
  - `test_unreadable_archive_is_recorded_not_fatal`;
  - `test_manifest_with_an_unreadable_entry_loads_and_verifies`: `load_manifest` and `verify_dataset` accept it, and an unknown status is still refused;
  - `test_valid_archive_entry_is_unchanged`;
  - `test_fetch_file_still_raises_for_the_audit`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `pytest -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: fetch repairable archives as ok and unreadable ones as recorded`.

*Open Tasks 5–7 as one PR.*

### Task 8: The frozen dataset specs

**Files:**
- Create: `config/datasets/full-range-2017-2024.toml`
- Modify: `config/datasets/full-range-2019-2024.toml`, to spec v1 §4's values. v2 does not run it, but a committed spec under a frozen name must not contradict §4.
- Modify: `.github/workflows/backtest.yml`: `full-range-2017-2024` in the `spec` input's options, so that the owner's Actions path can dispatch the scored window once its manifest is committed
- Test: `tests/test_full_range_specs.py`

**Interfaces:**
- **`full-range-2017-2024`,** exactly as spec v1 §4:
  - name `full-range-2017-2024`; traded `BTCUSDT`, `ETHUSDT`, `XRPUSDT`; market proxy `BTCUSDT`;
  - breadth basket BTC, ETH, BNB, SOL, XRP, DOGE, LTC, LINK and TRX (USDT pairs);
  - `warmup_start = "2018-06"`, `daily_warmup_start = "2018-06"`, `start = "2019-01"`, `end = "2024-12"`;
  - `initial_quote = "100"`, `fee_rate = "0.001"`, `slippage_rate = "0.0005"`, `participation = "0.10"`, `assumed_spread_pct = "0.05"`;
  - basket exclusions (from inclusive, to exclusive): SOLUSDT 2018-06-01 to 2020-08-11T06:00Z; DOGEUSDT 2018-06-01 to 2019-07-05T12:00Z; LINKUSDT 2018-06-01 to 2019-01-16T10:00Z; TRXUSDT 2018-06-01 to 2018-06-11T11:00Z; DOGEUSDT 2020-02-01 to 2020-03-01 (rule 5).
- **`full-range-2019-2024`,** corrected to §4:
  - `daily_warmup_start = "2018-07"`;
  - SOLUSDT's exclusion ends at 2020-08-11T06:00Z, and DOGEUSDT's at 2019-07-05T12:00Z;
  - LINKUSDT is excluded from 2019-01-01 to 2019-01-16T10:00Z;
  - DOGEUSDT is excluded from 2020-02-01 to 2020-03-01.

- [ ] **Step 1: Write the failing tests:**
  - `test_full_range_2017_2024_matches_spec_v1_section_4`: every field and exclusion above, and `required()` lists 1,164 kline files (216 1m, 711 1h and 237 1d);
  - `test_full_range_2019_2024_matches_spec_v1_section_4`;
  - `test_every_dataset_spec_is_a_workflow_choice`: it loads `backtest.yml` with `yaml.safe_load`, and asserts that the set of the `spec` input's options equals the set of names of the committed `config/datasets/*.toml` files (the YAML order is not sorted). PyYAML reads the `on:` key as `True`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Write the spec files, and add the workflow choice.**
- [ ] **Step 4: Run `pytest -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `data: the frozen full-range dataset specs`.

### Task 9: Bob's re-fetch, and the manifest

**Files:**
- Create: `scripts/fetch_full_range.py`, a pinned script
- Create: `docs/tasks/<date>-bob-full-range-2017-2024-fetch.md`, in the format of `docs/tasks/2026-09-27-bob-p8-funding-archives.md`
- Later, from Bob's report: `config/datasets/full-range-2017-2024.manifest.json`

**Interfaces:**
- **`scripts/fetch_full_range.py <data-dir> [--spec PATH] [--reported-spec PATH]`,** the committed `full-range-2017-2024.toml` and `full-range-2019-2024.toml` by default:
  - copies the spec into `<data-dir>`, so that every write lands under the git-ignored `data/`. Bob's workflow refuses any change outside a new `docs/reviews/*-bob-*.md` (`bob-task.yml:305-309`);
  - calls `fetch_dataset(..., instruments=...)` with the BTCUSDT, ETHUSDT and XRPUSDT filters taken from the committed `config/datasets/long-bull-bear-2022.manifest.json`, so no request goes to `data-api.binance.vision`, which Bob's prompt forbids (`bob-task.yml:228-233`). The copied filters keep that manifest's `fetched_at` (`fetch_dataset` would stamp them with now, `dataset.py:471-476`; the script restores them), and the manifest PR notes the copy. The fetcher is wrapped with bounded retries for `FeedError` only, as `audit_run._fetch` retries, since `archive_get` has none and one transient failure in about 2,450 requests would end the run; a checksum failure is never retried;
  - fetches BTCUSDT's funding archives for 2020-01 to 2024-12 with `fetch_funding_file`, from `data.binance.vision`, so the manifest matches spec v1 §4. **Every funding month must be `ok`:** a 404 gives `fetch_funding_file` a `missing` entry (`dataset.py:435`), which `verify_dataset` accepts and `mask-report` never exercises, while `load_funding` later refuses it for G and the full stack. So the script stops before writing any manifest when a funding entry is not `ok`, and names the months;
  - **assembles and writes the manifest.** `fetch_dataset` returns the kline manifest as a dictionary, and each `fetch_funding_file` call returns one entry. So the script appends the 60 funding entries after the kline entries, where `fetch_dataset` puts the funding entries it keeps. It then writes the result with `write_manifest` (an atomic write) to `manifest_path` of the copied spec, before anything reads it;
  - then runs `verify` and `mask-report` on that copy. Both load the manifest from disk;
  - **the reported window's manifest too.** The frozen v1 scorer's `read_frozen` requires every registered stage-2 window's spec and manifest (`acceptance.py:1058-1076`), and `full-range-2019-2024` is registered as reported-only. Its files are a subset of `full-range-2017-2024`'s: 1m from 2019-07, 1h from 2019-01, 1d from 2018-07, the same nine symbols and the same 60 funding months. So the script then runs `fetch_dataset` for the second spec on the same `<data-dir>`, with the first manifest as `previous` so the funding entries are kept. `_fetch_verified` reuses a stored file whose SHA-256 matches (`dataset.py:378`), so only `.CHECKSUM` requests go out. The script asserts that every entry equals the first manifest's entry for the same file, writes the second manifest, and runs `verify` on it.
- **Bob's report:**
  - **a compact digest,** which the script prints: a header with the manifest's `created_at`; one row per kline archive with its file name (not the path), SHA-256, status, `bytes`, and `FileStats` only where they differ from a complete month (rows = expected rows, no gaps, first and last opens at the month's bounds, units `ms`), else the word `full`; a `missing` archive's row carries its name and `missing` only, as `fetch_file` writes such an entry with no `sha256`, `bytes` or `FileStats` (the pre-listing months of SOL, DOGE and LINK are expected `missing`); an `unreadable` archive's row carries its name, SHA-256, `bytes`, `unreadable` and its reason, which `_validate_manifest` requires (Task 7); one row per funding archive with its name, SHA-256, `bytes` and record count. The header also carries the second manifest's `created_at` and both manifest files' SHA-256: Claude rebuilds both from the one digest, the second as the subset its spec's `required()` selects, and must reproduce both hashes. A full-path table with every `FileStats` field would be about 230 KB, over `validate_bob_artifact.py`'s 200,000-byte limit (`REPORT_MAX_BYTES`), and the publish step would reject the whole run; this form is about 130 KB;
  - **`mask-report`'s summary only:** its totals, every symbol-month with a masked hour or an exclusion, and XRP's line. The full JSON stays under `<data-dir>`, and the report prints its SHA-256;
  - the script prints the report's byte count. Above 190,000 bytes Bob stops and reports the count instead.
  Bob's fetch has already checked each archive against Binance's `.CHECKSUM` (`fetch_file`'s rule), and a mismatch stops the run. Claude rebuilds the manifest from the digest, which carries each SHA-256, and checks the digest against the SHA-256 that Bob's report prints for it, as with P8. Claude makes no request to Binance. The manifest is committed in a reviewed PR.
- **Stop conditions:**
  - a checksum mismatch; any request to another host; any month after 2024-12; a pair-window left with fewer than 2 included pairs;
  - `mask-report` excludes any symbol-month under the 17% rule. The eligibility record measured every symbol-month of this window that has expected hours under 17% (its 772 measured pair-months; the one unusable month here, DOGEUSDT 2020-02, has no expected hours), so an exclusion contradicts it. Bob stops and reports it. It is a signal to report, and no rule is tuned to it.
- **Order:** the task file's PR merges only after Tasks 1–7 are on main. A merge that adds a task file starts Bob at once (`bob-task.yml:5-6`), and Bob needs `mask-report` and the new fetch statuses.
- **The manifest PR** commits both manifests. Its tests assert `full-range-2017-2024`'s 1,164 kline entries and 60 funding entries, and that `full-range-2019-2024.manifest.json` holds exactly its spec's `required()` files, each entry equal to the 2017–2024 entry for the same file, plus the 60 funding entries. The test also pins Task 7's fallback. #156's manifest left 108 archives `unparsed`: 82 1h and 26 1m, from 2018-07 to 2023-03. Each must appear with the status and the full `FileStats` that Bob's digest reports, written into the test, not only counted. The rebuilt manifest carries each entry's `bytes` and the run's `created_at`, from the digest's rows and header.

- [ ] **Step 1: Write the failing test** `test_fetch_full_range_writes_only_under_data_and_uses_committed_filters`. It runs the script with `--spec` on a one-month synthetic spec (the same symbols, basket and pricing; one evaluation month and its warm-up), against a fake fetcher that serves complete synthetic archives with matching `.CHECKSUM`s, plus one funding month. The committed spec's 1,164 archives cannot be synthesized complete in a unit test, and incomplete ones would mask every hour and make `verify` exit 2. It asserts:
  - no file outside `<data-dir>` changes, and no request goes to another host;
  - every funding month the spec covers is fetched (the committed spec's 60 are the script's default list);
  - the manifest exists under `<data-dir>` before `verify` and `mask-report` run, holds every kline entry `required()` lists and the funding entries, and keeps the copied filters' `fetched_at`;
  - `verify` prints `"valid"` and `mask-report` prints its JSON;
  - a transient `FeedError` on one request is retried and the run completes; a checksum mismatch is not retried and stops it;
  - a 404 for a pre-listing kline month gives a `missing` row with name and status only, and the rebuilt entry equals the manifest's;
  - a checksum-valid archive with two zip members gives an `unreadable` row with its reason, and the rebuilt entry equals the manifest's and passes `_validate_manifest`;
  - a 404 for a funding month stops the script before any manifest is written, naming the month;
  - the second spec's manifest (a one-month synthetic `--reported-spec` whose files are a subset) is written with no archive re-downloaded, every entry equal to the first manifest's, and `verify` accepts it.
- [ ] **Step 2: Run it.** Expected: FAIL.
- [ ] **Step 3: Write the script and the task file.** The task file holds the steps, the stop conditions, the report's format and the self-check from `BOB_PRACTICE.md`.
- [ ] **Step 4: Run `pytest -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `docs: Bob's task to fetch full-range-2017-2024, and its pinned script`.

*Open Tasks 8–9 as one PR, and merge it only after Tasks 1–7 are on main. The manifest follows in its own PR after Bob's run.*

### Task 10: The stage-1 identity check

**Files:**
- Create: `scripts/stage1_identity.py`
- Test: `tests/test_stage1_identity_script.py`

**Interfaces:**
- **Produces:** `python scripts/stage1_identity.py <stage-1 results dir> <re-run results dir>`. It keys each `results.json` by dataset, policy and path. The two key sets must be equal and hold no duplicate: a file missing on either side, an extra file, or two files with one key fails the check before any comparison, naming the keys, so a rerun that lost a download cannot pass on the files that remain. It then prints `IDENTICAL` or the differing keys for each pair, and exits 0 only when the inventories match and every pair is identical apart from `code_commit` and `code_sha256`, with no new mask field (decision 18).
- **The re-run:** stage 1's 24 workflow runs at the commit that merges Tasks 1–7, compared with stage 1's downloads. Dispatching them needs the owner's go.
- **What it proves.** Identical `results.json` files prove that the engine's output is unchanged. They cannot show by themselves which reader ran: a phantom repair that still matches exactly would change no bar and write no key, since `Kline` does not store the close timestamp the repair rewrites. So the script's companion check is `mask-report` on `practice-2022` and `verify-2024h1`, with no replay, which must print `None` for every symbol's mask and zero repaired, dropped and masked counts (Task 5). Together they show that every stage-1 symbol took today's strict path and that the repaired reader finds nothing to repair in stage 1's archives.

- [ ] **Step 1: Write the failing tests:** `test_identical_apart_from_fingerprints_passes`, `test_any_other_difference_fails`, `test_a_new_mask_field_fails`, and `test_missing_extra_or_duplicate_file_fails` (one file absent on one side, one extra, and two files with one key, each failing with the key named).
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `pytest -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `test: the stage-1 identity check (decision 18)`.
