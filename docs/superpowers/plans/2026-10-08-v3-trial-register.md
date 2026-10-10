# V3 trial-register implementation plan

> Execute inline with superpowers:executing-plans and test-first verification.

**Goal:** retain the complete known experiment history and prevent V3 execution before
its reviewed inputs and implementation are pinned in committed registration events.

**Architecture:** an append-only JSONL document and an offline validator/writer outside
the strategy package. Registration, completion, result and correction are distinct
events. The future V3 dispatch integration consumes the validated completion; Bob's
report publisher receives no new write permission.

**Tech stack:** Python standard library, Git subprocesses, existing pytest tooling.

**Spec:** `docs/EXPERIMENT_SPEC_V3.md`, section 9 step 2, with the event fields from
`docs/reviews/2026-09-25-claude-data-reuse-proposal.md` section 4. The frozen spec rules.

## Constraints

- Implement after #209's freeze corrections clear review; do not change the frozen spec.
- Register before V3 strategy implementation; complete the registration only after
  reviewed data and code exist, before any V3 run. Never invent future hashes.
- No strategy run, market download, external dependency or reserved-window access.
- Retrospective means not preregistered. Unknown historical details stay explicitly
  unknown; family summaries do not pretend to enumerate every historical trial.
- Existing V0, V1 and MS outputs stay unchanged; no strategy files are modified.

## Review focus

Duplicate event identifiers; references to missing or wrong-stage events; malformed
or nonfinite JSON; a rewritten/reordered historical prefix; staged-only registrations
mistaken for committed records; forged completion pins; incomplete historical counts.

## Task 1 — event schema and historical inventory

Files: `docs/trials/README.md`, `docs/trials/register.jsonl`,
`scripts/trial_register.py`, `tests/test_trial_register.py`.

- [ ] Define schema version 1 with common fields: event_id, trial_id, event_type,
  recorded_at (UTC), agent, family, parent_trial_id, sources and payload.
- [ ] Define retrospective payloads with preregistered=false, known scope, provenance,
  outcome references and explicit missing fields. Inventory V0's recorded variants
  and reproductions, V1's candidate family, D, #137's rules and V2's mode switcher.
  Use dated reports and exact source revisions, not guessed trial counts.
- [ ] Define candidate registration with preregistered=true, hypothesis, frozen-spec
  hash and commit, candidate versions, fees, sizes, folds, masks, seeds, budget,
  stopping/selection rules and explicitly pending data/code pins.
- [ ] Add failing tests for duplicate JSON keys, blank/truncated records, NaN/Infinity,
  wrong required types, duplicate event IDs and retrospective mislabelling.
- [ ] Implement `load_events(path: Path) -> list[dict[str, Any]]` and
  `validate_events(events: list[dict[str, Any]]) -> None`; reject invalid inputs with
  ValueError and line-specific diagnostics. No silent dropping of malformed lines.
- [ ] Populate historical records and V3's initial candidate-space registration with
  all 12 rules, quarterly selection, m=1/2/3, double costs and both hold comparisons.
  State that prior exposure is incomplete and does not produce an effective trial count.
- [ ] Run schema tests and independently check every source and the frozen-spec hash.

## Task 2 — append-only trusted writer and completion validation

Files: same script/tests; no changes to Bob's publisher.

- [ ] Add failing tests for modified historical bytes, reorder/deletion, completion
  before registration, duplicate completion, bad hashes and results with missing
  completion references. Corrections must name an existing event and preserve it.
- [ ] Implement `validate_append(base: bytes, candidate: bytes) -> None`: candidate
  starts with the complete base bytes, both parse and validate, and new IDs are unique.
- [ ] Add CLI `validate --register PATH [--base-ref REF]`, which reads the base blob
  through Git and checks the append-only prefix, and `append --event FILE`, which
  validates the entire prospective document before an atomic file replacement.
  No implicit commit, push, network call or shared worker credentials.
- [ ] Completion references the initial registration event and records full code
  commit, code content hash, manifest path/hash and config/spec pins. Define the code
  content-hash algorithm explicitly over sorted tracked implementation paths and
  canonical Git blob bytes, avoiding a self-referential completion-commit hash.
- [ ] `check-ready --trial-id ID --revision SHA` reads only committed blobs at that
  exact revision, validates the event chain, recomputes pinned files and verifies
  the code revision is an ancestor. Missing completion or mismatched pins fails.
- [ ] Test a temporary Git repo: working-tree or staged completion cannot satisfy
  readiness; committed valid completion can; later code/config/spec changes fail.
  All inputs are synthetic, with networking blocked.

## Task 3 — CI and later dispatch contract

Files: `.github/workflows/quality.yml`, register tests and README.

- [ ] Add an offline register validation check for every PR, comparing the JSONL
  prefix against the PR base. Handle initial creation explicitly; do not require
  a completion event for a candidate-space-only register.
- [ ] Document that readiness validation is mandatory before the future V3 runner's
  first data read or worker launch. There is no V3 dispatch path yet; do not claim
  the existing V1/V2 workflow enforces V3 registration or modify its behavior.
- [ ] Define result-event requirements for success, invalid, failed and cancelled
  attempts, including exact completion event and run/artifact provenance. The future
  trusted result writer must recover interrupted dispatches; completion validation
  alone does not guarantee every dispatched attempt is subsequently recorded.
- [ ] Run pytest, lint/format, mypy, security/report checks and the required
  `scripts/byte_identity.py check` on a stable committed checkout. Do not commit
  during identity tests. Use only its synthetic inputs.
- [ ] Publish one focused register PR with exact-head Bob review; no strategy code,
  data fetch or workflow dispatch. Keep missing data/code pins pending honestly.

## Subsequent independent batches

After register approval: dataset definition and tested offline fetch tooling plus
owner-started Bob task; then synthetic-tested `crypto_grid_bot.trend` rules, sizing
and account; then walk-forward/scorer and output-only lifecycle diagnostics; finally
committed completion and authorized runs. Each has its own implementation plan and
review. Do not treat this register plan as a shortcut around those gates.

Current owner: Codex Desktop. This plan is prepared while #209 review runs; no register
or V3 implementation is claimed complete by it.

## Relationship to the full trading-agent objective

The register is a prerequisite, not completion of the product. The owner targets
20–30% yield per evaluation cycle; this is a research target, not a promised return
or permission to tune against already-seen evaluation results. Report the target's
attainment frequency, losses and drawdown alongside compounded net performance.
An evaluation cycle must have a declared duration before comparisons are meaningful.
V3 already fixes quarterly selection and reports monthly returns; retain those
intervals for V3, and define the interval in any subsequent experiment specification.

The current V3 specification tests the core directional hypothesis first. Do not
silently expand that frozen experiment to satisfy the broader brief. The following
work remains explicitly outstanding after this register batch:

| Requested capability | Implementation/evidence needed | Sequence |
| --- | --- | --- |
| Long/short directional strategies and volatility sizing | New trend package implementing the exact V3 menu, allocation and funding/accounting rules; synthetic causal tests and walk-forward evidence | V3 after registration |
| Portfolio leverage, margin and liquidation controls | Hand-calculated boundary cases, funding-induced margin breach, adverse gap, exposure caps and event-order tests against V3 rules | V3 accounting batch |
| Backtest integration and benchmarks | Pinned eligible futures inputs, quarterly selection without future data, net metrics and risk-matched hold comparisons; preserve legacy outputs | V3 evaluation batch |
| Four-state adaptive regime engine | Separately specified causal features and transition hysteresis; bullish, bearish, volatile range and compression fixtures; ablation against directional baseline | Later registered experiment |
| ATR, order-flow imbalance, volume profile and EMA/Supertrend features | ATR/EMA/Supertrend can use bars; genuine order flow needs timestamped trades/books with declared coverage. OHLCV cannot establish order-book imbalance or latency behavior | Data feasibility before later spec |
| Adaptive bounded grid/DCA and fast profit-taking | Explicit maximum inventory, averaging limits, exit and re-entry rules; fee/slippage stress tests and state transitions with open inventory | Later registered strategy family |
| Liquidity sweep/squeeze breakout with R:R >= 1:3 | Causal entry, invalidation, stop and target definitions; demonstrate planned ratio after costs and report realized outcomes separately | Later registered strategy family |
| Fractional Kelly or ATR allocation | V3 uses its frozen volatility sizing. Any replacement needs bounded exposure, estimation-error stress tests and nested training-only fitting | Later sizing comparison |
| Dynamic hard stops, daily portfolio circuit breaker and margin de-risking | Define daily timezone/reset, realized plus unrealized loss, halt/restart state and priority relative to fills/funding; deterministic event tests | Later risk specification where beyond V3 |
| Limit chase, IOC and post-only lifecycle | Paper execution adapter with serialized order state, partial fills, rejection/cancel races, stale acknowledgments, fees and latency fixtures; no real order routing | Separate execution batch |
| Sharpe, Sortino, Calmar, win rate, profit factor and net PnL/MDD | Explicit units, annualization, flat/no-trade and zero-denominator behavior; independent hand-worked metric fixtures | Scorer plus separately specified missing metrics |
| Monte Carlo liquidation probability | Seeded block resampling preserving cross-asset dependence and funding/price ordering; replay the account model, confidence intervals and stress scenarios. Historical bootstrap is model-conditional, not a guarantee about future ruin | Separate analytics batch |
| Aggressive configuration presets | Versioned JSON schema with validated exposure/margin/stop limits and provenance; frozen V3 values first. Label later presets unvalidated until their own held-out evaluation passes | Configuration batch |

Each later family requires its own explicit specification and registration before
results are inspected. The existing spot manifest is not evidence of futures prices,
funding, order books, or executable fills. No artificial book imbalance or unmeasured
latency should be represented as observed data. Synthetic tests establish behavior;
they do not establish profitability. A broader product completion audit must verify
every row, including runtime integrations and evidence, rather than treating a green
V3 test suite or a successful register validation as full completion.
