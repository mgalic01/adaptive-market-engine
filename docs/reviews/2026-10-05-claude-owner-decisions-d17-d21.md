# Owner decisions D17–D21: manual resume, the exhaustion halt, and the V2 structure layer

Index: **Owner decisions, 2026-10-05.** D17: after an emergency or integrity halt, a manual resume works like the automatic restart at any depth. D18: an exhaustion halt is refused by name. D19: V2's FTA cap is replaced by sell-at-resistance, a V2 trial. D20: V2's rules and settings are frozen before any V2 result counts, and V2 stays out of v1's selection. D21: swing highs stay strict, and the rule is written down.

- **Date and author:** 2026-10-05, written by Claude (session `b9db01ca`).
- **Owner:** gave the choices below in Claude's session on 2026-10-05, shortly before 08:00 UTC.
- **Where the questions came from:** Claude's strategy audit (`docs/reviews/2026-09-29-claude-strategy-audit.md`, the decision table and sections D17–D21). Bob's handoffs, issues #161 and #162, listed all five as open.
- **Scope:**
  - D17 and D18: the paper runner's `resume()`, the spec and `docs/PAPER_SIMULATION.md`.
  - D19: V2 code that runs only with `--structure`.
  - D20 and D21: `docs/STRUCTURE_PREREGISTRATION.md` and a test that pins it.
  - **V0 replay results do not change.** Replay never resumes, and V2 is off by default.

## What the owner decided, in the owner's words

The owner asked Claude to "start building" D17–D21 (2026-10-05, about 07:18 UTC). Because these were the owner's decisions, Claude put them to him as four multiple-choice questions, each with Claude's recommendation first. Below are the selections, with the text of the chosen option.

1. **D17.** Question: "after an integrity or emergency halt with the account 8% or more below its peak, a manual resume is refused forever today, while a real 12% crash restarts by itself after a day. What should a manual resume do?"
   - Chosen: **"Allow, any depth"**, Claude's recommendation.
   - Option text: "After you check what happened, a manual resume works like the automatic restart. The safety stops re-measure from the current balance, the scorecard (C1) still counts from the original peak, and it stays blocked while the emergency signal is on or the day's loss is 3%+. This also lifts the spec's 'stays refused past 12%' rule for emergency halts. Backtest results don't change."
2. **D19.** Question: "the 'cap sell targets below resistance' rule never actually moves a sell order. It mostly stops grids from opening, and gives the wrong reason when it does. What should it become?"
   - Chosen: **"Build sell-at-resistance"**. Claude had recommended removing the rule for now.
   - Option text: "Redesign so sell targets sit just below the nearest resistance (raised or lowered to it), as you described on 29 September. A new V2 grid design, registered as a trial."
3. **D20.** Question: "one V2 rule was chosen after looking at backtest results (results we now know were invalid). How should V2 count as evidence?"
   - Chosen: **"Freeze V2 first"**, Claude's recommendation.
   - Option text: "Write down and pin every V2 rule and setting now. V2 results count only after that. V2 stays out of v1's selection, so v1's trial count is unchanged, and goes into your planned post-v1 spec v2."
4. **D18 and D21.** Question: "both would follow what you've already written. OK to do them that way?"
   - Chosen: **"Yes, both"**, Claude's recommendation.
   - Option text: "D18: an 'out of money' halt is refused by name, as the spec says (today it's refused only by accident). D21: swing highs stay strict, 'higher than N bars on each side' as in your own definition, and this gets written down. Only flat tops within 3 bars are missed."

5. **The V2 zone width,** asked after the agent building D20 found that the owner's 29 September record says swing points "within one ATR" merge into a zone, while the code merged them within 0.5 ATR. Claude explained what each value does, with no results. Question: "Which should be frozen?"
   - Chosen: **"Use 1.0"**, Claude's recommendation.
   - Option text: "Your original design: wider, fewer zones, sell targets more conservative inside a resistance cluster, fewer skipped buy levels. I change the default and the freeze; V2 only."

Options the owner did not choose:
- D17: "Allow, 8–12% only" and "Keep them final".
- D19: "Remove it for now" and "Explicit 'no grid' veto".
- D20: "V2 stays exploratory" and "Freeze V2 into v1".
- Zone width: "Keep 0.5".

## What follows from each decision

- **D17:**
  - Preconditions: a manual resume of an `emergency` or `integrity` halt keeps every existing precondition.
  - Risk check, case 1: if the plain risk check allows the resume, nothing changes.
  - Risk check, case 2: if the plain check refuses only because of drawdown, at any depth, the resume applies the automatic restart's tentative ALLOW. It is still refused while the emergency flag is set or the day's loss is 3% or more.
  - What a successful resume does: it rebases the runtime safety reference `risk_high` to current equity and journals the rebase, as the restart does.
  - What it does not change:
    - C1's drawdown is measured from equity peaks in the results, not from `risk_high`.
    - A `drawdown` halt is unchanged: a manual resume does not bypass the 24-hour automatic restart of Amendment 1.
- **D18:** `resume()` refuses an `exhaustion` halt by name, before any risk check. Spec and code now agree.
- **D19:** the FTA cap is removed. When a grid opens under `--structure` in a RANGE market, the grid's levels and spacing stay V0's, and each buy level's sell target follows the nearest resistance above it, on any timeframe and at any distance:
  - a zone within its timeframe's search radius (5 ATR) sets the target just below it (× 0.999, floored to the tick), raising or lowering it;
  - a zone beyond reach can only lower a target, so no target ever sits at or above a known resistance;
  - with no zone above, the target is the normal grid level.
  - A level whose moved target cannot clear costs gets no buy order, and every order keeps V0's size.
  - Targets are fixed at grid open, from completed bars only.
  - The rules are in `docs/STRUCTURE_PREREGISTRATION.md` (rules 3, 9, 13 and 14).
- **D20:** `docs/STRUCTURE_PREREGISTRATION.md` lists every V2 rule and parameter with its value. A test fails if any of them changes.
  - V2 results count only after that document merges.
  - V2 is not part of v1's selection, so v1's `N_family` is unchanged. The document will be folded into the post-v1 spec v2.
  - Every V2 run inspected so far is listed there as a prior trial whose results do not count.
- **D21:** a swing high must be strictly higher than `swing_n` (3) bars on each side. Equal highs within 3 bars of each other (a flat top) are not swings; equal highs further apart each are. This is written into the pre-registration and the code's docstring.

## Still open

D19's details are Claude's reading of the owner's 29 September description, from his words and from risk logic, never from results. They are open to the owner's, Bob's and Codex's review:
- the nearest resistance on any timeframe counts, and every known zone caps;
- the search radius only limits raising;
- zone strength is not used;
- a skipped level enlarges no other order;
- the grid's upper bound includes a raised target.
