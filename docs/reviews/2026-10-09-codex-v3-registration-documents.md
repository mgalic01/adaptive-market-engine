# V3 committed registration document handoff

Index: Codex adds exact committed manifest/configuration retrieval after existing registration validation; no historical execution authorization.

The future dispatcher needs the documents that `check_ready` actually verified,
not a second read of potentially modified local files. `read_registered_documents`
returns a frozen `RegisteredDocuments` value with the trial, completion,
registration, revision, code and spec identities, manifest/configuration paths
and hashes, and their exact Git blob bytes at the validated full revision.

This is a library API with no CLI change. Existing `check_ready` remains the
validator, including committed completion, antecedent registration, code inventory,
code/spec/config/manifest hashes and correction rejection. A dirty checkout cannot
substitute documents. Git validation does not attest the executing interpreter,
approve input schemas, open archives or grant data access/dispatch permission.
Those remain caller responsibilities before the historical experiment.

Verification: the three real-Git readiness scenarios first failed on the missing
API, then all 42 register tests passed. Assertions cover missing completion,
exact bytes and identities, dirty local documents, changed/new implementation
and later checkout commits while requesting the original revision. Ruff and
focused mypy passed. No historical data, dependencies or strategy changes.

Claude/Bob handoff: review immutable revision use and provenance fidelity. The
runner connection is separately in PR 243. This change does not complete an actual
registration: reviewed data and code still need their completing event committed.
