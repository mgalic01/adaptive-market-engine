# Registered V3 input contract

Goal: bind the existing committed registration documents to an already verified
inventory and explicit reviewed portfolio calendar before passing inputs to the
experiment. This is an offline supplied-object bridge, not historical dispatch.

The committed configuration has exactly schema_version=1, experiment="v3" and
first_months for the fixed ten symbols. No strategy parameters or overrides are
accepted. The committed manifest is the exact inventory manifest. Check both raw
document hashes, inventory manifest/spec identities and config shape before
assembly. Reuse assemble_replay_inputs for candidate-calendar agreement, fixed
inventory completeness and separate strategy/hold streams. Read documents only
through read_registered_documents and inventory through load_inventory_inputs in
the eventual caller; this helper does not attest the runtime or permit data access.

Tests: valid binding preserves provenance, hold stream and replay_ready=False;
changed raw config/manifest, inventory identity/spec mismatch, unknown config
fields, duplicate JSON keys, wrong types, reserved dates and calendar disagreement
all fail closed. Use synthetic supplied objects only. Run existing registration,
loader and assembly checks, static checks and independent review.

Remaining after this bridge: runtime code attestation and authorized CLI, durable
report publication, all-attempt/training coverage checks, final verdict and
append-only result registration. The executor question remains independent.
