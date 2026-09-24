# Owner decisions confirmed in conversation with Claude (2026-09-24)

- **Recorded by:** Claude, from the owner's own replies in the Claude session on
  2026-09-24.
- **Where:** PR #16. The decisions become binding for the experiment only when spec v1
  is frozen after Codex's review.
- **Why this file:** earlier the same day, six "owner decision" files were committed
  directly to `main` without review (dated 2025-09-25, recorded by Bob). The owner
  asked that they be treated as **proposals** and reviewed on PR #16. This file records
  which of them the owner then confirmed, changed or left open.

| Topic | Owner's decision | Effect |
| --- | --- | --- |
| Status of Bob's six files on `main` | "Treat as proposals" | Labelled as proposals in the index; nothing in them applies unless confirmed here. |
| Acceptance criteria | The combined set: C1 (10% on total and active equity, hard-halt veto), C2 (median > 0 on **each** path, and mean > 0), C3 (strict: every run's drawdown below buy-and-hold), C4 (integrity), C5 (≥ 1 completed cycle per week on average), C6 (gated beats ungated V0 in ≥ 60% of runs), R1 (economics reported only) | [`EXPERIMENT_SPEC_V1.md`](../EXPERIMENT_SPEC_V1.md) §6. Supersedes Bob's six-criteria proposal and the earlier four-criteria set. |
| Reserved-window universe | Five deciding pairs (BTC, ETH, XRP, SOL, ADA); a robustness set (five extra pairs plus the delisted top-30 pairs) reported only | Spec §7. Answers Bob's survivorship point. |
| Volume drift | Bob's proposal confirmed: OHLC must match exactly; volume-only drift ≤ 0.1% is counted separately, not fatal; everything else stays fatal | Implemented in `4034e91` for the hourly and daily checks. `practice-2022` now verifies (one drift day per pair, 2022-04-13). |
| Variants E, G, H | Include all three in this round | Spec §3 E, G, H and §4. E counts for selection only after Codex's risk review. G uses the public funding-rate archive, never a futures API. H3 is the only rule that loosens an entry gate, and it never touches risk limits. |
| Variants A–F | Confirmed (already in spec v1) | — |
| Tick-size method (Bob's proposal) | Not separately decided | Spec P4: SOL's 0.01 tick matches the archives. The invalidity comes from the spread model, so SOL stays invalid in the primary comparison. Bob's one-tick fallback may only be a labelled sensitivity scenario (Codex's ruling). Open for the owner if he wants it treated differently. |
| Final run | Not before the owner's explicit go | Spec §7 owner gate (unchanged). |
