# Claude: V4 step 2, universe and data

Index: V4.0 delivery step 2 (universe and data), built 2026-10-20 on `claude/v4-step2-data` from the merged design (PR #289). New package `src/crypto_grid_bot/v4/data/`, CLI `scripts/v4_data.py`, sharded workflow `.github/workflows/v4-data.yml`. Every task was reviewed, then the whole branch. Also carries a spec amendment: multiplier perpetuals, PR #289's three P2s, per-coin hourly packs, and non-ASCII symbols excluded by rule. No market data was fetched; the first dispatch is discover-only.

Author: Claude Code (session f7f187df), 2026-10-20 UTC.
Plan: `docs/superpowers/plans/2026-10-20-v4-step2-universe-and-data.md`.
Spec: `docs/superpowers/specs/2026-10-17-v4-design.md`.

## What is built

| Task | Module | What it does |
|---|---|---|
| 1 | `v4/data/config.py`, `config/v4_data.json` | Pinned data settings and the end-month guard |
| 2 | `v4/data/archives.py` | Allowlisted HTTP transport (two hosts, fixed URL shapes, no redirects, no proxy, size caps), checksum-verified fetch, retries on transport failures only |
| 3 | `v4/data/listing.py` | S3 listing with pagination; discovery of spot USDT symbols, perpetuals and months |
| 4 | `v4/data/bars.py` | Readers with V3's repairing rules (spec v1 §5 rule 1) and masks; funding-month validation with V3's exact schedule |
| 5 | `v4/data/universe.py` | Static exclusions, the stable-price rule, and the monthly top 10 with the hourly check down to rank 20 |
| 6 | `v4/data/filters.py` | Present-day venue rules, or the fixed fallback for delisted symbols |
| 7 | `v4/data/pack.py` | Canonical gzipped JSON pinned by SHA-256: the daily pack, one pack per coin, and the hourly index |
| 8 | `scripts/v4_data.py`, `v4/data/inputs.py`, the workflow | Stages discover, fetch, select (candidates, final) and pack, run on GitHub in sharded jobs |
| 9 | `listing.perpetual_for` and the CLI | Each coin's perpetual, multiplier contracts such as 1000SHIBUSDT included |

## How it was reviewed

- **Per task:** each task had a fresh implementer, then a reviewer on spec compliance and quality, then fix rounds with scoped re-reviews until clean.
- **Whole branch:** a final review covered the branch and judged it ready with fixes, finding 2 Important and 8 Minor issues. One fix round followed, and its scoped re-review found every finding addressed.
- **Decisions:** 36 controller rulings were made along the way, recorded in the session's ledger. The ones that change behaviour are in the plan's R5 and in the spec.
- **Testing:** only focused module tests ran locally, under the owner's rule against CPU-heavy work on their PC. The full suite runs in CI on this PR.

## Spec amendment carried here

- **Multiplier perpetuals:** a coin's perpetual is `XUSDT`, or the one `P+X+USDT` with P in 1000, 10000, 100000, 1000000 or 1M. It needs an archive at or before the end month. A base starting with `0` gets only its plain symbol.
- **PR #289's three Codex P2s:**
  - a no-bar 00:00 decision keeps a pending replacement buy (4321115387);
  - dust keeps a lifecycle open until it is sold or censored (4321115397);
  - funding uses the perpetual's open or carried mark (4321115404).
- **Per-coin hourly packs plus a pinned index:** no step holds every coin's whole history at once.
- **Non-ASCII names excluded by rule:** USDT symbols with non-ASCII names (币安人生USDT, 牛来USDT) are excluded, recorded and counted, never dropped silently. This is disclosed as an owner decision to widen.
- **Listing-month funding slots:** their conservatism is disclosed.

## Open for the owner

- **Agreement sizing:** whether weak agreement between the speeds should mean smaller positions, as the merged design specifies, or full size.
- **Non-ASCII coins:** whether to include them. That would widen the fetch allowlist.

## After this PR

The first `workflow_dispatch` uses `stage: discover`. It fetches no archive contents and reports counts only: symbols, perpetuals, multiplier contracts, unsupported names and archives per kind. The owner sees those numbers before the full data run.
