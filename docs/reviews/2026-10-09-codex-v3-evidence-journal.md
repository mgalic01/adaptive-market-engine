# V3 immutable attempt metadata journal

Index: Journal and replay writer implemented; recovery now verifies finished artifacts and refuses unfinished attempts; full decision and failed-replay evidence remain pending.

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
report integration were unfinished at the initial journal commit; see the subsequent
implementation and recovery updates below.

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

Recovery review response (Bob at a13a2c3): reopening AttemptRecorder now verifies
every finished artifact's hash, framing and counts, binds its filename to its run,
and checks finished identity against the start. Missing/truncated artifacts and
changed identities fail explicitly. Unfinished starts prevent reopening for new
dispatch; EvidenceJournal.pending remains a metadata-only inspection API, not a
completed-result validator. Five new regression cases failed before this fix and
passed after it (16 combined journal/writer tests). The inherited runner formatting
failure was reproduced locally and corrected without changing behavior.

Still open: explicit interrupted-attempt adjudication/adoption, linking the complete
pick schedule, complete daily decision evidence, and retaining partial runner data
when execution itself raises. Serialization failure intentionally leaves the start
pending; that is not a finished or successful result. Memory is bounded per serialized
row, not for the whole replay or the five retained sensitivity runners. No historical
dispatch is authorized by these changes. Claude handoff: these are evidence integrity
fixes; no new dependency, credential handling or trading-rule change.

Partial execution evidence follow-up: ReplayExecutionError now carries the unfinished
ReplayResult and chains the original exception. Failures after runner construction
mark it engine_failure without inventing a terminal mark or censoring active trades.
Training, OOS and sensitivity handlers persist that partial result before re-raising.
Two regressions reproduced missing partial evidence before implementation; the writer
test now verifies the preceding hour and failed account state in the actual artifact.
All 39 focused replay/writer/orchestration tests excluding the slow full-training
scenario pass. Ruff and mypy pass. Compatibility: execution-time engine errors are
now wrapped in ReplayExecutionError; preflight errors retain their original types.
The earlier full-suite process tests the recovery-only snapshot f8c28db, not this
subsequent change. Full decision evidence and report/recovery completion remain open.

Daily decision evidence follow-up: ReplayResult now retains each decision timestamp,
selected rule and DailyDecision, including all twelve raw rule signals, effective
signals, final targets, exit candidates and sizing diagnostics. SizingResult now
also records pre-cap scaled weights and the binding coin/gross caps without changing
the arithmetic producing weights. The writer emits these as decision rows before
account records; partial failures carry the decisions reached before the error.
Tests reproduced absent replay decisions, absent serialized decisions and absent cap
diagnostics before implementation. Sixty-eight focused sizing/decision/replay/writer
tests pass; a nonempty synthetic record is read back to check exact signal, volatility,
scaled-weight and cap preservation. The full-training orchestration scenario also
passed for the preceding partial-error change (40 combined tests). Full latest-tree
verification and external review remain required. Start-record pick schedule linkage,
explicit recovery finalization and whole-experiment reports are still unfinished.
