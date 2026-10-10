# V3 Runtime Preflight Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this bounded plan task by task. Checkboxes track implementation, not current authorization to dispatch.

**Goal:** Make V3 evidence trustworthy by rejecting a wrong or changed runtime checkout before the future historical dispatcher opens inventory data.

**Architecture:** Keep committed registration validation separate from runtime checks. Add a stdlib-only bootstrap/preflight module that checks pinned checkout files before project imports, then checks actual imported module origins in a fresh isolated interpreter.

**Tech stack:** Existing Python >=3.12, standard library, local Git objects and synthetic pytest fixtures; no new dependency.

**Spec:** `docs/EXPERIMENT_SPEC_V3.md` section 9 and `docs/superpowers/plans/2026-10-09-v3-registered-input-contract.md`.

## Scope and gates

This plan adds an offline runtime contract and tests, not a historical-run CLI. Defer full dispatch, replay, result publication and environment-package attestation. Preserve completing committed registration, owner/data-access authorization, reviewed coverage/calendar and reserved-window gates. Passing preflight grants none of them; registered replay inputs remain `replay_ready=False`. No network, market-data reads, collection retries or strategy runs are needed for this work.

`check_ready` and `read_registered_documents` validate committed Git objects; do not make them reject unrelated local document edits. `bind_registered_inputs` validates supplied input linkage, not the interpreter. A dependency lockfile match does not establish that installed distributions match it.

## One implementation batch

Create `scripts/v3_runtime_preflight.py` and `tests/test_v3_runtime_preflight.py`. Keep module-level imports standard-library only. Reuse existing registration validation after checkout inspection; do not duplicate its event/schema rules or import `v3_registered_inputs` before checking the checkout. The future launcher must call this contract from a fresh isolated Python process, not a reused notebook/test process. Start with `-I -S -B`, load the checker by `importlib.util.spec_from_file_location` before adding project paths, and register its module before `exec_module`. `-S` disables site startup, including `.pth`/editable-install startup hooks; `-I` alone does not do that. Use a fresh checkout without bytecode caches; never clean another active worktree to make this pass.

Interfaces:

- `preflight_runtime(root: Path, trial_id: str, revision: str) -> RuntimeSnapshot`
- `check_import_origins(snapshot: RuntimeSnapshot) -> None`
- `recheck_runtime(snapshot: RuntimeSnapshot) -> None`

`RuntimeSnapshot` records resolved root, exact revision, registered code digest, expected implementation paths/blob identities and observed file hashes. It is diagnostic evidence, not an authorization token. Failure raises `ValueError` with the failed boundary/path; never silently repair, change branches, retry or load data.

- [x] Add synthetic repository and subprocess tests from the matrix below; run them and confirm the missing implementation fails.
- [x] Implement checkout preflight: resolve Git top-level and require the supplied root; require HEAD equal the full supplied revision. Validate committed registration and its complete implementation inventory. Check every pinned source/dependency file directly against its Git blob, independently of Git status; reject missing files, staged implementation changes and redirected/symlinked implementation paths. Include the checker/bootstrap itself in the registered code inventory. Bootstrap code and interpreter remain trusted prerequisites, not self-authenticated code.
- [x] Permit exact blob bytes or, for a narrow documented text allowlist (`.py`, `pyproject.toml`, `requirements.txt`, `requirements-dev.lock`, exact path `scripts/byte_identity_baseline.json`), uniform LF-to-CRLF checkout rendering of an LF-only blob. Preserve the registered digest over raw Git blobs. Otherwise require exact bytes; never strip whitespace, normalize JSON or invoke custom Git clean filters. Do not depend on mutable attributes to define this comparison.
- [x] Before project imports, enumerate the permitted import roots (`scripts/`, `src/`) including ignored files. Reject unregistered Python sources, package initializers, bytecode and native extension modules that could affect imports. For this minimal runner require no project bytecode caches; isolated startup plus `-B` prevents writing caches but does not itself prevent reading existing ones. Unrelated files outside import roots do not fail solely for being untracked.
- [x] Define fresh-process import setup: isolated Python startup, explicit verified `scripts/` and `src/` paths, no CWD/PYTHONPATH/editable-install resolution for project modules. After fixed project imports, verify every loaded project/script module's resolved `__file__`, `__spec__.origin`, loader and package search paths against registered paths. Reject missing/ambiguous origins and preloaded project modules (local or foreign) even when current `sys.path` is correct; only the checker may already be loaded.
- [x] Implement recheck of HEAD, implementation bytes and imported origins. The eventual authorized caller must use it immediately before dispatch and before accepting published results. A mismatch invalidates that attempt; it never licenses a rerun. This batch tests those boundaries using callbacks only, without implementing dispatch/publication.
- [ ] Run focused checks: `python -m pytest tests/test_v3_runtime_preflight.py tests/test_trial_register.py tests/test_v3_registered_inputs.py`; run existing static checks appropriate to changed files. Record actual results and obtain independent review before integration.

Local checks completed: 86 passed, 1 platform skip, with native Python 3.12.14
runtime subprocesses; Ruff/mypy/Bandit passed. Final independent review remains
with the parent before integration; see the implementation handoff in
`docs/reviews/2026-10-09-codex-v3-runtime-preflight.md`.

## Adversarial synthetic test matrix

| Input/change | Required result |
| --- | --- |
| Correct registration, exact checkout and local imports | Snapshot returned; no inventory/data access |
| Valid old registration but different HEAD or different resolved checkout | Reject |
| Dirty/staged/deleted implementation; same-size edit with restored timestamp; assume-unchanged or skip-worktree | Direct file comparison rejects |
| LF versus uniform Windows CRLF | Both accepted; identical raw-Git registered digest |
| Changed token, indentation, extra newline, binary bytes or custom-filter content | Reject |
| Ignored/untracked shadow module, package initializer, bytecode or extension in import roots | Reject before project imports |
| Foreign editable checkout or preloaded project module; disagreeing origin/file/package path | Reject after imports |
| Source symlink or parent junction redirects outside root | Reject; platform fixtures skip only unsupported link creation |
| Files or HEAD change between checks | Recheck rejects; downstream callback/result acceptance not called |
| Unrelated untracked notes outside import roots | Do not reject merely for workspace dirt |
| Any preflight/origin failure | Inventory/replay callbacks remain uncalled |

Review especially bare script-module imports, namespace packages, Windows path casing/junctions, hidden Git-index flags and pre-existing bytecode. Avoid weakening the comparison to make a platform-specific fixture pass.

## Limits

This detects accidental checkout/import drift in a cooperative offline runner; it is not a security sandbox. Origin checks cannot prove loaded functions were never monkey-patched. Rechecks cannot eliminate concurrent modification races, arbitrary import hooks or in-memory mutation. A compromised checker/interpreter can lie. Stronger guarantees require a separately designed immutable execution snapshot/runtime boundary; do not claim them here or expand this batch to build them.
