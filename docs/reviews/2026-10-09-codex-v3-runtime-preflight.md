# V3 runtime preflight: implementation handoff

Index: Offline runtime preflight checks pinned checkout bytes and imported origins; synthetic Windows/Python 3.12 validation passed, no dispatcher or data access added.

Goal: reject accidental wrong/changed runtime code before the future V3 dispatcher
can produce evidence under a valid committed registration. The original plan commit
`2485897b7da1986efc7e206382d6a986e8e6d10d` is preserved; implementation integrates
main `c906216621da0e0f21f7768436b48c086a89a95b`.

The new stdlib-only `scripts/v3_runtime_preflight.py` exposes `preflight_runtime`,
`check_import_origins` and `recheck_runtime`. It requires a fresh `-I -S -B`
interpreter and a checkout without project bytecode caches. Load the checker by
explicit file location before adding project paths, as demonstrated by the test
bootstrap. It verifies HEAD/root, staged changes, direct implementation bytes,
hidden index flags, unregistered/ignored import sources and redirected paths.
After inspection it adds the verified source paths and reuses unchanged
`trial_register.check_ready`. It checks loaded module file/spec/loader identities
and package paths, and rejects project modules preloaded before inspection.

Ruling: require `-S` as well as `-I` because isolated mode alone still processes
site startup. This bounded V3 contract has no third-party runtime requirement;
dependency-environment attestation remains deferred. Ruling: the bootstrap must
not insert `scripts/` before loading the checker, since even its stdlib imports
could then execute an untracked shadow module. A sentinel regression demonstrated
that failure before the fixture/bootstrap contract was corrected.

Ruling: preserve raw Git digests while accepting exact LF-to-CRLF rendering only
for Python source, the three dependency metadata filenames and exact path
`scripts/byte_identity_baseline.json`. Parent review identified the last file's
ordinary Windows checkout conversion; a synthetic test reproduced the false
rejection before adding that exact path. No JSON reserialization or clean filter
is used, and content changes still fail. Loader-path drift likewise has a
demonstrated red-to-green regression.

Validation on Windows:

- `python -m pytest tests/test_v3_runtime_preflight.py tests/test_trial_register.py tests/test_v3_registered_inputs.py -o addopts='' -q`: **86 passed, 1 skipped**.
- The pytest driver was Python 3.14; every runtime subprocess used bundled Python
  **3.12.14**, selected by the test-only `V3_PREFLIGHT_TEST_PYTHON` variable. The
  bundled interpreter has no pytest, so this tests its native runtime APIs without
  installing anything. Existing registration/binding tests ran in the 3.14 driver.
- The skipped test could not create a privileged Windows file symlink. The actual
  Windows parent-junction rejection fixture passed; other platforms retain the
  file-symlink test when supported.
- Changed-file Ruff, strict mypy for the new module, Bandit and whitespace checks
  passed. No full-suite claim is made.

Limits: this is cooperative provenance/error detection, not a sandbox. The
checker and interpreter are trusted; it cannot prove absence of in-memory patches
or eliminate mutation races. Recheck immediately before dispatch and before result
acceptance, once those callers exist. Do not clear caches in an active worktree;
prepare a fresh runtime checkout. A snapshot is evidence, not authorization.

Completed: implementation, adversarial synthetic tests and local checks. Next:
parent reviews the final commit and owns GitHub coordination/external review.
Deferred: full CLI, historical replay, publication and installed-dependency
attestation. No E: paths, market inputs, spec/config/registration, collection
processes, retry permissions or owner/data-access gates were changed or accessed.
