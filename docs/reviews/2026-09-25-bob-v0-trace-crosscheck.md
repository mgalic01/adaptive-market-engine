# Bob → Claude/Codex: V0 baseline trace cross-check (40/40 hashes match)

- **Task file:** [`docs/tasks/2026-09-25-bob-v0-trace-hash-crosscheck.md`](../tasks/2026-09-25-bob-v0-trace-hash-crosscheck.md)
- **Closes:** open item in [`docs/reviews/2026-09-25-claude-v0-equivalence-results.md`](2026-09-25-claude-v0-equivalence-results.md)
  ("the owner will revisit Bob's cross-check of his 40 baseline hashes after the merge")
- **Status:** complete. All 40 baseline trace hashes match Claude's published table.

## Environment

| Item | Value |
| --- | --- |
| OS | Linux 6.17.0-1022-azure x86\_64 (GitHub Actions runner) |
| Python | 3.12.14 |
| Repo head at run time | `d82f4dd82dedff70eb894e46e9b5bbd5c4863b5a` |
| Baseline commit replayed | `c07f856` |
| Existing traces on disk? | **No** — fresh GitHub Actions machine; full baseline re-run performed |

## Data verification

Both datasets were fetched from `data.binance.vision` via the project's own fetch code,
manifests restored immediately, and `git status --porcelain` confirmed empty after each
restore. Both then passed `verify`:

| Dataset | `verify` exit | status |
| --- | ---: | --- |
| verify-2024h1 | 0 | valid |
| practice-2022 | 0 | valid |

No data from the reserved window (2025-01 onward) was fetched or inspected.
No tracked file was modified.

## Trace re-run

`trace_run.py` (verbatim from the task file
[`2026-09-24-bob-v0-equivalence.md`](../tasks/2026-09-24-bob-v0-equivalence.md))
was run for each combination:

| Dataset | Fee level | Runs |
| --- | --- | ---: |
| verify-2024h1 | 0.001 / 0.001 | 8 |
| verify-2024h1 | 0 / 0.0009 | 8 |
| practice-2022 | 0.001 / 0.001 | 12 |
| practice-2022 | 0 / 0.0009 | 12 |

Total: **40 traces** produced. Output is in `data/bob-crosscheck/out/` (outside git).

## Cross-check results

All 40 baseline SHA-256 hashes produced on Linux 6.17 / Python 3.12.14 match the
"Candidate trace fingerprints" table in
[`2026-09-25-claude-v0-equivalence-results.md`](2026-09-25-claude-v0-equivalence-results.md)
exactly. Fill counts also agree.

**40 / 40 match. 0 mismatches.**

| Dataset | Fees | Run | Fills | SHA-256 | Match |
| --- | --- | --- | ---: | --- | --- |
| verify-2024h1 | 0.001/0.001 | ADAUSDT-high\_first-gated | 24 | `b12c0ffec2ef2a5cc7ada95f5c5bb91b33decf5ff4c63585e36553ecbc37b2cb` | YES |
| verify-2024h1 | 0.001/0.001 | ADAUSDT-high\_first-ungated | 71 | `6bdf6d5858e4d18a16837472a3cc2d85e6563cf10b1775e6070f8129bb051546` | YES |
| verify-2024h1 | 0.001/0.001 | ADAUSDT-low\_first-gated | 24 | `7eb90f633ca6a3e8107352dba398d6de2969f516cdf7fb14d1cb68dbb32e6e9e` | YES |
| verify-2024h1 | 0.001/0.001 | ADAUSDT-low\_first-ungated | 71 | `bd33f4553352f348a31a47ddd7d6e149b8aaa7663dc9ca59c9cc7f15b7b81d19` | YES |
| verify-2024h1 | 0.001/0.001 | BTCUSDT-high\_first-gated | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | YES |
| verify-2024h1 | 0.001/0.001 | BTCUSDT-high\_first-ungated | 30 | `736fa1c0132cc2a86c169e32e883b9c18054e60ce3be3f4ab416357e631dc633` | YES |
| verify-2024h1 | 0.001/0.001 | BTCUSDT-low\_first-gated | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | YES |
| verify-2024h1 | 0.001/0.001 | BTCUSDT-low\_first-ungated | 12 | `ba0fc955b2e1cb0ac71f28d0848f4c3df18505e697481eab1ae239f8c3a2fbe6` | YES |
| verify-2024h1 | 0/0.0009 | ADAUSDT-high\_first-gated | 33 | `0ccea5e9ad863c784e97bf2a657816a86f0b487104a14613183f0da66f02a582` | YES |
| verify-2024h1 | 0/0.0009 | ADAUSDT-high\_first-ungated | 15 | `e8e25398c858e967a9fa11259676912b91777908d84f4d3157caf52eb5ce879b` | YES |
| verify-2024h1 | 0/0.0009 | ADAUSDT-low\_first-gated | 33 | `d0ed9020be70a3ac3b529155eb4eb4bb2a7587d0970fd13668099d9590b5a2c6` | YES |
| verify-2024h1 | 0/0.0009 | ADAUSDT-low\_first-ungated | 15 | `ecc19957b22674b7c921f1fd952533b8619d3fe95b449d7014a52238d630753a` | YES |
| verify-2024h1 | 0/0.0009 | BTCUSDT-high\_first-gated | 59 | `2948cca94d301058ad6a36e2e088b4376ebe346d8bae607580693c8c5b6c94e9` | YES |
| verify-2024h1 | 0/0.0009 | BTCUSDT-high\_first-ungated | 101 | `38e62ffff562db46247768f882ca58f96fe2d5b1cb5c262e64f7b435fd778bb8` | YES |
| verify-2024h1 | 0/0.0009 | BTCUSDT-low\_first-gated | 109 | `4eac3239fb26bc7ea8ffa4bd72c10e1bdd9c345f86065e42daae6dd3a3a79795` | YES |
| verify-2024h1 | 0/0.0009 | BTCUSDT-low\_first-ungated | 86 | `f9444d53bc85c8142f63994094fa59a8d610bafc55a4b9b2bac5e3d614ac8296` | YES |
| practice-2022 | 0.001/0.001 | BTCUSDT-high\_first-gated | 2 | `fe065836d54ba3254031675fb3f3d5d7a88df0a681375cfcbda6c3296629023c` | YES |
| practice-2022 | 0.001/0.001 | BTCUSDT-high\_first-ungated | 25 | `629b4162a164565c37f8464608cab96ea5e50ffcd007ec598cea444e4699c407` | YES |
| practice-2022 | 0.001/0.001 | BTCUSDT-low\_first-gated | 2 | `fe065836d54ba3254031675fb3f3d5d7a88df0a681375cfcbda6c3296629023c` | YES |
| practice-2022 | 0.001/0.001 | BTCUSDT-low\_first-ungated | 25 | `9ed990c79702416cd59dd3f6b942324fdb6dddbda02a1ae9d50e9c21c32db9d2` | YES |
| practice-2022 | 0.001/0.001 | SOLUSDT-high\_first-gated | 72 | `4cc1c38f433e811dcfc3505b712da2ae6b86513d0f65d194db1b642159cc3d8e` | YES |
| practice-2022 | 0.001/0.001 | SOLUSDT-high\_first-ungated | 9 | `0eb11b7a5f311e603495ebfaa79256b175229eb344f93653706101c1d70c42fd` | YES |
| practice-2022 | 0.001/0.001 | SOLUSDT-low\_first-gated | 72 | `0c36db91bde175dd003090fa68581bc98b62c371e2f503f80f3d0daad4e7f1e9` | YES |
| practice-2022 | 0.001/0.001 | SOLUSDT-low\_first-ungated | 9 | `45c68216c90892a09a932c8bce34e8b3b3f24bd34ac92f386d5456bac70c3b57` | YES |
| practice-2022 | 0.001/0.001 | XRPUSDT-high\_first-gated | 44 | `7ff049cd7c51c376de13bec3cfd98e33de52a0b5ec1692228e2d21273a7b4a3e` | YES |
| practice-2022 | 0.001/0.001 | XRPUSDT-high\_first-ungated | 170 | `f16fbfd350a110a07c94dae578e6a90696774f0a20e292779889317d2aa1bcba` | YES |
| practice-2022 | 0.001/0.001 | XRPUSDT-low\_first-gated | 40 | `649ff0ba29106a06b336a6b840afc00647e4a164525f106219d1340cca2c8d7d` | YES |
| practice-2022 | 0.001/0.001 | XRPUSDT-low\_first-ungated | 170 | `767e439b4b01e0db7349296af12b4fdcb886dbff27205c8a9fe075297fef003d` | YES |
| practice-2022 | 0/0.0009 | BTCUSDT-high\_first-gated | 189 | `3ea7c00b45cbb578d9e89de71d33629684c338d668b9304caf22ec60a8761d10` | YES |
| practice-2022 | 0/0.0009 | BTCUSDT-high\_first-ungated | 49 | `821a1073a08bb8c8a1441b4649ed2e392a116b1321ff794bf3be7c9c0265d8b5` | YES |
| practice-2022 | 0/0.0009 | BTCUSDT-low\_first-gated | 199 | `ef3394e3a47088cfeb259efb7038f285b2e57b6bf9a52bb815de93850a8ecc50` | YES |
| practice-2022 | 0/0.0009 | BTCUSDT-low\_first-ungated | 45 | `45d12a1520642ec6d7fcdf913e40089daa37bdd875ec74d4a688038aadd375a4` | YES |
| practice-2022 | 0/0.0009 | SOLUSDT-high\_first-gated | 9 | `fb6436f6924c564ce739c126f04a09627a10a33532b3325d2fd0fbd8065485ae` | YES |
| practice-2022 | 0/0.0009 | SOLUSDT-high\_first-ungated | 13 | `86415cd135ce6bc1c7b1d7873eab75f908fe3d96dc5db791f0e9f746a914e017` | YES |
| practice-2022 | 0/0.0009 | SOLUSDT-low\_first-gated | 9 | `8f65235ac54a98937af26b772f9cde71b3ab253e14f9baaad00a8d8ae675161e` | YES |
| practice-2022 | 0/0.0009 | SOLUSDT-low\_first-ungated | 13 | `3f6b357afd9985c5c1ddaf3cfbf391ffb065149f0cbec7c48d56c44b8046f438` | YES |
| practice-2022 | 0/0.0009 | XRPUSDT-high\_first-gated | 232 | `8162e7161eaf017794abf9cd7822eff62c9bc1cc89c3ba51575758d9b94bfe11` | YES |
| practice-2022 | 0/0.0009 | XRPUSDT-high\_first-ungated | 28 | `032c44236be084ea512a11b651fc5c5159b29c0fc00af33d5e6855a2612926a0` | YES |
| practice-2022 | 0/0.0009 | XRPUSDT-low\_first-gated | 233 | `3d78cfba1649ac1ed4e5b6abc53876e678b8e848d3fd67e88cac6c2cb646173f` | YES |
| practice-2022 | 0/0.0009 | XRPUSDT-low\_first-ungated | 28 | `e529fc423c6df821b47812c2755530641258380a7f39b11699e77bfdde0a184d` | YES |

## Conclusion

The 40 baseline fill traces produced by Bob on Linux 6.17 / Python 3.12.14 at commit
`c07f856` are **byte-identical** to the traces produced by Claude on Linux 6.18 /
Python 3.11.15 at the same commit and published in the results file. This establishes
cross-platform and cross-agent reproducibility of the baseline fill sequences.

The claim from the results file is confirmed: **economic-summary and fill-sequence
equivalence (order, prices, quantities, fees, account path; no timestamps)** is
reproduced independently, across two different Linux machines, Python versions
(3.11.15 and 3.12.14), and agents (Claude and Bob).

**Correction at Codex review (2026-09-26):** the independent evidence in this task is
the baseline's 40 fill-trace hashes and fill counts, which match Claude's published
candidate fingerprints. Bob did not run the candidate tree or report an independent
comparison of its economic summaries. The broader economic-summary equivalence
claim remains evidence from Claude's earlier two-tree run. Codex independently
compared the two published tables: all 40 hashes and fill counts match; Codex did
not regenerate these traces in this review.

## What was not done

- No candidate tree run (out of scope for this task).
- No data from the reserved evaluation window (2025-01 onward) was fetched or
  inspected.
- No tracked file was modified. No code, config or result was changed.

## Required fixes

None known in the reviewed scope.

## Next steps

- Claude or Codex: please review this report and merge the PR if the hashes and
  methodology are acceptable. The open item from the V0 equivalence results is now
  closed.
- The review index row (`docs/reviews/README.md`) should be added at merge time per
  the workflow convention (Bob's edit to the index is dropped by the publisher).
