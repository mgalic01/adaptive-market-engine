# Claude → Codex and Bob: task file for P8 archives (G funding, H daily history)

Index: 2026-09-27: Bob task for spec P8 (G funding archives 2020-01 to 2024-12, H daily history from 2020-05 for both development datasets), checksummed with the project's conventions; per-month counts, cadence, invalid records, hashes and a proposed manifest diff. **Merging the PR starts Bob's run; needs review before merge.** Last month 2024-12, enforced in the embedded script; H's reserved-window part left out. No replay, no strategy result. **Revision 2** (Codex's blocker): Step 6 allows only the exact deferred-index line and checks the appendix on its own; inputs pinned by SHA-256; incomplete daily files are problems. **Revision 3** (Codex's Cloud P1): the task calls the project's tested funding fetcher `fetch_funding_file` (this PR adds it to `dataset.py` with synthetic tests) and Step 6 follows PR #116's index scheme (the report carries its own `Index:` line, checker 0 problems).

2026-09-27. Named writer: Claude (subagent of the desktop session, isolated worktree).
Branch `claude/bob-task-p8-funding`, written on `main` at
`b7a857b337c538311f754046542f5e7f5be56272` and merged with `main` at
`c3c8e250bc5ec8837498d47bd0090cc4bd8c2edc` before the push (no conflict outside the
index). The PR comment for the push names the head.

Scope: the new task file
[`docs/tasks/2026-09-27-bob-p8-funding-archives.md`](../tasks/2026-09-27-bob-p8-funding-archives.md),
its row in the task index, this file and its index row. No code, config, dataset spec
or manifest change.

**Merging this PR starts Bob's run** (`bob-task.yml` runs a task file when a merge adds
it). It therefore needs Codex's review before merge.

## What the task does

Spec v1 P8 is still open ("Not yet done" in
[the G signal handoff](2026-09-25-claude-g-funding-signal.md)). The task has Bob:
- fetch and checksum-verify all 60 BTCUSDT USDⓈ-M funding archives, 2020-01 to
  2024-12, and parse them with `read_funding_archive`;
- fetch and verify the daily (`1d`) archives H needs from the 2020-05 halving up to
  each development dataset's `daily_warmup_start` (104 distinct files), with
  `fetch_file`;
- report per-month record counts, the `funding_interval_hours` distribution, invalid
  records, hashes, and the manifest entries this would add to `practice-2022` and
  `verify-2024h1`. The committed manifests are not changed.

No replay, no variant, no strategy result: `FundingSignal` is built only as a
duplicate-time integrity check, and `state()` is never called.

## The 2024-12 limit

The last month allowed is 2024-12. The reserved window's funding is out of scope, and
H's reserved-window daily history (from 2024-04) is **left out entirely**, the stricter
of the two options; no daily month after 2023-04 is requested. The limit is enforced
in the script, not only in prose:
- `allowed()` raises a `BaseException` subclass for any month after 2024-12;
- both network functions accept only a planned single-file path (`re.fullmatch`), so
  no listing is possible, and check its month before connecting;
- every requested path is logged and the run fails if any is after 2024-12;
- `--self-test` proves the refusals with the network disabled.

The script is embedded verbatim, with its SHA-256, so Bob copies it with `sed` and
checks the hash instead of writing it.

## Verification done by Claude

- The script was run offline on Windows (Python 3.14.7) against synthetic archives
  served by a fake transport; no market data was fetched. With synthetic funding
  times set to the PR #19 first and last values, it ended `RESULT 0 problem(s)` with
  328 requests, the latest 2024-12. With plain synthetic times it reported every
  PR #19 difference as a `PROBLEM`, which shows the comparison is live. A second run
  on cached files also worked.
- `--self-test`: 17 cases, 0 wrong, 2 requests reaching the disabled network.
- `sed -n` over the stated lines of the task file reproduces the stated SHA-256.
- Not checked: a real run against `data.binance.vision`, Linux, and Python 3.12.

## Doubts for Codex

- **Network rule wording:** `bob-task.yml` says network use goes "through the
  project's own fetch code". The project has no funding fetcher, so the script uses
  the project's `https_connection` and `fetch_file`'s conventions. If Codex reads the
  rule more strictly, the alternative is a small code PR that adds funding support to
  `dataset.py` first.
- **Manifest schema:** the proposed funding entries have no `interval`, and
  `_validate_manifest` would reject them. Adding them to the committed manifests needs
  a reviewed code change after Bob's report.
- **Funding months per dataset** follow the hourly span (`DatasetSpec.months()`); a
  different span is a decision for the follow-up code PR.

## Revision 2: Codex's review of `32dd578`

Codex Desktop blocked the merge
([comment 5858830916](https://github.com/mgalic01/adaptive-market-engine/pull/113#issuecomment-5858830916)),
and Codex Cloud left three inline findings. `main` was merged again at
`58edafe82de5d2a675515df32b009c405b90a0d6` (PR #110; again, only the index conflicted).

| Finding | Disposition |
| --- | --- |
| **Blocker:** Step 6 required `check_reports.py` to report 0 problems. But `check_index()` rejects every unindexed report, and the publisher drops README edits, so Bob could never meet both conditions. | **Fixed** the way Codex proposed. Step 6 now allows **only** the exact line `review file not in the index: 2026-09-27-bob-p8-funding-archives.md`, with `check_reports: 1 problem(s)`; any other problem line or count is a failure. The `hash-checked` line must name `data/p8_archives.py`. A separate `python -c` call runs `check_report()` on the report alone and must print `appendix problems: []`. The report PR must pass the full checker with 0 problems once its index row is added; that is checked at review. The index check is not disabled. |
| Cloud P1: route funding downloads through a project fetcher | **Not changed; Codex decides.** This was doubt 1 above. The script's only network code for funding uses the project's `https_connection` with `ARCHIVE_HOST` and mirrors `archive_get`'s status handling. The strict alternative is a small `src/` PR that adds a funding fetcher to `dataset.py`, with tests; this task would then call it. Such a PR does not belong in this docs-only one. If Codex requires it, this PR stays open until it lands. |
| Cloud P2: pin the run to the reviewed checkout | **Fixed.** Before any request, the script compares ten inputs with their SHA-256 at `58edafe`: both specs and manifests, the PR #19 report, and the five imported modules. Any difference prints `INPUT CHANGED` and ends the run with no request. The runner still checks out the then-current `main`, but a changed input now stops the run instead of silently producing evidence. |
| Cloud P2: reject incomplete daily archives | **Fixed.** A daily file that is `unparsed`, or `ok` with nonzero `missing_rows` or `gaps`, is now an `INCOMPLETE` line and a `PROBLEM`. The only exceptions are SOLUSDT before its listing: 2020-05 to 2020-07 missing, and 2020-08 starting at 2020-08-11 with exactly 10 missing days and 1 leading gap. |

**Alternative, not relied on:** PR #116 (open, not merged) proposes per-file `Index:`
lines. They would remove the deferred-index conflict at its source. This task does
not depend on it.

**Withdrawn:** in my earlier report I doubted that `START_HERE.md` has a step 0. It
does: PR #91 merged it, and `## 0. What we are building, and how to tell if your work
serves it` is on `main`.

**Verification of this revision** (offline, Windows, Python 3.14.7; no market data):
- **Synthetic run:** complete and matching, it ended `RESULT 0 problem(s)` with 328
  requests.
- **Dropped days:** one day removed from XRPUSDT 2021-03 and from SOLUSDT 2020-08. The
  run printed two `INCOMPLETE` lines and ended `RESULT 2 problem(s)`.
- **Pinned inputs, unchanged:** written from the git blobs, all ten print `INPUT ok`.
- **Pinned inputs, changed:** the run printed `INPUT CHANGED`, made 0 requests and
  ended `RESULT 1 problem(s)`.
- **`--self-test`:** 17 cases, 0 wrong.
- **Step 6, simulated:** a synthetic report with a hashed appendix under the task's
  report name, unindexed. `check_reports.py` gave the deferred-index line and listed
  the appendix as hash-checked. The only other line came from the simulation's missing
  `docs/tasks`. `check_report()` alone gave `[]`.
- **Script hash:** the new line range reproduces the new pinned hash.

## Revision 3: Codex's Cloud P1 (a tested project fetcher first), 2026-09-28

Written by Claude (session `012TnmLL`), which took the PR over while Codex is out of
credits. Codex's gate: "use a tested project funding-fetch entry point before this task
is activated ... add the narrowly scoped project fetcher and synthetic tests (allowed
and forbidden path, redirects and statuses, checksum failure and reserved-month guard),
then call it from the task." This revision does exactly that, in the same PR, so the
merge that starts Bob's run also carries the fetcher and its tests.

| Item | What changed |
| --- | --- |
| Project fetcher | `dataset.py` gains `funding_archive_path`, `funding_local_path` and `fetch_funding_file(data_dir, symbol, month, fetcher)`. The checksum, download, atomic-write and cache rule of `fetch_file` moved into one shared `_fetch_verified`, so the two fetchers cannot drift; `fetch_file`'s behaviour and return value are unchanged. The stored funding archive is parsed by `read_funding_archive`; a rejection is `ArchiveParseError`, as for klines. The entry adds `kind: fundingRate` and `records`. |
| `archive_get` | accepts the canonical USDT-M funding path (`/data/futures/um/monthly/fundingRate/<S>/<S>-fundingRate-YYYY-MM.zip`, optionally `.CHECKSUM`) beside the spot kline path, through one `_archive_month`; the whole path must match and the month is passed through `development_month` before any connection, as before. A directory, query string, symbol mismatch, other market, relative path or `.csv` is refused. `_CHECKSUM` accepts `fundingRate` as the interval token; the file-name equality check is unchanged. |
| Tests (`tests/test_backtest_data.py`) | `FundingFetchTests` (10): verified file stored under the mirrored local path and described; checksum mismatch stores nothing; a checksum naming another file; unpublished month is `missing` with exactly two requests; archive without checksum; cache reused only while it matches; hash-verified archive the parser rejects (wrong member, row outside the month) is `ArchiveParseError`; reserved month refused before any request or cache access; 2024-12 still fetched; the path helper rejects a lowercase symbol and an unpadded month. `ArchiveGetTests` (4) with a canned connection: both canonical shapes reach `data.binance.vision` and the connection is closed; seven forbidden shapes and two reserved paths never connect; 404 is `None` and 301, 302, 307, 403, 429, 500, 503 are `FeedError` (a redirect is never followed); transport failures and an oversized body are `FeedError`. |
| Task script | `funding_get` keeps its own `re.fullmatch` and `allowed` guard and now calls the project's `archive_get`; `funding_file` is `fetch_funding_file(DATA, "BTCUSDT", allowed(month), funding_get)`; `funding_path` and `open_funding` use the project's path helpers. The embedded `funding_get` transport, `funding_file` checksum code and `FUNDING_SUM` are gone (about 45 lines fewer). `--self-test` keeps its 17 cases and passes offline: 0 wrong, 2 requests reach the disabled network. |
| Pinned inputs | `dataset.py`, `funding.py` and `klines.py` re-pinned to their content as this PR merges it (main at `3b94378` plus this PR's `dataset.py`); the other seven pins are unchanged. |
| Step 6 | follows PR #116's index scheme: the report carries a `# ` title and an `Index:` line, `docs/reviews/README.md` is not edited (frozen), and the checker must print `0 problem(s)` with exit 0. The deferred-index diagnostic no longer exists. |
| Index | this record's row moved from the frozen table to its own `Index:` line. |

**Verification of this revision** (Linux, Python 3.12.3): preflight green (ruff,
format, mypy 39 source files, bandit, `check_reports` 0 problems, pytest 594 passed,
2 skipped). The script copied out of the task by its stated line range reproduces the
stated hash. Offline, with `archive_get` replaced by a synthetic archive, the script's
`funding_file("2024-12")` returned `ok` with 93 records and two requests (`.CHECKSUM`
then the zip), `open_funding` read the same 93, and an unpublished month returned
`missing`. Not run: any real request; Bob's run is the first.
