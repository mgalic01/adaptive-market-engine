# Codex → Claude: high-performance strategy roadmap

Index: Documentation-only V2 I–M and V3 futures planning proposal; existing acceptance and paper-only policy preserved; no merge requested.

- Writer: Codex Desktop, 2026-10-05.
- Branch: `codex/high-performance-crypto-strategy-roadmap`.
- Base: `c4cfb87c3560131c5b14d0165f6b026c215f9a2d`.
- Checkout: dedicated `roadmap-repo` clone in the owner's local ChatGPT project workspace.
- Scope: [strategy roadmap](../HIGH_PERFORMANCE_CRYPTO_STRATEGY_ROADMAP.md), based on the referenced owner conversation and supplemented with implementation contracts.
- Status: documentation prepared for the owner's requested branch publication; no merge or independent-review approval asserted. The containing Git commit identifies this batch.

The roadmap preserves the compounded-return/drawdown/ruin-risk philosophy, I–M research families, V3 long/short architecture and indicative parameters. It distinguishes the binding C1 10% acceptance ceiling from the 12% runtime hard stop. PR #165 is recorded as merged rather than left as a stale instruction. Source retrieval truncated after Stage 11; editorial completion and added contracts are explicitly labeled.

Verification before publication: required-topic and relative-link checks passed; `python scripts/check_reports.py` reported 0 problems, with its existing 14 unverifiable historical hashes disclosed. `git diff --cached --check` is the final staged formatting check. No strategy code, configuration, data, or acceptance criteria changed. No performance experiment, reserved-data access, security scan, or full software test suite was run for this documentation-only change.

No known required fixes in the reviewed documentation scope. No concrete security finding or runtime compatibility change was identified; strategy profitability and live-execution safety remain unverified. The main compatibility risk is treating candidate settings as approved policy, which the roadmap expressly disallows.

Next owner: the project owner selects and authorizes a development task from §26. Before implementation, the assigned writer reconciles the pinned baseline and completes preregistration. Future reviewers should check policy separation, leverage denominators, point-in-time feature rules and research gates. This durable handoff is available in the branch; no separate agent message or review trigger is part of this publication request.
