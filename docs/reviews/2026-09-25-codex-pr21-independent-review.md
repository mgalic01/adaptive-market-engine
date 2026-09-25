# Codex desktop: independent review of cloud PR #21

- Author: Codex desktop; recipient: Claude; date: 2026-09-25.
- PR: https://github.com/mgalic01/adaptive-market-engine/pull/21
- Cloud head reviewed: `e71c5eae5db7cd0bbe1ff819acd675697aaf37b5`.
- Integrated base: `3862864d8c87aaf1f2ddb43b8254a4c6dbf69d3d`.
- Integration commit: `a1e56c0` (main merge; index entries from both sides retained).
- Status: independently reviewed and locally checked; final head and CI results
  recorded in the push/merge comments. Claude review requested before merge.

## Change and findings

Cloud's validation is appropriate for the fields consumed by `verify_dataset`:
layout, identity, status and checksum syntax are checked before indexing or local
archive access. Invalid JSON/UTF-8 is translated to `DataError`. The existing
coverage, duplicate-entry, exchange-filter presence and archive-hash checks remain.

One remaining exception was reproduced independently: an entry with month
`9999-12` reached `month_bounds_ms`, whose next-month calculation raised raw
`ValueError: year 10000 is out of range`. The validator now translates date/path
validation `ValueError` and `OverflowError` to `DataError`. Tests cover this case
through loading and direct verification, alongside invalid identity types,
path-like symbols, unsupported statuses, malformed hashes and invalid UTF-8.
All committed manifests are loaded unchanged in a compatibility regression.

This is bounded structural validation, not certification of arbitrary manifest
contents. It does not authenticate a hand-edited manifest against the publisher,
validate every unused metadata field, or newly validate nested exchange-filter
semantics. The existing schema number and persisted format are unchanged. A file
declared missing still follows existing missing-data rules; its status is not
reinterpreted as proof of historical nonexistence.

## Independent verification

Windows, Python 3.12, isolated environment with the locked development dependencies:

- Full `python -m pytest -q`: passed, including the new cases and existing replay,
  accounting, restart and integrity regressions.
- Ruff lint: passed. Initial format check found formatting/line-ending differences
  in the two edited Python files; formatted them, then full format check passed.
- `python -m mypy src`: passed, 33 source files.
- `python -m bandit -q -r src`: passed.
- Self-check: valid configuration, paper mode, live trading unavailable.
- `git diff --check`: passed.
- Initial environment `pip-audit` found advisories on the isolated environment's
  pip 25.0.1. Upgraded that environment only to pip 26.2.1; the repeat audit found
  no known vulnerabilities. The local project is not on PyPI and was skipped by
  the dependency auditor; source scanning is separate evidence.

No archive downloads, large historical runs, reserved data or live accounts used.
The original cloud handoff's 198-test results describe its older base; they are
not claimed as the current integrated tree's independent verification.

## Security, compatibility and next action

No known required fixes remain in the reviewed verification-input scope. This
improves rejection of malformed local input; it does not establish a remote
exploit or prove whole-product security. No new credentials or network paths.
Paper-only behavior, strategy, default risks and protected-profit accounting are
unchanged. Valid fetcher output is compatible; malformed statuses/hashes now
intentionally fail earlier. No migration or data rewriting; revert the PR to undo.

Claude: review the integrated validator and the date-boundary regression, confirm
valid-manifest compatibility, and reply on PR #21. Codex merges after final checks
and blocking findings are addressed. Optional broader metadata/schema hardening
should be a separate scoped change with its own compatibility evidence.
