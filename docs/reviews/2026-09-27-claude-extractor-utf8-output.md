# Claude → Bob and Codex: the Bob answer extractor writes UTF-8 on every platform

2026-09-27. Named writer: Claude (desktop session, worktree `cool-goodall-18de60`).
Branch `claude/extractor-utf8-output`, base `main` at
`cebf848ef2ee2c16f25de8602478e8f75696183c`. The PR comment for the push names the head.

Scope: `scripts/extract_bob_answer.py`, `tests/test_extract_bob_answer.py`, this file
and its index row. No change to what the extractor accepts or rejects, or to either
Bob workflow.

## Bug and cause

On Windows, `tests/test_extract_bob_answer.py::test_cli_prints_the_answer_or_refuses_without_raw_output`
failed when pytest was launched from PowerShell: each em dash in the CLI's output came
back as `â€”`. It passed with `PYTHONUTF8=1`, and it passed from Git Bash. The owner saw
the same failure on `main` at `15ab9cf822501ea74a2bf7a614c180336cdfce3a`.

The CLI and the test each relied on a platform default, and the two defaults are set
separately:

- **The CLI** read its input as UTF-8 but wrote to `sys.stdout` with whatever encoding
  the environment gave it: the ANSI code page (cp1252) on a Windows pipe, or the value
  of `PYTHONIOENCODING` when that is set.
- **The test** called `subprocess.run(..., text=True)`. That decodes with
  `locale.getpreferredencoding()`, cp1252 here, and ignores `PYTHONIOENCODING`.

The PowerShell session that failed had `PYTHONIOENCODING=utf-8:surrogateescape` in its
process environment (it is not set in the User or Machine scope). So the child wrote
UTF-8 (`E2 80 94`) and the parent decoded it as cp1252: `â€”`. Git Bash had no
`PYTHONIOENCODING`, so both sides used cp1252 and agreed by accident. `PYTHONUTF8=1`
made both sides UTF-8. Measured in this worktree with Python 3.14.7:

| Environment | `sys.flags.utf8_mode` | locale encoding | `PYTHONIOENCODING` | old test |
| --- | --- | --- | --- | --- |
| PowerShell (this session) | 0 | cp1252 | `utf-8:surrogateescape` | fails, `â€”` |
| PowerShell, variable cleared | 0 | cp1252 | unset | passes |
| Git Bash | 0 | cp1252 | unset | passes |

CI is unaffected either way: Linux runners use a UTF-8 locale, so the posted answer's
bytes are the same before and after this change.

## Change

- **CLI:** `main()` reconfigures `sys.stdout` to UTF-8 with `errors="strict"`, and
  `sys.stderr` to UTF-8 with `errors="backslashreplace"`, when they are ordinary text
  streams. Strict on stdout means an answer that cannot be encoded is an error; it is
  never written with replaced or escaped characters, even when `PYTHONIOENCODING`
  asks for `surrogateescape`. The docstring now says output is UTF-8.
- **Test:** the three `subprocess.run` calls pass `encoding="utf-8"` instead of
  `text=True`, so the test states the contract rather than inheriting the locale.

The extraction rule, the size limit, the refusal messages and the exit codes are
unchanged.

## Verification actually run

All on Windows 10 with Python 3.14.7.

- **Reproduced** the reported failure from PowerShell on the original code.
- **Negative control:** with only the test changed (UTF-8 decode) and the old CLI,
  the test fails from Git Bash with
  `UnicodeDecodeError: 'utf-8' codec can't decode byte 0x97`. The CLI had written
  cp1252, which shows the CLI itself relied on the platform default.
- **After the fix,** the test passes from Git Bash with `PYTHONIOENCODING` unset,
  `cp1252`, `utf-8:surrogateescape` and `latin-1`, and with `PYTHONUTF8=1`.
- **Fail-closed check:** a stream whose signed answer contains a lone surrogate
  (`\ud800`) still exits 1 and writes 0 bytes to stdout. It fails in `extract()`'s
  UTF-8 size check, before any output, as it did before this change. It surfaces as a
  `UnicodeEncodeError` traceback rather than a `Rejected:` line; that is unchanged
  and out of scope here.
- **Preflight, from PowerShell** (`PYTHONIOENCODING=utf-8:surrogateescape` set),
  before rebasing onto `cebf848`:
  - `python -m pytest`: exit 0; 1028 tests, 0 failures, 0 errors, 2 skipped (JUnit XML
    counts).
  - `python -m ruff check .`: all checks passed.
  - `python -m ruff format --check .`: 202 files already formatted.
  - `python -m mypy`: no issues in 38 source files.
  - `python scripts/check_reports.py`: 0 problems.

  The PR comment for the push records the rerun at the pushed head.

Not tested: macOS; a Windows console, as opposed to a pipe (the workflows and the
test only use pipes).

No known required fixes in the reviewed scope.

## Requested

Bob: a reading of the diff at the head named in the PR comment. In particular, does
anything in the change widen what the extractor publishes? Codex: an independent
Windows run of the extractor tests from PowerShell, if convenient.

## Revision 2: a regression test that CI can fail

Reviews of the first head, `89bfeb120b251cfe1d2d3fccd0e3389963e10e9c`:

- The `@bob` workflow gave
  [`NO ISSUES`](https://github.com/mgalic01/adaptive-market-engine/pull/110#issuecomment-5858613842).
  The owner's Bob session also gave
  [`NO ISSUES`](https://github.com/mgalic01/adaptive-market-engine/pull/110#issuecomment-5858723161).
- The automated Claude review gave
  [`CHANGES NEEDED`](https://github.com/mgalic01/adaptive-market-engine/pull/110#issuecomment-5858640742), with one required fix.

**The required fix, agreed.** On Linux CI the ambient encoding is already UTF-8, so the
CLI test passed with or without the `reconfigure` calls. Only the manual Windows run
above guarded the fix.

**Fixed in `63dac12`.** The new `test_cli_writes_utf8_whatever_the_environment_says`
sets `PYTHONIOENCODING` in the child's environment and clears `PYTHONUTF8`. It runs
with `cp1252`, `latin-1` and `utf-8:surrogateescape`, and asserts on raw bytes:

- the accepted answer's stdout is exactly `(ANSWER + "\n").encode("utf-8")`;
- a refusal writes 0 bytes to stdout, and its stderr decodes as UTF-8 with the
  `'— IBM Bob (...)'` em dash intact.

The comparison normalises `\r\n` to `\n`, because Windows text mode writes `\r\n`. The
existing text-mode test ignores line endings the same way, and newline handling is not
part of this bug.

**Negative control.** With the CLI restored from `cebf848`, the old code fails two of
the three cases:

| `PYTHONIOENCODING` | Result with the old CLI | Why |
| --- | --- | --- |
| `cp1252` | fails | stdout carries byte `0x97` |
| `latin-1` | fails | exit 1: the em dash cannot be encoded |
| `utf-8:surrogateescape` | passes | the old CLI already wrote UTF-8 here, and the original failure was on the test's decoding side |

The third case stays as coverage that the fixed CLI still writes strict UTF-8 in that
environment.

**Nits from the same review.** The stdout/stderr asymmetry (`strict` against
`backslashreplace`) is explained in "Change" above: the published answer
fails closed, and diagnostics are best-effort. No other
CLI in the repository reconfigures its streams, so there is no shared pattern to
document yet.

`main` was merged in at `c3c8e250bc5ec8837498d47bd0090cc4bd8c2edc`. The only conflict
was the index, where all rows were kept. The PR comment for the push names the new head
and records the preflight at that head.
