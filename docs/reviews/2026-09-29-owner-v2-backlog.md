# V2 backlog: owner-confirmed research items and open directions

Index: 2026-09-29: Consolidated list of v2 research questions, open directions, and
missing capabilities confirmed by the owner during the 2026-09-29 session with Bob
(owner's desktop session). Not a spec, not registered trials — these are hypotheses
to validate before any strategy or infrastructure change is made.

- **Recorded by:** Bob (owner's desktop IBM Bob session), 2026-09-29.
- **Status:** Living document. Add rows as new items are confirmed. Remove rows only
  when a measured backtest result or owner decision closes them.

---

## Strategy research items

### S1 — Regime-adaptive grid spacing
**Source:** Owner conversation, 2026-09-29. Detail: `docs/reviews/2026-09-29-owner-regime-adaptive-grid-spacing.md`

In a sideways (RANGE) market, tight grid spacing (~1–2%) harvests frequent small
oscillations. In a trending market (BULL/BEAR), wide spacing or a pause avoids the
grid being blown through by a directional move. Currently spacing is fixed at grid-open
time regardless of regime changes.

**Questions to answer:**
- What spacing targets are right for each regime (needs backtest measurement)?
- How fast should the grid rebuild on a regime change?
- Does adaptive spacing interact with drawdown recovery (amendment 1)?

**Owner decisions needed:**
- [ ] Schedule as formal Bob task or hold until v1 comparison is complete?
- [ ] Which regime-to-spacing mapping to test first?

---

### S2 — Market structure perception and FTA sell targets
**Source:** Owner conversation + Luka Hranjec Jeri's analysis, 2026-09-29.
Detail: PRs #147, #148, #150 (open, not yet merged).

The bot needs to independently detect market structure (swing highs/lows, support/
resistance zones, multi-timeframe trend alignment) and use the FTA (First Trouble Area)
as sell targets rather than fixed geometric spacing. PR #147 implements the perception
module; PR #148 wires FTA into GridBuilder; PR #150 adds structure_alignment to the
regime classifier. A backtest comparison task is in PR #149.

**Questions to answer (via PR #149 backtest):**
- Do FTA-aware sell targets improve fill rate and per-cycle return vs geometric targets?
- Does structure_alignment as a regime signal reduce false RANGE classifications?
- What is the right weight for structure_alignment vs the other regime signals?

**Owner decisions needed:**
- [ ] Approve PRs #147–#150 for merge once reviewed by Claude/Codex.

---

### S3 — Monte Carlo / out-of-sample validation
**Source:** Community best-practice advice relayed by owner, 2026-09-29.

Backtest results on development datasets are hypotheses, not proof. Before any capital
or strategy decision, results need:
1. **Monte Carlo simulation** — randomise entry timing and order within the backtest
   period; check that results hold across many path realisations, not just the single
   historical path.
2. **Out-of-sample (reserved window) test** — run on data the strategy was never
   optimised against. The reserved window (2025-01 onwards) is already set aside for
   this. Owner must give explicit go before any reserved-window data is opened.

**What needs building:**
- A Monte Carlo wrapper around the existing replay engine (randomise bar order within
  windows, re-run N times, report distribution of outcomes).
- A protocol for opening the reserved window: owner decision + documented rationale.

**Owner decisions needed:**
- [ ] When to open the reserved window for out-of-sample validation (after v1 is stable)?
- [ ] How many Monte Carlo runs are required before a strategy is considered validated?

---

### S4 — Counterfactual logging ("log the setups you skipped")
**Source:** Community best-practice advice relayed by owner, 2026-09-29.

Currently the bot logs what it trades. It does not log why it chose *not* to open a
grid on a given symbol or time — the regime was wrong, the opportunity score was too
low, the drawdown limit was hit, etc. Without this, it is impossible to know whether
skipped setups were actually good opportunities that were wrongly filtered.

**What needs building:**
- A "near-miss" log: for each evaluation that resulted in no action, record the symbol,
  the regime score, the opportunity score, and what threshold it failed.
- Track outcome of near-misses alongside actual trades to measure whether the filters
  are calibrated correctly.

**Owner decisions needed:**
- [ ] Where should counterfactual logs be stored (repo, separate file, database)?
- [ ] Retention policy (30/60 days as suggested, or full history)?

---

### S5 — Forward test period before any live capital
**Source:** Community best-practice advice relayed by owner, 2026-09-29.

Paper trading catches what backtesting misses (partial fills, slippage, connectivity).
The recommendation is 30+ days of uninterrupted paper trading across at least one
regime change before going live with any real capital.

**What needs building:**
- A sustained paper-trading deployment (not just backtest runs): the bot running against
  live market data, paper-only, for 30+ days with full logging.
- A pass/fail checklist: what metrics must hold for the forward test to count as passed?

**Owner decisions needed:**
- [ ] When to start the forward test period (after v1 spec comparisons complete)?
- [ ] What are the pass/fail criteria (e.g. no drawdown halt triggered, positive return,
  fill rate within X% of backtest)?

---

## Infrastructure items

### I1 — Reliable 24/7 hosting (VPS or homelab)
**Source:** Community best-practice advice relayed by owner, 2026-09-29.

Free-tier or sleeping hosts break 24/7 market monitoring. For the forward test and
any live deployment, the bot needs a process that never sleeps. Issue #121 (deploy
two remote Codex reviewers) is related infrastructure but does not address the trading
bot's hosting.

**Owner decisions needed:**
- [ ] VPS provider, or homelab server?
- [ ] This is not needed until the forward test starts. Low priority until then.

---

## Closed / addressed items

*(Move items here when a backtest result or owner decision resolves them.)*

None yet.

— IBM Bob (owner's desktop session)
