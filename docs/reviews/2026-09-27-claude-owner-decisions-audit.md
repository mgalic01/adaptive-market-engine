# Owner decisions on the 2026-09-27 audit proposals

- **Date:** 2026-09-27
- **Decided by:** the owner (mgalic01), in a Claude Code session; recorded by Claude.
- **Context:** the full audit found eight issues that needed a proposed fix before any
  code changed. One agent per issue proposed a fix; Claude put the five questions below
  to the owner. The owner's answers are quoted exactly.

| # | Question | Owner's answer | Where it is applied |
| --- | --- | --- | --- |
| 1 | May the paper account settle profit and open new grids while it holds a remainder worth less than one minimum order, which no exchange would let it sell? | "yes that is acceptable" | PR #122: `execution.exitable`, `PaperSimulator._resolved`; `docs/PAPER_SIMULATION.md` |
| 2 | That fix moves published V0 replay results. What happens to the old ones? | "keep the old results published and count the fixed version as an extra registered trial." | PR #122: `engine_version` `exit-residue-v1` in every summary and `results.json`; spec C7 counts it in `N_family` |
| 3 | Replace the deflated Sharpe ratio with a Holm step-down and make it gate the reserved-window run (C7)? | "ok" | `EXPERIMENT_SPEC_V1.md` §6, C7 — recorded as **adopted in principle, not yet binding**: Codex's review of 2026-09-27 showed the series is undefined, the family size is only a floor, and the other two agents must acknowledge retiring the DSR. The owner's decision stands; the specification is open. [coherence record](2026-09-27-claude-dsr-coherence.md) |
| 4 | Approve a paid Bob re-run for the defect calendar? | "i approve al paid bob reruns because bob has a huge pool of credits., dont save on bob, he has more credits then both Clode and Codex combined." | Standing approval for paid Bob runs. First uses: [combined defect census](../tasks/2026-09-27-bob-combined-defect-census.md), [rescued-month masking](../tasks/2026-09-27-bob-rescued-month-masking.md) |
| 5 | Approve pinning Python 3.12 in the Bob workflows? | "I approve." | PR #122: `bob-task.yml` publish job, `bob-review.yml` |

## What these do not change

- A Bob task still starts only when its task file is merged after review; answer 4
  removes the cost question, not the review.
- Answer 3 adopts C7 in principle. Its family size, return series and the other agents'
  acknowledgment are all open (spec §6, C7), so it cannot be computed yet. Because the
  owner's decision was that a multiple-testing test gates the reserved run, an unresolved
  C7 **holds that run closed** rather than letting it proceed under C1–C6; C1–C6 remain
  the binding set for development selection.
- Paper-only, no API keys, the reserved window, and the no-tuning rule are unchanged.

## Still open with the owner

- PR #102: the policy after the soft-drawdown lockout (options B, C or D) and the
  no-tuning waiver its 24-hour cool-off needs. Its flat-stretch evidence is corrected on
  that PR: "235 days" means "at least until the data ran out".
- Freezing spec v1.
- The merge rule, including whether Claude may merge its own work.
- The record of the 2025-01 format inspection.
