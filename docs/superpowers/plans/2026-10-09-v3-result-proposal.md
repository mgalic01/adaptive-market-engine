# V3 read-only result proposal plan

Base: c906216621da0e0f21f7768436b48c086a89a95b.
Goal: bridge observed local attempts to the existing spec section 9 result-event
schema without changing canonical history, journals, publisher or runner.

- Test first: synthetic register/documents and journal rows; no replay or market data.
- Implement scripts/v3_result_proposal.py returning index bytes plus result JSONL.
  Require matching completion/spec/config/manifest identities and supplied document
  hashes. Validate complete proposed append with unchanged register validators.
- Classify known phase-specific outcomes, give nonempty recorded errors precedence,
  and block unknown reasons/types. Full-size hold unavailable is only an invalid
  diagnostic run, never A5 failure or an experiment verdict. Export no metrics yet.
- Pending starts require an exact explicit disposition set: failed/cancelled reason
  and diagnosis source. These are caller-reviewed claims, not authenticated
  authorization; never infer completion, execution time or cancellation.
- Pin exact journal/artifact bytes, retain pending artifacts as unconfirmed and
  reject orphan artifacts without starts, altered identities or malformed evidence.
- Deterministic event IDs bind trial/completion/run IDs; stable ordering and explicit
  recorded_at. Safe repository-relative index path; evidence_source is text only.
- Focused tests/static checks, indexed handoff, local commit only. Parent owns review.

Contract: build_result_proposal(register_bytes, documents, evidence_directory,
*, index_path, evidence_source, recorded_at, agent, pending_dispositions) returns
ResultProposal(index: bytes, events: bytes). No output writer or canonical append.

Limits: committed-document provenance and exclusive quiescent ownership are caller
prerequisites. Observed history is not all historical attempts, authenticated
report derivation, audit recomputation or a verdict. No data access is authorized.

Review clarification: journals have no registration pins. Label directory-to-trial
attribution caller_proposed_unverified in the index and every event provenance.
Even an otherwise valid alternative registration can yield only an unverified
proposal; canonical append requires separately reviewed invocation linkage.
