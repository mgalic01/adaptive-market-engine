# Claude → Codex and Bob: G funding signal implemented (spec v1 §3 G)

- **Status:** PR on `claude/repo-connection-mqhoss`. The owner authorised a merge on
  Bob's positive review with green checks while Codex is unavailable
  (2026-09-25). Codex: please review after the fact.
- **Scope:** the funding archive parser and the point-in-time G signal only. They are
  **not wired into replay**. V0, risk limits, exits, the profit vault, paper-only scope
  and the reserved window are unchanged, and no data is fetched.

## What changed

- `src/crypto_grid_bot/backtest/funding.py` (new):
  - `parse_funding_rows` / `read_funding_archive` strictly parse Binance USDⓈ-M
    monthly `fundingRate` CSVs:
    - the header must be exact;
    - millisecond or microsecond times are accepted;
    - each settlement must fall in the archive month, in strictly increasing order.

    An empty or non-integer interval and a non-finite rate are **kept** as records,
    so G can see them and fail closed. They are never dropped.
  - `FundingRecord`:
    - `scheduled_ms` is `calc_time` floored to the UTC hour;
    - `usable_ms` is `calc_time` truncated to the second, plus 60 s;
    - `valid` means an accepted interval {1, 2, 4, 8} and a finite rate.
  - `FundingSignal(records).state(t)` applies the uniform-cadence rule over the three
    newest usable records:
    - it checks, in order: insufficient history, invalid newest record, invalid older
      record, mixed interval, step mismatch, and overdue
      (`t >= scheduled(r3) + I + 60 s`);
    - a duplicate scheduled time raises `DataError` (integrity failure);
    - it blocks when the signal is unavailable, or when all three rates are
      `> 0.0005` (strict).
- `klines.read_member`: the zip-member reader shared by both parsers (no change in
  behaviour).
- **Spec §3 G:** the two optional review nits from PR #20:
  - the 4 → 8 test is spelled out as (4, 4, 8) and (4, 8, 8) unavailable and
    (8, 8, 8) available;
  - "missing newest record" now names the overdue deadline and `4 × I`, instead of a
    fixed 32 hours.

## Evidence

- `tests/test_funding.py` has 17 tests with 23 subtests, one per spec required-test
  line, all on synthetic series:
  - constant cadence;
  - both transitions, including the between-deadline observations and the first
    changed record's publication boundary;
  - hidden gap;
  - missing newest record;
  - invalid newest records (0, 3, 12, empty, NaN, ±Infinity), never falling back;
  - insufficient history (0, 1, 2 records);
  - invalid older records;
  - unseen shortening;
  - duplicate scheduled times;
  - the rate, usability and overdue boundaries;
  - recovery after a gap and after a transition;
  - negative funding;
  - the parser's structure errors and archive-member check.
- `pytest`, `ruff check`, `ruff format --check`, `mypy src` and `bandit` are clean
  (Python 3.12).

## Not yet done

- **"Existing grids and exits unchanged in every unavailable state":** this needs
  replay wiring, so it belongs to the next step. So does the P8 funding-archive
  fetch and manifest.
