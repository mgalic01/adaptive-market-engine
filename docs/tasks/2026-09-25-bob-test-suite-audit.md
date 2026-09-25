# Task for Bob: test-suite audit (isolation, order, hash seeds, warnings, gaps)

- **Written by:** Claude, 2026-09-25, at the owner's request to give Bob as much
  checking work as possible.
- **Review:** starts automatically when this file is merged, under the current merge
  rule.
- **Report:** `docs/reviews/2026-09-25-bob-test-suite-audit.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md).

## Why

CI runs the suite once, in one order, on one Python version. Tests that pass only
together, only in that order, or only with one hash seed would hide real bugs. The
same is true of warnings nobody reads, and of code no test reaches. This task looks
for each of these. It uses only what is installed: pytest and the Python standard
library (no new packages).

## Steps

Run from the repository root, and keep each command's full output under `data/`.
Record `git rev-parse HEAD` and `python --version` first.

1. **Baseline, exactly as CI:**
   `pytest 2>&1 | tee data/t-baseline.log`, then
   `python -m crypto_grid_bot.app --config config/default.toml --self-check` and
   `python -m crypto_grid_bot.app --config config/default.toml --paper-demo --database data/paper.db`.
   Record the pass, fail and skip counts.
2. **Each test file alone:**
   `for f in tests/test_*.py; do pytest -q -p no:cacheprovider "$f" > "data/t-alone-$(basename "$f" .py).log" 2>&1; echo "$f $?"; done`
   A file that fails alone but passes in the full suite depends on another file.
3. **Reverse file order:** `pytest -q -p no:cacheprovider $(ls tests/test_*.py | sort -r)`.
4. **Hash seeds:** the full suite with `PYTHONHASHSEED` set to `0`, `1`, `2`, `4242` and
   `random`, one run each.
5. **Warnings as errors:** `python -X dev -W error -m pytest -q -p no:cacheprovider`.
   Failures here are findings, not stop conditions. For each, give the warning text and
   the test.
6. **Slowest tests:** `pytest -q -p no:cacheprovider --durations=25`.
7. **Repeat for flakiness:** run the full suite 5 more times. Report any test whose
   result changes between runs.
8. **Coverage by reading (no tools):** list every public function and class (no
   leading underscore) under `src/crypto_grid_bot/`. For each, grep `tests/` for its
   name. Report the ones no test names, grouped by module. Write this as
   `data/untested.py` and give its SHA-256. The grep is only a first pass: for each
   module with gaps, read the code and say whether the function is reached indirectly
   through another tested function. Name the test that reaches it, or say it is
   untested.
9. **Fail-closed spot check:** pick the five untested or weakly tested functions that
   handle money, orders, risk limits or parsed external data. For each, describe one
   concrete input that should be rejected and what the code does with it, by reading
   the code. You may run it in a throwaway script under `data/`, but do not add tests
   to the repository.

## Report

`docs/reviews/2026-09-25-bob-test-suite-audit.md`:
- the commit, Python version, and every command with its exit code;
- a results table for steps 1 to 7: mode, passed, failed, skipped, errors;
- every failure with the test name and the key lines of output;
- the step 8 list (grouped by module) and the step 9 cases;
- **Ideas and proposals** (separate): which tests Claude should add first and why,
  ordered by risk. For each, name the function, the input and the expected behaviour
  precisely enough that the test can be written from your description alone.

## Stop conditions

- Step 1 fails (CI's own commands): report and continue with the other steps, because
  they help diagnose it. Say so at the top of the report.
- A tracked file changes, or anything outside `data/` and your report appears in
  `git status --porcelain --untracked-files=all`: stop and report.
- Anything else unexpected: stop, keep everything, report.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish". Every "untested"
claim was checked by reading, not only by grep.
