# Claude: V4 also tests 100 USDT, reported only (v4-d30)

Index: 2026-11-08. Owner decision v4-d30 adds 100 USDT to V4's run: 72 cells instead of 48. The pass rule stays at 1,000 and 10,000 USDT, and nothing about a 100 USDT cell changes the verdict except a re-run. The diagnostic workflows cannot run 100, so no result exists before the registration.

Written by Claude Code (session c5f98f3b), on main `504a320`.

## The owner's words

- "the nevers version we do needs to eb teste on 100 , 1000 and 10 000 $"
- Asked whether that means V4 now or the next version: "Yes, add it to V4".
- Asked whether 100 counts in the pass rule or is reported only (2026-11-08 UTC, already 2026-11-09 in Zagreb): "no, 100 does not count in the pass rule."

## What changes

| Piece | Change |
| --- | --- |
| `arms.CAPITALS` | `(100, 1000, 10000)`, so `all_cells()` gives 72 cells; the run plan, expected file, registration and report follow from it |
| `arms.DIAGNOSTIC_CAPITALS` | New, `(1000, 10000)`. `v4_cells_plan` allows only these, so `v4-cells` refuses 100; `v4-v3.yml`'s fixed matrix does not list it |
| `rule.decide` | The fail precedence and "anything missing" read the judged capitals only. A 100 USDT finding is listed as `reported only` and does not affect the outcome. A re-run of any cell stays incomplete |
| `report.py` | The page says that 100 USDT is reported only, and the adapter's wording covers it |
| `CAPITALS_JUDGED` | Unchanged, `(1000, 10000)`. There are still 8 checks |
| V4 spec | The amendment block, v4-d05, v4-d30, "Versions in the run" and "Pass rule" |

## The runner image is pinned (owner, 2026-11-08)

`v4-run.yml` and `v4-data.yml` now name `ubuntu-24.04` instead of `ubuntu-latest`. `ubuntu-latest` moved from Ubuntu 24.04 to 26.04 between the runs of 2026-10-24 and 2026-11-08, and could move again during the run or between the two data runs. Runs 40122823348 (data pins), 40040422092 (V3's pack and picks) and 40106774107 (rehearsal) all ran on 24.04, so that is the image the evidence comes from. The `quality` workflow and the diagnostic workflows are unchanged.

## Why a 100 USDT cell cannot change the verdict

The registered run happens once. `v3_as_built` maps any V3 stop to `engine_error`, and 100 USDT has never run on this engine with real data, so a failure there is plausible. Under the old "every cell counts" rule, that one failure would leave V4 with no verdict from its only run. Keeping these cells outside the precedence leaves the 48 judged cells exactly as strict as v4-d25 made them.

## Bob's deep review (FLAGGED, answered)

At `66783a1` and `a58740c`, Bob's review found the design sound in `rule.decide` and raised these:
- **Fixed:** `report._headline` read a stop at 100 USDT as the cause of a failure, which would have put a false sentence on the registered page. It now reads the judged capitals, with a test.
- **Fixed:** an unexpected error in a measure at 100 USDT would have stopped the verdict step, and so cost the run its only verdict. `v4_verdict._measured` now records it as that pair's reason, by error type only. The same error at a judged capital still stops the step, and both cases have tests.
- **Fixed:** a stale count in the `v4-run.yml` header, and the `decide` and `v4_verdict` docstrings, which still read as if every cell counted.
- **Fixed, a wording choice:** the page now says "A pass says nothing about 100 USDT."
- **Left to the timing run:** the analysis job's disk and the verdict job's time. No rehearsal scenario forces a stop at 100 USDT; the CLI tests above cover that path.
- **Goes in the Kali docs PR:** `ubuntu-24.04` is a label, not an image version, and `setup-python` takes the current 3.12 patch, so the registered run's record names both.

## Why it is not tuning

No V4 result at 100 USDT exists. The diagnostic run covered 1,000 and 10,000 USDT only, and the pass rule does not move.

## Checked and not checked

- Run locally at this change: the `tests/test_v4_*` files that touch capitals, each in seconds, and `ruff`. The full suite and `mypy` run in CI, not on the owner's PC.
- Not yet checked: the engine at 100 USDT at real size. The rehearsal and timing run cover it on synthetic data after the merge, and the timing run measures the larger analysis job (about 7.4 GB for the 66 cells, estimated). Real market data first meets 100 USDT in the registered run.
- The step-5 plan's counts and the run archive change in the Kali docs PR, which lands before B.
