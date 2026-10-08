# V3 immutable attempt metadata journal

Index: Seven synthetic journal tests pass; replay artifact serialization and callback integration remain pending.

EvidenceJournal records started/finished metadata as separate immutable JSON files.
It fsyncs a temporary file before atomic hard-link publication, never replacing an
existing record. A finished record requires a valid start. Recovery validates
records and reports starts without finishes; interrupted publication leaves the
start visible. Decimal strings preserve precision; floats, nonfinite values,
unsafe identities, duplicate keys and oversized metadata are rejected.

Seven tests cover reopen/recovery, no overwrite, finish without start, numeric
refusal, malformed records, duplicate keys and simulated publication failure.
Ruff and mypy pass. No new dependency or network/data access.

Limits: single-writer ownership is required. Filesystems without hard-link support
fail explicitly. File fsync and atomic publication are not a guarantee against
every power failure; directory-entry durability differs by platform. Metadata is
limited to 4 MiB. Orphan temporary files are retained after abrupt termination and
are not treated as valid evidence. The journal does not authorize or automatically
retry runs. Full streamed replay artifacts, digest linkage, Attempt callback and
report integration remain unfinished per the implementation plan.

Replay callback integration: AttemptRecorder now persists starts before replay,
streams full runner evidence to immutable JSONL, then publishes a finished record
pinning SHA-256, bytes and row count. Account positions, events, fills, funding,
hour decisions/results, audits, equity path, samples and completed/active lifecycles
are preserved, including outcome and signed residual. A changed finished identity
is rejected; engine errors without a result remain explicit failed attempts.
verify_artifact checks row framing/schema, exact digest and counts on read-back.
Eleven journal/writer tests pass, including five actual synthetic sensitivities,
fill/funding evidence and deliberate artifact tampering; Ruff and mypy pass.
Combined writer/journal/orchestration checks excluding the slow training test pass.
Spot evidence, recovery finalization, reports and historical registration/loading
remain pending. Failed serialization/publication leaves a pending start; orphan
artifacts are retained and are not silently overwritten or retried.
