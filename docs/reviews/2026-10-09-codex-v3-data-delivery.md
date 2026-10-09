# V3 recovery collection: verified data delivery

Index: Recovery attempt 02 completed and verified 1,914 archives and two snapshots; coverage/calendar candidates delivered for review, no replay authorization.

The owner-approved recovery collected the fixed development inventory using collector commit `6fae09299bdcb382a26e02d094c7271cbfb60ebb`. Attempt 01 remains untouched. Fetch and offline verification both exited zero. This is a data delivery, not a strategy result or completing registration.

## Counts and byte identity

Raw manifest SHA-256: `78d997a2f0a6e83705df339cc2ec0a0421faebdc18ee4337de8f07400a4b013a`. The raw manifest and snapshots are under `config/datasets/v3-20261009/`; scoped Git attributes preserve their exact bytes. ZIPs remain local under `E:/adaptive-market-engine/v3/inventory-20261009-02/archives`. The Git delivery is not a self-contained archive cache.

| Kind | Eligible | Excluded | Missing | Total identities |
| --- | ---: | ---: | ---: | ---: |
| funding | 576 | 9 | 375 | 960 |
| futures | 577 | 8 | 375 | 960 |
| spot | 741 | 3 | 46 | 790 |

The verifier re-read and checked 1,914 archives and both snapshots. Total retained collection size: 68,680,581 bytes. All 2,710 planned identities are represented; missing discovery archives are recorded absences, not silently replaced. Eligible counts describe per-kind parsing, not final portfolio eligibility.

| Snapshot | Raw bytes | SHA-256 |
| --- | ---: | --- |
| futures | 1,147,714 | `db6a0c5bde5fc247224826f26be78729da74eecd2bc419a93728f255fd9244f4` |
| spot | 17,744,018 | `d5dbeeb908dde49269e7e654359b59981e7958636b2ed61103999bdec826b05d` |

## Candidate calendar requiring review

| Symbol | First full spot candidate | First full futures candidate | Portfolio candidate | Prior spot calendar days | Eligible portfolio months |
| --- | --- | --- | --- | ---: | ---: |
| ADAUSDT | 2018-06 | 2020-02 | 2020-02 | 610 | 59 |
| BNBUSDT | 2018-06 | 2020-03 | 2020-03 | 639 | 58 |
| BTCUSDT | 2018-06 | 2020-01 | 2020-01 | 579 | 60 |
| DOGEUSDT | 2019-08 | 2020-08 | 2020-08 | 366 | 53 |
| ETHUSDT | 2018-06 | 2020-01 | 2020-01 | 579 | 60 |
| LINKUSDT | 2019-02 | 2020-02 | 2020-02 | 365 | 59 |
| LTCUSDT | 2018-06 | 2020-02 | 2020-02 | 610 | 59 |
| SOLUSDT | 2020-09 | 2020-10 | 2020-10 | 30 | 50 |
| TRXUSDT | 2018-07 | 2020-02 | 2020-02 | 580 | 59 |
| XRPUSDT | 2018-06 | 2020-02 | 2020-02 | 610 | 59 |

These are conservative coverage candidates, not exchange listing dates. The first candidate test quarter is **2021-07**, with **14 candidate test quarters** through 2024-12. SOL has only **30 calendar days** between its first full spot candidate and portfolio candidate; the frozen signal warmup rules still determine when indicators are usable. Calendar days do not prove uninterrupted bars.

## Exclusions, masks and mandatory closes

- SOLUSDT 2022-11: causes funding; previous month eligible: True; futures close candidate 2022-10-31T01:00:00+00:00; risk-matched hold close candidate 2022-10-31T01:00:00+00:00.

This SOL funding exclusion is the only excluded portfolio month after the respective first-portfolio candidates. Its close candidates are available; a close is required only when the replay actually holds a position. Pre-start/partial archives remain fully recorded in the manifest and detailed evidence.

| Kind | Archives with masks | Masked hour entries | Archives with repairs | Repaired hour entries |
| --- | ---: | ---: | ---: | ---: |
| spot | 198 | 1797 | 92 | 92 |
| futures | 16 | 3040 | 0 | 0 |
| funding | 0 | 0 | 0 | 0 |

Full per-archive reasons, repaired/masked hours, first/last timestamps, daily bars and funding cadence are retained in the raw manifest. [Readable coverage details](evidence/2026-10-09-v3-data-delivery/coverage-details.json) include all excluded archives and masked/repaired entries; no defect was removed to improve results.

## Provenance and limitations

- Frozen spec SHA-256: `e337dbcaa89ca1bfeb5293f678aded60c3350aa8465c594e7a8c1c78aae3c191`.
- Original spot source manifest SHA-256: `069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e`. Non-ADA spot archives retain those source pins; ADA is the separately approved addition.
- Filter snapshots are current metadata collected on 2026-10-09 under the explicit endpoint exception. They do not establish historical exchange filters. Price/funding collection ended at 2024-12; no reserved-window market data was fetched.
- No independent backup has been verified. Git retains the raw manifest/snapshots and normalized logs, not the ZIP cache.
- Transcripts below are UTF-8/LF-normalized copies; their bytes are not claimed to equal original Windows logs. Raw logs remain under `E:/adaptive-market-engine/v3/logs-20261009-02`.
- `replay_ready` remains false and `coverage_review_required` remains true. External data/calendar review, integrated code, completing registration and the reviewed execution task remain required before replay.

## Evidence

[Delivery summary](evidence/2026-10-09-v3-data-delivery/delivery-summary.json) contains the complete candidate calendar and verification output. [Fetch end](evidence/2026-10-09-v3-data-delivery/fetch-end.json.txt), [verification start](evidence/2026-10-09-v3-data-delivery/verify-start.json.txt), [verification result](evidence/2026-10-09-v3-data-delivery/verify.stdout.log.txt), and [verification end](evidence/2026-10-09-v3-data-delivery/verify-end.json.txt) preserve the execution evidence.

Goal served: provide fixed, inspectable inputs for an honest V3 experiment without changing strategy parameters or interpreting profitability. Next owner: Codex coordinates Bob data/coverage review and only then prepares the reviewed calendar/configuration.

## Review follow-up: preflight, size provenance and readable manifest

The original [preparation record](evidence/2026-10-09-v3-data-delivery/preparation.json.txt)
and [offline plan](evidence/2026-10-09-v3-data-delivery/offline-plan.json.txt) are now
included with their preserved preparation and one-shot execution wrappers. The
preparation wrapper checks every locked dependency version, exact clean tracked
HEAD and original input hashes before recording success. The execution wrapper
checks absent output and empty cache again, then sets the exact checkout cwd and
PYTHONPATH before invoking the collector. The earlier environment freeze is
labelled earlier; the recovery preparation verifies those locked versions anew.

The [pre-start console record](evidence/2026-10-09-v3-data-delivery/pre-start-console.json)
was extracted from this chat's original command-execution event, timestamped
2026-10-09 17:05:23 UTC, before the 17:05:42 collection start. It records the exact
collector HEAD, clean tracked status, absent output, no listed Python process and
**729,168,007,680 free bytes** on E:. This is recovered contemporaneous evidence,
not a newly run check presented as historical evidence. Its source description
and original command/output are retained. It is not a signed execution attestation.

[Retained files](evidence/2026-10-09-v3-data-delivery/retained-files.csv) lists each
relative path, raw size and SHA-256, generated after verification. Summing its
1,917 rows (1,914 ZIPs, two snapshots and one manifest) reproduces exactly
**68,680,581 bytes**. The original summary generator is also preserved as text.
No collection file or raw manifest byte was changed to add this evidence.

The raw manifest now has a complete text diff while retaining `-text` to prevent
checkout conversion. Only the large raw exchange snapshots suppress their diff;
their parsed filters, sizes and hashes remain in the readable evidence. Reviewers
can inspect all 2,710 manifest records, not merely the coverage projection.
