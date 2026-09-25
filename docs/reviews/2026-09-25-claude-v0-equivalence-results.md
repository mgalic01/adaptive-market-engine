# Claude → Codex: V0 equivalence results (Bob's approved task, completed on Linux)

- **Status:** evidence for PR #16. It completes the approved task
  [`2026-09-24-bob-v0-equivalence.md`](../tasks/2026-09-24-bob-v0-equivalence.md) at the
  approved commits. Bob ran the inputs, all 40 baseline traces and one candidate trace
  on Windows, then asked Claude to finish on Linux
  ([Bob's status](https://github.com/mgalic01/crypto-grid-bot/blob/bob/v0-equivalence/docs/reviews/2026-09-25-bob-v0-equivalence-status.md), `68a78c0`).
- **Independence:** Claude wrote the code under test and ran both sides here, so this
  is **not** independent evidence. The one cross-agent point: Bob's candidate trace for
  `verify-2024h1` `ADAUSDT-high_first-gated` at 0.1% (`b12c0ffe…`, 24 fills) equals
  Claude's. The owner will revisit Bob's cross-check of his 40 baseline hashes after
  the merge.
- **Scope of the claim:** "economic-summary and fill-sequence equivalence (order, prices,
  quantities, fees, account path; no timestamps)". The claim is not about timing.

## Inputs and commands

- **Commits:**
  - baseline `c07f856`;
  - candidate `99996bc7a1c521d6f48762c079d4a68d57d87f2e` (the SHA in Codex's approval).
- **Environment:** Linux 6.18, Python 3.11.15. The task asks for 3.12, and this is the
  one deviation from it. Both trees ran on the same interpreter.
- **Data:** the local archive cache, which verifies against both trees' committed
  manifests. `verify` exited 0 for both datasets in both trees. `check_inputs.py`
  passed:
  - practice: 124 shared archives, 51 extra `1d`;
  - verify: 92 shared, 28 extra `1d`.

  No fetch was needed, and no tracked file changed.
- **Scripts:** the three Python blocks, extracted verbatim from the task file at
  `99996bc`. `trace_run.py` ran per tree, dataset and fee level with `fork`, 4 workers.
  `compare.py` ran with the expected run counts 8 and 12.

## Results

| Dataset | Fees (maker/taker) | Runs | `compare.py` | Exit |
| --- | --- | ---: | --- | ---: |
| verify-2024h1 | 0.001 / 0.001 | 8 | 8 runs, 0 problems | 0 |
| verify-2024h1 | 0 / 0.0009 | 8 | 8 runs, 0 problems | 0 |
| practice-2022 | 0.001 / 0.001 | 12 | 12 runs, 0 problems | 0 |
| practice-2022 | 0 / 0.0009 | 12 | 12 runs, 0 problems | 0 |

**All 40 fill traces are byte-identical, and all listed summary fields are equal.**
The expected SOL case: `practice-2022` SOLUSDT has 82,792 rejected frames in both
trees (spec P4), and those runs still match exactly.

**Later commits:** after `99996bc`, `src/` changed only in:
- verification (proxy and basket completeness, strict volume);
- dataset-spec parsing (`basket_exclusions`, type-check order);
- one comment in `check_accounting`.

`replay()`, the simulator and the fill paths are unchanged, and both dataset specs are
unchanged. The equivalence therefore carries to the current head for the replay.

## Candidate trace fingerprints (SHA-256 of each `.trace.jsonl`)

| Dataset | Fees | Run | Fills | Return % | Rejected frames | SHA-256 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| verify-2024h1 | 0.001/0.001 | ADAUSDT-high_first-gated | 24 | -2.27 | 0 | `b12c0ffec2ef2a5cc7ada95f5c5bb91b33decf5ff4c63585e36553ecbc37b2cb` |
| verify-2024h1 | 0.001/0.001 | ADAUSDT-high_first-ungated | 71 | -10.01 | 0 | `6bdf6d5858e4d18a16837472a3cc2d85e6563cf10b1775e6070f8129bb051546` |
| verify-2024h1 | 0.001/0.001 | ADAUSDT-low_first-gated | 24 | -2.08 | 0 | `7eb90f633ca6a3e8107352dba398d6de2969f516cdf7fb14d1cb68dbb32e6e9e` |
| verify-2024h1 | 0.001/0.001 | ADAUSDT-low_first-ungated | 71 | -9.97 | 0 | `bd33f4553352f348a31a47ddd7d6e149b8aaa7663dc9ca59c9cc7f15b7b81d19` |
| verify-2024h1 | 0.001/0.001 | BTCUSDT-high_first-gated | 0 | 0.00 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| verify-2024h1 | 0.001/0.001 | BTCUSDT-high_first-ungated | 30 | -4.93 | 0 | `736fa1c0132cc2a86c169e32e883b9c18054e60ce3be3f4ab416357e631dc633` |
| verify-2024h1 | 0.001/0.001 | BTCUSDT-low_first-gated | 0 | 0.00 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| verify-2024h1 | 0.001/0.001 | BTCUSDT-low_first-ungated | 12 | -11.20 | 0 | `ba0fc955b2e1cb0ac71f28d0848f4c3df18505e697481eab1ae239f8c3a2fbe6` |
| verify-2024h1 | 0/0.0009 | ADAUSDT-high_first-gated | 33 | -8.44 | 0 | `0ccea5e9ad863c784e97bf2a657816a86f0b487104a14613183f0da66f02a582` |
| verify-2024h1 | 0/0.0009 | ADAUSDT-high_first-ungated | 15 | -10.58 | 0 | `e8e25398c858e967a9fa11259676912b91777908d84f4d3157caf52eb5ce879b` |
| verify-2024h1 | 0/0.0009 | ADAUSDT-low_first-gated | 33 | -8.38 | 0 | `d0ed9020be70a3ac3b529155eb4eb4bb2a7587d0970fd13668099d9590b5a2c6` |
| verify-2024h1 | 0/0.0009 | ADAUSDT-low_first-ungated | 15 | -10.58 | 0 | `ecc19957b22674b7c921f1fd952533b8619d3fe95b449d7014a52238d630753a` |
| verify-2024h1 | 0/0.0009 | BTCUSDT-high_first-gated | 59 | -7.88 | 0 | `2948cca94d301058ad6a36e2e088b4376ebe346d8bae607580693c8c5b6c94e9` |
| verify-2024h1 | 0/0.0009 | BTCUSDT-high_first-ungated | 101 | -7.29 | 0 | `38e62ffff562db46247768f882ca58f96fe2d5b1cb5c262e64f7b435fd778bb8` |
| verify-2024h1 | 0/0.0009 | BTCUSDT-low_first-gated | 109 | -7.93 | 0 | `4eac3239fb26bc7ea8ffa4bd72c10e1bdd9c345f86065e42daae6dd3a3a79795` |
| verify-2024h1 | 0/0.0009 | BTCUSDT-low_first-ungated | 86 | -7.09 | 0 | `f9444d53bc85c8142f63994094fa59a8d610bafc55a4b9b2bac5e3d614ac8296` |
| practice-2022 | 0.001/0.001 | BTCUSDT-high_first-gated | 2 | -1.20 | 0 | `fe065836d54ba3254031675fb3f3d5d7a88df0a681375cfcbda6c3296629023c` |
| practice-2022 | 0.001/0.001 | BTCUSDT-high_first-ungated | 25 | -8.03 | 0 | `629b4162a164565c37f8464608cab96ea5e50ffcd007ec598cea444e4699c407` |
| practice-2022 | 0.001/0.001 | BTCUSDT-low_first-gated | 2 | -1.20 | 0 | `fe065836d54ba3254031675fb3f3d5d7a88df0a681375cfcbda6c3296629023c` |
| practice-2022 | 0.001/0.001 | BTCUSDT-low_first-ungated | 25 | -7.89 | 0 | `9ed990c79702416cd59dd3f6b942324fdb6dddbda02a1ae9d50e9c21c32db9d2` |
| practice-2022 | 0.001/0.001 | SOLUSDT-high_first-gated | 72 | 1.79 | 82792 | `4cc1c38f433e811dcfc3505b712da2ae6b86513d0f65d194db1b642159cc3d8e` |
| practice-2022 | 0.001/0.001 | SOLUSDT-high_first-ungated | 9 | -9.66 | 82792 | `0eb11b7a5f311e603495ebfaa79256b175229eb344f93653706101c1d70c42fd` |
| practice-2022 | 0.001/0.001 | SOLUSDT-low_first-gated | 72 | 1.83 | 82792 | `0c36db91bde175dd003090fa68581bc98b62c371e2f503f80f3d0daad4e7f1e9` |
| practice-2022 | 0.001/0.001 | SOLUSDT-low_first-ungated | 9 | -9.11 | 82792 | `45c68216c90892a09a932c8bce34e8b3b3f24bd34ac92f386d5456bac70c3b57` |
| practice-2022 | 0.001/0.001 | XRPUSDT-high_first-gated | 44 | 5.60 | 0 | `7ff049cd7c51c376de13bec3cfd98e33de52a0b5ec1692228e2d21273a7b4a3e` |
| practice-2022 | 0.001/0.001 | XRPUSDT-high_first-ungated | 170 | -5.16 | 0 | `f16fbfd350a110a07c94dae578e6a90696774f0a20e292779889317d2aa1bcba` |
| practice-2022 | 0.001/0.001 | XRPUSDT-low_first-gated | 40 | 5.83 | 0 | `649ff0ba29106a06b336a6b840afc00647e4a164525f106219d1340cca2c8d7d` |
| practice-2022 | 0.001/0.001 | XRPUSDT-low_first-ungated | 170 | -5.30 | 0 | `767e439b4b01e0db7349296af12b4fdcb886dbff27205c8a9fe075297fef003d` |
| practice-2022 | 0/0.0009 | BTCUSDT-high_first-gated | 189 | 1.22 | 0 | `3ea7c00b45cbb578d9e89de71d33629684c338d668b9304caf22ec60a8761d10` |
| practice-2022 | 0/0.0009 | BTCUSDT-high_first-ungated | 49 | -5.67 | 0 | `821a1073a08bb8c8a1441b4649ed2e392a116b1321ff794bf3be7c9c0265d8b5` |
| practice-2022 | 0/0.0009 | BTCUSDT-low_first-gated | 199 | 2.98 | 0 | `ef3394e3a47088cfeb259efb7038f285b2e57b6bf9a52bb815de93850a8ecc50` |
| practice-2022 | 0/0.0009 | BTCUSDT-low_first-ungated | 45 | -6.42 | 0 | `45d12a1520642ec6d7fcdf913e40089daa37bdd875ec74d4a688038aadd375a4` |
| practice-2022 | 0/0.0009 | SOLUSDT-high_first-gated | 9 | -10.01 | 82792 | `fb6436f6924c564ce739c126f04a09627a10a33532b3325d2fd0fbd8065485ae` |
| practice-2022 | 0/0.0009 | SOLUSDT-high_first-ungated | 13 | -8.09 | 82792 | `86415cd135ce6bc1c7b1d7873eab75f908fe3d96dc5db791f0e9f746a914e017` |
| practice-2022 | 0/0.0009 | SOLUSDT-low_first-gated | 9 | -9.89 | 82792 | `8f65235ac54a98937af26b772f9cde71b3ab253e14f9baaad00a8d8ae675161e` |
| practice-2022 | 0/0.0009 | SOLUSDT-low_first-ungated | 13 | -8.07 | 82792 | `3f6b357afd9985c5c1ddaf3cfbf391ffb065149f0cbec7c48d56c44b8046f438` |
| practice-2022 | 0/0.0009 | XRPUSDT-high_first-gated | 232 | -4.15 | 0 | `8162e7161eaf017794abf9cd7822eff62c9bc1cc89c3ba51575758d9b94bfe11` |
| practice-2022 | 0/0.0009 | XRPUSDT-high_first-ungated | 28 | -8.57 | 0 | `032c44236be084ea512a11b651fc5c5159b29c0fc00af33d5e6855a2612926a0` |
| practice-2022 | 0/0.0009 | XRPUSDT-low_first-gated | 233 | -2.87 | 0 | `3d78cfba1649ac1ed4e5b6abc53876e678b8e848d3fd67e88cac6c2cb646173f` |
| practice-2022 | 0/0.0009 | XRPUSDT-low_first-ungated | 28 | -8.55 | 0 | `e529fc423c6df821b47812c2755530641258380a7f39b11699e77bfdde0a184d` |

Baseline fingerprints are identical by construction, since `compare.py` compares the
bytes. Raw outputs stay outside git, per the conventions. The returns agree with the
published [fee-level report](../backtests/fee-levels-2026-09.md).
