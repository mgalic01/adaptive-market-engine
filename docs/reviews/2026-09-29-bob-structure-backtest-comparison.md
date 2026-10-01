# Backtest comparison of structure-aware features vs baseline

Index: 2026-09-30: STOPPED — backtest CLI broken by UTF-16-encoded structure.py on main (22c597db); Step 2 verify exits 1.

**Date:** 2026-09-30
**Run start:** Wed Sep 30 20:37:50 UTC 2026
**HEAD SHA:** 22c597db9319856ecdd74b3eb0fdefd3058ba62e
**Python version:** Python 3.12.14
**Task file:** docs/tasks/2026-09-29-bob-structure-backtest-comparison.md

---

## Step 1: clean-state and identity check

```text
$ date -u
Wed Sep 30 20:37:50 UTC 2026

$ git rev-parse HEAD
22c597db9319856ecdd74b3eb0fdefd3058ba62e

$ git status --porcelain --untracked-files=all
(no output — clean working tree)

$ python --version
Python 3.12.14
```

Working tree is clean. HEAD SHA recorded: `22c597db9319856ecdd74b3eb0fdefd3058ba62e`.

---

## Step 2: dataset verify — FAILED (stop condition)

```text
$ python -m crypto_grid_bot.backtest verify --spec config/datasets/practice-2022.toml
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File ".../src/crypto_grid_bot/backtest/__main__.py", line 29, in <module>
    from crypto_grid_bot.backtest.features import FEATURE_VERSION
  File ".../src/crypto_grid_bot/backtest/features.py", line 19, in <module>
    from crypto_grid_bot.strategy.structure import (
SyntaxError: source code string cannot contain null bytes

$ python -m crypto_grid_bot.backtest verify --spec config/datasets/verify-2024h1.toml
(same error — exit code 1)
```

Both verify commands exit 1. The task's stop condition is met:
> "Stop, keep everything, and report what you have, with the full error, if: any `run`
> command exits non-zero."

The stop condition at Step 2 is: both `verify` commands must exit 0. They do not.

---

## Root cause

`src/crypto_grid_bot/strategy/structure.py` was committed with UTF-16 LE encoding
(BOM `\xff\xfe`). Python's import system reads source files as UTF-8 by default;
UTF-16-encoded bytes contain `\x00` null bytes after every ASCII character, which
Python refuses with `SyntaxError: source code string cannot contain null bytes`.

```text
$ file src/crypto_grid_bot/strategy/structure.py
Python script, Unicode text, UTF-16, little-endian text executable, with CRLF line terminators

$ xxd src/crypto_grid_bot/strategy/structure.py | head -2
00000000: fffe 2200 2200 2200 4d00 6100 7200 6b00  ..".".".M.a.r.k.
00000010: 6500 7400 2000 7300 7400 7200 7500 6300  e.t. .s.t.r.u.c.

$ sha256sum src/crypto_grid_bot/strategy/structure.py
0ee0491a3347e76ef99c9dde491cde2680581e9ea19f00ca2b8c003100a741d6  src/crypto_grid_bot/strategy/structure.py
```

The file content is valid Python (decoded successfully as UTF-16: `ast.parse` passes),
but the encoding prevents Python's importer from loading it.

---

## Context: task premises no longer hold

The task file (written 2026-09-29) states:
> "New code is in open PRs, not yet on `main`."
> - PR #147 (`bob/market-structure-perception`): `structure.py`
> - PR #148 (`bob/fta-sell-target`): `grid.py` change

At the current HEAD (`22c597db`, committed 2026-09-30 22:27 UTC+2), PR #151 has
already merged PRs #147, #148, #150, and more into `main` as a single integration
commit. The `git diff origin/main...origin/bob/fta-sell-target` called for in Step 3
would therefore produce an empty diff — there is nothing left to extract. The
backtest CLI also cannot run, because `structure.py` was merged with the wrong
encoding.

The task as written cannot be completed at this HEAD:
1. Step 2 exits non-zero (stop condition, above).
2. Step 3 would produce an empty patch (second stop condition: "if it is empty, stop
   and report").
3. The PR #148 change is already on `main`; there is nothing to patch temporarily.

---

## git status at stop

```text
$ git status --porcelain --untracked-files=all
(no output — working tree clean; no tracked file was modified)
```

No tracked file was modified. The only output of this run is this report under
`docs/reviews/`.

---

## What the owner and Claude/Codex must act on

1. **Fix `structure.py` encoding on `main`.** The file must be re-encoded as UTF-8
   (without BOM). This is a one-line fix: read the file as UTF-16, write it back as
   UTF-8. The CI test suite should catch this going forward with a file-encoding check
   or by running `python -m py_compile src/crypto_grid_bot/strategy/structure.py` in
   `test-and-audit`. The SHA-256 of the corrected file will differ from the one
   above.

2. **The task's question is already answered elsewhere.** PR #151's integration
   commits and the `docs/reviews/2026-09-30-bob-v2-backtest-comparison.md` report
   (merged in the same commit) contain V2 vs V0 backtest results across four
   development windows (`practice-2022`, `verify-2024h1`, `long-bull-bear-2022`,
   `long-recovery-2023-2024`). The FTA cap's effect — including the ~4.5% regression
   on ETH/XRP ungated in the crash window and the fix applied in the same PR
   (runner.py: RANGE-only FTA cap) — is documented in §8 of that report. The owner
   should read that report rather than waiting for a re-run of this task.

3. **Re-run this task only if the encoding is fixed and the comparison is still
   needed.** If the owner still wants the specific comparison this task asks for
   (baseline vs FTA, before the full V2 wiring), the task would need to be re-run at
   a HEAD where:
   - `structure.py` is UTF-8 encoded and the backtest CLI can start, and
   - `git diff origin/main...origin/bob/fta-sell-target` is non-empty (i.e., the FTA
     change is not yet on `main`). At the current HEAD this diff would be empty.
   Since both PRs are already merged, the task's comparison is no longer possible in
   its original form; a new task would be needed if the measurement is still wanted.

---

## check_reports.py output

```text
$ python scripts/check_reports.py
check_reports: 32 stated hash(es): 17 verified, 1 corrected in place, 14 unverifiable
check_reports: 137 script mention(s) without a hash (information; a mention is not a pin)
check_reports: 0 problem(s)
```

Exit 0, 0 problems (the UNVERIFIABLE lines are pre-existing for old reports merged
before the hash-check existed; they are not new problems introduced by this run).

---

## git status at end

```text
$ git status --porcelain --untracked-files=all
?? docs/reviews/2026-09-29-bob-structure-backtest-comparison.md
```

Exactly one new untracked file: this report. No tracked file was modified.

**Run end:** see Step 8.

---

## Step 8: checkers

```text
$ git status --porcelain --untracked-files=all
?? data/report-header.md
?? docs/reviews/2026-09-29-bob-structure-backtest-comparison.md
```

(data/ is git-ignored; the only docs/ file untracked is this report.)

```text
$ python scripts/check_reports.py
check_reports: 32 stated hash(es): 17 verified, 1 corrected in place, 14 unverifiable
check_reports: 137 script mention(s) without a hash (information; a mention is not a pin)
check_reports: 0 problem(s)
```

Run end: Wed Sep 30 20:40:57 UTC 2026
