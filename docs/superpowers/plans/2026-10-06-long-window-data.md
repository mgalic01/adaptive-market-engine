# Long-Window Data Implementation Plan

> **How this plan runs:** task by task, each with a fresh implementer and then a fresh reviewer, and a whole-branch review at the end. That is the subagent-driven execution the owner chose on 2026-10-06. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `full-range-2017-2024` replayable under spec v1 §5's frozen data rules, so that spec v2 can be judged on it, and leave every v1 stage-1 result identical.

**Architecture:**
- **A repairing reader** returns an archive's bars and statistics together with the hours it could not trust, instead of rejecting the whole archive.
- **A pure masking module** decides, month by month, which hours enter the replay: rules 1, 2 and 5, the 17% coin-month rule, and the days that rule 3 skips.
- **Every consumer gets the masks:** the cross-check phase computes one mask per symbol, and the CLI passes the whole `{symbol: mask}` map to every run. `prepare_run` applies it to the pair, the proxy and every basket series, and variant D's minutes use it too.
- **The CLI** writes the comparison mask before any run starts, and applies XRP's actual-quotes test.
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
  - Whichever plan merges second rebases onto the other in `replay.py`, `jobs.py` and `__main__.py`.
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
    - `stats: FileStats`, equal to the strict parser's when nothing is repaired or dropped;
    - `repaired: frozenset[int]`, the opens of repaired rows;
    - `masked_hours: frozenset[int]`, the opens of the hours with an untrusted row;
    - `unreadable: str`, "" when the archive could be read, else the reason;
  - `parse_rows_repaired(text: str, interval: str, month: str) -> RepairedRead`, for `1m` and `1h` only;
  - `read_archive_repaired(path: Path, symbol: str, interval: str, month: str) -> RepairedRead`. An archive that `read_member` cannot open or decode gives `unreadable`, with no bars.
- **The repair rule,** exactly as spec v1 §5 rule 1 and `audit.fix_closes`'s refined rule (`audit.py:186-188`). A row gets close `open + step − 1`, in memory only, when:
  - its close is off the step boundary;
  - its open is aligned (`open % step == 0`);
  - and it is the file's last row, or its next row in file order opens at `open + step` or later, an adjacent row included.
- **Untrusted rows:** a row that would make `parse_rows` raise for any other reason masks the hour its open falls in, and is dropped. That covers a duplicated open, an open not after the previous row's (both rows' hours are masked), an unaligned open, a close whose next row opens before `open + step`, a malformed field, and a row outside the month.
- **Daily archives** keep the strict `read_archive`: daily bars are never masked, and a missing or duplicated daily bar stays fatal (spec v1 §5).
- **The strict path is unchanged.** `parse_rows`, `read_archive` and `fetch_file` keep their behaviour, which `audit_run._fetch` and `tests/test_backtest_audit.py` rely on.

- [ ] **Step 1: Write the failing tests:**
  - `test_valid_archive_reads_the_same_both_ways`: for every archive the existing `tests/test_backtest_data.py` fixtures accept, `parse_rows_repaired` returns the same bars and the same `FileStats` as `parse_rows`, with nothing repaired or masked.
  - `test_repair_rule_matches_the_refined_rule` (Review Focus 1). Three rows are repaired: a last row with close `open + step − 2`, a row whose next row opens exactly `open + step`, and a row whose next row opens two steps later. Two are not, and each masks its hour: an unaligned open, and a row whose next row opens before `open + step`. The cases mirror `tests/test_backtest_audit.py`'s refined-rule cases (2019-06 and 2021-12).
  - `test_duplicate_and_out_of_order_rows_mask_only_their_hours`: a 1m archive with one duplicated minute and one out-of-order minute masks exactly those minutes' hours, and keeps every other bar.
  - `test_unreadable_archive_has_no_bars`: a zip with two members gives `unreadable` and no bars.
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
    - `repaired: frozenset[int]`;
    - `open_only: frozenset[int]`: the masked hours whose two bars are complete and whose `differing_fields(aggregated, official, tol) == ("open",)`, where `tol` is `VOLUME_DRIFT_TOLERANCE`, or `Decimal(0)` for a repaired hour, as the eligibility record measured. Hourly-only months have none;
    - `excluded: bool`, set by the 17% rule;
  - `traded_month_mask(minutes: RepairedRead, hourly: RepairedRead, month: str, exclusions: Sequence[BasketExclusion]) -> MonthMask`, for a traded pair's evaluation month (rules 1 and 2). An expected hour enters only if:
    - exactly one 1h bar exists;
    - exactly one 1m bar exists at each of its 60 minute opens, and none elsewhere in it;
    - and the aggregated minutes match the 1h bar under `drift-tolerance-v1`, or exactly (`Decimal(0)`, prices and volume) when either archive repaired a row in that hour.
    Every other expected hour is masked, with its reason;
  - `hourly_only_month_mask(hourly: RepairedRead, month: str, exclusions: Sequence[BasketExclusion]) -> MonthMask`, for untraded basket symbols, an untraded proxy, and traded pairs' hourly warm-up months (rule 1, "Hours with no minute data", and rule 5). An expected hour enters only if exactly one 1h bar exists and it is not a repaired row;
  - `SEVENTEEN = Fraction(17, 100)`, and `apply_seventeen_percent(month: MonthMask) -> MonthMask`. A month is excluded when its real defects, its masked hours other than `open_only`, are more than 17% of its expected hours. An excluded month has all its expected hours masked;
  - `masked_days(masked: Iterable[int]) -> frozenset[int]`, the UTC day opens that contain a masked hour (rule 3).
- **Hours inside a documented exclusion** are neither expected nor fed to the features. They stay absent, as today.

- [ ] **Step 1: Write the failing tests:**
  - `test_clean_hour_enters_and_incomplete_hour_is_masked`: 60 matching minutes enter; 59 minutes mask the hour (rule 2).
  - `test_repaired_hour_needs_an_exact_match` (Review Focus 2): a repaired hour whose volume differs by 0.05% is masked, and the same hour unrepaired enters as drift.
  - `test_extra_minute_or_second_hourly_bar_masks_the_hour`
  - `test_hourly_only_symbol_masks_repaired_hours` (rule 5)
  - `test_seventeen_percent_rule_boundary_listing_and_open_only` (Review Focus 4):
    - in a 700-hour expected month, 119 real defects (exactly 17%) keep it, and 120 exclude it;
    - open-only hours do not count toward either;
    - in SOLUSDT 2020-08, the 246 hours before listing are not expected, so they do not count.
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
- Modify: `src/crypto_grid_bot/backtest/jobs.py`: `prepare_run`, `run_job` and `cross_check_job`
- Modify: `src/crypto_grid_bot/backtest/trend_benchmark.py`: `trend_job`, which passes the masks through
- Test: `tests/test_backtest_masked_checks.py`

**Interfaces:**
- **Consumes:** Tasks 1 and 2.
- **Produces:**
  - **`load_candles(..., mask: frozenset[int] | None = None)` and `load_minutes(..., mask=...)`:**
    - with `mask=None`, exactly today's strict loading, which refuses an archive with repaired or dropped rows. So only callers carrying a mask admit repaired data, and every stage-1 run reads as before;
    - with a mask, they read 1m and 1h archives with `read_archive_repaired` and drop every bar in a masked hour;
    - **fail-closed, as today:** an archive the manifest lists as `ok` that reads as unreadable raises `DataError` (`tests/test_backtest_loaders.py:115-131`). Only manifest status `"unreadable"` (Task 7) gives no bars, which `_archive_months` already ensures;
  - **the three cross-checks** take the masked hours and remove them from the expected set (spec v1 §5, "The post-mask expected set"). `cross_check_daily` takes the masked days from its caller, skips each, and counts it in `daily_days_skipped_for_masks`, a key it writes only when non-zero (rule 3);
  - **`cross_check_job`** computes every symbol's masks month by month (Task 2): the pair, the proxy and each basket member. It returns `masks: {symbol: sorted masked hours}` and the per-month table, both written only when non-empty;
  - **`run_job(..., masks: Mapping[str, Sequence[int]] = {})` and `trend_job(..., masks=...)`.** `prepare_run` applies each symbol's mask to the pair's hourly bars, to the proxy's series and to every basket member's series. So `prepared.hourly` is post-mask, which Plan 1's `Perception` reads. D's minutes use the pair's mask, and D's rows carry Task 4's fields.
- **With no masks,** every function behaves byte for byte as today.

- [ ] **Step 1: Write the failing tests:**
  - `test_no_mask_changes_nothing`: each check and loader with no mask equals today's on the existing fixtures.
  - `test_masked_hour_leaves_the_expected_set`: a masked hour with no minutes fails no check.
  - `test_daily_check_skips_and_counts_masked_days`: the day is skipped and counted, and its official 1d bar stays in use.
  - `test_masks_reach_the_proxy_the_basket_and_variant_d` (Review Focus 3)
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
- **Produces,** on every row, D's and MS's included, each field written only when non-zero (spec v1 §5 rule 1, "Each run reports"):
  - `masked_hours`: the run's masked evaluation hours;
  - `days_skipped_for_masks` (rule 3);
  - `fills_after_masked_span`: fills on the first replayed bar after a masked span (rule 4). Orders stay open across the span, and the engine's own gap rules apply unchanged.

- [ ] **Step 1: Write the failing tests:** `test_fill_after_a_masked_span_is_flagged`, and `test_unmasked_run_rows_gain_no_field`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `pytest -q` and `python scripts/byte_identity.py check`.** Expected: PASS, and `ALL IDENTICAL`.
- [ ] **Step 5: Commit** `feat: runs report masked hours, skipped days and fills after a masked span`.

*Open Tasks 1–4 as one PR.*

### Task 5: The comparison mask, written before scoring

**Files:**
- Modify: `src/crypto_grid_bot/backtest/__main__.py`: the `run` command and a new `mask-report` command
- Test: `tests/test_backtest_cli.py`, `tests/test_backtest_acceptance.py`

**Interfaces:**
- **Produces:**
  - **`results.json["comparison_mask"]`,** written before any run starts, and only when its content is non-empty: a masked hour, an excluded month or a breach of XRP's test. It holds, per symbol, the masked hours as merged `[from, to)` ISO ranges with their reasons, and the excluded pair-months. The CLI passes the `{symbol: mask}` map to every run;
  - **`python -m crypto_grid_bot.backtest mask-report --spec X --data-dir data`,** which prints JSON without replaying:
    - the comparison mask;
    - for each symbol-month: the expected hours, the masked hours, the open-only hours, the real-defect share, and whether it is excluded;
    - XRP's test statistic, the widest quote spread found, whether or not it breaches.
- **`acceptance.py` is unchanged,** as Plan 1 also requires. Masked hours never exclude a pair-window. The one exclusion these rules add, XRP's (Task 6), reaches the scorer through the cross-checks that `window_of` already reads.

- [ ] **Step 1: Write the failing tests:**
  - `test_mask_is_written_before_runs_and_only_when_non_empty`;
  - `test_mask_report_prints_shares_without_replaying`;
  - `test_window_of_is_unchanged_without_the_new_keys`, a synthetic `window_of` test on cross-checks that carry none of the new keys. The real stage-1 check is Task 10: stage 1's files are not in the repository, and the scorer pins its own code.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `pytest -q` and `python scripts/byte_identity.py check`.** Expected: PASS, and `ALL IDENTICAL`.
- [ ] **Step 5: Commit** `feat: the comparison mask in results.json, and mask-report`.

### Task 6: XRP's actual-quotes test

**Files:**
- Modify: `src/crypto_grid_bot/backtest/masking.py`; `jobs.cross_check_job`; `__main__.py`'s `INTEGRITY_FIELDS`
- Test: `tests/test_masking.py`, `tests/test_backtest_cli.py`, `tests/test_backtest_acceptance.py`

**Interfaces:**
- **Produces:** `widest_spread_pct(minutes: Iterable[Kline], symbol: str, spread: Decimal, tick: Decimal) -> Decimal`, the largest `(ask − bid) ÷ ask × 100` over every quote that `replay.bar_quotes(kline, symbol, "high_first", spread, tick)` synthesizes. Both paths give the same four quotes, so one path suffices. A breach is `widest_spread_pct(...) > limit_pct`: the engine's own condition (`runner.py`, `_validate_frame`).
- **The rule** (spec v1 §5 rule 8, decision 16): for XRPUSDT only, over the window's replayed minutes, which are the evaluation months after masking, with the dataset's assumed spread, the manifest's tick and `config/default.toml`'s `maximum_spread_pct`. It is computed month by month, like the masks.
- **Only a breach writes anything** into `results.json`. A pass writes nothing, so `practice-2022`, whose XRP passes, keeps its stage-1 identity. A breach excludes XRP's pair-window for every variant, through the existing machinery:
  - XRP's cross-check record gains `tick_limit_quotes`, the number of quotes above the limit, written only when non-zero;
  - `__main__.INTEGRITY_FIELDS` gains that field, read as 0 when absent, so `scoped_failures` makes it XRP's own failure. `excluded_pairs["XRPUSDT"]` then names it, and `acceptance.window_of` excludes the same pair-window, with `acceptance.py` unchanged;
  - the comparison mask records the breach.

- [ ] **Step 1: Write the failing tests:**
  - `test_one_wide_quote_excludes_xrp_and_a_pass_writes_nothing` (Review Focus 5). Warm-up minutes do not count;
  - `test_quotes_at_the_limit_pass`;
  - `test_practice_2022_xrp_passes`, on a synthetic copy of its tick and spread;
  - `test_scorer_excludes_the_same_xrp_window`: `acceptance.window_of` on a results file with `tick_limit_quotes` excludes XRP's pair-window, and no XRP run is then expected.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `pytest -q` and `python scripts/byte_identity.py check`.** Expected: PASS, and `ALL IDENTICAL`.
- [ ] **Step 5: Commit** `feat: XRP's actual-quotes test (spec v1 section 5 rule 8)`.

### Task 7: Repairable and unreadable archives in a fetch

**Files:**
- Modify: `src/crypto_grid_bot/backtest/dataset.py`: `fetch_dataset` and `verify_dataset`
- Test: `tests/test_backtest_data.py`

**Interfaces:**
- **Produces:** for 1m and 1h archives, a fallback in `fetch_dataset`, not in `fetch_file`, which `audit_run._fetch` and `tests/test_backtest_audit.py:258-283` rely on to raise `ArchiveParseError`. When `fetch_file` raises it after the archive downloaded and verified against its checksum, `fetch_dataset` reads the stored file with `read_archive_repaired`:
  - an unreadable archive gets status `"unreadable"`, with its reason;
  - any other archive gets status `"ok"`, with the repaired read's `FileStats`. #156's manifest of this window lists 108 such archives, from 2018-07 to 2023-03, and the first is the sixth file `required()` lists.
- **`verify_dataset`** accepts `"unreadable"` with its SHA-256. The loaders give no bars for it, so its hours are absent, then masked, and they count toward the 17% rule (spec v1 §5 rule 1, "The reader").
- **A strictly valid archive's entry is unchanged,** so refetching a stage-1 window gives the same manifest.

- [ ] **Step 1: Write the failing tests:**
  - `test_truncated_close_archive_is_fetched_as_ok_with_repaired_stats`;
  - `test_unreadable_archive_is_recorded_not_fatal`;
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
  - `test_full_range_2019_2024_matches_spec_v1_section_4`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Write the spec files.**
- [ ] **Step 4: Run `pytest -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `data: the frozen full-range dataset specs`.

### Task 9: Bob's re-fetch, and the manifest

**Files:**
- Create: `scripts/fetch_full_range.py`, a pinned script
- Create: `docs/tasks/<date>-bob-full-range-2017-2024-fetch.md`, in the format of `docs/tasks/2026-09-27-bob-p8-funding-archives.md`
- Later, from Bob's report: `config/datasets/full-range-2017-2024.manifest.json`

**Interfaces:**
- **`scripts/fetch_full_range.py <data-dir>`:**
  - copies the committed spec into `<data-dir>`, so that every write lands under the git-ignored `data/`. Bob's workflow refuses any change outside a new `docs/reviews/*-bob-*.md` (`bob-task.yml:305-309`);
  - calls `fetch_dataset(..., instruments=...)` with the BTCUSDT, ETHUSDT and XRPUSDT filters taken from the committed `config/datasets/long-bull-bear-2022.manifest.json`, so no request goes to `data-api.binance.vision`, which Bob's prompt forbids (`bob-task.yml:228-233`);
  - fetches BTCUSDT's funding archives for 2020-01 to 2024-12 with `fetch_funding_file`, from `data.binance.vision`, so the manifest matches spec v1 §4;
  - then runs `verify` and `mask-report` on that copy.
- **Bob's report:**
  - a compact digest table, one row per archive: path, SHA-256, status and `FileStats`. It stays under `validate_bob_artifact.py`'s 200,000-byte limit; #156's full manifest was 529,180 bytes;
  - the `mask-report` output.
  Claude rebuilds the manifest from the digest, checks each SHA-256 against Binance's `.CHECKSUM` files, and commits it in a reviewed PR, as with P8.
- **Stop conditions:** a checksum mismatch; any request to another host; any month after 2024-12; a pair-window left with fewer than 2 included pairs.
- **Order:** the task file's PR merges only after Tasks 1–7 are on main. A merge that adds a task file starts Bob at once (`bob-task.yml:5-6`), and Bob needs `mask-report` and the new fetch statuses.
- **The manifest PR,** and a test there, assert all 1,164 kline entries and all 60 funding entries.

- [ ] **Step 1: Write the failing test** `test_fetch_full_range_writes_only_under_data_and_uses_committed_filters`. It runs the script against a fake fetcher, and asserts that no file outside `<data-dir>` changes, that no request goes to another host, and that all 60 funding months are fetched.
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
- **Produces:** `python scripts/stage1_identity.py <stage-1 results dir> <re-run results dir>`. It pairs each `results.json` by dataset, policy and path, and prints `IDENTICAL` or the differing keys for each pair. It exits 0 only when every pair is identical apart from `code_commit` and `code_sha256`, and no new mask field appears (decision 18).
- **The re-run:** stage 1's 24 workflow runs at the commit that merges Tasks 1–7, compared with stage 1's downloads. Dispatching them needs the owner's go.

- [ ] **Step 1: Write the failing tests:** `test_identical_apart_from_fingerprints_passes`, `test_any_other_difference_fails`, and `test_a_new_mask_field_fails`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `pytest -q`.** Expected: PASS.
- [ ] **Step 5: Commit** `test: the stage-1 identity check (decision 18)`.
