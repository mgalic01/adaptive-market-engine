# Documentation audit report (links, indexes, stale statements, rules)

- **Task:** [`docs/tasks/2026-09-25-bob-docs-audit.md`](../tasks/2026-09-25-bob-docs-audit.md)
- **Commit:** `876f7ce9d3a32b4a31bc558a0eb038a462c1472e`
- **Author:** IBM Bob (task run)
- **Date:** 2026-09-25

---

## 1. Execution Summary and Scripts

All helper scripts were written to `data/` and executed using Python 3.12 (standard library only).

| Script | SHA-256 | Exit Code | Description |
| --- | --- | --- | --- |
| `data/links.py` | `0bb844577884ecb1e9eb10c9d7a2faaa05161680ff1ff2851ee83fcf6450a80e` | 0 | Markdown relative link and GitHub heading anchor checker |
| `data/check_review_index.py` | `ca5350088f3b54bbfc75b12963054a2c0017884ae091942253ce839c0d8c186c` | 0 | Review files disk vs `docs/reviews/README.md` cross-checker |
| `data/check_task_index.py` | `1279a2e647ff8a63d31f22fecd729f85c4e5b632121e7a3c70658c571c306782` | 0 | Task status in `docs/tasks/README.md` vs git history checker |

---

## 2. Findings by Step

### Step 1: Links and Anchors

- **Markdown files inspected:** 68 tracked files (plus report file)
- **Total Markdown links checked:** 182
- **Broken relative links found:** 0
- **Absolute HTTP(S) links to repo (`github.com/mgalic01/...`):** 22

#### Broken Relative Links
None (0 broken links found).

#### Repository HTTP(S) Links
The following 22 links reference the repository via absolute HTTP(S) URLs rather than relative Markdown links or issue/PR numbers:

| File:Line | Target URL | Link Text | Suggested Fix |
| --- | --- | --- | --- |
| `docs/reviews/2026-09-24-claude-team-list-fixes.md:6` | `https://github.com/mgalic01/crypto-grid-bot/pull/16` | PR #16 comment | Keep as historical external reference or convert to PR note |
| `docs/reviews/2026-09-24-claude-three-agent-proposal.md:45` | `https://github.com/mgalic01/crypto-grid-bot/pull/16#issuecomment-5823521558` | comment 5823521558 | Historical record link |
| `docs/reviews/2026-09-24-claude-three-agent-proposal.md:46` | `https://github.com/mgalic01/crypto-grid-bot/pull/16#issuecomment-5823174687` | comment 5823174687 | Historical record link |
| `docs/reviews/2026-09-24-codex-experiment-spec-review.md:3` | `https://github.com/mgalic01/crypto-grid-bot/pull/16` | #16 | Historical record link |
| `docs/reviews/2026-09-24-codex-fee-measurement-review.md:5` | `https://github.com/mgalic01/crypto-grid-bot/pull/14` | #14 | Historical record link |
| `docs/reviews/2026-09-24-codex-historical-replay-review.md:297` | `https://github.com/mgalic01/crypto-grid-bot/actions/runs/35994466940` | 35994466940 | Actions run link |
| `docs/reviews/2026-09-24-codex-historical-replay-review.md:299` | `https://github.com/mgalic01/crypto-grid-bot/actions/runs/35994466794` | 35994466794 | Actions run link |
| `docs/reviews/2026-09-24-codex-replay-fixes-verification.md:13` | `https://github.com/mgalic01/crypto-grid-bot/pull/12` | #12 | Historical record link |
| `docs/reviews/2026-09-24-codex-replay-fixes-verification.md:16` | `https://github.com/mgalic01/crypto-grid-bot/pull/11` | PR #11 | Historical record link |
| `docs/reviews/2026-09-24-codex-replay-fixes-verification.md:149` | `https://github.com/mgalic01/crypto-grid-bot/actions/runs/35997701356` | quality run 35997701356 | Actions run link |
| `docs/reviews/2026-09-24-codex-replay-fixes-verification.md:204` | `https://github.com/mgalic01/crypto-grid-bot/actions/runs/35999203599` | GitHub quality run 35999203599 | Actions run link |
| `docs/reviews/2026-09-25-claude-v0-equivalence-results.md:7` | `https://github.com/mgalic01/crypto-grid-bot/blob/bob/v0-equivalence/docs/reviews/2026-09-25-bob-v0-equivalence-status.md` | Bob's status | Historical branch file link |
| `docs/reviews/2026-09-25-codex-event-driven-reviews.md:49` | `https://github.com/mgalic01/crypto-grid-bot/pull/18#issuecomment-5830388266` | the request | Historical comment link |
| `docs/reviews/2026-09-25-codex-pr19-review.md:17` | `https://github.com/mgalic01/adaptive-market-engine/pull/19#issuecomment-5831428546` | his reproduction | Historical comment link |
| `docs/reviews/2026-09-25-codex-pr19-review.md:58` | `https://github.com/mgalic01/adaptive-market-engine/pull/19#issuecomment-5831975456` | Claude's separate v2 proposal | Historical comment link |
| `docs/reviews/2026-09-25-codex-pr20-review.md:13` | `https://github.com/mgalic01/adaptive-market-engine/pull/20#issuecomment-5834901842` | the reviewed head | Historical comment link |
| `docs/reviews/README.md:58` | `https://github.com/mgalic01/crypto-grid-bot/pull/7` | #7 | Historical PR link |
| `docs/reviews/README.md:59` | `https://github.com/mgalic01/crypto-grid-bot/pull/9` | #9 | Historical PR link |
| `docs/reviews/README.md:60` | `https://github.com/mgalic01/crypto-grid-bot/pull/11` | #11 | Historical PR link |
| `docs/reviews/README.md:61` | `https://github.com/mgalic01/crypto-grid-bot/pull/12` | #12 | Historical PR link |
| `docs/reviews/README.md:62` | `https://github.com/mgalic01/crypto-grid-bot/pull/13` | #13 | Historical PR link |
| `docs/reviews/README.md:63` | `https://github.com/mgalic01/crypto-grid-bot/pull/14` | #14 | Historical PR link |

---

### Step 2: Review Index Integrity

- **Markdown files on disk in `docs/reviews/` (excluding `README.md` and this report):** 44
- **Total links in `docs/reviews/README.md` table:** 44 review links (plus 10 other links/PR references)
- **Unindexed review files on disk:** 0
- **Broken links in review index:** 0

All 44 review documents present on disk are correctly indexed in [`docs/reviews/README.md`](README.md).

---

### Step 3: Task Index Status vs Repository Evidence

- **Total task rows in `docs/tasks/README.md`:** 8
- **Outdated or unmerged task status entries:** 2

| File:Line | Task | Current Table Status | Evidence | Suggested Fix |
| --- | --- | --- | --- | --- |
| `docs/tasks/README.md:21` | `docs/tasks/2026-09-24-bob-v0-equivalence.md` | `Approved at 99996bc. Bob: inputs and 40 baseline traces on Windows; completed by Claude on Linux: 40/40 identical (results)` | The Linux re-run was completed by Claude, but the task was originally written for Bob. The subsequent task `2026-09-25-bob-v0-trace-hash-crosscheck.md` was completed by Bob and verified in `docs/reviews/2026-09-25-bob-v0-trace-crosscheck.md` (merged in commit `d58c0be`). | Status is accurate regarding Claude's completion; no fix required, but could explicitly note that Bob's crosscheck followed. |
| `docs/tasks/README.md:22` | `docs/tasks/2026-09-24-bob-p8-data-survey.md` | `Approved at 99996bc; done — report on bob/p8-data-survey (761b2ee)` | The report file is not merged into `docs/reviews/` on `main` (`git log --oneline -- docs/reviews/2026-09-24-bob-p8-data-survey.md` returns empty; file does not exist on `main`). | Update status note to clarify that the report remains on branch `bob/p8-data-survey` (`761b2ee`) and was not merged to `main`. |

---

### Step 4: Rules Documentation vs Workflow Implementations

Audit comparison across `docs/AGENT_HANDOFF.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `docs/tasks/README.md`, and `.github/workflows/*.yml`:

| File:Line (Doc) | Document Statement | File:Line (Workflow) | Workflow Implementation | Problem / Mismatch | Suggested Fix |
| --- | --- | --- | --- | --- | --- |
| `docs/AGENT_HANDOFF.md:12` | Bob's quick review: `reads the comment, PR description and diff, and docs/reviews/README.md; answers once. No commands, no files, no token` | `.github/workflows/bob-review.yml:14-15` | `permissions: contents: read, pull-requests: write, issues: write` | Document says "no files, no token", but workflow checks out repo (`contents: read`) and passes `GH_TOKEN` to `gh pr diff` and `gh pr comment`. Bob's process itself has no GH token, but the job does. | Clarify in docs: "Bob's process receives no GitHub token; the workflow runner checks out read-only files and posts the comment." |
| `docs/AGENT_HANDOFF.md:193` | "Bob: runs in the owner's session only, for a reviewed task file or an owner question." | `.github/workflows/bob-task.yml:25-34` | Triggers on push to `main` with new task file, `/bob-run` comment by owner, or `workflow_dispatch`. | Stale clause from before `bob-task.yml` automation was added. Contradicts lines 13 and 210-226 in same file. | Update line 193 to: "Bob: runs automated task workflows on GitHub Actions when a task file is merged to main or triggered via `/bob-run`, or runs in the owner's session." |
| `docs/AGENT_HANDOFF.md:235-236` | "Workflows may not open PRs in this repository (owner decision: grant nothing new), so the reply links the branch and Claude opens the PR after checking it adds exactly one report" | `.github/workflows/bob-task.yml:427-432` | `if url=$(gh pr create ...); then ... else echo "Could not open the PR..."; fi` | Workflow actually attempts `gh pr create` first, and falls back to linking branch if creation fails. | Align doc text: "Workflows attempt `gh pr create` with `GITHUB_TOKEN`; if GitHub settings block workflow PR creation, the workflow replies with the branch link and Claude opens the PR." |
| `AGENTS.md:32-33` | "They apply only after Codex and Bob have both explicitly agreed on PR #16 and it has merged." | `docs/reviews/2026-09-25-codex-pr16-final-review.md:1` | PR #16 was agreed and merged (`9678365` / `5811fce`). | Historical conditional statement remains in present/future conditional phrasing. | Update text to: "PR #16 has merged with Codex and Bob agreement; the Three Agents operating model is active." |
| `docs/AGENT_HANDOFF.md:168-170` | "**Status: in force only after both Codex and Bob have explicitly agreed in PR comments on the PR that adds this section (PR #16), and that PR has merged.**" | `docs/reviews/2026-09-24-claude-three-agent-proposal.md:44-48` | Both agreed and PR #16 merged. | Conditional phrasing is obsolete now that PR #16 is merged into `main`. | Update status to: "**Status: In force.** (Agreed on PR #16 and merged)." |

---

### Step 5: Internal Contradictions Between Documentation Files

| File:Line (Doc 1) | Statement 1 | File:Line (Doc 2) | Statement 2 | Contradiction / Stale Aspect | Suggested Fix |
| --- | --- | --- | --- | --- | --- |
| `docs/AGENT_HANDOFF.md:193` | "Bob: runs in the owner's session only, for a reviewed task file or an owner question." | `docs/AGENT_HANDOFF.md:210-212` | "Bob task runs on GitHub ... `bob-task.yml` lets Bob run a reviewed task file on a GitHub Linux machine with command access" | Line 193 says "runs in the owner's session only", but §"Bob task runs on GitHub" details the GitHub Actions task runner. | Amend line 193 to acknowledge GitHub Actions execution via `bob-task.yml`. |
| `AGENTS.md:31-33` | "A third agent, Bob, is proposed ... They apply only after Codex and Bob have both explicitly agreed on PR #16 and it has merged." | `docs/AGENT_HANDOFF.md:3-8` | "This is the single place for how the three agents (Claude, Codex and Bob) are started and how they reach each other." | `AGENTS.md` presents Bob as proposed pending PR #16 merge, while `docs/AGENT_HANDOFF.md` describes the active three-agent setup. | Update `AGENTS.md` line 31-33 to state that PR #16 is merged and Bob's task rules are active. |
| `docs/AGENT_HANDOFF.md:168-170` | "Status: in force only after both Codex and Bob have explicitly agreed in PR comments on the PR that adds this section (PR #16), and that PR has merged." | `docs/reviews/README.md:24` | `[Codex: PR #16 final merge review]` records final merge review and agreement. | Header in `AGENT_HANDOFF.md` still states the prerequisite as pending. | Replace pending condition with confirmation that PR #16 merged. |

---

## 3. Metric Counts Summary

| Audit Item | Count |
| --- | ---: |
| Tracked Markdown files checked | 68 |
| Total relative Markdown links checked | 182 |
| Broken relative Markdown links / anchors | 0 |
| HTTP(S) links to repo (`github.com/mgalic01/...`) | 22 |
| Review documents in `docs/reviews/` | 44 |
| Review files missing from `docs/reviews/README.md` | 0 |
| Broken links in `docs/reviews/README.md` | 0 |
| Tasks in `docs/tasks/README.md` | 8 |
| Task status discrepancy / clarification items | 2 |
| Workflow vs Documentation discrepancies | 5 |
| Internal documentation contradictions | 3 |

---

## 4. Ideas and Proposals

1. **Automated Markdown Link and Anchor Linter in CI:**
   - *Why:* Broken links and anchors previously caused missed communications between agents and manual repair commits.
   - *Implementation:* Integrate `data/links.py` into `.github/workflows/quality.yml` as `python data/links.py` or `python scripts/check_links.py`.
   - *How to test:* Run against PR diffs; fail if any relative file path or `#anchor` does not resolve to an existing heading.

2. **Automated Review Index and Task Index Validation:**
   - *Why:* When agents add new review handoffs or complete tasks, manual indexing can be omitted or status text can lag git history.
   - *Implementation:* Add a small test `tests/test_docs_indexes.py` that verifies `docs/reviews/` matches `docs/reviews/README.md` and that task files match `docs/tasks/README.md`.
   - *How to test:* Run with `pytest tests/test_docs_indexes.py` in `quality.yml`.

3. **Relative Markdown Link Enforcement for Repo URLs:**
   - *Why:* Links formatted as `https://github.com/mgalic01/...` break when branches are renamed or if viewed offline/in local clones.
   - *Implementation:* Enhance `data/links.py` with an optional `--strict` flag that flags in-repo HTTP(S) links when a relative link or PR reference format can be used instead.
