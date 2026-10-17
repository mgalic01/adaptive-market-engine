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

## Earlier runs

Earlier trials in [the trial register](trials/register.jsonl) name their own local
sources in each event's `sources` field. For example, the V3 replay of 2026-10-09 names
`E:/adaptive-market-engine/v3/replay-20261009-01`. Those locations are as recorded by the
agent that ran them. They were not re-verified when this page was written.
