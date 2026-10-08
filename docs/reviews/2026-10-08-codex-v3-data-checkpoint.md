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

Offline exchange-filter parsing added with bounded numeric fields and strict symbol/
filter uniqueness. Both LOT_SIZE and MARKET_LOT_SIZE are preserved; zero market step
falls back to LOT_SIZE. Snapshot parsing rejects missing symbols, nonperpetual futures,
wrong quote assets, missing/duplicate filters and inconsistent quantity bounds.
Combined focused suite: 65 tests pass; Ruff, mypy and Bandit pass in changed scope.
No real snapshot was requested. Manifest linkage and complete fetch task remain pending.

Manifest inspection now ties each verified archive to hash, source path, kind,
symbol/month, eligibility and parsing diagnostics. Synthetic spot, futures and
funding zip tests cover full-month rows; a single exact futures CSV header is
recognized and its removal recorded. Raw bytes remain unchanged and hashed.
Focused suite: 70 tests pass; Ruff (after import sorting), mypy and Bandit pass.

Format reference consulted: https://github.com/binance/binance-public-data (official
README, data columns/checksum description). That documentation displayed a few
2025-dated example rows incidentally; no archive or reserved dataset was requested,
and those examples were not used for returns, strategy design or parameter choices.
Record this incidental exposure for any later reserved-window methodology review.

Manifest integration regression: repairing-reader masks can include an out-of-month
bad row. The V3 bridge now keeps only in-month mask hours before aggregation; the
reader's documented contract says out-of-month hours do not count. A failing test
reproduced the previous rejection and now passes. Focused data/helper suite: 71
passed, strict mypy clean. The legacy reader remains unchanged.

Deterministic inventory manifest assembly added: stable sorted JSON, duplicate entry
rejection, canonical path/hash checks, raw snapshot hashes and parsed limits for all
ten symbols. It remains replay_ready=false until coverage, close diagnostics and
verified local snapshot/archive paths are integrated. Combined focused suite: 72
passed; Ruff, mypy and Bandit clean. This is not a completed replay manifest.

Collector integration now saves verified archives and both raw filter snapshots in
a fresh output directory, validates every request before transport access, and
publishes the inventory manifest only after collection succeeds. Existing output
directories are refused. Spot cache reuse verifies the original pinned SHA-256;
if an archive must be downloaded again, it must still match that original pin.
Corrupt cached bytes and changed upstream bytes fail rather than silently replacing
the dataset. Synthetic collector and reuse regressions were observed failing before
implementation and now pass. Focused suite: 77 tests; Ruff/format and mypy pass.

Current foundation batch remains preparatory: no CLI, actual retrieval, automatic
request-universe generation, committed-manifest reuse-map loader, complete coverage
or mandatory-close integration yet. The inventory remains replay_ready=false.
The register is now merged in main 3f1ef45; its earlier full-suite and byte-identity
results belong to the register batch, not to this data batch. Codex owns the remaining
implementation. Independent review and this batch's full verification are pending.

Independent Codex review of foundation head 336c2b20eec8e7afc820e878b0ce288963f982b6
found two P2 defects. Both were reproduced by failing synthetic tests and fixed:
undecodable compressed members now use the existing reader's decoder-error
classification and become excluded entries, while unrelated filesystem failures
still propagate; bounded raw filter responses are saved before semantic parsing,
so a malformed one-time futures response survives for diagnosis. A failed parse
still produces no final manifest. Focused suite: 82 passed; repository Ruff,
format, mypy (74 files) and Bandit clean. The earlier full-suite and byte-identity
runs were deliberately interrupted before this fix pass and are not pass evidence.
External exact-head review and full verification remain pending.

PR #211 validation at f02ec0a: Bob NO ISSUES; CI 1,839 passed, 2 skipped,
1,595 subtests passed; local legacy byte identity ALL IDENTICAL. The duplicate local
full pytest was stopped after CI provided completed full-suite evidence. Before
merge, Cloud review then identified the valid dual MIN_NOTIONAL/NOTIONAL shape
already supported by the legacy exchange parser. Merge was held. Two new regression
cases reproduced the rejection and now pass; V3 parses every supplied minimum and
uses their maximum. Missing/malformed values remain errors. New-head review and CI
are required; the prior verdict is not carried over to this fix.
