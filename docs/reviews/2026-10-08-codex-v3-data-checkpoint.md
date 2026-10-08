# V3 data validation checkpoint

Index: Codex added synthetic-only V3 funding eligibility and daily aggregation; no fetch or strategy run, external review pending.

Worktree: codex/v3-data-validation, based on local register commit 52e0c2f.
Funding schedule validation accepts all divisors of 24, checks every expected slot,
and rejects duplicate, missing, off-slot, changing-cadence and invalid-rate records.
The legacy G funding gate is unchanged. Daily aggregation masks repaired and absent
hours, needs at least 20 valid hours per UTC day, and excludes months only above
17% masked. A bridge consumes the repairing reader's repair/mask union.

Validation so far: 28 focused tests pass; Ruff and strict mypy pass. Inputs are
synthetic February 2024 records. No archives or reserved data were opened.
Pending: fetch tooling and manifest schema/integration, complete data diagnostics,
independent review, legacy-equivalence/full suite for the eventual data batch.
The register branch's long validation runs remain isolated in its original worktree.

Mandatory-close diagnostic added: earliest unmasked futures hour from 01:00 on the
previous month's last day through 23:00; no valid hour returns None for the caller
to flag as invalid. Midnight and hours in the excluded month cannot satisfy it.
The focused suite now has 31 passing tests; Ruff and strict mypy pass. Manifest
serialization and runner consumption remain pending; this helper alone does not
claim execution integration.

Archive preparation helper added outside src with injected retrieval only. It admits
only V3's ten symbols and canonical pre-2025 monthly names for spot/futures 1h and
funding files. It rejects missing/malformed/mismatched checksums and enforces byte
limits; no real network adapter or CLI dispatch exists yet. Combined data/helper
suite: 45 passing tests, Ruff and strict mypy clean. Actual fetch task, committed
manifest and filter snapshot still require completion and external review.

Network adapter implemented outside src with fixed public hosts and paths, reserved
month validation before connection creation, no redirects, bounded response reads,
and connection cleanup. Futures filters allow one GET attempt per fetch instance;
a failed attempt does not reset that guard. There is still no fetch CLI or task
execution. All transport tests replace HTTPSConnection with fakes. Combined focused
suite: 52 tests pass; Ruff, mypy and Bandit pass for the changed helper/module scope.
