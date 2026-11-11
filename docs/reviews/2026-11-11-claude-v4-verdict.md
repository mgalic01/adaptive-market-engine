# Claude: the V4.0 verdict, FAIL

Index: V4.0 verdict record, written 2026-11-11 UTC. Registered run 42953425248 (trial
`v4-0-registered-1`) completed on GitHub at its first attempt, and its own verdict job gave
**FAIL**: `v4_main` holds conditions 1 to 3 at both judged capitals, but condition 4 (equity at the
window's end above its 2025-01-01 level) holds at neither. The result files are on the owner's PC
only ([run archive](../RUN_ARCHIVE.md)); this record gives the verdict, aggregated numbers and
fingerprints, as owner decision v4-d29 allows.

Author: Claude Code (session c5f98f3b), 2026-11-11 UTC. Branch `claude/v4-verdict-record` on main
`58aad6f`. Documents only. No market data was fetched for this record; it reads the run's own
artifacts on the owner's PC with `python -I` scripts kept outside the archive.

## The run

- **Registration:** PR #305, merged 2026-11-11 02:12 UTC as main M
  `58aad6f32dd20a932d00f1ef57768fa521559e17` (parents B `0c87fdd` and the registration's head
  `31bbd6e`). The owner's go and its dated answers are in
  [the registration review](2026-11-09-claude-v4-registration.md).
- **Data run (step 9):** 42944460786 from main at M, 02:12:59 to 03:31:11 UTC, all 44 jobs
  succeeded. Its config, end month, daily and index pins equal the run manifest's.
- **Preflight (step 10):** every check passed: main is M, the P..M diff holds only the allowed
  paths, S is on main, the data run is under 20 hours old, no other `v4-run` is active or titled
  for S, the BACKUPS disk is mounted read-write with SMART passing and 616 GB free, and the
  downloader's SHA-256 matches.
- **The one dispatch:** 2026-11-11 03:32:26 UTC, "v4-run registered
  2309be5a8cc5e44e9cfd4adc2d01880c902e88b556e1c1cb434db6c9681d42fe", head M, with `data_run`
  42944460786. It was never cancelled and never re-run.
- **Jobs:** 79 at attempt 1, 78 succeeded. `scenarios` was skipped, as it is in every mode but a
  rehearsal. Plan 03:32:30 to 03:33:15; the 66 V4 cells by about 03:59; v3-pack and v3-picks
  03:33:18 to 05:36:06; the six `v3_as_built` cells 05:36:09 to 05:53:37; verdict 05:53:40 to
  05:56:50; the status job ended 05:57:08, and the run itself at 05:57:09. The run's conclusion is success.
- **Step 12a** was not needed: the verdict and analysis jobs both succeeded at attempt 1.

## The archive (steps 12b, 12c and 12f)

- `/mnt/backups/v4-run-42953425248/`: all 150 artifacts, each zip equal to GitHub's upload digest,
  about 8.7 GB unpacked. 150 equals the run's `total_count`.
- `sha256sum -c SHA256SUMS.txt` passed on 750 files after `sync` and a fresh mount of the disk.
- GitHub's copies were deleted on 2026-11-11 once the copy was verified: the run's 150 and data
  run 42944460786's 44 (194 deletions, each answered 204). The first data run, 42614834522, had
  none left.

## Verdict: FAIL

From the verdict job's `verdict.json` (outcome `fail`). Missing cells, refused folders, re-run
cells and other dispatches: none.

| Capital | Condition | Holds | `v4_main` | Other side |
| --- | --- | --- | --- | --- |
| 1,000 | 1. return / max drawdown against `hold_universe` | yes | 4.055 (+235.9% / 58.2%) | 0.482 (+43.7% / 90.6%) |
| 1,000 | 2. return against `v3_as_built`, 2021-07-01 to 2024-12-31 | yes | +44.5% | +34.6% |
| 1,000 | 3. net profit at doubled costs | yes | ends at 2,132.44 | from 1,000.00 |
| 1,000 | 4. equity at the end against 2025-01-01 | **no** | ends at 3,358.85 | 3,964.58 at 2025-01-01 |
| 10,000 | 1. return / max drawdown against `hold_universe` | yes | 4.012 (+233.4% / 58.2%) | 0.472 (+42.8% / 90.7%) |
| 10,000 | 2. return against `v3_as_built`, 2021-07-01 to 2024-12-31 | yes | +43.2% | +34.5% |
| 10,000 | 3. net profit at doubled costs | yes | ends at 21,124.84 | from 10,000.00 |
| 10,000 | 4. equity at the end against 2025-01-01 | **no** | ends at 33,342.14 | 39,082.75 at 2025-01-01 |

Conditions 1 and 2 skip, for both sides alike, the hours where either side has no complete mark:
852 and 299 hours, listed in `verdict.json`. Condition 4 means a loss of about 15.3% (1,000) and
14.7% (10,000) from 2025-01-01 to the window's end, 2026-09-30 23:00 UTC.

The pass rule needs all 8 checks, so V4.0 fails. The 100 USDT cells are reported only (v4-d30)
and change nothing. A pass would have meant "promising, not proven"; a fail means V4.0 as
registered is not taken forward, and, by the registration's stopping rule, results are not tuned:
anything next needs a new bounded hypothesis.

## Aggregated numbers by arm

Each figure is the mean of the arm's two judged cells (1,000 and 10,000 USDT) at the cost level
named. Return is compounded over each cell's own window; the eras are the spec's three, the third
being the only one unseen when V4 was designed. Every cell's outcome is `complete`, with no
liquidation.

| Arm | Costs | Return | Max drawdown | to 2020-12-31 | 2021 to 2024 | 2025-01-01 to end |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `v4_main` | 1x | +234.7% | 58.2% | +86.4% | +111.2% | -15.0% |
| `v4_main` | 2x | +112.2% | 62.6% | +72.9% | +65.0% | -25.6% |
| `v4_long_only` | 1x | +344.1% | 44.1% | +62.0% | +186.1% | -4.2% |
| `v4_vol25` | 1x | +160.6% | 38.4% | +62.7% | +78.2% | -10.1% |
| `v4_vol60` | 1x | +340.2% | 69.0% | +114.0% | +181.5% | -26.9% |
| `v4_faster` | 1x | +296.7% | 58.2% | +148.2% | +65.8% | -3.6% |
| `v4_slower` | 1x | +161.6% | 46.5% | +43.7% | +130.2% | -20.9% |
| `v4_btc200_shorts` | 1x | +259.1% | 52.8% | +76.8% | +133.5% | -13.0% |
| `v4_confirm3` | 1x | +124.2% | 61.0% | +75.8% | +89.6% | -32.7% |
| `hold_universe` | 1x | +43.2% | 90.6% | +20.9% | +114.7% | -44.8% |
| `hold_btc` | 1x | +1085.1% | 77.1% | +311.1% | +223.1% | -10.8% |
| `hold_btc_trend` | 1x | +1012.0% | 67.2% | +308.6% | +161.9% | +3.9% |
| `v3_as_built` | 1x | +34.5% | 64.9% | n/a | +34.5% | n/a |

Every V4 arm lost money in the unseen era at normal costs; among all arms only `hold_btc_trend`
gained there. These arms are reported only and decide nothing (registration, "selection").

## Fingerprints

| File | SHA-256 |
| --- | --- |
| `v4-verdict-attempt-1/verdict.json` | `520691853931afb626af155a3d4cf88a89db4ea850ade4835139c06dd863e765` |
| `v4-verdict-attempt-1/verdict.md` | `64d5996cdac5093a40a47a46b0ad89dc99d2b7e6b905813b0134f03ac1dd04b4` |
| `v4-analysis-attempt-1/diagnosis.md` | `50f47c3be9d64f79bafb45268fbfad1dddeff4afe6e9e55170427d5d44233a1f` |
| `v4-analysis-attempt-1/diagnosis.json` | `9db54c6d8ccba5b1536dcb64bbcd48aaa4d777285044e2971476239df49aa797` |
| the archive's `SHA256SUMS.txt` | `1e24e50b3876af6f0335625deea40c77d5fb1bb8f092e8ac97c00b90a75dd4f6` |
| registration S (`config/v4_registration.json`) | `2309be5a8cc5e44e9cfd4adc2d01880c902e88b556e1c1cb434db6c9681d42fe` |
| run manifest | `128f82e820cc735773f51600502de90f6e8539679004473b5bb5fa3387bcdd35` |
| data config | `7868b35a21db5e725db3febf61f4d7d8c1cee7d6729bffb939de5d4a1ea36659` |

Code pin P `40e5ba8cad74c07083bf7583d2a3e7e1a7b017cb`, dispatched from M
`58aad6f32dd20a932d00f1ef57768fa521559e17`.

## The register

This PR appends one `result` event for `v4-0-registered-1`:
- run ID `42953425248`;
- status **`failed`**, the status the owner chose for a fail with the go (step 7 of
  [the step-5 plan](../superpowers/plans/2026-10-24-v4-step5-registration.md));
- provenance: the archive, the digest check, P, M as `dispatched_from`, S, the manifest's
  SHA-256, the data run and the verdict files' SHA-256;
- the report is this file.

## Follow-ups (owed, not in this PR)

- **Economic readout and four-level risk check for Codex's independent review**, then a joint
  recommendation to the owner, as agreed in
  [Codex's handoff](https://github.com/mgalic01/adaptive-market-engine/pull/305#issuecomment-6783658317).
  This run made the 2025+ era seen, so any next hypothesis needs forward paper evidence before
  it can be judged.
- Main is no longer frozen: the dispatch has happened, so other PRs may land.
- Bob's workflow downloads its tool from IBM on every run because no Actions cache entry
  exists; worth a look now that main is open.
