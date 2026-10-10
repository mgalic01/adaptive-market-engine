# Codex: first V2 diagnosis implementation batch

> 2026-10-10 consolidation: Historical evidence preserved from PR #208, whose V2 implementation is superseded. No V2 runtime patch is included here. Schema, implementation and test claims below describe that unmerged branch, not current main. See the [maintained research index](../RESEARCH_INDEX.md).


Index: Output-only selected Uptrend entry attribution, separating selected opportunities from continuation buy attempts; no strategy change, historical rerun, or V3 implementation. Frozen synthetic numeric equivalence retained; position lifecycle attribution remains separate.

Owner request: start implementing the diagnosis proposal. Named writer: Codex Desktop.
Base: `0978e911141989fbbbad4600dc9430de7ee3c41d`.

Detailed evidence: [V2 diagnosis and artifact provenance](../backtests/2026-10-08-spec-v2-diagnosis.md). Published at the owner's request after initially being omitted from this PR; recommendations are historical, with V2 closure explicitly noted.

## Why this exists

The scored BTC result had 140 Uptrend selections but 48 completed trades. Those
counts do not measure the same thing. Existing reports could not distinguish
execution refusals from selection or continuation. The new additive report makes
the entry stage inspectable without selecting another strategy or changing risk.

See [the report schema](../backtests/ENTRY_ATTRIBUTION.md) and
[the implementation plan](https://github.com/mgalic01/adaptive-market-engine/blob/558c86dc6a0cec1d496a007ea58d050d0099369a/docs/superpowers/plans/2026-10-08-v2-attribution.md).

## Verification and review

- Test-first: four missing runner fields and two missing collector/export fields
  failed before implementation; the execution-context test also failed before its
  fields were added.
- Twelve targeted tests pass, including partial fills, repeated depth waits, budget
  refusals, overlapping blockers, same-frame recovery, JSON serialization, legacy
  input, copy isolation and replay export.
- The existing frozen numerical-equivalence digest passes after excluding only the
  added fields alongside the pre-existing selector explanations. Its expected hash
  was not changed.
- Ruff checks and formatting, mypy, Bandit, self-check and the synthetic paper demo
  pass. Dependency audit found no known vulnerabilities; its cache emitted
  deserialization warnings and ignored those entries.
- Independent Codex reviewer found no important correctness issue; ran the original
  entry tests and mode-switch replay tests (30 passing at that point). The subsequent
  tests cover the review's stated edge-case coverage gaps; runtime code did not
  change after that review. This is not the required external Claude/Bob approval.
- Full-suite status is recorded in the PR handoff after completion. The targeted
  checks above do not claim a historical replay equivalence proof.

No new dependencies, live-order path, risk setting, frozen spec or market-data access.
No new concrete security finding. Compatibility: MS output gains `modes.entries`
and relevant frame reports gain `uptrend_entry`; strict consumers must allow those
additive fields. V0 output is unchanged by this reporting path.

## Scope and handoff

Claude's newly opened #206 records V2 closure, and #207 proposes V3. This branch does
not reopen the experiment, start a replay, or compete with the V3 design. Claude
should assess whether this small explanatory layer merits merging now or retaining
as a reference for V3 reporting. Do not merge without external review.

Still unimplemented: linking selected entries through final position outcomes,
full trade favorable/adverse excursion and net accounting attribution, and grid
inventory lifecycle attribution. Those remain Codex's next diagnostic batch only
if useful to the chosen successor; they are not represented as completed here.
