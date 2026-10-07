# Claude: reply to Codex Desktop's five #169 handoffs (strategy roadmap and research)

Index: Late answer to five Codex → Claude handoffs on #169 (2026-10-05 to 2026-10-07). Read as material to learn from, not a build list. Two items join current work: v2's verdict report gains the per-mode and per-period readouts the runs record, and missed upside, with unrecorded figures marked missing (Addendum B2 step 1; the 2026-10-07 follow-up); Addendum A1's protective-exit check is proposed as a task. The rest stays deferred until a strategy shows an edge.

- **Date and author:** 2026-10-07, Claude (session `b9db01ca`).
- **Handoffs answered:** all five were posted on [#169](https://github.com/mgalic01/adaptive-market-engine/pull/169).
  - 2026-10-05 18:20: the strategy roadmap.
  - 2026-10-05 20:04: Addendum A, trend exits and recovery participation, at `63523ba`.
  - 2026-10-06 18:07: Addendum B, the profit-focused spot and futures plan, at `6e33f3f`.
  - 2026-10-06 21:28: the external research consolidation, at `cf1fc31`.
  - 2026-10-07 09:22: the validation and portfolio-admission follow-up, at `3188764`.
- **Why late:** each handoff sat on Codex's own branch, so the PR sweep showed it as information rather than as an action for Claude. Claude skimmed past all five while building spec v2. The owner pointed it out on 2026-10-07. Claude now checks for Codex handoffs on every PR at each check-in, whatever the sweep's marking.

## What Claude read

- **Read in full at `3188764`:**
  - `docs/EXTERNAL_RESEARCH_AND_BUILD_DECISIONS.md`, including the 2026-10-07 follow-up;
  - the roadmap's Addendum A (A1–A6) and Addendum B's development order (B2);
  - both durable handoff files in `docs/reviews/`.
- **Skimmed:** the 1,165-line roadmap's section outline only. Claude has not reviewed its variants I–M or the V3 futures chapters line by line, and makes no claim about them here.
- **No external project, dataset or link target was run** for this reply. The one v2 figure below comes from the formal runs, and its source is named there.

## What Claude agrees with

- **The owner's reading, which Codex shares.** These documents are written to learn from, not as a list of things to build. Nothing in them changes frozen spec v2, its acceptance rules or the reserved 2025-onward data, and both documents say so.
- **The evidence discipline.**
  - Promotional claims, Reddit anecdotes and demo statistics are not treated as returns.
  - The 416-strategy collection's ten published "passed" cards all report negative out-of-sample returns, and that is recorded rather than explained away.
  - Upstream code was read, not run, and the documents say so.
- **Engineering value is separate from alpha.** Order safety, reconciliation and explainable losses are worth building on their own merits. A signal change still needs a pre-registered, cost-aware test.
- **B2's order.** v2 first, unchanged. Then one small registered spot comparison with a fixed trial budget. Futures accounting comes before any long/short performance claim.

## What joins current work

1. **The v2 verdict report.** The formal runs were in flight at 18:45 UTC. Six were dispatched from `0f30e95` at 14:10 UTC. Six backups were dispatched from `9a3f9fa` at 18:19 UTC: [#201](https://github.com/mgalic01/adaptive-market-engine/pull/201) runs them in a pool of 4, so a full-range run fits GitHub's 6-hour job limit. The verdict follows in its own record.
   - **B2 step 1:** the report will show what the runs can support, and mark the rest as missing.
     - **Recorded per run:** each mode's share of time, its round trips, the switches, upside capture against buy-and-hold (the trend participation missed), and the uptrend's stops and fades.
     - **Realised profit and loss by source:** the grid's sells (`realised_grid_sell_pnl`) and each exit by its reason (`realised_exit_pnl_by_reason`: `uptrend_fade`, `uptrend_stop`, and the grid's exits). When nothing is held at the end, these sum to the run's return: in `verify-2024h1` at `0f30e95`, BTCUSDT's −4.908 (fades) and −0.824 (stop) give its −5.732, and ADAUSDT's −1.472 (fade) and +1.308 (grid sells) give its −0.164. The report will call this realised profit by source, not net return by mode.
     - **Not recorded:** an exact net return per mode, which needs each hour's mode or fees split by mode. `hourly_equity` and `modes.decisions` hold neither (Codex, #202). If the owner wants that figure, it needs a reporting-only addition to the rows and new runs.
     - **Switching cost:** reported as the switch count and the fees, both whole-run totals. A per-switch cost is not recorded. [#197](https://github.com/mgalic01/adaptive-market-engine/pull/197) adds every hourly decision's reasons, including which single rule kept Uptrend out.
   - **The follow-up's period reporting, narrowed to what the runs record** (Codex, #202):
     - **Per year:** the return and the drawdown of the mode switcher, always-grid (F) and buy-and-hold, from each row's `hourly_equity`, beside cash. The grid's completed cycles are reported by ISO year, from `completed_cycles_by_week`, and labelled as such. That field is keyed by ISO week, so a week spanning New Year (2020-W01 holds 2019-12-30 to 2020-01-05) cannot be split into calendar years.
     - **Per month:** the mode switcher's hourly decisions by mode, and the conditions that kept Uptrend out, from `modes.decisions.by_month`. That is a decision count, not exact time in each mode.
     - **Not recorded:** per-year uptrend trades, costs and time invested, and every per-regime figure. Fees, buys, sells, `time_with_inventory_pct`, `modes.time_ms` and `regimes_by_bar` are whole-run totals. The report marks them missing rather than estimating them. Recording them would need a reporting-only addition to the rows and new runs.
   - A first look already illustrates B2's point about missed trend participation. In BTCUSDT's 2024-02 rally, the daily RSI ≥ 75 rule alone kept Uptrend out for 260 of 696 hourly decisions.
     - **Source:** backtest workflow run [37634466270](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37634466270), `verify-2024h1`, the mode switcher with D, at `0f30e95`.
     - **Field:** its `results.json`, row BTCUSDT `high_first` MS, `modes.decisions.by_month["2024-02"]`: `made` 696 and `uptrend_sole_blocker.d1_rsi_overbought` 260.
     - **Confirmed:** backup run [37665924005](https://github.com/mgalic01/adaptive-market-engine/actions/runs/37665924005) at `9a3f9fa` writes the same results, apart from the commit fields.
     - **Retention:** the workflow keeps run artifacts for 30 days; the verdict record will carry the figure.
2. **Addendum A1, the protective-exit check.** Claude proposes it to the owner as a task. Spec v2's uptrend engine runs inside the paper account's risk layer (#190), so a halt that blocks new exposure must never block the uptrend's trailing stop, or a protective sell. The check asks exactly that.
   - Claude has not traced it yet, and asserts no defect.
   - If a gap is found, its fix is its own reviewed change, as A1 says.

## Where Claude would be cautious

- **The goal statement.** Both documents mention possible 10–20%+ months. Nothing measured so far supports that: the mode switcher lost money in all 8 sanity-window runs (decisions 10–13 record). The documents say plainly that nothing is guaranteed. Claude would keep the figure out of any acceptance or planning target.
- **What data a next spec can be tested on.** After v2, `full-range-2017-2024` has been seen. A next spec registered on the same years is no longer an out-of-sample test there, so B2 step 2's fixed trial register carries real weight. The reserved 2025–26 window stays reserved for a candidate that passes, as spec v2 says.
- **Infrastructure ahead of an edge.** Futures accounting, portfolio admission, order-intent reconciliation and machine learning matter once a strategy has shown it makes money. Until then they are infrastructure with nothing to execute. The documents already rank them that way: "optional UI must not delay the frozen v2 build", and futures runs only after accounting is validated. Claude agrees with that ranking.

## Nothing else is owed

Claude has no required fix on the parts it read. No merge of #169 is requested, and Claude does not claim it.
