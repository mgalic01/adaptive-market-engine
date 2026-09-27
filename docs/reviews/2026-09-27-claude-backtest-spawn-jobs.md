# Claude → Codex and Bob: backtest pool jobs importable under spawn (PR #103)

2026-09-27. Named writer: Claude (desktop session, worktree `cool-goodall-18de60`).
Branch `claude/backtest-spawn-jobs`. Original base `de38fdb27e3e094061c69f8ecc7530761120f9f4`;
the code commit is `4dc85c81fbb06d57ef10800b91ae244becd881a9`. That commit was then
merged with `main` at `5f95dcebe4c4f283eba3cbcb0767a71061f8f753` and this file was added
([Codex's request](https://github.com/mgalic01/adaptive-market-engine/pull/103#issuecomment-5856725792)).
The PR comment for that push names the new head.

Scope: `src/crypto_grid_bot/backtest/jobs.py` (new), `src/crypto_grid_bot/backtest/__main__.py`,
`tests/test_backtest_pool.py` (new), this file and its index row. No change to strategy,
parameters, dataset specs, integrity rules or output.

## Bug and cause

On Windows (spawn start method, Python 3.14.7),
`python -m crypto_grid_bot.backtest verify|run ... --jobs N` failed on the first pool job
with `BrokenProcessPool`. The worker reported
`AttributeError: module '__main__' has no attribute 'cross_check_job'`. The jobs were
defined in the package `__main__`, so they pickled as `__main__.<name>`, and a spawned
worker never re-runs a module named `*.__main__` (`multiprocessing.spawn._fixup_main_from_name`).
Agents had been working around this with a launcher that imports `main` from
`crypto_grid_bot.backtest.__main__`. That launcher also needs an
`if __name__ == "__main__":` guard, or each spawned worker re-runs it.

## Change

`run_job`, `cross_check_job` and their helper `manifest_path` moved unchanged to
`backtest/jobs.py`. An AST source comparison against `de38fdb` found all three
character-identical. `__main__` imports them, so `cli.run_job`, `cli.cross_check_job`
and `cli.manifest_path` still resolve for `tests/test_backtest_cli.py` and the Bob
task script in `docs/tasks/2026-09-24-bob-v0-equivalence.md`.

## Verification actually run

All of the following ran on Windows 10 with Python 3.14.7.

- **Reproduced** at `de38fdb`: `verify --jobs 2` exited 1 with the reported traceback.
- **Regression tests** in `tests/test_backtest_pool.py` force spawn, because CI runs
  Linux on Python 3.12, where fork is the default:
  1. The functions submitted to the pool are exactly `{cross_check_job, run_job}`. None
     is defined in a `__main__` module, and each pickles by reference.
  2. A real spawn pool can unpickle each of them.
  3. `runpy.run_module(..., run_name="__main__", alter_sys=True)` with spawn forced,
     which is what `python -m` does, runs `verify --jobs 2` on a synthetic
     two-symbol dataset.
- **Negative control:** in a `de38fdb` checkout, tests 1 and 3 fail, and test 3's
  stderr carries the reported `AttributeError`. Test 2 passes there, because the old
  module was importable under its full name; that is complementary coverage only.
  Codex independently reran the negative/positive synthetic check on Windows
  ([comment](https://github.com/mgalic01/adaptive-market-engine/pull/103#issuecomment-5856725792)).
- **Real-data equivalence**, one V0 replay: dataset `verify-2024h1` (months 2023-05 to
  2024-06 only), `config/default.toml`, `--jobs 4`, data in the owner's local
  `amengine-data`.
  - Before: `de38fdb` through the guarded launcher. After: plain `python -m` at
    `4dc85c8`. Both exited 0.
  - `results.json` is byte-identical (`cmp`): SHA-256
    `32629224a8806303966a8455da1ab05da8b0fb609185661778ee848ac8213c0d`, 3,729,088 bytes,
    `valid: true`, 8 results, no failures.
  - `summary.md` is also byte-identical: SHA-256
    `0eedb74098c1b1321119a47b8b3051bc7865e2cfecad6ba162bbc9517a960a7c`.
- **Local checks:** at `4dc85c8`, `scripts/preflight.py` passed with 428 passed and
  2 skipped (the existing Windows symlink-privilege skips), 565 subtests.
  `mypy src scripts` found no issues in 45 files. The results after the merge with
  `main` are in the push comment.

## Limits

- The equivalence evidence covers one replay (one dataset, one config, one fee level).
  Other outputs are argued, not measured: the function bodies are unchanged and only
  their module moved.
- The new tests do not exercise a real `run` replay. The recorder mocks it, and the
  subprocess test runs `verify` only.
- macOS, and Linux under forkserver (Python 3.14's Linux default), were not run.
- The real-data run is author evidence. No reviewer has rerun it.

## Compatibility, security, rollback

- **Compatibility:** the CLI arguments, output files and the names reachable from
  `crypto_grid_bot.backtest.__main__` are unchanged. The launcher workaround keeps
  working but is no longer needed.
- **Security:** no new dependency, network access, credentials or live-trading path.
  The new test runs `sys.executable` with fixed arguments on a temporary synthetic
  dataset.
- **Rollback:** revert the PR's code commit. Nothing is migrated or persisted.

## Bob's failed answer on this PR

[The alert](https://github.com/mgalic01/adaptive-market-engine/pull/103#issuecomment-5856240880)
came from [run 36322134416](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36322134416).
Bob finished and read the diff, but `scripts/extract_bob_answer.py` rejected its final
answer: 163 lines with no line starting `IBM Bob` and two signatures. The workflow worked
as designed. The cause is the recurring signing and header habit that PR #98 addresses.
Bob is asked again at the new head.
