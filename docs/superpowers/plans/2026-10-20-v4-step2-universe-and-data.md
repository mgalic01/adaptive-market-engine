# V4.0 Step 2: Universe and Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build V4's data step. It discovers every Binance USDT spot symbol, delisted ones
included, chooses the monthly top 10 by volume, fetches and verifies the hourly spot,
hourly futures and funding archives those coins need, and writes two packs pinned by
SHA-256. A GitHub workflow runs it all.

**Architecture:** This is a new package, `src/crypto_grid_bot/v4/data/`, with one focused
module per responsibility: config, listing, archives, bars, universe, filters and pack.
A CLI, `scripts/v4_data.py`, runs the stages, and `.github/workflows/v4-data.yml` runs the
CLI on GitHub's machines in sharded jobs. The heavy steps run only there, never on the
owner's PC.

The frozen readers in `backtest/` refuse every month after 2024-12. V4 therefore has its own
small readers and its own end-month guard, taken from `config/v4_data.json`. The V3 and
V3.1 guards stay untouched.

**Tech Stack:** Python 3.12, standard library only: `urllib`, `zipfile`, `gzip`, `json`,
`xml.etree.ElementTree` and `decimal`. pytest with the network blocked. GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-17-v4-design.md`, sections "Universe: coins
chosen by a rule", "Data" and "Delivery" (step 2). Step 1 is done (#287, #288).

## Global Constraints

- Paper simulation only. No API keys, no account endpoints, no orders.
- Hosts are an allowlist: `data.binance.vision` for archives, and
  `s3-ap-northeast-1.amazonaws.com` for bucket `data.binance.vision`, listing only. No
  other host is opened.
- Never edit `src/crypto_grid_bot/simulation/`, `trend/`, `strategy/` or `backtest/`.
  Importing from them is fine where the import does not run their 2024 guard. Their
  readers do run it, so V4 has its own readers.
- The window starts at the first eligible daily bar on or after 2017-08-17.
- The window ends at `end_month` in `config/v4_data.json`, the last complete calendar month
  before prepare runs. Owner decision v4-d03 opens 2025 onward for V4 only. No month after
  `end_month` is ever requested or read.
- The universe uses these exact values from the spec:
  - stablecoin bases `USDC BUSD TUSD USDP PAX DAI FDUSD USDD UST EUR GBP AUD TRY BRL`;
  - the stable-price rule: daily close within `0.02` of `1.0` on at least `90%` of the
    last `90` days;
  - leveraged suffixes `UP DOWN BULL BEAR`;
  - wrapped bases `WBTC WBETH BETH STETH`;
  - a minimum of `200` daily bars before the selection date;
  - a `30`-day mean of daily quote volume, counting only days with a bar;
  - a top `10`, with ties broken alphabetically;
  - selection at 00:00 UTC on the first of each month.
- Decimal for prices and volumes, int for millisecond timestamps. Timestamps are
  microseconds from 2025-01 and are normalised to milliseconds.
- Fetch retries are exactly as in `scripts/v31_fetch.py`: 4 tries, with sleeps of 1, 2
  and 4 s, on transport failures only. A hash mismatch, a 4xx, a size breach or a guard
  refusal is never retried.
- Every archive is verified against Binance's `.CHECKSUM` (SHA-256) when first fetched. A
  missing or mismatched checksum is an error, never a skip.
- Packs are canonical JSON, gzipped, written with `xb`. The pin is the SHA-256 of the
  canonical JSON, not of the gzip bytes. This is the `combined/driver/packs.py` convention,
  re-implemented in V4 because that module also carries the 2024 guard.
- Tests block the network, using the autouse fixture pattern from
  `tests/test_v31_fetch.py`. Fakes implement the transport protocol.
- No new dependency. Ruff check and format clean. Commit attribution:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Rulings this plan makes:**

- **R1, leveraged tokens.** A base counts as a leveraged token only if it is
  `X + suffix` and `X` is itself the base of another listed USDT symbol. So BTCUP and
  ETHBEAR are excluded, while JUP and SYRUP are not. The spec's bare "ends in UP" would
  also exclude JUP.
- **R2, filters for delisted symbols.** A symbol absent from the pinned present-day
  `exchangeInfo` gets inferred filters, recorded as `inferred`:
  - `tick` = 10^-d, where d is the most decimals seen in its price fields;
  - `step` = 10^-d for its base-volume field, and `min_qty` = `step`;
  - `max_qty` = `9000000000`;
  - `min_notional` = `5` (spot and futures).
- **R3, filter snapshots.** The present-day filters are the snapshots already committed and
  pinned for V3.1: `config/datasets/v3-20261009/snapshots/{spot,futures}.json`, with pins
  in `config/v3_1_prepare.json` under `filter_snapshots`.
- **R4, the V3 comparison.** V3's frozen pipeline refuses 2025 onward, so `v3_as_built`
  can only cover up to 2024-12, and its common period with V4 ends there. The spec already
  says comparisons use the common period. This is recorded for step 4 and does not affect
  this plan.

## Review Focus

1. **A symbol that was delisted and later relisted** has a gap in its archives. Days
   without bars must not count as zero volume or as history. Pinned in Task 5,
   `test_relisted_symbol_counts_only_days_with_bars`.
2. **Listing pagination.** An S3 listing over 1,000 keys continues through `NextMarker`.
   Losing page 2 silently drops symbols. Pinned in Task 3,
   `test_listing_follows_next_marker_until_not_truncated`.
3. **Mixed timestamp units.** A 2025 kline row is in microseconds. It must land in the
   right month as milliseconds and must not be rejected or read 1000x late. Pinned in
   Task 4, `test_2025_microsecond_rows_normalise_to_milliseconds`.
4. **Futures CSVs have a header row and spot CSVs do not.** A header read as data, or a
   spot first row dropped as a header, corrupts a month. Pinned in Task 4,
   `test_futures_header_is_dropped_and_spot_first_row_kept`.
5. **A checksum file that names another archive or is absent** must fail. Accepting it
   pins the wrong bytes. Pinned in Task 2,
   `test_checksum_for_another_file_or_absent_is_an_error`.

---

## File Structure

| File | Responsibility |
|---|---|
| `config/v4_data.json` | Pinned data-step settings (values above) and `end_month` |
| `src/crypto_grid_bot/v4/__init__.py`, `v4/data/__init__.py` | Package markers (docstrings only) |
| `src/crypto_grid_bot/v4/data/config.py` | `DataConfig`, loading and validation, month range, end-month guard |
| `src/crypto_grid_bot/v4/data/listing.py` | S3 listing parse and pagination, symbol and month discovery |
| `src/crypto_grid_bot/v4/data/archives.py` | Transport protocol, HTTP transport with allowlist, verified fetch with retries, manifest entries |
| `src/crypto_grid_bot/v4/data/bars.py` | V4 readers: daily bars, hourly klines (spot and futures), funding records |
| `src/crypto_grid_bot/v4/data/universe.py` | Static exclusions, stable-price rule, monthly selection |
| `src/crypto_grid_bot/v4/data/filters.py` | Present-day or inferred `VenueRules` per symbol and venue |
| `src/crypto_grid_bot/v4/data/pack.py` | Canonical gzip JSON writer and reader, the daily and hourly pack documents |
| `scripts/v4_data.py` | CLI stages: `discover`, `fetch`, `select`, `pack` |
| `.github/workflows/v4-data.yml` | Sharded GitHub run of the CLI, with artifacts |
| `tests/test_v4_data_*.py` | One test module per source module, network blocked |

---

### Task 1: Config and window

**Files:**
- Create: `config/v4_data.json`, `src/crypto_grid_bot/v4/__init__.py`,
  `src/crypto_grid_bot/v4/data/__init__.py`, `src/crypto_grid_bot/v4/data/config.py`
- Test: `tests/test_v4_data_config.py`

**Interfaces:**
- Produces:
  - `DataConfig`, a frozen dataclass with:
    - `start_day: str` (`"2017-08-17"`), `end_month: str` (`"YYYY-MM"`);
    - `stablecoins: frozenset[str]`, `leveraged_suffixes: tuple[str, ...]`,
      `wrapped: frozenset[str]`;
    - `stable_band: Decimal`, `stable_share: Decimal`, `stable_days: int`;
    - `min_daily_bars: int`, `volume_days: int`, `top_n: int`;
    - `filter_snapshots: dict[str, dict[str, str]]` (venue -> `{path, sha256}`).
  - `load_data_config(path: Path) -> DataConfig`.
  - `months(start: str, end: str) -> tuple[str, ...]`.
  - `refuse_after_end(month: str, config: DataConfig) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_committed_config_loads_with_the_spec_values():
    c = load_data_config(Path("config/v4_data.json"))
    assert c.start_day == "2017-08-17" and c.top_n == 10 and c.min_daily_bars == 200
    assert c.volume_days == 30 and c.stable_days == 90
    assert c.stable_band == Decimal("0.02") and c.stable_share == Decimal("0.9")
    assert c.stablecoins == frozenset("USDC BUSD TUSD USDP PAX DAI FDUSD USDD UST EUR GBP AUD TRY BRL".split())
    assert c.leveraged_suffixes == ("UP", "DOWN", "BULL", "BEAR")
    assert c.wrapped == frozenset({"WBTC", "WBETH", "BETH", "STETH"})

def test_months_is_inclusive_and_ordered():
    assert months("2024-11", "2025-02") == ("2024-11", "2024-12", "2025-01", "2025-02")

def test_months_after_end_month_are_refused(tmp_path):
    c = replace(load_data_config(Path("config/v4_data.json")), end_month="2026-09")
    refuse_after_end("2026-09", c)
    with pytest.raises(ValueError, match="after end_month"):
        refuse_after_end("2026-10", c)

@pytest.mark.parametrize("change", [{"top_n": 0}, {"end_month": "2026-13"}, {"stable_share": "1.5"}, {"extra": 1}])
def test_invalid_or_unknown_config_fields_are_refused(tmp_path, change): ...
```

- [ ] **Step 2: Run them to see them fail**

Run: `pytest tests/test_v4_data_config.py -q`. Expected: import error.

- [ ] **Step 3: Implement**

Add `config/v4_data.json` with the values above, `"end_month": "2026-09"`, and
`filter_snapshots` copied from `config/v3_1_prepare.json`. `load_data_config` refuses
unknown and missing keys, non-integer counts, and shares outside (0, 1]. It refuses a
`start_day` before 2017-08-17 and an `end_month` that is not `YYYY-MM`.

- [ ] **Step 4: Run them to see them pass.** Then commit:
  `v4 data: pinned config and the end-month guard`.

### Task 2: Verified archives and the manifest

**Files:**
- Create: `src/crypto_grid_bot/v4/data/archives.py`
- Test: `tests/test_v4_data_archives.py`

**Interfaces:**
- Produces:
  - `class Transport(Protocol)` with `def get(self, url: str) -> bytes | None`, where None
    means HTTP 404.
  - `HttpTransport(timeout: float = 30)`, which uses `urllib.request` and refuses any host
    or path outside the allowlist before opening a connection.
  - `archive_path(kind: str, symbol: str, month: str) -> str`.
  - `ManifestEntry(kind, symbol, month, path, sha256, bytes)`, frozen.
  - `fetch_verified(transport, kind, symbol, month, config, *, sleep, log) -> tuple[ManifestEntry, bytes] | None`.
  - `fetch_pinned(transport, entry: ManifestEntry, *, sleep, log) -> bytes`.

- [ ] **Step 1: Write the failing tests**
  - `test_archive_paths_match_binance_layout` (the four kinds, exact strings)
  - `test_checksum_for_another_file_or_absent_is_an_error` (Review Focus 5)
  - `test_mismatched_checksum_is_an_error_and_not_retried` (sleeps recorded as `[]`)
  - `test_transport_failures_retry_four_times_with_1_2_4_second_sleeps`
  - `test_a_404_archive_is_none_but_a_404_checksum_is_an_error`
  - `test_http_transport_refuses_other_hosts_without_opening_a_socket`
  - `test_months_after_end_month_are_refused_before_any_request`
  - `test_pinned_fetch_refuses_bytes_whose_sha256_differs`

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement.**
  - Checksum parsing as in `scripts/fetch_v3_data.py::fetch_verified_archive`.
  - Retry classification as in `scripts/v31_fetch.py::_transport_failure`.
  - Archive byte cap: 64 MiB.
  - Allowed paths: the four `archive_path` shapes plus `.CHECKSUM`, and the listing query
    `?delimiter=/&prefix=data/...` with an optional `&marker=`, which Task 3 uses.

- [ ] **Step 4: Run them to see them pass.** Then commit:
  `v4 data: verified archive fetch with allowlist and retries`.

### Task 3: Listing and discovery

**Files:**
- Create: `src/crypto_grid_bot/v4/data/listing.py`
- Test: `tests/test_v4_data_listing.py`

**Interfaces:**
- Consumes: `archives.Transport` and `HttpTransport`'s listing allowlist (Task 2).
- Produces:
  - `ListingPage(prefixes: tuple[str, ...], keys: tuple[str, ...], next_marker: str | None)`.
  - `parse_listing(xml: bytes) -> ListingPage`.
  - `list_all(transport, prefix: str) -> ListingPage`, which merges all pages.
  - `discover_spot_usdt_symbols(transport) -> tuple[str, ...]`, sorted.
  - `discover_months(transport, kind: str, symbol: str, config) -> tuple[str, ...]`, where
    kind is one of `spot_1d`, `spot_1h`, `futures_1h` or `funding`.

- [ ] **Step 1: Write the failing tests**

  The fakes serve S3 `ListBucketResult` XML, built from small fixtures in the test.
  - `test_parse_listing_reads_prefixes_keys_and_marker`
  - `test_listing_follows_next_marker_until_not_truncated` (Review Focus 2)
  - `test_spot_usdt_symbols_come_from_the_klines_prefixes`: `BTCUSDT`, `LUNAUSDT` (delisted
    but present) and `BTCUP` + `USDT` are listed; `BTCBUSD` and `USDTBRL` are dropped
  - `test_months_come_from_zip_keys_and_stop_at_end_month`: a `-2026-10.zip` key with
    `end_month` `2026-09` is left out; `.CHECKSUM` keys are ignored
  - `test_listing_query_is_bucket_and_prefix_only`: the fake records the exact URL
    `https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/spot/monthly/klines/`
    with an optional `&marker=`, which Task 2's `HttpTransport` allowlist accepts

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement** with `xml.etree.ElementTree`. Use the S3 namespace
  `http://s3.amazonaws.com/doc/2006-03-01/`. Refuse a page over 4 MiB. The prefixes are:
  - `spot_1d`: `data/spot/monthly/klines/{S}/1d/`
  - `spot_1h`: `.../{S}/1h/`
  - `futures_1h`: `data/futures/um/monthly/klines/{S}/1h/`
  - `funding`: `data/futures/um/monthly/fundingRate/{S}/`

- [ ] **Step 4: Run them to see them pass.** Then commit:
  `v4 data: archive listing and symbol and month discovery`.

### Task 4: V4 readers

**Files:**
- Create: `src/crypto_grid_bot/v4/data/bars.py`
- Test: `tests/test_v4_data_bars.py`

**Interfaces:**
- Consumes: archive bytes from Task 3.
- Produces:
  - `DailyBar(open_ms: int, open: Decimal, high: Decimal, low: Decimal, close: Decimal, quote_volume: Decimal)`.
  - `HourBar` with the same fields plus `volume: Decimal`.
  - `FundingRow(time_ms: int, rate: Decimal)`.
  - `read_daily(content: bytes, symbol: str, month: str) -> tuple[DailyBar, ...]`.
  - `read_hourly(content: bytes, symbol: str, month: str, *, futures: bool) -> tuple[HourBar, ...]`.
  - `read_funding(content: bytes, symbol: str, month: str) -> tuple[FundingRow, ...]`.

- [ ] **Step 1: Write the failing tests**
  - `test_2025_microsecond_rows_normalise_to_milliseconds` (Review Focus 3)
  - `test_futures_header_is_dropped_and_spot_first_row_kept` (Review Focus 4)
  - `test_rows_outside_their_month_or_unordered_are_errors`
  - `test_quote_volume_is_csv_column_7`
  - `test_funding_reads_calc_time_and_rate`, with the header
    `calc_time,funding_interval_hours,last_funding_rate`
  - `test_member_name_must_match_the_archive`: the zip holds exactly `<file>.csv`

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement.**
  - The column map follows `backtest/klines.py` (`_row_bar`) and its µs rule (`_timestamp`).
    Do not call those, because they run the 2024 guard.
  - The futures header text equals `scripts/fetch_v3_data.py::KLINE_HEADER`.

- [ ] **Step 4: Run them to see them pass.** Then commit: `v4 data: readers for 2017 onward`.

### Task 5: Candidates and the monthly universe

**Files:**
- Create: `src/crypto_grid_bot/v4/data/universe.py`
- Test: `tests/test_v4_data_universe.py`

**Interfaces:**
- Consumes: `DataConfig` (Task 1) and `DailyBar` (Task 4).
- Produces:
  - `static_exclusion(symbol: str, bases: frozenset[str], config) -> str | None`. It returns
    a reason (`"stablecoin"`, `"leveraged"`, `"wrapped"`), or None.
  - `stable_price(bars: Sequence[DailyBar], at_ms: int, config) -> bool`.
  - `MonthlyUniverse`, frozen, with `month: str`, `selected: tuple[str, ...]`,
    `ranked: tuple[tuple[str, Decimal, int], ...]` (symbol, mean quote volume, bars in
    window), `excluded: tuple[tuple[str, str], ...]`, `entered: tuple[str, ...]` and
    `left: tuple[str, ...]`.
  - `select_universe(daily: Mapping[str, Sequence[DailyBar]], config) -> tuple[MonthlyUniverse, ...]`.

- [ ] **Step 1: Write the failing tests**
  - `test_static_exclusions_follow_the_spec_and_ruling_r1`:
    - `BTCUP` gives `"leveraged"` when BTC is a base, and `JUP` gives None;
    - `USDCUSDT` gives `"stablecoin"`, and `WBTCUSDT` gives `"wrapped"`.
  - `test_stable_price_rule_needs_90_percent_of_90_days_within_2_percent`: 81 of 90 is
    stable, and 80 of 90 is not.
  - `test_ranking_uses_the_30_day_mean_over_days_with_bars_and_needs_200_bars`.
  - `test_relisted_symbol_counts_only_days_with_bars` (Review Focus 1).
  - `test_ties_break_alphabetically_and_only_the_top_10_are_selected`.
  - `test_first_selection_is_the_first_month_any_symbol_has_200_bars`: with BTC from
    2017-08-17, the first non-empty selection is `2018-04` (227 days before 2018-04-01,
    196 before 2018-03-01).
  - `test_entered_and_left_are_relative_to_the_previous_month`.

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement.**
  - A selection at month M uses only bars with `open_ms` before M's first millisecond.
  - Volumes are Decimal means.
  - The output is ordered by month.

- [ ] **Step 4: Run them to see them pass.** Then commit:
  `v4 data: candidates and the monthly top 10`.

### Task 6: Filters

**Files:**
- Create: `src/crypto_grid_bot/v4/data/filters.py`
- Test: `tests/test_v4_data_filters.py`

**Interfaces:**
- Consumes:
  - `combined.driver.venues.venue_rules(snapshot, symbol, venue) -> VenueRules`;
  - `combined.execution.VenueRules(step, min_qty, max_qty, min_notional, tick)`;
  - bars from Task 4.
- Produces: `rules_for(symbol: str, venue: str, snapshot: Mapping[str, object], bars: Sequence[HourBar]) -> tuple[VenueRules, str]`.
  The second element is `"present_day"` or `"inferred"`.

- [ ] **Step 1: Write the failing tests**
  - `test_present_day_symbol_uses_the_snapshot`
  - `test_absent_symbol_infers_tick_and_step_from_decimals_ruling_r2`: prices `0.09865` and
    `0.1` give tick `0.00001`; volumes `1601.1` give step `0.1`; min_notional is `5`
  - `test_inferred_rules_are_labelled_inferred`

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement.** Count decimals from the Decimal exponent of the CSV string
  values, never from floats.

- [ ] **Step 4: Run them to see them pass.** Then commit:
  `v4 data: present-day or inferred venue rules`.

### Task 7: Packs

**Files:**
- Create: `src/crypto_grid_bot/v4/data/pack.py`
- Test: `tests/test_v4_data_pack.py`

**Interfaces:**
- Consumes: Tasks 2-6 types.
- Produces:
  - `write_canonical(document: Mapping, path: Path) -> str`, which returns the pin.
  - `read_canonical(path: Path, expected_sha256: str) -> dict`.
  - `daily_pack_document(config, manifest: Sequence[ManifestEntry], daily: Mapping[str, Sequence[DailyBar]], exclusions: Mapping[str, str], universes: Sequence[MonthlyUniverse]) -> dict`,
    with format `"v4-daily-pack/1"`.
  - `hourly_pack_document(config, manifest, spot: Mapping[str, Sequence[HourBar]], futures: Mapping[str, Sequence[HourBar]], funding: Mapping[str, Sequence[FundingRow]], rules: Mapping[tuple[str, str], tuple[VenueRules, str]]) -> dict`, with
    format `"v4-hourly-pack/1"`.

- [ ] **Step 1: Write the failing tests**
  - `test_pin_is_sha256_of_canonical_json_not_gzip_bytes`
  - `test_existing_file_is_refused`
  - `test_reader_refuses_a_wrong_pin_duplicate_keys_floats_and_nan`
  - `test_round_trip_keeps_decimals_as_strings`
  - `test_documents_record_config_sha256_end_month_and_every_manifest_entry`

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement** with the `combined/driver/packs.py` conventions:
  - `sort_keys`, separators `(",", ":")`, ASCII, `allow_nan=False`;
  - gzip `mtime=0` and no filename;
  - read cap 2 GiB.

  Rows are lists: daily `[open_ms, o, h, l, c, quote_volume]` and hourly
  `[open_ms, o, h, l, c, volume, quote_volume]`.

- [ ] **Step 4: Run them to see them pass.** Then commit:
  `v4 data: canonical packs pinned by SHA-256`.

### Task 8: CLI and GitHub workflow

**Files:**
- Create: `scripts/v4_data.py`, `.github/workflows/v4-data.yml`
- Test: `tests/test_v4_data_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: Sequence[str] | None = None, *, transport: Transport | None = None, sleep=time.sleep) -> int`,
  with these subcommands:
  - `discover --out D`: writes `D/symbols.json` (candidates, exclusions and per-kind month
    lists) and prints counts only.
  - `fetch --kind spot_1d|spot_1h|futures_1h|funding --symbols-file F --shard i/n --cache C --out D`:
    writes `D/manifest-<kind>-<i>.json`.
  - `select --daily-manifests ... --cache C --out D`: writes `D/universe.json` and
    `D/selected.txt`, the symbols ever in a top 10.
  - `pack --manifests ... --cache C --out D`: writes both packs and `D/data.json` with the
    pins.

- [ ] **Step 1: Write the failing tests** (network blocked, fake transport, two-month world)
  - `test_end_to_end_on_a_fake_world_produces_both_packs_and_pins`
  - `test_shards_partition_symbols_without_overlap_or_gap`
  - `test_no_output_prints_bar_values`: stdout holds counts and pins only
  - `test_workflow_has_the_expected_jobs_and_no_cache_of_results`: parse the YAML and check:
    - jobs `discover`, `fetch-daily` (matrix of 16 shards), `select`, `fetch-hourly`
      (matrix of 8 shards with the three kinds), and `pack`;
    - `workflow_dispatch` only, with input `stage` (`discover` stops after `discover`;
      `full` runs every job);
    - shard artifacts at `retention-days: 1`, and the pack artifact `v4-data` at `90`.

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement.**
  - The workflow runs on `ubuntu-latest` with Python 3.12, pins actions by full SHA (as in
    `v31-run.yml`), and uses `timeout-minutes: 300` per job.
  - Each fetch job uploads its verified archives and manifest piece. `pack` downloads them
    all, re-verifies every archive against its manifest SHA-256, and builds the packs.
  - A final step refuses any file named for a month after `end_month`.

- [ ] **Step 4: Run them to see them pass.** Then commit:
  `v4 data: CLI and the sharded GitHub workflow`.

- [ ] **Step 5: Push and open the PR.** CI runs the full suite; it is not run on the
  owner's PC.

  The PR follows the standing review bar: a claim, Bob's deep review, Codex, CI and the
  automated review. After the PR is integrated, `workflow_dispatch` becomes possible.

  The first real dispatch is `discover` only, to report the symbol and archive counts and
  an estimate of size and time. The full data run follows after the owner sees those
  numbers.
