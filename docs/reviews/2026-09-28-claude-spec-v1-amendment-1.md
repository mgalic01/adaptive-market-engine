# Claude → Codex and Bob: spec v1 amendment 1, drawdown recovery

- **Date / writer:** 2026-09-28 (the owner's local date; 2026-09-27 about 23:00 UTC).
  Claude, Claude Code desktop session `a05e63c8`, on branch
  `claude/spec-v1-drawdown-amendment`.
- **What this is.** The scoped spec amendment that PR #102 §5 requires before any code
  or rerun. It turns the owner's 2026-09-27 decisions into spec text. It changes two V0
  controls, the soft-drawdown reduction and the hard-drawdown halt, and nothing else.
- **Authority.** The owner's decisions, relayed verbatim on PR #102 by session
  `e0b16be3`: option C; a fully automatic restart after a hard-drawdown halt; no loss
  floor; no capital threshold; the no-tuning exception granted on record for both
  controls. The analysis and review history are in
  [2026-09-27-claude-soft-drawdown-lockout.md](2026-09-27-claude-soft-drawdown-lockout.md)
  (PR #102, revision 5 at `fd66a25`, where Bob gave NO ISSUES and the automated review
  approved).
- **Codex could not review the last two points.** Codex reached its usage limit. The
  owner asked Bob to confirm them instead. Bob's answer on #102 at 22:36 UTC:
  - H = 24 h is acceptable, anchored to the halt's `observed_at`;
  - integrity halts stay latched and manual;
  - the halt reason must become a structured field, because `Account.halt` is free text
    today.

  All three are in the amendment. Codex's review of this amendment is still owed when
  its allowance returns.

## What changes in `docs/EXPERIMENT_SPEC_V1.md`

The six contents that PR #102 §5 requires, and where each one is:

| Required content | Where |
| --- | --- |
| 1. Both controls, word for word, with every parameter fixed | §3 "Drawdown recovery (amendment 1)": the soft path, the hard path, and parameters 24 h / 24 h |
| 2. Identical in every grid variant; the same control, not the same effect | §3 common rule (amended in V0 itself, so every variant inherits it); "Same control, not same effect" |
| 3. C6 compares against the amended V0 | "Same control, not same effect": the amended ungated V0 |
| 4. Pre-change results published; both V0 versions registered as trials | §3 V0, "Two versions" |
| 5. Supersede §3's "No variant delays, suppresses or clears" and the latched-halt statement for these two controls only; update `PAPER_SIMULATION.md` | §3 common rule, new paragraph; header risk-limit sentence; `PAPER_SIMULATION.md` pending-change note |
| 6. The halts that stay latched | "Hard drawdown": categories `emergency`, `exhaustion` and `integrity` |

**Two consequences that PR #102 did not spell out, added here:**
- **C1(b)'s reference (§6).** C1(b) measured against "the runtime's reserve-adjusted
  `risk_high`". Under option C that value is rebased, so C1(b) now uses a separate
  **measurement reference**. It follows `risk_high` exactly, including settlement
  scaling and new highs, but is never rebased. P2 records it. C1(a)'s total-equity peak
  is stated as never scaled and never rebased. Without this, the rebase would silently
  weaken the owner's 10% acceptance limit.
- **The halt category** is a four-valued field (`drawdown`, `emergency`, `exhaustion`,
  `integrity`), set where each halt is raised, never parsed from text. If the emergency
  flag and the hard drawdown are true together, the category is `emergency`, matching
  the risk engine's order.

`docs/PAPER_SIMULATION.md` gets a pending-change note under its recovery table. The table
keeps describing the code until the implementation PR changes both.

## Revision 2: Bob's two concerns at `784f411`

Bob FLAGGED the first head with two concerns, and both are fixed.

| Bob's concern | Change |
| --- | --- |
| The automatic restart clears the halt "as `resume()` clears it today", so any other state `resume()` resets would be cleared too | The restart now lists exactly the fields it changes. These are the same ones `resume()` changes on `main`: `halt`, `liquidating`, the range-exit state and timers, the grid bounds, `risk_high` (the committed rebase), the halt start and category, and a recovery pause. It states what it does not touch: the daily baseline, both C1 references, the reserves and the vault. The emergency flag is a per-frame signal, not account state, so nothing can clear it. A test for the side effects was added |
| The C1(b) reference is defined only by reference to `risk_high` | A standalone definition with three update points: creation (initial active capital, as `Account.new`), every mark (`max(reference, last_equity)`, as `_mark`), and every settlement (the same factor as `_settle`). An equivalence test was added: with no rebase or restart, the reference equals `risk_high` at every evaluation, which catches any later drift |

#102 merged at `fd66a25` (Bob NO ISSUES, automated APPROVE, green), so its decision
record is on `main`. This branch merges that `main`; only the index conflicted, and every
row is kept.

## What this does not do

- No code. The implementation follows as its own PR, with the tests listed under
  "Tests required before any rerun".
- No rerun, and no market data opened. Nothing from 2025 or later.
- The spec header still says DRAFT, not yet frozen. This amendment does not freeze it.

## Verification

- `python scripts/check_reports.py`: 0 problems. `pytest`, `ruff`, `ruff format --check`
  and `mypy` were run on this branch; the results are in the PR comment for this head.
- Code facts checked against `main` `8a45cb5`:
  - halts are raised with free-text reasons at three call sites in
    `simulation/runner.py` (`_risk_action`, the `ValueError` handler, and capital
    exhaustion in `_step`);
  - the risk engine checks the emergency flag before the hard drawdown
    (`risk/engine.py`).
- Not checked: whether the implementation can keep the C1(b) reference and `risk_high`
  byte-identical for pre-amendment runs. That is the implementation PR's equivalence test.

Rollback: revert this PR. It changes documentation only.
