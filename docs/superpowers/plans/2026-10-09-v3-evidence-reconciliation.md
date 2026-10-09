# V3 evidence reconciliation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Authenticate supplied training scores against recorded evidence and reconcile the exact completed experiment menu without another replay.

**Architecture:** One offline reader returns compact semantic role-to-artifact bindings. Existing journals, evidence writers, selection arithmetic, and runner remain unchanged. Completion here means the expected menu finished without engine errors; known strategy-invalid outcomes remain invalid.

**Tech Stack:** Python 3.12+, standard library, existing V3 Decimal metrics, pytest synthetic fixtures.

**Spec:** `docs/EXPERIMENT_SPEC_V3.md`, sections 7–9; existing `orchestration.py`, `evidence_writer.py`, and `selection_report.py` contracts.

## Global constraints

- No market data, replay, network, E: access, registration mutation, dispatcher, publication, or verdict.
- Work from cached origin/main c906216 in isolated branch codex/v3-evidence-reconciliation.
- Own only the new module, its tests, this plan and a review handoff. Discuss existing runner changes first.
- Caller supplies an exclusively owned existing evidence directory and registered first-month calendar; registration/provenance/authorization remain upstream.
- Preserve the report's uncertified status and all prerequisite text. This checker does not establish complete historical attempt coverage outside its supplied directory.

## Artifact sufficiency and limits

Started/finished records already bind phase, interval, futures rule, multiple, cost and pick schedule, and bind each run to artifact path/SHA256/byte and row counts. Replay rows contain outcome reason, account settings/stopped reason, audits, samples, equity path, completed and active lifecycles. These suffice for training Sharpe recomputation with `validate_sample_path`, `sample_returns`, and `sharpe`, plus explicit finalization/settings/reason checks. Spot rows contain cost and stopped reason; full-size hold rows additionally contain interval, schedule, budgets and outcome reason.

No new artifact fields are needed for this limited verifier. Artifacts do not independently pin a registration, and nontraining report summaries lack run IDs. Return explicit bindings for future integration; do not claim arbitrary supplied nontraining report values were derived from those artifacts. Recomputing every report metric, strategy decision, fee or market input is outside scope. Hashes establish byte linkage, not truthful execution against market data.

## Proposed API and algorithm

New `src/crypto_grid_bot/trend/evidence_reconciliation.py`:

`reconcile_experiment_evidence(directory: Path, training: Sequence[TrainingScore], picks: Mapping[int, str | None], first_months: Mapping[str, str]) -> tuple[EvidenceBinding, ...]`

Frozen `EvidenceBinding` contains semantic role (training quarter/rule, main, sensitivity multiple/cost, fixed rule, spot cost, full-size hold), run ID, artifact SHA256/path/bytes/records, and observed invalid reason. It carries no pass verdict.

1. Require an existing regular directory; reject linked evidence/journal files and unknown published artifacts. Validate journal start/finish identities, no pending attempts, no engine errors and no orphan artifacts using existing framing/hash validators without creating a missing directory.
2. Validate supplied training menu/picks via existing selection checker. Derive windows from BTCUSDT first month and exact expected identities: 12 training runs per quarter; main m2/base; five frozen sensitivities; twelve fixed rules; two spot holds; one full-size hold. Match semantics, never UUID naming. Reject missing, duplicate or unexpected attempts and wrong intervals/settings/schedules. Require training run IDs equal supplied score IDs.
3. Read one artifact at a time, bounding each row with existing LIMIT and checking its hash/counts on the same read consumed for reconciliation. Require unique account/outcome headers, correct account kind/settings and compatible known reason/stopped values; finalized accepted audits and no active lifecycle. Crosscheck full-size hold interval and cost; retain unavailable-first-purchase as an invalid diagnostic.
4. For valid training only, collect samples and minimal equity states, validate the complete ordered sample/path relationship and training boundaries, then recompute exact Decimal Sharpe and compare with supplied score. For invalid training require known matching reason and no score; do not fabricate Sharpe. Crosscheck futures artifact decision rules against the declared schedule where those rows exist, without claiming decision completeness or replay derivation.
5. Return deterministically sorted compact bindings after exact menu reconciliation. Never modify report prerequisites, journals, artifacts or canonical registration.

Memory is O(attempt metadata + one training artifact's equity marks/samples), not O(all replay artifacts). Ignore bulky fills/events/strategy inputs after row validation. Existing metrics require equity/sample sequences, so retain those for one training run only; no full runner or market bars are reconstructed. Reading hashes twice through existing integrity validation is acceptable I/O; no strategy is rerun.

## Review focus

- Authentic but swapped training artifacts must fail semantic/run identity or score checks.
- Rehashed malformed duplicate headers, unknown reasons and dishonest settings must fail.
- Interrupted, failed, missing, duplicate and extra attempts must not resemble a completed menu.
- Decimal context changes must not change recomputed scores or chosen schedules.
- A valid binding must never imply report derivation, registration, history completeness or acceptance.

## Task 1: Implement and test the bounded reconciler

**Files:** Create the module above and `tests/test_v3_evidence_reconciliation.py`.

- [ ] Write synthetic fixtures with real journal/writer serialization and fixed window menu; assert successful bindings and known-invalid preservation. Demonstrate failure because API is absent.
- [ ] Implement exact menu/identity checks and compact binding output; run focused tests.
- [ ] Add adversarial tests for missing/extra/duplicate roles, wrong intervals/rules/costs/multiples/schedules, score/run-ID/reason alteration, malformed headers, bad sample/path, active lifecycle, rejected audits, pending/failed/orphan records and hash changes. Observe red before each behavior batch.
- [ ] Implement bounded artifact checks and score recomputation; retain existing metrics and no replay calls. Test altered Decimal context and artifact-size-independent discarded rows.
- [ ] Run focused reconciliation, evidence writer/journal, selection and experiment runner tests; static checks for changed files. Report any wider validation limitation explicitly.
- [ ] Document verification, API limitations and remaining dispatcher/report linkage; commit locally, no push.

## Review gate

Parent approved the design before implementation. Implementation and focused
verification are complete; see the indexed handoff for the verified counts and
the agent usage-limit interruption. External review and integration remain pending.
