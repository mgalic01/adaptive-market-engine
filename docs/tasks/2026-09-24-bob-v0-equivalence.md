# Task for Bob: independent V0 equivalence re-run

- **Written by:** Claude, 2026-09-24, at the owner's request to delegate big runs to Bob.
- **Review:** Codex reviews this task file on PR #16. **Start only after a Codex → Bob
  handoff comment says this task is approved** (or the owner says go).
- **Branch for your report:** `bob/v0-equivalence`. Do not push to any other branch.

## Goal

Spec v1 §2 requires V0's fills, returns and accounting to be **identical** before and
after the prerequisites P1–P7 plus the later integrity changes. Claude checked this
itself at 0.1% fees ([evidence](../reviews/2026-09-24-claude-spec-v1-prerequisites.md#v0-equivalence-evidence-spec-2)).
This task is the **independent** check, done by an agent that did not write the code,
and at both fee levels.

## Fixed inputs

| Item | Value |
| --- | --- |
| Baseline commit | `c07f856` (last commit before P1–P7; runtime equal to the replay reviewed in PR #14) |
| Candidate commit | `1e918ef` (PR #16 head when this task was written). If Codex's approval names a newer head, use that and say so. |
| Datasets | `config/datasets/verify-2024h1.toml`, `config/datasets/practice-2022.toml`, each as committed **in the commit being run** |
| Committed manifests at the candidate | `practice-2022.manifest.json` sha256 `e8665c9a9e2b3117f4e825989b81a0bfe98dfa42eca84ae81fd236d8092ae288`; `verify-2024h1.manifest.json` sha256 `48a239f4dfbe923b5a3c9c29336c884c40435617206d5c75b76b8461b0aaa9cf` |
| Config | `config/default.toml` of the commit being run |
| Fees | (a) spec default 0.001 / 0.001; (b) Revolut X primary: `--maker-fee 0 --taker-fee 0.0009` |
| Python | 3.12 with `requirements-dev.lock` |

## Commands, in order

```sh
git clone https://github.com/mgalic01/crypto-grid-bot.git bob-eq && cd bob-eq
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.lock
git worktree add ../base c07f856
git worktree add ../cand 1e918ef
DATA=$(pwd)/../bob-data   # shared archive cache, outside git
OUT=$(pwd)/../bob-out     # results, outside git

for tree in base cand; do
  for ds in verify-2024h1 practice-2022; do
    cd ../$tree
    # fetch rewrites the manifest (new timestamps and TODAY's exchange filters).
    # Download only, then restore the committed manifest before anything else.
    PYTHONPATH=src python -m crypto_grid_bot.backtest fetch --spec config/datasets/$ds.toml --data-dir $DATA
    git checkout -- config/datasets/
    git status --porcelain            # must print nothing
    PYTHONPATH=src python -m crypto_grid_bot.backtest verify --spec config/datasets/$ds.toml --data-dir $DATA
    PYTHONPATH=src python -m crypto_grid_bot.backtest run --spec config/datasets/$ds.toml --data-dir $DATA --out $OUT/$tree
    PYTHONPATH=src python -m crypto_grid_bot.backtest run --spec config/datasets/$ds.toml --data-dir $DATA --out $OUT/$tree --maker-fee 0 --taker-fee 0.0009
    cd -
  done
done
```

Then compare every `results.json` pair (same dataset, same fees) with this script:

```python
import json, sys
FIELDS = ["final_total_equity", "return_pct", "buys", "sells", "fees", "turnover",
          "grids_opened", "range_exits", "reserve_pending", "reserve_secured",
          "final_inventory", "halted_at", "halt_reason", "accounting_problems",
          "buy_and_hold_return_pct", "realised_grid_sell_pnl", "realised_exit_pnl",
          "exit_sells", "order_requests", "max_order_requests_per_day", "transient_pauses"]
base, cand = (json.load(open(p)) for p in sys.argv[1:3])
key = lambda r: (r["symbol"], r["path_mode"], r["strategy"])
b = {key(r): r for r in base["results"]}
c = {key(r): r for r in cand["results"]}
assert b.keys() == c.keys(), (b.keys() ^ c.keys())
diffs = [(k, f, b[k][f], c[k][f]) for k in sorted(b) for f in FIELDS if b[k][f] != c[k][f]]
print(f"{len(b)} runs, {len(diffs)} differing fields")
for d in diffs: print(d)
```

## Validity checks

- Every `verify` at both commits exits 0, except as expected below.
- `git status --porcelain` is empty in both worktrees after every fetch/restore.
- The candidate's `results.json` has `"integrity_rules": {"version": "drift-tolerance-v1", ...}`.
- Expected, **not** failures: `practice-2022` SOLUSDT runs are invalid (rejected frames)
  at both commits (spec P4). `buy_and_hold_max_drawdown_pct` and `max_drawdown_pct`
  may differ (P2 changed the sampling; measurement only), so they are not compared.

## What to report

`docs/reviews/2026-09-24-bob-v0-equivalence.md`, added to the index, with:
- the exact commits, Python version, OS, and the four stdout `out` directories;
- the SHA-256 of every `results.json`;
- per dataset and fee level: runs compared and the script's full output;
- every invalid run and every failure, including the expected SOL ones.

Then a **Bob → Claude/Codex handoff** comment on PR #16 with the report link and the
verdict: "identical" or the list of differences.

## Stop conditions

Stop, keep everything, and report (do not retry, fix or rerun) if:
- any `verify` fails other than as expected above, or a download fails its checksum;
- `git status` shows a changed tracked file;
- the comparison finds any difference in the listed fields;
- anything asks for a key, a login or data from 2025 or later.

Never touch the reserved window (2025-01 onward), `src/`, tests, configs, dataset specs
or manifests.
