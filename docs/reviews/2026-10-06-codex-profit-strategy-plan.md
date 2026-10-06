# Codex to Claude: profit-focused strategy research plan

Index: PR #169 Addendum B assesses OpenTraderWorld examples and updates spot/futures research sequencing; documentation only, no merge.

Owner requested a concrete spot/futures plan and an assessment of whether the
external strategies can benefit our product. Named writer: Codex Desktop.
Main was refreshed to `2f51a3c89b1548af1087f0796500b3adb2c8b4d0`.
The roadmap now explicitly recognizes current spec v2 and preserves its freeze.

Source inspection at upstream `a3383baff1b5bb6d78c349437c45fbbe32cd4836`
confirmed demo strategy definitions and hard-coded saved-run statistics in
`core/otw-core/src/demo_seed.rs`. These are examples, not profitability evidence.
Prioritize a bounded spot trend comparison, then isolated grid/allocation research,
with a separate futures accounting foundation before long/short performance tests.
No upstream code or runtime dependency is imported.

Validation: formatting and repository report checker are run before publication;
their actual results accompany the exact-head PR handoff. No strategy run, reserved
data access, runtime modification or live trading occurred. No profitability or
external-review approval is claimed. No concrete security finding is introduced by
this documentation change. Main compatibility risk: confusing future research with
approved frozen-spec behavior; the new opening update and addendum forbid that.

Next owner: assigned strategy writer after current v2 evidence, to register the
bounded comparison. Futures implementation remains a separately assigned task.
Claude should use this as a planning reference; no interruption or merge requested.

## Chat research consolidation

Owner subsequently requested all research from this chat in the existing document/PR.
Added [external research and build decisions](../EXTERNAL_RESEARCH_AND_BUILD_DECISIONS.md)
and a prominent roadmap link. Includes OpenTraderWorld/trend-switcher continuity,
Reddit coverage limits, all ten published passed strategy-card metrics, and pinned
Jesse/MDRAP/Fenix findings from source and test inspection. Separates existing bot
capabilities, beneficial engineering patterns, deferred signals and rejected wholesale
platform adoption. No upstream tests were executed or new dependencies installed.

Publication main refresh: `e9279aeff6b8b0138f387e10443be321869394ee`.
Engineering comparison baseline: `7c5a472ea52b72fb48c591325f9d5b258c79eb1f`.
These are deliberately distinct; this documentation branch does not integrate main.
Verification commands: git diff --check, scripts/check_reports.py, local relative-link
and expected-section checks, and the PR claims check before pushing. Exact results
are posted with the containing commit on PR #169. Main risk is treating research
recommendations as implemented capabilities or trading authorization; the document
explicitly separates those states. No runtime/security fix or profitability validation
is claimed. PR #177 retains the separate offline probe. No merge requested.
