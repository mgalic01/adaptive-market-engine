# Claude → Codex and Bob: task file for P8 archives (G funding, H daily history)

2026-09-27. Named writer: Claude (subagent of the desktop session, isolated worktree).
Branch `claude/bob-task-p8-funding`, from `main` at
`b7a857b337c538311f754046542f5e7f5be56272`. The PR comment for the push names the head.

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
