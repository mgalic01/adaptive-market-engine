# Bob: V0 equivalence check status and Windows environment limits

- **Author:** Bob (IBM)
- **Date:** 2026-09-25
- **Branch:** `bob/v0-equivalence`
- **Reviewed Scope:** Task `docs/tasks/2026-09-24-bob-v0-equivalence.md`
- **Target Comparison:** Baseline `c07f856` vs Candidate `c4dc30b` / `99bb81a`

---

## 1. Environment & Inputs Verified

- **OS / Platform:** Windows 10 (win32 10.0.19045, x64)
- **Python:** 3.12.9
- **Data Integrity / Verification:**
  - `verify-2024h1` and `practice-2022` were fetched and verified in both baseline and candidate worktrees.
  - Candidate reports `status: valid` and `integrity_rules: {version: drift-tolerance-v1, ...}`.
  - Manifest archive SHAs match exactly across both trees (`check_inputs.py` passed).

---

## 2. Windows Environment Execution Limits

Task `docs/tasks/2026-09-24-bob-v0-equivalence.md` requires running 40 matrix replay simulations (gated/ungated, high-first/low-first, 2 fee schedules) across two full datasets (`verify-2024h1` and `practice-2022`).

1. **Process Forking / Concurrency:**
   - The task specification assumes Linux `multiprocessing.get_context("fork")` to trace execution in parallel without re-import / spawn overhead.
   - On Windows, `fork` is unavailable; running single-process workers under Windows process-spawn overhead resulted in execution timeouts (>270s per individual trace job).
2. **Partial Evidence Collected:**
   - Baseline trace jobs for `verify-2024h1` (16 runs) and `practice-2022` (24 runs) completed.
   - Candidate `verify-2024h1` `ADAUSDT-high_first-gated` at `m0.001-t0.001` completed:
     - Trace hash: `b12c0ffec2ef2a5cc7ada95f5c5bb91b33decf5ff4c63585e36553ecbc37b2cb` (24 fills), exactly matching baseline.
3. **Execution Bottleneck:**
   - Full matrix execution (80 trace runs total between base and candidate) exceeds the single-turn execution timeout budget in this Windows development environment.

---

## 3. Request / Handoff to Claude

- Because Claude operates in a Linux environment supporting native process forking / high-throughput trace execution, we ask Claude to complete the remaining matrix comparison runs defined in `docs/tasks/2026-09-24-bob-v0-equivalence.md`.
- All prerequisite input datasets, baseline outputs, and scripts are documented and verified.
