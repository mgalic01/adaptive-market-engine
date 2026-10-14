# V3.1 run driver: design

Status: Claude, 2026-10-12. The owner approved the test plan the same day. Data
preparation and registration are authorized; the historical run needs a separate owner
go. Synthetic tests only until then. This document is the spec for
`docs/superpowers/plans/2026-10-12-v3-1-run-driver.md`.

## Purpose

Run the registered V3.1 experiment once, on GitHub Actions, from committed and pinned
data, and keep every result. The driver turns these into acceptance:
- the registration (`docs/superpowers/specs/2026-10-11-v3-1-registration-proposal.md`);
- the replay and baseline code on PR #269;
- the acceptance code on PR #269.

## Fixed inputs (owner decisions, 2026-10-11 and 2026-10-12)

- **W1, pass/fail:** 2021-07-01 00:00 UTC to 2025-01-01 00:00 UTC, on ten coins.
- **W0, reported only:** 2020-03-01 to 2025-01-01, on the eight coins with futures then
  (BTC, ETH, BNB, XRP, ADA, LINK, LTC, TRX). Only the `combined` arm runs here, with no
  acceptance.
- **Capitals:** 10,000 USDT, and EUR 100 at the ECB reference rate for 2024-12-31,
  copied at registration.
  *Note, 2026-10-14: the owner replaced these with three USDT capitals, 100, 1,000 and
  10,000 USDT (`small`, `medium`, `research`), with no FX conversion
  (`docs/V3_1_SOURCE_INVENTORY.md`, "Owner decision on the capitals, 2026-10-14"). The run
  then has 324 cells, and the workflow splits its cells into three matrices (selector,
  minute, the rest) to stay within GitHub's 256 jobs per matrix.*
- **Costs:** base and doubled profiles, as in proposal section 4.
- **Arms:** the 10 V3.1 arms and the 32 baselines. V1 uses all nine variants, `a b c e f g
  cg h ch`, and each minute baseline runs in both path modes.
- **Scenarios:** both modeled scenarios for every V3.1 arm.
- **No 2025+ data:** nothing at or after 2025-01-01 is fetched, opened or read
  (`1_735_689_600_000` ms).

## Architecture

**1. Prepare (one job).**
- Fetches every archive the registration names from data.binance.vision through the
  existing guarded transports (`backtest.dataset.archive_get` for 1m spot and
  `scripts/fetch_v3_data.V3Transport` for the inventory). It verifies each archive
  against its committed SHA-256 and writes no data to git.
- Decodes the archives into one **input pack** per window: per coin, the spot and
  futures 1h bars (masked and repaired hours removed), the daily bars (V3's day rule),
  the funding records (excluded months included, `interval_hours` kept), the venue rules
  and the flow schedule.
- Derives the window's skipped hours mechanically and refuses a window that breaks the
  registration checklist.
- Writes each pack deterministically, so its SHA-256 is reproducible and pinnable.

**2. Flow schedule.** The grid's minute flow gate depends only on minute data, so the
driver precomputes it per coin as two flags for every window hour:
- `open_allowed[h]`, the gate state after feeding the minutes up to `h`;
- `withheld[h]`, true if the gate is blocked at the opening or at any minute inside
  `[h, h+1h)`.

The prepare job streams the minute archives month by month into the same
`MinuteFlowGate`. A whole window's minutes are never held in memory: holding them as
`Kline` objects would take about 18 GB for ten coins.

The replay takes the schedule in place of minutes. A schedule built from fixture minutes
must give a trace identical to the replay fed those minutes, and a test enforces this.

**3. Run (one job per cell).** Each job:
- loads the pack;
- passes the execution gate: the checkout equals the registered code commit, and the
  pack, registration config and run-manifest equal their pins. The cell's arm, window,
  capital, cost profile and scenario come only from the registration, so a doubled-cost
  cell cannot be run at base cost;
- runs one cell and writes a **cell artifact**: the serialized `RunOutcome` and `Report`,
  plus the cell's evidence records.

V3.1 cells use `replay_strategy`. The baselines use their adapters. The V3 selector's
walk-forward picks are computed once in their own job and shared.

**4. Aggregate (one job).**
- Reads every cell artifact and runs `experiment.evaluate`.
- For each V3.1 cell: builds `cell_comparison`, renders the page with
  `render_bundle_report`, and writes the evidence bundle once with `write_bundle`.
- Writes a summary: the verdict JSON, a Markdown table and the W0 reported-only reports.
  Claude commits the summary afterwards in a reviewed PR; the full bundles stay as
  artifacts, recorded by SHA-256.

**5. Smoke mode.** The same workflow runs end to end on a tiny synthetic registration,
with synthetic packs and no network, before the real run. This catches wiring failures
cheaply; V3's one real invocation failed after seven hours in its last phase.

## Registration artifacts

- `config/v3_1_registration.json` is the single config pin. It holds the windows with
  their skipped hours, the capitals with the FX pin, the cost profiles, the arms and V1
  variants, the scenarios, the observation policy, the adapter module pins and the cell
  list. *(Since 2026-10-14 the capitals are the three USDT ones and hold no FX pin.)*
- `config/v3_1_run_manifest.json` is the single manifest pin. It holds every data
  manifest SHA-256, the filter-snapshot SHA-256 values and the input-pack SHA-256 values.
- The trial register (`docs/trials/register.jsonl`, family `spec-v3.1`) gets a
  candidate-space registration and a completing event that pins both files and the code
  commit, as `scripts/trial_register.py` requires.

## Runtime

- **Runners:** public repository, so standard runners (4 vCPU, 16 GB) are free. There are
  20 concurrent jobs and a 6-hour limit per job.
- **Cells:** 80 V3.1 cells in W1, 8 in W0, 28 V3 cells, 4 hold cells and 96 minute-baseline
  cells. *(Since 2026-10-14, with three capitals: 120, 12, 42, 6 and 144, 324 in all.)*
- **Time:** a V3.1 cell is estimated at about 20-25 minutes. A minute-baseline cell replays
  three pairs one at a time, at about 2 GB of minutes per pair.
- **Rule:** every attempt is recorded and none is retried.

## Out of scope

Any change to frozen code. Live trading. Reading 2025+ data. Retuning any V3.1 rule after
seeing results.
