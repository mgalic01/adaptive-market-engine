# Codex → Claude handoff: manifest validation

- **Status / PR / base / head:** Codex, for Claude, 2026-09-25. Working branch
  `work`; base `af0b1c2e3a47f6bc2a4ebaa9d0f61083a7210362`; implementation reviewed at
  `6135112`. The checkout has no configured Git remote and `gh` has no credentials,
  so the current PR conversation and a pushed head could not be inspected here.
- **Changes and reasons:** Backtest manifest loading now translates malformed JSON
  into the project's `DataError` boundary. Loading and direct verification both
  validate the manifest fields that verification indexes, including file identity,
  status and lowercase SHA-256 syntax. This prevents malformed or hand-edited
  manifests from escaping as `JSONDecodeError`, `KeyError`, or misleading status
  handling. Regression tests cover invalid JSON, incomplete entries and unknown
  statuses.
- **Checks passed / failed / not run:** `python -m pytest tests/test_backtest_data.py`
  passed (13 tests, 20 subtests); `python -m ruff check .` passed; `git diff --check`
  passed before the implementation commit. On the final tree, `python -m pytest`
  passed (198 tests, 351 subtests), and Ruff, strict mypy, Bandit, pip-audit and
  `git diff --check` all passed. No live Binance download or historical replay was
  run because this change concerns pre-verification input validation and its
  network-free regression coverage.
- **Required fixes and proposed corrections:** No known required fixes in the
  reviewed scope.
- **Security findings, mitigations and review limits:** The malformed-input failure
  boundary described above was corrected. No other known security findings in the
  reviewed scope. Review was limited to manifest ingestion and verification; passing
  unit tests or dependency scans does not prove the wider application secure.
- **Optional improvements and compatibility risks:** Valid manifests emitted by the
  current fetcher remain compatible. Previously tolerated malformed or unknown file
  statuses now fail closed with `DataError`; this is intentional. No persisted-format
  migration, accounting change, strategy change, execution change or paper-only
  scope change is involved.
- **Next steps and intended owner:** Claude should independently inspect the validation
  boundary and regression cases; the owner can merge after required checks and any
  blocking review findings are addressed.
- **Question for Claude:** Please check `backtest/dataset.py` for manifest shapes that
  a valid current or historical fetch could emit but the new validator would reject,
  and reply on the PR; put any substantial response in a new indexed review file.
- **Revert / migration notes:** Revert implementation commit `6135112` to restore the
  old permissive/error-leaking behavior. No data rollback is needed.
