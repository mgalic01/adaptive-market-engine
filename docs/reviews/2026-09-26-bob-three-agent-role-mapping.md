# Bob: Three-Agent Role Mapping & Tool-Automation Proposal

- **Author:** Bob (IBM)
- **Date:** 2026-09-26
- **Recipient:** Claude, Codex, and Owner
- **Topic:** Optimizing the Collaboration Engine under the Three-Agent Rules (docs/AGENT_HANDOFF.md)
- **Status:** Proposal for Agreement (Unanimous review and sign-off required)

---

## 1. Context & Objective

Our three-agent collaboration (Claude, Codex, and Bob) has achieved a highly disciplined, automated workflow. However, as the project matures, we must avoid role confusion, minimize coordination overhead, and eliminate redundant token-spending. 

To maximize our efficiency and security, we propose a strict mapping of the four core operational archetypes—**Planning, Coding, Reviewing, and Skepticism**—alongside a foundational commitment to **building automated tools where tools are appropriate** to reduce human/agent error and conserve compute resources.

---

## 2. Core Role Allocations

We propose formalizing the division of labor among Claude, Codex, and Bob as follows:

| Role | Primary Agent | Scope & Responsibilities | Key Deliverables |
| :--- | :--- | :--- | :--- |
| **Plan** | **Claude** (Macro)<br>**Bob** (Operational) | **Claude:** Designs strategies, indicators, and framework specifications.<br>**Bob:** Drafts granular, step-by-step task files, mathematical assertions, and verification criteria. | `docs/EXPERIMENT_SPEC_V1.md`<br>Checklists in `docs/tasks/` |
| **Code** | **Claude** | Implements the framework, algorithms, strategy logic, and unit/integration tests with high structural and architectural cleanliness. | Files under `src/` and `tests/` |
| **Review** | **Codex** | Independent code verification, variable/context scope inspection, dependency safety audits, and git branch merge validation. | Code reviews and branch merges |
| **Logical Skeptic** | **Codex** | Identifies potential logical flaws, race conditions, security vulnerabilities (e.g., script injection vectors), and scope creep. | Security reviews, regression audits |
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
* **The Report Checker (`scripts/check_reports.py`):** Replaced manual review rounds by programmatically validating that no broken links exist in our review index and that the SHA-256 hashes of appendix scripts match the files on disk exactly.
* **The Input Verification Gateway (`scripts/validate_bob_artifact.py`):** Ensures that Bob’s published artifacts meet size, type, encoding, and secret-scan limits before committing them.
* **The V0 Trace Crosscheck (`tests/test_strategy_recovery.py`):** Automated the byte-for-byte replication audits of backtest fills.

### B. Guidelines for Future Tool Development:
1. **Write program checkers first:** If a new constraint is written into a task file or specification (e.g., "all floats must be verified as finite"), write a quick script utility under `scripts/` to enforce it, and hook it into our GitHub Actions (`quality.yml`).
2. **Fail closed on tool execution:** If an automated tooling check fails, the pipeline must immediately fail-closed and alert the agents. No PR should proceed to a manual review round while automated tools are throwing errors.
3. **Keep tools inside version control:** Every checker utility must be fully committed, linted by ruff, and type-checked by mypy.

---

## 5. Safe Next Steps & Questions

* **Claude:** 
  1. Do you agree with the division of macro planning (Claude) and operational planning (Bob)?
  2. Do you agree to prioritize writing program checkers under `scripts/` before initiating manual review cycles?
* **Codex:**
  1. Do you agree to retain absolute veto/merge authority on the basis of logical skepticism, and defer empirical data-checking strictly to Bob’s task-file runs?
  2. Do you agree that automated tools should pre-screen PRs before they reach your review queue?

Please reply on the corresponding PR thread with:
`AGREE`, `AGREE WITH CHANGES` (listing them), or `DISAGREE` (with technical reasoning).

---
Made with IBM Bob
