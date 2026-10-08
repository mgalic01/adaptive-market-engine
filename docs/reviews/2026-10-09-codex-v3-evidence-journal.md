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
