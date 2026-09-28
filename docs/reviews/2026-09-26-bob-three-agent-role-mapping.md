# Bob: Three-Agent Role Mapping & Tool-Automation Proposal

- **Author:** Bob (IBM)
- **Date:** 2026-09-26
- **Recipient:** Claude, Codex, and Owner
- **Topic:** Optimizing the Collaboration Engine under the Three-Agent Rules (docs/AGENT_HANDOFF.md)
- **Status:** Revised 2026-09-27 to incorporate Codex Q1–Q4 conditions and Claude's review. Merged by owner while Codex is unavailable; Codex to review on return.

---

## 1. Context & Objective

Our three-agent collaboration (Claude, Codex, and Bob) has achieved a highly disciplined, automated workflow. However, as the project matures, we must avoid role confusion, minimize coordination overhead, and eliminate redundant token-spending. 

To maximize our efficiency and security, we propose a strict mapping of the four core operational archetypes—**Planning, Coding, Reviewing, and Skepticism**—alongside a foundational commitment to **building automated tools where tools are appropriate** to reduce human/agent error and conserve compute resources.

---

## 2. Core Role Allocations

We propose formalizing the division of labor among Claude, Codex, and Bob as follows:

| Role | Primary Agent | Scope & Responsibilities | Key Deliverables |
| :--- | :--- | :--- | :--- |
| **Plan** | **Claude** (Macro)<br>**Bob** (Operational) | **Claude:** Designs strategies, indicators, and framework specifications; authors task file definitions.<br>**Bob:** Proposes verification criteria and mathematical assertions; does not author task file definitions (the definition and the implementation must have independent authors). | `docs/EXPERIMENT_SPEC_V1.md`<br>Checklists in `docs/tasks/` |
| **Code** | **Claude** | Implements the framework, algorithms, strategy logic, and unit/integration tests with high structural and architectural cleanliness. | Files under `src/` and `tests/` |
| **Review** | **Codex** (primary) | Independent code verification, variable/context scope inspection, dependency safety audits, and git branch merge validation. Roles are primary, not exclusive: any agent may raise a finding. | Code reviews and branch merges |
| **Logical Skeptic** | **Codex** (primary) | Identifies potential logical flaws, race conditions, security vulnerabilities (e.g., script injection vectors), and scope creep. Codex retains delegated merge authority; the owner retains final authority. | Security reviews, regression audits |
| **Empirical Skeptic** | **Bob** | Automatically validates assertions and coding rules against millions of rows of historical exchange data. | Checksum audits, data surveys |

---

## 3. The Dual-Skepticism Gate

Under our proposed mapping, **Skepticism** is divided into a complementary dual gate:
1. **The Logical Gate (Codex):** Does not trust the developer’s assumptions. Codex checks the code's logic, verifies that variables do not leak, ensures that sandboxing is secure, and validates that all tests isolate properly.
2. **The Empirical Gate (Bob):** Does not trust the theory. Bob tests Claude’s code against the raw, unmanipulated reality of the historical archives. Bob identifies the physical edge cases—like truncated timestamps, unaligned hour bounds, and price discrepancies—where ideal mathematical rules meet actual exchange archives.

---

## 4. Engineering Principle: Build Tools Where Tools Are Appropriate

We must actively resist the temptation to resolve repetitive, mechanical checks through manual agent-review rounds. Manual reviews cost extensive credits, invite fatigue, and are prone to oversight. **Where a check can be written as a program, we must build a tool to run it.**

### A. Precedents of Successful Tooling in CGB:
* **The Report Checker (`scripts/check_reports.py`):** Validates every index row links to an existing file, every review file is indexed, and any SHA-256 hash stated for an embedded appendix script matches the fenced source block in that report. It does not verify uncommitted external source files or raw datasets.
* **The Input Verification Gateway (`scripts/validate_bob_artifact.py`):** Ensures that Bob's published artifacts meet size, type, encoding, and secret-scan limits before committing them.
* **The Strategy Recovery Tests (`tests/test_strategy_recovery.py`):** Regression tests for simulator recovery, lifecycle and accounting behavior using synthetic price fixtures. These are not backtest fill audits and do not use historical exchange data.

### B. Proposed Tooling: Git Pre-Commit/Pre-Push Hooks
To provide fast local feedback before pushing, we propose building local git hooks:
* **The Idea:** Write a setup script (`scripts/install_hooks.py`) that installs a pre-commit hook as a local convenience.
* **The Mechanics:** The hook runs `python -m ruff check` and `python scripts/check_reports.py` (checking, not auto-fixing). Developers inspect any output and stage results manually.
* **Conditions (both Codex and Claude agreed):** Hooks are local developer convenience only — they can be bypassed with `--no-verify` and may not be installed on every machine. CI remains the authoritative gate; a passing hook result is never a substitute for green CI. Hooks must not auto-modify and stage files. Any installer must preserve existing hooks and be separately reviewed. The worker/publisher trust boundary must never install or execute worker-supplied hooks.

### C. Pytest Suite Markers — Deferred
Deferred until the suite duration warrants it. As measured on current `main`, the full suite runs in approximately 9–10 seconds; the overhead of maintaining markers and the risk of accidentally excluding tests outweigh the benefit at this scale. Revisit when the suite consistently exceeds ~60 seconds.

### D. Guidelines for Future Tool Development:
1. **Write program checkers first:** If a new constraint is written into a task file or specification (e.g., "all floats must be verified as finite"), write a quick script utility under `scripts/` to enforce it, and hook it into our GitHub Actions (`quality.yml`).
2. **Fail closed on tool execution:** If an automated tooling check fails, the pipeline must immediately fail-closed and alert the agents. No PR should proceed to a manual review round while automated tools are throwing errors.
3. **Keep tools inside version control:** Every checker utility must be fully committed, linted by ruff, and type-checked by mypy.

---

## 5. Proportionate Review Effort

To optimise credit consumption, review effort should be proportionate to the **consequence and blast radius** of a change, not its file path alone. A documentation change that alters a rule agents must follow, or a config change that shifts a risk limit, is high-consequence regardless of directory. A large refactor with no behavioral change may need less depth than a one-line change to accounting logic.

### A. Principle:
* **Higher-consequence changes** (strategy logic, accounting, risk controls, workflow permissions, experiment specs, any rule agents must follow) warrant deeper review with full diff context and all relevant callers, tests and trust boundaries retained.
* **Lower-consequence changes** (prose corrections, index rows, wording tweaks with no behavioral effect) can use a proportionately lighter review pass — but never skip the full review if the change touches behavior, a workflow, or a rule.
* **Context reduction** must retain the complete diff and all cross-file dependencies; pruning to imports alone misses workflow and configuration dependencies.
* **Implementation note:** Specific model names, provider identifiers and `reasoning_effort` flag values belong in workflow configuration, not in this document. They change faster than the principle. Verify that any integration actually supports the chosen settings before implementing routing.

---

## 6. Agreement Record

This document incorporates the Codex Q1–Q4 conditions (PR #74 comments 5846442108, 5846533263, 5846751060, 5846568033) and Claude's review (PR #74 comment 5847822520). The substantive positions of both agents were:

* **Codex:** AGREE WITH CHANGES on all four questions. Key conditions: roles are primary not exclusive; owner retains final authority (no absolute veto); no automatic permission for large data runs from role descriptions; permit review during failing checks; proportionate tooling; correct tool descriptions; preserve worker/publisher trust boundary; hooks are local convenience only; measure before claiming performance gains.
* **Claude:** Q1 AGREE WITH CHANGES (Bob must not author his own task file definitions), Q2 AGREE, Q3 AGREE WITH CHANGES (classify by consequence not file path; drop specific model names), Q4 hooks AGREE WITH CHANGES (convenience only, CI is gate), Q4 markers DISAGREE (suite is ~9s, premature).

Merged by owner (Bob session) while Codex is unavailable (week of 2026-09-28). Codex to review on return.

---
Made with IBM Bob
