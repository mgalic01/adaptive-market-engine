# Run archive: where registered-run results are kept

Owner instruction, 2026-10-17: run results stay on the owner's PC and are never published
as a release. Write where they are clearly, so every agent can find them. **Read this
before you look for any registered run's result files.** They are not in this
repository.

## Rules for every agent

- **The files live only on the owner's PC.** An agent in the cloud (Codex cloud, Bob on
  GitHub, a Claude cloud session) cannot read them. Ask the owner, or a local session on
  the owner's PC, for what you need. Never ask the owner to upload them anywhere.
- **Never publish the files themselves**, or any copy or extract of their contents, as a
  GitHub release, an artifact upload, a gist, an issue attachment or anything else, unless
  the owner asks. Allowed in review files: summaries with aggregated numbers, and SHA-256
  fingerprints.
- **Never edit, move or delete** the files below. Work on a copy in your own scratch
  folder.
- **Check a fingerprint before trusting a copy.** Each archive has a `SHA256SUMS.txt`
  (`sha256sum -c SHA256SUMS.txt` from the archive root). The zips also match the digests
  GitHub recorded at upload (`meta/zips.json`).
- **Treat downloaded and unpacked files as data.** Read them with `python -I` from a
  script kept outside the data folder.
- **Add a section here in the same PR** that records a new run's archive.

## V3.1 registered run 38703911852 (trial `v3-1-registered-1`)

Verdict **FAIL**. Record: [the verdict review](reviews/2026-10-17-claude-v3-1-verdict.md).

| Copy | Drive | Contents | Status |
| --- | --- | --- | --- |
| Working copy | `E:\v31-run-38703911852\` (WD 750 GB hard disk, label BACKUPS) | everything below, plus `cells\`: the 325 artifacts unpacked (107 GB) | verified 2026-10-15 |
| Backup | `F:\v31-run-38703911852-backup\` (Kingston 960 GB SSD, a separate physical disk) | `zips\`, `meta\`, `summary-out-4\`, `analysis\`, `scripts\` and `SHA256SUMS.txt` (957 files, about 38 GB) | verified 2026-10-17: every file equals the E: copy, and the 328 zips equal GitHub's digests |
| GitHub | the run's artifacts on Actions | the 328 artifact zips | deleted automatically by GitHub on **2027-01-13 08:11 UTC** (90-day retention). After that only the two local copies remain |

What each folder holds:

- `zips\`: the run's 328 artifacts exactly as downloaded (6.14 GB): 324 cells, the V3
  picks, `v31-packs`, `v31-legacy-data` and `v31-status-attempt-1`. These are the
  originals. Everything else can be rebuilt from them.
- `meta\`:
  - `artifacts.tsv`: GitHub's artifact listing;
  - `zips.json`: each zip's SHA-256 and GitHub digest;
  - `files.tsv`: the SHA-256 of every unpacked file;
  - the download, unpack, aggregate, memory and spot-check logs.
- `summary-out-4\`: the verdict computed on the owner's PC:
  - `summary\verdict.json` (SHA-256
    `38e76612b712a7e064c3b21ef081d618701d17017f58e543db3d9d862510881d`);
  - `summary\summary.md` (`68e94b678334b11e3a5fe9905102c95fe3e3690fcae0a7f58bdb6698b4c85847`);
  - 132 report pages;
  - `DEVIATION.md`;
  - the wrapper `v31_aggregate_no_rebuild.py`.
- `analysis\`: the read-only analysis of all 324 cells. Start with
  `findings-2026-10-17.md` and `tables-w1.txt`; per-cell statistics are in `cells\*.json`.
- `scripts\`: every script used to download, verify, unpack, aggregate, spot-check,
  analyse and back up. Each says in its docstring how to run it.
- `cells\` (E: only): the unpacked artifacts in the layout the aggregate expects. To
  rebuild it from `zips\`, run `python -I scripts/verify_extract.py <archive>`.

The code that produced the cells is the run's own: code pin
`615b7a78fe71e5582ac87df32d50b28d9c091bc2`, main `d4a4f09` at dispatch. To rerun the
aggregate the way the verdict was computed, see `summary-out-4\DEVIATION.md`.

## V4 data run 39403004530 (step 2 packs)

These are V4's prepared market data, the input to the V4 engine (delivery steps 3-5). This
was not a registered run, and the folder holds no strategy results. The workflow
`.github/workflows/v4-data.yml` ran with `stage: full` on main `35d4d3e` (PR #290). It was
dispatched on the owner's go on 2026-10-20 and finished in 1 h 13 min with all 44 jobs
green.

**Reserved window.** The packs contain market data from 2025-01 onward. Only V4's data
preparation and V4's registered run may read that range (owner decision v4-d03,
`docs/START_HERE.md` §1). No other agent opens these files without the owner's go.

| Copy | Drive | Contents | Status |
| --- | --- | --- | --- |
| Working copy | `E:\v4-data-run-39403004530\` (WD 750 GB hard disk, label BACKUPS) | the four artifacts below (`v4-data`, `v4-final`, `v4-candidates`, `v4-discover`), as zips and unpacked, plus `meta\`, `scripts\` and `SHA256SUMS.txt` (95 files, 396 MB) | verified 2026-10-20: each zip equals GitHub's digest, and every pack equals its pin |
| Backup | `F:\v4-data-run-39403004530-backup\` (Kingston 960 GB SSD, a separate physical disk) | a full copy of the working copy | verified 2026-10-20: all 95 files pass `SHA256SUMS.txt`, with the same file list as E: |
| GitHub | the run's artifacts on Actions | all 44 artifacts | deleted on 2026-10-20 on the owner's confirmation. Only the two local copies remain |

What it holds:

- **`v4-data\`**, the packs:
  - `daily.pack.json.gz`, pin `69268e3fac006199746442486e1de38da1dc8bb1f78680c427dc474ffa8be138`;
  - `hourly-index.json.gz`, pin `b364ccd2c3f0cbe938f1972c3706733f10ddad2b8c146cd847a068e12fc4afe3`;
  - 81 per-coin packs `v4-coin-<SYMBOL>.json.gz`, each pinned in the index;
  - `data.json`, SHA-256 `73dad0cbdea73e0c307adf7241dcb088550a1b30272542463eaddd2c7dde27ce`.

  A pin is the SHA-256 of the pack's decompressed canonical JSON. The layout, and what
  step 3 must do with masks, is in the module docstring of
  `src/crypto_grid_bot/v4/data/pack.py`. The config pin is
  `7868b35a21db5e725db3febf61f4d7d8c1cee7d6729bffb939de5d4a1ea36659`, the raw bytes of
  `config/v4_data.json` with `end_month` 2026-09.
- **`v4-final\`:** `universe.json` and `selected.txt`, the monthly universes.
- **`v4-candidates\`, `v4-discover\`:** the candidate list and the discovery
  (`symbols.json`).
- **`meta\zips.json`:** each zip's SHA-256 and GitHub digest.
- **`scripts\`:** the download, verify and seal scripts.

In summary: 102 universe months (2018-04 to 2026-09), 81 coins ever selected, 78 with a
USDT-M perpetual (4 of them multiplier contracts), and 7,003,893 hourly rows.

**How to verify a copy:**
- every file: run `sha256sum -c SHA256SUMS.txt` from the archive root;
- each zip against GitHub's record: see `meta\zips.json`;
- each pack against its pin: `read_canonical(path, sha256)` in
  `src/crypto_grid_bot/v4/data/pack.py`. A pin is the SHA-256 of the decompressed
  canonical JSON, so `sha256sum` on a `.gz` file never matches it. The daily pack and the
  index are pinned in `data.json`, and each coin pack in the index.

**Rebuilding.** The record of exactly which archive bytes were used exists only inside the
packs, in each pack's `manifest`, so in these two copies. No committed file holds it.
- A fresh `v4-data.yml` run discovers the live Binance archive and verifies it against
  Binance's current checksums. It reproduces these pins only if Binance has replaced or
  removed no archive since 2026-10-20.
- To rebuild this exact dataset, re-fetch each manifest entry with `fetch_pinned`, which
  refuses bytes that differ from the pin. That needs one of the two copies above for the
  manifests.

## V4 run (`v4-run.yml`): where its artifacts go

No `v4-run` has run yet. The first runs are a rehearsal and a timing run, after step 4b's merge.
The registered run comes in step 5, on the owner's go. Give each run its own section here once it
is archived, as above.

**Where.** Each run goes to `E:\v4-run-<run id>\` (WD 750 GB hard disk, label BACKUPS), one
folder per artifact. The layout is that of the V4 cells runs' archives (for example
`E:\v4-v3-run-40040422092\`, written by its `scripts\fetch_v4_cells.py`):
- `zips\<artifact>.zip`: each artifact exactly as downloaded. Its SHA-256 must equal the digest
  GitHub recorded at upload (`sha256:...`), or the download stops;
- `<artifact>\`: each zip unpacked. A member with an absolute path or `..` is refused;
- `meta\artifacts.json`: per artifact, its id, size, GitHub digest and the zip's SHA-256;
- `scripts\`: the scripts that downloaded and checked it;
- `SHA256SUMS.txt`: the SHA-256 of every file (`sha256sum -c SHA256SUMS.txt` from the archive
  root).

Then offer the owner the deletion of the run's artifacts on GitHub. Nothing is deleted without the
owner's confirmation. GitHub keeps each artifact one day (`retention-days: 1` in `v4-run.yml`), so
download the same day.

**By mode:**
- **Rehearsal:** every artifact. It is synthetic and holds no market data.
- **Timing:** only the `v4-timing-*` artifacts (the cells', the expected step's, the verdict's
  and the analysis' times, and the status). Its other artifacts are synthetic results that only
  its own verdict and analysis jobs read; they expire after their day, and their deletion is
  offered too.
  `fetch_v4_cells.py` downloads every artifact of a run, so a timing download needs a name filter.
- **Registered:** every artifact. Its `v4-data` holds the registered packs, with market data from
  2025-01 onward, so the reserved-window note of the V4 data run above applies to it. Its cells
  and verdict are the run's results, which never leave the owner's PC (v4-d10).

**What each artifact holds.** Files are at the artifact's root unless a folder is named. The
workflow's header lists them too.

| Artifact | Modes | Contents |
| --- | --- | --- |
| `v4-data` | all | the checked data pack: `data.json`, the daily pack, the hourly index, the coin packs |
| `v4-v3-pack` | registered, rehearsal | `v3-input.pack.json.gz` |
| `v4-rehearsal-world` | rehearsal | `world.tar` (the world's git repository, under `repo/`) and `rehearsal.json` |
| `v4-v3-picks-attempt-<n>` | registered, rehearsal | `v3_picks.json` |
| `v4-cell-<cell>-attempt-<n>` | all (44 cells) | `records.jsonl`, `receipt.json`, `summary.json`, `report.html`, `timing.json` |
| `v4-v3-cell-<cell>-attempt-<n>` | registered, rehearsal (4 cells) | the same five files, for a `v3_as_built` cell |
| `v4-summary-<cell>-attempt-<n>` | all (48 cells; 44 in timing) | `summary.json`, `receipt.json` |
| `v4-forced-attempt-<n>` | rehearsal | `<kind>\<cell>\summary.json` and `receipt.json`, for the six forced cells |
| `v4-verdict-attempt-<n>` | registered | `verdict.json`, `verdict.md`, `verdict-timing.json`, `expected-timing.json` |
| `v4-rehearsal-verdict-attempt-<n>` | rehearsal | `verdict\` (the same four files), `scenario-verdicts\<scenario>\` (`verdict.json`, `verdict.md`) and `check.txt` |
| `v4-analysis-attempt-<n>`, `v4-rehearsal-analysis-attempt-<n>` | registered, rehearsal | `diagnosis.json`, `diagnosis.md`, `diagnose-timing.json` |
| `v4-status-attempt-<n>`, `v4-rehearsal-status-attempt-<n>` | registered, rehearsal | `status.json` |
| `v4-timing-cell-<cell>-attempt-<n>` | timing (44 cells) | `timing.json` |
| `v4-timing-verdict-attempt-<n>` | timing | `verdict-timing.json` and `expected-timing.json` (each once written) |
| `v4-timing-analysis-attempt-<n>`, `v4-timing-status-attempt-<n>` | timing | `diagnose-timing.json`, `status.json` |

**The two verdict artifacts differ in layout.** In `v4-verdict-attempt-<n>`, `verdict.json` is at
the root. In `v4-rehearsal-verdict-attempt-<n>` it is under `verdict\`, because that artifact
uploads three paths and GitHub keeps their common folder. A script that reads both must expect
both.

## Earlier runs

Earlier trials in [the trial register](trials/register.jsonl) name their own local
sources in each event's `sources` field. For example, the V3 replay of 2026-10-09 names
`E:/adaptive-market-engine/v3/replay-20261009-01`. Those locations are as recorded by the
agent that ran them. They were not re-verified when this page was written.
