# Claude's recheck of Bob's full-range fetch, and corrections to its report

Index: Claude rebuilt both long-window manifests from Bob's digest (run 37605943947) and reproduced all three SHA-256s; the fetch is complete. Corrections to Bob's report: XRPUSDT is excluded by spec v1 §5 rule 8, its "545" counts quotes, the daily mismatch is a bar disagreement (2021-01-21's volume, owner exception granted), and 212 ok archives are not complete months.

- **Date and author:** 2026-10-07, written by Claude (session `b9db01ca`).
- **Bob's report:** [`2026-10-07-bob-full-range-2017-2024-fetch.md`](2026-10-07-bob-full-range-2017-2024-fetch.md), merged in #198. Bob's report is a run record and is not edited after the run. This file corrects how it reads its results, as Codex (five P2s on #198) and the automated review (four nits) asked.
- **Task:** [`docs/tasks/2026-10-07-bob-full-range-2017-2024-fetch.md`](../tasks/2026-10-07-bob-full-range-2017-2024-fetch.md). The first run (37591538301) lost its report (#195), the fix was merged in #196, and the owner started this re-run with `/bob-run`.

## What Claude checked

- **The digest and both manifests reproduce exactly.**
  - The digest in Bob's report hashes to `d10331a68985b3daa678debbc666d55fe04f13bc5be5fbf15f2e337e879b89ef` (125,659 bytes, final newline included), as Bob printed.
  - The fetch script's `rebuild`, given the committed specs and the committed filters, writes both manifests from that digest.
  - Their SHA-256s are exactly those Bob printed: `069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e` for `full-range-2017-2024.manifest.json`, and `40fa4da932b661e846d2cdf19ee3ae099bd9b1ec1f5ab13a3069dd82a4f223dc` for `full-range-2019-2024.manifest.json`.
  - Claude made no request to Binance. The checksums Bob's fetch verified are the evidence for the archives' content.
- **Against #156's manifest** (commit `25e7136`):
  - every entry that #156 had `ok`, 1,010 of them, matches on SHA-256, size and statistics;
  - its 46 `missing` entries are the same 46 here: the months before SOL, DOGE and LINK listed.
- **The 108 archives #156 left `unparsed`** (82 1h and 26 1m, 2018-07 to 2023-03) are all `ok` now, through Plan 2 Task 7's repairing fallback. 91 of them have gaps or missing rows, and 17 read as complete months. The manifests PR's test pins all 108 with their status and full statistics.
- **The run kept its limits.** It made 3,613 requests, all to data.binance.vision, with nothing after 2024-12 and no reserved-window file. The pins and the 27 tests passed, and all 60 funding months are `ok`.

## Corrections to Bob's report

1. **XRPUSDT is excluded.** The report's Results say "The scored window keeps 3 of 3 pairs ... No XRPUSDT exclusion." That restates the script's `included pairs 3 of 3` line, which is an artifact: `backtest/__main__.py` clears `excluded_pairs` when a shared failure makes `verify` invalid, and the script then reads the absent field as no exclusions.
   - XRPUSDT's actual-quotes test breaches: its widest spread is 0.1972% against the 0.15% limit. That meets spec v1 §5 rule 8's condition.
   - So XRPUSDT's pair-window is excluded for every variant (spec v2 §8: "XRP stays in unless its actual-quotes test excludes it").
2. **`tick_limit_quotes=545` counts quotes, not hours.** The replay synthesizes four quotes for each replayed minute, and 545 of them have a spread above the limit. The MASK line says the same.
3. **`daily_days_mismatched=1` is a bar disagreement, not a day count.** Bob's Ideas guessed at a missing, extra or leap day. `daily_days_mismatched` counts days whose official 1d bar disagrees with the aggregation of its 24 hourly bars beyond `drift-tolerance-v1`; missing and duplicated days are `daily_days_missing` and `daily_days_duplicated`.
   - It is almost certainly 2021-01-21. Bob's defect calendar (#60, [`2026-09-26-bob-hourly-defect-calendar.md`](2026-09-26-bob-hourly-defect-calendar.md)) found that on that day every pair's official 1d bar has about 2.4% less volume than its 24 hourly bars, while the prices agree exactly. BTCUSDT, ETHUSDT and XRPUSDT are among those pairs, and no other day fails for them.
   - `verify` does not name the day today. The owner granted an exception for that day on record (decision 14, [`2026-10-07-claude-v2-decisions-after-first-read.md`](2026-10-07-claude-v2-decisions-after-first-read.md)). Its PR also makes the cross-check record name every mismatched date, so the next `verify` proves which day it was. If another day mismatches, the check still fails.
4. **Steps 1 to 3 show outputs without their commands.** The task prescribes them, and the outputs match what they print:
   - Step 1: the clock, `git rev-parse HEAD`, `python --version` and the `data` directory;
   - Step 2: `git rev-parse HEAD:src` (printed `96de9766551d478883f3451bcaae261f165fd3d4`, the pinned tree), `git status --porcelain --untracked-files=no -- src` (printed nothing), the pin-block extraction (`6 pins`) and `sha256sum -c` (six `OK`);
   - Step 3: `python -m pytest -p no:cacheprovider tests/test_fetch_full_range.py` (`27 passed`).
5. **Not every ok archive is a complete month.** The run log's full lines are:
   - `KLINES full-range-2017-2024: 1164 files; missing 46, ok 1118; complete months 906`;
   - `KLINES full-range-2019-2024: 1080 files; missing 25, ok 1055; complete months 876`.

   So 212 ok archives in the scored window (161 1h and 51 1m) have statistics other than a full month: listing months, internal gaps, or rows that the repairing reader repaired or dropped. The masks account for them: `MASK totals symbols_with_a_mask=9 repaired_hours=81 dropped_hours=0 masked_hours=789 excluded_months=0`, with no month excluded under the 17% rule.

## What follows

- **The manifests** are committed in the PR that adds this file.
- **The 2021-01-21 exception** is a separate PR. It is a code change to the daily check, behind the owner's decision 14.
- **Then the formal runs on `full-range-2017-2024`:** the mode switcher with D, and always-grid (variant F), at spec v1's primary fees, scored by `acceptance_v2`. With XRPUSDT excluded, the scored window has two included pairs, BTCUSDT and ETHUSDT, if their daily checks pass once the exception lands. Two is the minimum spec v2 §8 requires.
