# IBM Bob → Codex and Claude: owner decisions session 2025-09-25

- **Date:** 2025-09-25
- **Author:** IBM Bob (AI consultant, IBM), working with the owner (mgalic01)
- **Recipient:** Codex and Claude
- **Branch:** `bob/owner-decisions-2025-09-25`

## Who I am and how I fit in

I am IBM Bob, an AI assistant made by IBM. I am **not** Codex and I am **not**
Claude. I have been working with the owner today in a consulting capacity —
reading the repo, discussing the project, and helping the owner articulate and
record decisions.

I am a consultant, not a project lead. The decisions recorded here reflect the
owner's thinking after discussion with me, but **I am not the final authority on
anything technical**. If you — Codex or Claude — disagree with any of these
decisions, or see a problem I missed, or think a proposal is wrong, **please say
so explicitly and with evidence**. That pushback is exactly what the owner needs.
Blind implementation of a bad idea is worse than a constructive disagreement.

I will be joining future sessions with the owner. I follow the same handoff
protocol as you: dated files in `docs/reviews/`, PR comments for notification,
replies that address findings individually. My files are named
`YYYY-MM-DD-bob-<topic>.md`. I will not push implementation code — that remains
with Codex and Claude.

---

## What happened in today's session

The owner and I went through every open decision that was blocking the variant
matrix and the untouched window run. All are now recorded and pushed to `main`.

### Decisions recorded (all on `main` as of `8960ba0`)

| File | Decision |
| --- | --- |
| [`2025-09-25-owner-variants-decision.md`](2025-09-25-owner-variants-decision.md) | Variants A–F approved for pre-registration. A, B, C highest priority; F lowest. Pre-registration rules accepted. |
| [`2025-09-25-owner-tick-size-decision.md`](2025-09-25-owner-tick-size-decision.md) | Historical filters per month (primary); single-tick rounding (fallback). Unlocks practice-2022 SOL runs. |
| [`2025-09-25-owner-volume-drift-decision.md`](2025-09-25-owner-volume-drift-decision.md) | Tolerate Binance volume drift ≤0.1% when OHLC matches exactly; count separately as `hours_volume_drift`. |
| [`2025-09-25-owner-acceptance-criteria.md`](2025-09-25-owner-acceptance-criteria.md) | Six acceptance criteria locked for the untouched 2025–26 window. All six must pass. Includes a new criterion 6: minimum activity ≥10% of bars invested. |
| [`2025-09-25-owner-variant-g-funding-rate.md`](2025-09-25-owner-variant-g-funding-rate.md) | Variant G pre-registered: no new grid when BTC perpetual funding rate persistently >+0.05% across the last 3 funding periods. |
| [`2025-09-25-owner-variant-h-cycle-context.md`](2025-09-25-owner-variant-h-cycle-context.md) | Variant H pre-registered: Bitcoin cycle context layer — halving phase tracker (H1), overextension guard (H2), deep discount signal (H3). Price-based, no hard-coded calendar dates. |

---

## Context behind the new variants (G and H)

The owner's stated goal is a bot that **actively trades and tries to profit** —
not one that stays in cash most of the time. The first backtest showed the
strategy was in cash ~99% of the time on BTC and ~99% on ADA. That is the
problem variants A–H are designed to address.

I ran four parallel research threads before proposing G and H:

1. **Multi-timeframe MAs:** Weekly and monthly SMAs are largely redundant with
   daily SMA50/200 already in Variant A. No independent evidence found for adding
   them. The existing design is already correct on this dimension.

2. **Volume climax / stopping volume:** Theoretically sound (Coulling/Wyckoff)
   but no quantitative crypto evidence. Variant E (already approved) is the right
   way to test it. Treat as genuinely experimental.

3. **Fear & Greed Index:** Rejected — 60–70% derived from the same price/volume
   data already in the model. Binance funding rates (Variant G) are a better free
   alternative: genuinely independent, reliable, hosted by Binance itself.

4. **Bitcoin 4-year cycle:** The owner correctly pushed back on my initial
   caution here. The supply-shock mechanism is real and documented across all
   cycles. The right approach is to encode it through price position and the
   known halving block timestamp — not calendar dates. Variant H does this.

---

## What I'd ask you both to do

### For Codex
1. Review the six decision files. If any threshold, rule or design choice looks
   wrong to you — technically, mechanically, or in terms of what the engine can
   actually support — say so. Propose a correction with evidence.
2. In particular: Variant H requires the halving block timestamp as a dataset
   constant and a phase tracker in the engine. Is that implementable cleanly
   within the existing architecture, or does it require structural changes?
3. Variant G requires historical BTC perpetual funding rate data. Can this be
   fetched from Binance's public archive and added to the manifest cleanly?

### For Claude
1. Review the six decision files. Challenge any assumption you disagree with.
   In particular: are the thresholds in H2 (60% above SMA200) and H3 (50% below
   ATH) reasonable starting hypotheses, or are they poorly calibrated based on
   what you've seen in the development windows?
2. The acceptance criteria now include criterion 6 (minimum activity ≥10% of
   bars). Does this interact poorly with any of the existing criteria, or create
   a perverse incentive (e.g. a variant that trades more but worse passing on
   criterion 6 while failing on criterion 2)?
3. The research found that weekly/monthly SMAs are redundant with daily SMA200.
   Do you agree, or is there a case for them I missed?

---

## What should happen next (my suggestion — push back if you disagree)

1. **Harness fixes first:** tick-size (historical filters + fallback) and volume
   drift tolerance. These unblock the practice-2022 SOL runs and should be done
   before the variant matrix.
2. **Implement Variants A–H** behind config flags (default off). G and H require
   new data sources (funding rates, halving timestamp); plan the data fetch before
   implementation.
3. **Run the variant matrix** on `verify-2024h1` and `practice-2022` (both fee
   levels). Report results before selecting the best variant.
4. **Owner reviews results** — I will be present for that discussion.
5. **One run on the untouched 2025–26 window** against the six locked criteria.

The owner is engaged and available for decisions. Bring questions here or in a
new `docs/reviews/` file named `YYYY-MM-DD-<codex|claude>-response-to-bob.md`.

---

## A note on my role going forward

I am here to help the owner think, not to replace your judgment. You have
context on this codebase that I am still building. If something I've written
is wrong, imprecise, or conflicts with established project decisions — say so.
The owner benefits most from genuine disagreement backed by evidence, not from
three agents agreeing with each other.
