# Claude → Bob and Codex: spec v1 amendment 1 implemented (drawdown recovery), engine `drawdown-recovery-v1`, schema 6

Index: 2026-09-28: the code for spec v1 amendment 1 (owner decisions of 2026-09-27 on PR #102): a soft-drawdown episode rebases `risk_high` after a 24 h cool-off and `recovery_frames` confirmations; a `drawdown` halt restarts by itself 24 h after it began, once the liquidation is complete, with a recovery pause; the halt's start and one of four categories are captured once on the transition; the manual `resume()` admits a residue below the exchange minimum (reversing PR #122's exact-zero rule, as the amendment decided); the C1(b) reference (`measure_high`) is scaled at settlement and never rebased. Engine `drawdown-recovery-v1`, paper schema 6 refusing 1 to 5, both cool-offs in the policy identity. 20 new tests, the spec's required list; the owner's principle restated on 2026-09-28: after a loss the bot pauses at most a day, then trades again, whatever is left. No run of any variant.

- **Date:** 2026-09-28. **Author:** Claude (session `012TnmLL`). **Branch**
  `claude/amendment-1-drawdown-recovery` on `main` at `eb66218` (PR #89 merged). The PR
  comment names the head.
- **Owner instruction, 2026-09-28 (chat):** "if a trade is made that loses money what
  needs to be done next is another trade ... the bot needs to continue trading after
  max 12 hours or a day." The recorded decision (spec §3, amendment 1) says 24 hours for
  both cool-offs; this PR builds 24 hours as the default and puts both values in the
  policy (`soft_cooloff_seconds`, `hard_cooloff_seconds`, persisted in the account
  identity), so a change to 12 hours is one setting, to be fixed before any registered
  run under the no-tuning rule. The owner has not asked for 12; 24 stands.
- **Scope.** `simulation/models.py`, `simulation/runner.py`, `backtest/replay.py`, five
  documents, one new test file and four test fixtures. No dataset spec, manifest,
  parameter or acceptance criterion is touched. Nothing was run on real data.

## What the spec says, and where the code does it

| Spec (§3 "Drawdown recovery") | Code |
| --- | --- |
| State: episode start, halt start and category, C1(b) reference | `Account.episode_since`, `episode_count`, `halt_since`, `halt_category`, `measure_high`; validated (`HALT_CATEGORIES`, a category iff a halt, no episode during a halt). Saved in schema 6; `control.py` refuses other schemas by the existing identity check. |
| Category set where the halt is raised, four values, never inferred from text; emergency before drawdown | `_risk_action` (`EMERGENCY` if the flag, else `DRAWDOWN`), the `ValueError` handler (`INTEGRITY`), the exhaustion site (`EXHAUSTION`). |
| Captured once on the not-halted to halted transition; later calls change nothing but orders and the exit arm | `_halt`: the identity block runs only when `account.halt` is empty. Tests: an invalid frame during a `drawdown` halt keeps its identity; a 12% fall during an `integrity` halt keeps `integrity`. |
| C1(b) reference: initial capital; `max` at every mark; scaled at settlement in the same statement as `risk_high`; never rebased or restarted; equals `risk_high` without either | `Account.start`, `_mark`, `_settle` (`account.measure_high *= factor` beside `risk_high`), and neither `_rebase` nor `_restart` touches it. Test with the risk observer: equal at every evaluation across a settlement. Replay's `active_max_drawdown_pct` now uses it; the observer signature gained the reference. |
| Soft drawdown 1: the first `REDUCE` outside an episode starts one | `_risk_action`, after the pause. |
| 2: each valid frame, before other changes: 24 h, `recovery_frames` confirmations with the tentative `ALLOW`, reset on gap, transient frame and ineligible frame, not halted | `_rebase`, called right after the mark and before the risk check; `episode_count` reset in the gap branch, the `TransientFrame` handler and on any non-confirming frame; `_tentative_allow` evaluates the engine with `risk_high` set to the current equity, without the observer. |
| 3: tentative rebase committed only on `ALLOW` | The confirmation is that evaluation; the commit needs it on the committing frame. |
| 4: runs first in the step; range-exit and pause rules then apply unchanged | Order in `_step`; test: a range exit waiting in cash is released on the rebasing frame. |
| 5: one rebase per episode; ends on any halt; new `REDUCE` starts a new one with its own cool-off; process restart restores it; recorded | `_rebase` clears the episode; `_halt` clears it; tests for each; `report["rebase"]` with time, old and new reference, episode start. |
| Hard drawdown: only `drawdown` restarts; emergency and integrity latched; exhaustion final | `_restart` returns early for any other category. Tests: an integrity halt does not restart after a day. |
| Preconditions 1 to 3, read after the liquidation attempt; "flat" is liquidation-complete; dust admitted | `_restart` after `liquidate` in the halted branch: cool-off from `halt_since`, no orders, `exit_state` not `incomplete`, eligibility, `account.validate`, tentative `ALLOW` (the emergency flag blocks it). Tests: thin book blocks, deep book restarts on the completing frame; the flag blocks while set. |
| Changes exactly the resume fields; pause "automatic restart after drawdown halt"; never the daily baseline, C1 references, reserves, vault | `_restart` sets exactly those; the settlement is deferred to the next frame (`restarted` skips the harvest on the restart frame) so the restart frame changes nothing else. Test diffs the saved state against the allowed set. |
| At most one restart per instance; a later fall is a new instance | The identity is cleared at the restart and captured again at the next transition. Test. |
| Recorded | `report["restart"]` with halt start, category, reason, old and new reference. Replay counts `drawdown_restarts` and `soft_drawdown_rebases`; `hard_drawdown_halts` counts instances (transitions), no longer "at most one". |
| Manual `resume()`: refused while incomplete, admitted with dust; risk check unchanged | `resume()` uses `exit_state`; the refusal text says the halt restarts by itself. Tests: dust resumable (an integrity halt), incomplete still refused, a drawdown halt still refused by hand. |
| Parameters: 24 h and 24 h, config values in the identity | `SimulationPolicy.soft_cooloff_seconds`, `hard_cooloff_seconds`, positive integers, in `identity()`. |
| Two versions: successor engine version, schema 6 | `ENGINE_VERSION = "drawdown-recovery-v1"`, `SCHEMA = 6`; the spec's "Two versions" bullet names them. |

## Tests (`tests/test_drawdown_recovery.py`, 20)

Soft drawdown: episode start and no rebase before 24 h; a trigger at 23:59:59 waits a
full day; no rebase under a daily pause, an emergency (which ends the episode) or a data
block; an ineligible frame resets the confirmations; one rebase per episode and a later
`REDUCE` starts a new one; a process restart before and after the rebase; a range exit
waiting in cash is released by the rebase. Measurement: the C1(b) reference equals
`risk_high` at every evaluation in a run without a rebase, across a settlement; it is
never rebased or restarted. Hard drawdown: restart after 24 h with the recovery pause;
the restart changes only the listed fields; incomplete liquidation blocks, dust admits;
the emergency flag blocks while set; one restart per instance, a new fall is a new
instance; only `drawdown` restarts; an invalid frame keeps the halt identity; the
restart is journaled and idempotent across a process restart. Manual resume with dust;
policy validation; account validation of the halt identity.

Existing tests changed: four fixtures that set `account.halt` directly now set the
category; the schema pin is 6 and schemas 1 to 5 are refused; "a hard-drawdown halt is
final" became "says it restarts by itself"; "a halt holding only dust stays halted"
became "is resumable" (the rule the amendment reversed); the replay summary's field set
gained `soft_drawdown_rebases` and `drawdown_restarts`.

## Verification

Preflight green on Linux, Python 3.12.3: ruff, format, mypy (42 source files), bandit,
`check_reports` 0 problems, the full pytest suite. No real-data replay: the amended V0
has not been run, by design (the spec's "Two versions": running it is a registered
trial).

## Open for review

1. The confirmation count for a rebase (`episode_count`) is a new field rather than
   `recovery_count`, because every `REDUCE` frame re-pauses and resets `recovery_count`
   today; the spec's "the normal `recovery_frames` confirmations" is implemented with
   the same length and the same resets on a counter that the pause path cannot reset.
2. A restart's settlement is deferred to the next frame so that the restart frame
   changes only the listed fields. The spec allows either reading ("the settlement of a
   held dust residue takes the drain-and-settlement path a resumed account takes
   today"); this is the one that makes the side-effect test exact.
3. A tentative evaluation is not reported to the risk observer, so replay's
   `risk_evaluations` counts only the engine's real evaluations (P2's wording).
4. The 24-hour values are the recorded decision; the owner's "max 12 hours or a day" of
   2026-09-28 is compatible and is not a change request unless the owner says so.
