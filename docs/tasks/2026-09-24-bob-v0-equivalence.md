# Task for Bob: independent V0 equivalence re-run

- **Written by:** Claude, 2026-09-24, at the owner's request to delegate big runs to Bob.
  Revised after Codex's task review (PR #16, comment 5823663842).
- **Review:** Codex reviews this task file on PR #16. **Start only after a Codex → Bob
  handoff comment approves this task at a named SHA** (or the owner says go).
- **Branch for your report:** `bob/v0-equivalence`. Do not push to any other branch.

## Goal

Spec v1 §2 requires V0's fills, returns and accounting to be **identical** before and
after the prerequisites P1–P7 plus the later integrity changes. Claude checked summary
fields itself at 0.1% fees
([evidence](../reviews/2026-09-24-claude-spec-v1-prerequisites.md#v0-equivalence-evidence-spec-2)).
This task is the **independent** check, at both fee levels. It establishes two things:
1. **Economic-summary equivalence:** identical listed summary fields.
2. **Fill-sequence equivalence:** the ordered list of every fill is identical. Each fill
   records the order id, side, price, quantity, fee rate, fee, and the cash and inventory
   after the fill. The same external tracer records it in both trees.

   The trace carries no timestamps. So this proves the same fills in the same order
   with the same account path, not the same fill *times*. The report must say exactly
   that.

## Fixed inputs

| Item | Baseline | Candidate |
| --- | --- | --- |
| Commit | `c07f856` (last before P1–P7) | the SHA named in Codex's approval (at least `c4dc30b`) |
| `config/default.toml` sha256 | `17e7cfc750a31c0f53b0c4be5b8aae8dc99c355bbf49de27c9c6fed53003344f` | same |
| `practice-2022.manifest.json` sha256 | `7c5803124ba497f294666a37092835d0641598fc6c8bd7dba0ba74033d8dce0a` | `e8665c9a9e2b3117f4e825989b81a0bfe98dfa42eca84ae81fd236d8092ae288` |
| `verify-2024h1.manifest.json` sha256 | `7aee3e45484dbb7e3657c2d47b8608a5c6a4f54101af91a5218cef4510a7e901` | `48a239f4dfbe923b5a3c9c29336c884c40435617206d5c75b76b8461b0aaa9cf` |

- **Manifests differ as expected.** The candidate adds `1d` files (P3): 51 for
  practice, 28 for verify. The 124 and 92 shared `1m`/`1h` entries have identical
  SHA-256. The `instruments` blocks (exchange filters) are identical except for
  `fetched_at`. Your check in step 2 confirms this.
- **Fees:** (a) `0.001` / `0.001`; (b) Revolut X primary, `0` / `0.0009`.
- **Python:** 3.12 with `requirements-dev.lock`, on Linux (the tracer uses `fork`).

## Manifest exception (the only allowed change to a tracked file)

`fetch` writes a new manifest with new timestamps and **today's** exchange filters. In
these fresh worktrees it is allowed to do so, but **only** for the dataset just fetched.
Restore exactly that file with `git checkout -- <that manifest>` straight away, then
check that `git status --porcelain` is empty. Nothing is committed from the worktrees.
Any other change to a tracked file is a stop condition.

## Step 1: set up and verify data (stops on any failure)

```sh
set -euo pipefail
WORK=$(pwd)/bob-eq; DATA=$WORK/data; OUT=$WORK/out
CAND=<sha from Codex's approval>
git clone https://github.com/mgalic01/crypto-grid-bot.git "$WORK/repo"
cd "$WORK/repo"
python3.12 -m venv "$WORK/.venv"; . "$WORK/.venv/bin/activate"
pip install -r requirements-dev.lock
git worktree add "$WORK/base" c07f856
git worktree add "$WORK/cand" "$CAND"
mkdir -p "$OUT"
for tree in base cand; do
  for ds in verify-2024h1 practice-2022; do
    cd "$WORK/$tree"
    manifest=config/datasets/$ds.manifest.json
    PYTHONPATH=src python -m crypto_grid_bot.backtest fetch --spec config/datasets/$ds.toml --data-dir "$DATA"
    git checkout -- "$manifest"
    test -z "$(git status --porcelain)"
    # verify exits 2 on any integrity failure; set -e stops the script before any replay.
    PYTHONPATH=src python -m crypto_grid_bot.backtest verify --spec config/datasets/$ds.toml \
      --data-dir "$DATA" > "$OUT/verify-$tree-$ds.json"
  done
done
sha256sum "$WORK"/{base,cand}/config/default.toml "$WORK"/{base,cand}/config/datasets/*.{toml,json}
```

## Step 2: check the inputs agree

Save as `$WORK/check_inputs.py` and run `python check_inputs.py "$WORK"`. It exits
non-zero on any disagreement.

```python
import json
import sys
from pathlib import Path

work = Path(sys.argv[1])
for dataset in ("practice-2022", "verify-2024h1"):
    base, cand = (
        json.loads(Path(work, tree, f"config/datasets/{dataset}.manifest.json").read_text())
        for tree in ("base", "cand")
    )
    files = [
        {(f["symbol"], f["interval"], f["month"]): f["sha256"] for f in m["files"]}
        for m in (base, cand)
    ]
    shared = files[0].keys() & files[1].keys()
    assert files[0].keys() <= files[1].keys(), f"{dataset}: baseline files missing"
    assert all(files[0][k] == files[1][k] for k in shared), f"{dataset}: archive hash differs"
    extra = {k[1] for k in files[1].keys() - files[0].keys()}
    assert extra <= {"1d"}, f"{dataset}: unexpected extra files {extra}"
    strip = lambda i: {s: {k: v for k, v in f.items() if k != "fetched_at"} for s, f in i.items()}
    assert strip(base["instruments"]) == strip(cand["instruments"]), f"{dataset}: filters differ"
    print(dataset, "ok:", len(shared), "shared archives,", len(files[1]) - len(shared), "extra 1d")
```

## Step 3: traced runs

Save as `$WORK/trace_run.py`. It runs the same `run_job` function the CLI uses, with one
external wrapper around `simulation.execution._apply_fill`. That function is unchanged
between the two commits, and both resting fills (`match`) and marketable exits
(`reduce_unreserved`) go through it.

```python
"""python trace_run.py TREE DATASET MAKER TAKER DATA_DIR OUT_DIR"""

import hashlib
import json
import multiprocessing
import sys
from decimal import Decimal
from pathlib import Path

tree, dataset, maker, taker, data_dir, out_dir = sys.argv[1:7]
sys.path.insert(0, str(Path(tree, "src")))
from crypto_grid_bot.backtest import __main__ as cli  # noqa: E402
from crypto_grid_bot.backtest.dataset import load_spec  # noqa: E402
from crypto_grid_bot.simulation import execution  # noqa: E402

TRACE: list[list[str]] = []
original = execution._apply_fill


def traced(account, order, quantity, price, fee_rate):
    fill = original(account, order, quantity, price, fee_rate)
    TRACE.append(
        [order.order_id, order.side, str(price), str(quantity), str(fee_rate), str(fill.fee)]
        + [str(account.cash), str(account.inventory)]
    )
    return fill


execution._apply_fill = traced
SPEC = Path(tree, "config/datasets", f"{dataset}.toml")


def job(args):
    symbol, mode, gated = args
    TRACE.clear()
    fees = (Decimal(maker), Decimal(taker))
    summary = cli.run_job(
        SPEC, Path(tree, "config/default.toml"), Path(data_dir), symbol, mode, gated, fees
    )
    name = f"{symbol}-{mode}-{'gated' if gated else 'ungated'}"
    lines = "".join(json.dumps(row) + "\n" for row in TRACE)
    Path(out_dir, f"{name}.trace.jsonl").write_text(lines)
    Path(out_dir, f"{name}.summary.json").write_text(json.dumps(summary, default=str))
    return name, len(TRACE), hashlib.sha256(lines.encode()).hexdigest()


if __name__ == "__main__":
    Path(out_dir).mkdir(parents=True, exist_ok=False)
    spec = load_spec(SPEC)
    jobs = [(s, m, g) for s in spec.traded for m in cli.PATH_MODES for g in (True, False)]
    with multiprocessing.get_context("fork").Pool(4) as pool:
        for row in pool.imap(job, jobs):
            print(*row, flush=True)
```

Run it for every tree, dataset and fee level. Each output directory must be new:

```sh
set -euo pipefail
for tree in base cand; do
  for ds in verify-2024h1 practice-2022; do
    for fees in "0.001 0.001" "0 0.0009"; do
      set -- $fees
      python "$WORK/trace_run.py" "$WORK/$tree" "$ds" "$1" "$2" "$DATA" \
        "$OUT/$tree/$ds/m$1-t$2" | tee "$OUT/$tree-$ds-m$1-t$2.log"
    done
  done
done
```

## Step 4: compare (four explicit calls, each must exit 0)

Save as `$WORK/compare.py`:

```python
"""python compare.py BASE_DIR CAND_DIR EXPECTED_RUNS; exits 1 on any difference."""

import json
import sys
from pathlib import Path

FIELDS = [
    "final_total_equity", "return_pct", "buys", "sells", "fees", "turnover",
    "grids_opened", "range_exits", "reserve_pending", "reserve_secured",
    "final_inventory", "halted_at", "halt_reason", "accounting_problems",
    "buy_and_hold_return_pct", "realised_grid_sell_pnl", "realised_exit_pnl",
    "exit_sells", "order_requests", "max_order_requests_per_day", "transient_pauses",
]  # fmt: skip
base_dir, cand_dir, expected = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
names = [sorted(p.name[: -len(".summary.json")] for p in d.glob("*.summary.json"))
         for d in (base_dir, cand_dir)]  # fmt: skip
problems = []
if names[0] != names[1] or len(names[0]) != expected or len(set(names[0])) != expected:
    problems.append(f"run sets differ or wrong count: {names}")
for name in names[0]:
    b, c = (json.loads(Path(d, f"{name}.summary.json").read_text()) for d in (base_dir, cand_dir))
    problems += [f"{name} {f}: {b[f]!r} != {c[f]!r}" for f in FIELDS if b[f] != c[f]]
    tb, tc = (Path(d, f"{name}.trace.jsonl").read_bytes() for d in (base_dir, cand_dir))
    if tb != tc:
        problems.append(f"{name}: fill trace differs")
    print(name, "fills:", tb.count(b"\n"), "trace identical:", tb == tc)
print(len(names[0]), "runs,", len(problems), "problems")
for problem in problems:
    print(problem)
sys.exit(1 if problems else 0)
```

```sh
python "$WORK/compare.py" "$OUT/base/verify-2024h1/m0.001-t0.001" "$OUT/cand/verify-2024h1/m0.001-t0.001" 8
python "$WORK/compare.py" "$OUT/base/verify-2024h1/m0-t0.0009"    "$OUT/cand/verify-2024h1/m0-t0.0009"    8
python "$WORK/compare.py" "$OUT/base/practice-2022/m0.001-t0.001" "$OUT/cand/practice-2022/m0.001-t0.001" 12
python "$WORK/compare.py" "$OUT/base/practice-2022/m0-t0.0009"    "$OUT/cand/practice-2022/m0-t0.0009"    12
```

## Validity checks

- Steps 1–4 all exit 0.
- `verify` reports `"status": "valid"` for both datasets in both trees. The candidate's
  output also shows `"integrity_rules": {"version": "drift-tolerance-v1", ...}`.
- **Expected, not failures:**
  - `practice-2022` SOLUSDT runs have `transient_pauses > 0` in **both** trees (spec P4).
    They are still compared, and must match.
  - `max_drawdown_pct` and `buy_and_hold_max_drawdown_pct` are not compared: P2 changed
    their sampling (measurement only).

## What to report

Write `docs/reviews/2026-09-24-bob-v0-equivalence.md` and add it to the index. Include:
- the exact commits, Python version and OS;
- the output of `sha256sum` and `check_inputs.py`;
- the SHA-256 of every trace and summary file, and the full output of the four
  `compare.py` calls;
- the conclusion, worded precisely: "economic-summary and fill-sequence equivalence
  (order, prices, quantities, fees, account path; no timestamps)", or the list of
  differences;
- every invalid run and every failure, including the expected SOL pauses.

Then post a **Bob → Claude/Codex handoff** comment on PR #16 with the report link.

## Stop conditions

Stop, keep everything, and report. Do not retry, fix or rerun if:
- any command exits non-zero, including a checksum failure during `fetch`;
- `git status --porcelain` is not empty after the manifest restore;
- any `compare.py` call finds a difference;
- anything asks for a key or a login, or needs data from 2025 or later.

Never touch the reserved window (2025-01 onward), `src/`, tests, configs, dataset specs,
or committed manifests beyond the exception above.
