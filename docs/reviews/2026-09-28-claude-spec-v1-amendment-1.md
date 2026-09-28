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

## Revision 3: the automated review at `fb2c43d`

| Finding | Change |
| --- | --- |
| Required: a soft episode that is open when a hard halt starts was undefined. If it survived, its stale 24-hour cool-off would already be satisfied at restart, merging the two separate waits | Soft path, step 5: any halt ends the open episode and clears its start. The restart's field list says no episode is open afterwards. A new test covers the case, and the same rule applies after a manual resume |
| Nit: broken parenthesis in the header's risk-limit sentence | Reworded |

Bob gave NO ISSUES at `fb2c43d` before this finding, so his verdict does not cover
revision 3.

#102 merged at `fd66a25` (Bob NO ISSUES, automated APPROVE, green), so its decision
record is on `main`. This branch merges that `main`; only the index conflicted, and every
row is kept.

## Revision 4 (2026-09-28, session `012TnmLL`): re-checked against `main` after PRs #122 and #123

Bob gave NO ISSUES at `28b7ed7`. Since then #122 (engine `exit-residue-v1`) and #123
merged, and #122 changed the code this amendment leans on. Re-checked against `main`
`ad98f7b`:

| What #122 changed | Effect on the amendment | Change |
| --- | --- | --- |
| `_settle` now puts the marked residue on both sides of the rescaling factor | The C1(b) reference's settlement step gave the old plain ratio; applied literally, it would drift from `risk_high` and fail its own equivalence test | Step 3 now states the current formula and binds the reference to whatever `_settle` computes, in the same statement as `risk_high` |
| `resume()` requires **exact zero** inventory, because a hard-drawdown halt was final | The restart inherited "every precondition of `resume()`", so a `drawdown` halt holding a dust residue could never restart or be resumed: a new lockout, the thing this amendment removes | Restart precondition 2 now defines "flat" as PR #122's *liquidation complete*: no exitable inventory (`exit_state` not `incomplete`); a dust residue stays held and marked. The manual `resume()` keeps exact zero, since it still protects the final halts. A test case is added. **This is a design choice made here, for Bob's, Codex's and the owner's review**; it follows the owner's 2026-09-27 acceptance of trading and settling with a residue held |
| `PAPER_SIMULATION.md` now says twice that a drawdown halt is final | The pending-change note did not say which statements it supersedes | The note names the two, and says what stands: emergency's conditional resume, exhaustion's finality, integrity's manual resume, and the manual resume's exact-zero rule |
| `_halt` gained `exit_requested`; the validation halt now arms liquidation | None: still three call sites (`_risk_action`, the `ValueError` handler, capital exhaustion), so the category is set at the same three places | None |

Also: the restart's field list now notes that the observation timestamps and the mark
are recorded by every valid step anyway; and the "Two versions" note says that the
amended V0 runs on `exit-residue-v1` and is the one extra V0 trial that #123's
`N_family` already counts, unless the un-amended fixed V0 is also run.

Merged `main` into the branch; only the index conflicted, and every row is kept. Code
facts above were read from `simulation/runner.py` on `main` `ad98f7b`.

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
