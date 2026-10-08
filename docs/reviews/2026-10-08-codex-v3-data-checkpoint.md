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
