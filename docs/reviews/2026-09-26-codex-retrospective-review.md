# Codex → Claude handoff: retrospective review, PRs #20–#70

- **Date:** 2026-09-26. **Author:** Codex desktop with three independent review sub-agents.
- **Repository:** mgalic01/adaptive-market-engine (renamed from crypto-grid-bot).
- **Reviewed main:** `a5bb058813f78270c61c2b7e94d70ac36753cf1c`; original offline audit at `1e87f054144405fd66023d742e658da616ddaddf`.
- **Scope:** the owner's original #20–#32 audit, extended to all merged PRs through #68 and open #69/#70. PR #33 receives a separate point-by-point response after this audit. Three agents independently reviewed runtime/data integrity, workflows, and research evidence; Codex desktop reproduced the material findings and integrates fixes.
- **Status:** retrospective findings established; focused code fixes and documentation corrections are being reviewed. This is not blanket approval of open PRs or a strategy-performance sign-off.
- **Boundaries:** paper-only; no strategy implementation, parameter change, spec freeze, reserved-window access, or large replay matrix. The owner later authorized Bob checks; one bounded read-only Bob review confirmed the #70 finding. No Bob task job or market-data download was started for this audit.

## Commit and review evidence ledger

Every row records the GitHub merge commit and merged PR head, checked against local Git history. The linked quality run is an archived successful run associated with that exact head, fetched independently; it is not a claim that a present-day Windows run passed. Review evidence links are historical, and are not reused as approval of later fixes.

| PR / change and disposition | Exact merge commit | Merged head | Review evidence / quality |
| --- | --- | --- | --- |
| [#20](https://github.com/mgalic01/adaptive-market-engine/pull/20): Uniform cadence; finite-rate and unseen-shortening limits preserved. Independent reference passes. | `84a4dc6c0ff86d8e124314ae3a434941a88ce4b7` | `7ed11c277e3bac2d209ef0cbd63f5bfffab60163` | [discussion](https://github.com/mgalic01/adaptive-market-engine/pull/20); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36154999802) |
| [#21](https://github.com/mgalic01/adaptive-market-engine/pull/21): Manifest shape boundary; missing nested instrument checks later fixed in #38. | `9274eaf7aeebdc6668c28a73fffd4683287b2ef4` | `c313172721aa351059c7276d83c64c254dbd8a77` | [discussion](https://github.com/mgalic01/adaptive-market-engine/pull/21); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36170282080) |
| [#22](https://github.com/mgalic01/adaptive-market-engine/pull/22): Pinned read-only Bob; vendor tool isolation remains part of trust boundary. | `09c1cd2d0dab26caa7e0cb0263eb838112c4da33` | `b11c3f99fbf8c246850001f4f1dadd433682704a` | [discussion](https://github.com/mgalic01/adaptive-market-engine/pull/22); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36164837404) |
| [#23](https://github.com/mgalic01/adaptive-market-engine/pull/23): Failure alerts; verify separately from model verdict. | `37642c82ae337f12f79525dc514ec0cfa03c8e4f` | `89efc90db6c46cf283641d9772ecf6b4db515fef` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/23#issuecomment-5836460798); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36165898310) |
| [#24](https://github.com/mgalic01/adaptive-market-engine/pull/24): Streaming output; extractor defects superseded by #39/#44. | `a145c277af7e5435e8ccb4880615ba568e0122eb` | `70c93b69f81ceb8ab6d780fcae53c1f94d14c609` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/24#issuecomment-5836927727); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36169576241) |
| [#25](https://github.com/mgalic01/adaptive-market-engine/pull/25): Funding parser/signal; extreme-rate rounding corrected in #38; not wired into replay. | `4a4ac96c72eda08d83ad8d3fdbe6571f612e5798` | `1237ec2f972fc32a93b3b843b3b3b1e28fe1af31` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/25#issuecomment-5837078236); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36170662790) |
| [#26](https://github.com/mgalic01/adaptive-market-engine/pull/26): Handoff and baseline task; task outcome in #40. | `9cbc31bc1acfff8682e7cd7a7ab9ee99699c4316` | `a0548a7396df0c563c1efa329ddae5d84b42dda5` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/26#issuecomment-5837282066); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36172150345) |
| [#27](https://github.com/mgalic01/adaptive-market-engine/pull/27): Owner-approved command worker; same-machine publication defect fixed in #36. | `c1dae266adafb013fc17079f99a4ca44e737fb11` | `5811fce2d07c4e067d60c55d45d1c8e6b2e6e84f` | [discussion](https://github.com/mgalic01/adaptive-market-engine/pull/27); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36173734530) |
| [#28](https://github.com/mgalic01/adaptive-market-engine/pull/28): Temporary audit instruction; removed by this retrospective PR. | `c518b21460263a2b32083fda150d4d18b7bb9c65` | `3932c3e1ba680e8e104fdb50bdddbd65a497dc4c` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/28#issuecomment-5837622236); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36174273859) |
| [#29](https://github.com/mgalic01/adaptive-market-engine/pull/29): Owner-approved automatic task start; queue issue fixed in #35. | `61e4f5fdafffe753cc6ac285714fc0586373f368` | `a3cff9a827768ad6e50f1b1082f79d47fdcf8c5b` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/29#issuecomment-5837762953); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36175420267) |
| [#30](https://github.com/mgalic01/adaptive-market-engine/pull/30): Original answer extraction defects reproduced; replaced by #39/#44. | `7c68cee9f3ce22137f0d01250471df8e86df5bc0` | `661493f86e6bda3c14b5afc79168b7865c1083fc` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/30#issuecomment-5837894534); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36175812782) |
| [#32](https://github.com/mgalic01/adaptive-market-engine/pull/32): Quick reference; historical exceptions to exact-head reviews recorded below. | `f0ba9356033aa353a0093be211f890bc0ff530b9` | `08398235b51722657f28da4d7bf82814fe119bbf` | [discussion](https://github.com/mgalic01/adaptive-market-engine/pull/32); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36176696520) |
| [#34](https://github.com/mgalic01/adaptive-market-engine/pull/34): Hash-pinned package/cache/retry path; no paid install/run used in this review. | `1e87f054144405fd66023d742e658da616ddaddf` | `9934d815369727a0f5500cb5db577c4060c03cc1` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/34#issuecomment-5838193691); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36178632479) |
| [#35](https://github.com/mgalic01/adaptive-market-engine/pull/35): Job-level bounded queue removes ordinary-comment cancellation; queue limit is 100. | `138f22a91627415b91b845eff8b24cc09600b721` | `2c615fb6272466dd3257c714a5d890a2e8844454` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/35#issuecomment-5838793983); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36183579958) |
| [#36](https://github.com/mgalic01/adaptive-market-engine/pull/36): Fresh publisher separates repository-write credentials; Windows fixture limitations corrected. | `d82f4dd82dedff70eb894e46e9b5bbd5c4863b5a` | `ee755675e85c9c023ef0f395a328df50b70c47c4` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/36#issuecomment-5839491751); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36188644365) |
| [#37](https://github.com/mgalic01/adaptive-market-engine/pull/37): Closed-thread/sweep rules; reconcile merge feedback on open threads. | `f936f817d7b02dfa31eba8d680f4609e9d0e7f51` | `cc4d56a40e9dd06cc73c05b9ab981d682a157eee` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/37#issuecomment-5840596374); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36197367636) |
| [#38](https://github.com/mgalic01/adaptive-market-engine/pull/38): Nested instrument validation and funding precision correction independently inspected/tested. | `2ebe8d0e70d1aea2945a07ca0a5df6bba02f4337` | `6185a3426ea0010c2f37eaa44affd76a56a70112` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/38#issuecomment-5840224130); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36194201936) |
| [#39](https://github.com/mgalic01/adaptive-market-engine/pull/39): Shared extractor rejects missing markers and final failure; regression suite reviewed. | `c4f8dfaa355a1bc2594f9783b8c46c3f8fff50aa` | `be500b67b94fadd35de98b087d36c7116dfc8b88` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/39#issuecomment-5840569307); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36197169912) |
| [#40](https://github.com/mgalic01/adaptive-market-engine/pull/40): 40 baseline trace fingerprints verified against candidate table; summary-independence claim corrected. | `1dacd054258acb279a6f39d3901e416ed8b0d410` | `0905a228756fe27777e712f997432b5633966c28` | [discussion](https://github.com/mgalic01/adaptive-market-engine/pull/40); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36198014956) |
| [#41](https://github.com/mgalic01/adaptive-market-engine/pull/41): Published branch remains usable when PR creation is denied; after-push alert accurate. | `691350311fc7c435ca216c8e7d650413cfb2f48f` | `99c425bdac47cd69d83e1746f8efab66e2aadb18` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/41#issuecomment-5840811558); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36199165163) |
| [#42](https://github.com/mgalic01/adaptive-market-engine/pull/42): Owner-authorized task batch; report evidence reviewed without rerunning matrix. | `876f7ce9d3a32b4a31bc558a0eb038a462c1472e` | `4b9be3d57664f654a12dd4d0f1c137453ee2a27b` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/42#issuecomment-5841281296); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36202796881) |
| [#43](https://github.com/mgalic01/adaptive-market-engine/pull/43): Catch-up/lessons record; merge SHAs cross-checked. | `b136639aa12e8baffd77b19908aa8504b5ca620a` | `328b1b1f26d866435456603a8eddb420461f0e40` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/43#issuecomment-5841633156); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36203774759) |
| [#44](https://github.com/mgalic01/adaptive-market-engine/pull/44): Header/signature robustness; tool boundary and terminal status fixtures. | `670085b2a027483e8558c0a60362f272329dfeec` | `ee9e3775c914daf7aa4f0ec89a66c7c9e35dfd00` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/44#issuecomment-5842548617); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36213072898) |
| [#49](https://github.com/mgalic01/adaptive-market-engine/pull/49): Inventory corrections retained; first-file versus first-clean month kept distinct. | `e9fa449e0a18ec1edd044fc19dae6d37b2751fe2` | `60738b05f19292f0bca24118ee59ddb23b75ef8a` | [discussion](https://github.com/mgalic01/adaptive-market-engine/pull/49); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36220759750) |
| [#50](https://github.com/mgalic01/adaptive-market-engine/pull/50): Docs audit historical counts; merged stale-role corrections located; not a current link census. | `dd3b2755c0eab3fdc9783ef5e02b0046c42d972b` | `24b25dad0d24b47ca69b910ebb02658937336df0` | [discussion](https://github.com/mgalic01/adaptive-market-engine/pull/50); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36220700229) |
| [#51](https://github.com/mgalic01/adaptive-market-engine/pull/51): Test coverage report led to #54; historical Linux flakiness runs not rerun here. | `7c4d4d09efc5211b1146abffd05f6c4556efbe74` | `a893604f1092c98e7ca592a0727ca69fe71d0075` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/51#issuecomment-5842633485); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36213756598) |
| [#52](https://github.com/mgalic01/adaptive-market-engine/pull/52): Diagnostic V0 fails C1/C2; recomputed table evidence, not a selection decision. | `5c7dd4841d261f9a254cb48c70a6df2c67a755b4` | `da281af30e39f24f8c4f3c65d7cf8372db0d1ef7` | [discussion](https://github.com/mgalic01/adaptive-market-engine/pull/52); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36215214197) |
| [#53](https://github.com/mgalic01/adaptive-market-engine/pull/53): Lessons and tasks; owner-approved task publication distinguished from code authorization. | `40f6fbdf92a64c354f7139893480e19c750d75fd` | `49664914c2305419952042eed186ca69ea5fa3c9` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/53#issuecomment-5842833392); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36215337820) |
| [#54](https://github.com/mgalic01/adaptive-market-engine/pull/54): Loader/gateway tests checked with actual fixtures; full Windows suite exposes separate #67 issue. | `645594977ebb961a07ecfc9af17c9c4d0a8517c3` | `ab8388549d7e4827230a49f962ac71556570ce0a` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/54#issuecomment-5842830245); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36215309111) |
| [#55](https://github.com/mgalic01/adaptive-market-engine/pull/55): Owner intentionally retains 12% emergency stop and 10% acceptance C1. | `1410892b7df1d5fa6b409ace9ea6641397c0a8c3` | `01a56d5512c02bcb3005cc4d39b364ae2b55bb9e` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/55#issuecomment-5843607936); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36221554493) |
| [#56](https://github.com/mgalic01/adaptive-market-engine/pull/56): Batch status/lessons; no strategy change. | `8df478ff6784229a1106ce44995bceca35bc7978` | `d3cd6e1b0899249ec7ac2e9fc3ebb6b4b8706597` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/56#issuecomment-5843610616); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36221575842) |
| [#59](https://github.com/mgalic01/adaptive-market-engine/pull/59): Corrected anomaly counts preserved; repair proposal is not parser adoption. | `853d7801e241934b3042376482205e2d0690dffa` | `581302ed4732081468f3e627ed8ce7c8fad289d0` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/59#issuecomment-5844136749); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36225718158) |
| [#60](https://github.com/mgalic01/adaptive-market-engine/pull/60): Missing-both-hour omission acknowledged; corrected measurement in #66. | `7ae6d0fab8a63d1d7baaecd2e907482fe4525d94` | `aeef6be1b9ea392089b0cca2dce469a5d7c1cf27` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/60#issuecomment-5844146732); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36225839263) |
| [#61](https://github.com/mgalic01/adaptive-market-engine/pull/61): Lessons from erroneous reports; no runtime change. | `b884e02b832c610b8a80c7dae18bdc06bbf76bda` | `f3704f475ef578a947fecd121474fa675e6b9b63` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/61#issuecomment-5844154196); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36225754263) |
| [#62](https://github.com/mgalic01/adaptive-market-engine/pull/62): Revised audit tasks; denominator excludes unparsed months by definition. | `8fe6484447bcc86ec825cdefa5bb1e79c372e636` | `5da81f6ffda20b34086155d6432328c311190eba` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/62#issuecomment-5844642261); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36226588744) |
| [#65](https://github.com/mgalic01/adaptive-market-engine/pull/65): 82/99/107 arithmetic checked; local repair-rule eligibility, not full replay validity. | `b2684b961ca1c9d5009555e22a97f6c60c3a88ab` | `817a49e97f01f72e0c70d1c98a856b6fcf4f5eb7` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/65#issuecomment-5846051325); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36240255326) |
| [#66](https://github.com/mgalic01/adaptive-market-engine/pull/66): 14 events/58 hours/6,646 mismatches checked from tables; parsed-subset limit clarified. | `169e84e088581b08d86f056da421e1eef22b6a56` | `c4cf452ad365ec446294fbf03bc19c2d79a2b7b2` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/66#issuecomment-5846010298); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36239889886) |
| [#67](https://github.com/mgalic01/adaptive-market-engine/pull/67): Confirmed scope/rename/Windows defects; focused workflow fix. | `071dad2bb3e9f63f64fad8f8e095d5f0e88aef6f` | `896c902f02723bb13db0fd4347d0a9ac75a6b874` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/67#issuecomment-5846012835); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36239329435) |
| [#68](https://github.com/mgalic01/adaptive-market-engine/pull/68): Startup order reviewed; GPL owner confirmation remains pending, no assumed new authority. | `a5bb058813f78270c61c2b7e94d70ac36753cf1c` | `cea40e3bef9c6b5ce79f4cf7c7fa758c028f630b` | [Bob](https://github.com/mgalic01/adaptive-market-engine/pull/68#issuecomment-5846117674); [quality](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36240785780) |

**Numbers that are issues, not PRs:** #31 is the first task-run issue (later report #40); #45–#48 are report-ready issues for #49–#52; #57/#58 correspond to #60/#59; #63/#64 correspond to #66/#65. They have no merged commit. The direct README commit `a54d1647be4826c375d4cd110a64ca9de9538734` was also inspected as part of the intervening history.

**Open heads at the review checkpoint:** #33 `9b7e5d5398ede31ebdb8d7c1aff3bc55dde26bb9`; #69 `4d3ae9d4841408445b848f80da53ab67e1c043c4`; #70 `e172a936093a06fcaa4486ea2b066fedd0abcea4`. These are not merged work. #69 is the return handoff; #70 has the blocking integrity finding below. Later heads need separate verification.

## Confirmed findings and disposition

### R1 — P1: unverified cached data can be scored as usable in open #70

At the reviewed #70 head, `audit_run._fetch` catches every `DataError` from
`fetch_file` and returns `unparsed`. That includes missing/malformed published
checksums and SHA-256 mismatch, not just parsing errors in verified bytes.
`audit_rules` then calls `_rows` on a pre-existing local ZIP.

**Independent reproduction:** populate temporary 1m/1h caches with the project's
`FakeArchive` and one synthetic hour, then replace both checksum responses with
64 zeroes. `_fetch` returns `unparsed`; `audit_rules` reports one narrow and one
refined usable pair-month from stale bytes. No external data or real secret was
used. Both the runtime reviewer and parent Codex ran this reproduction; Bob
independently confirmed the static path in comment 5846317344.

**Disposition:** blocking #70; Claude owns the fix. Parsing failures may enter the
repair audit only after successful integrity verification; checksum failures must
propagate. Tests must cover changed/malformed/missing checksum and legitimate
verified-but-unparsed input. See [the finding](https://github.com/mgalic01/adaptive-market-engine/pull/70#issuecomment-5846313586).
This flaw is in an open PR, not evidence that merged #65/#66 data failed hashing.

### R2 — P2: replay journal rounds valid fill amounts differently from accounts

The simulator updates balances at Decimal precision 50, but `_record_fills` used
the caller's ordinary precision 28. An accepted 18-decimal price/quantity fixture
produces account fees `0.002895899852004268860190519987501905210` and journal fees
`0.002895899852004268860190519988`, failing cash/fee identities. This is a
pre-existing runtime defect discovered in the expanded whole-code review, not a
regression attributed to a particular #30–#68 merge.

**Disposition:** [#72](https://github.com/mgalic01/adaptive-market-engine/pull/72)
uses a local precision-50 context for
journal calculations. Regression evidence includes an actual matched buy, partial
maker sell and taker exit; the caller context remains unchanged. Two 600-bar
synthetic V0 replays (38 fills each, both intrabar paths) have identical complete
account state and equal metrics before/after. Existing lower-precision historical
results are not claimed affected; the large historical matrix was not rerun.
Protected reserves and execution policy are unchanged.

### W1–W3 — P2: report-scope bypasses and Windows regression

In #67, comparing only index link targets allowed a new report to rewrite existing
approval/status text and policy prose or duplicate old rows. Dropping the source
from `R100 LICENSE -> docs/reviews/2026-09-26-bob-x.md` also hid an unrelated file
deletion. On Windows, `str(INDEX)` rejected valid Git forward-slash paths.

**Disposition:** [#71](https://github.com/mgalic01/adaptive-market-engine/pull/71)
requires one added report, one modified index and exactly one inserted row with
all existing index content preserved; rename/copy/malformed status records fail
closed. The [focused handoff](https://github.com/mgalic01/adaptive-market-engine/blob/326db155016dd0307d8d5ff65ba616363fce17a9/docs/reviews/2026-09-26-codex-report-scope-fixes.md) records tests.
Two symlink fixtures skip only Windows privilege error 1314; Linux still tests
production rejection. This fixes fixture setup, not an exception to validation.

### D1–D4 — P2: evidence claims exceed the measurements

Corrections in this review preserve historical reports and append explicit dated
annotations. Embedded script sources and their hashes are unchanged; copyable
line-range verification commands are updated to the new positions.

- **#40:** Bob regenerated 40 baseline trace hashes and fill counts, matching
  Claude's candidate table. He did not independently run the candidate tree or
  compare economic summaries. Codex compared the published tables, not the data.
- **#65:** 82 narrow and 99 refined eligible pair-months (107 with files) count
  different local repair conditions. They do not establish full replay validity,
  complete hourly/daily checks, filters, warm-up or the spec comparison mask.
- **#66:** 14 events, 58 hours, seven major events and 6,646 mismatch hours describe
  parsed pair-months within the ten-pair basket. Unparsed periods remain unknown;
  these are not a complete exchange-wide outage census or proof of outage causes.
- **#59/#61/#69:** 61,203 + 4,804 + 172 = **66,179 unaligned-open rows**. Adding the
  original 20 other rows yields **66,199 other-class rows**. These categories must
  not be conflated. The practice lesson/report are corrected here; Claude was
  asked to correct #69's handoff separately.

## Earlier defects now fixed; no duplicate fix PR

The initial audit at `1e87f05` reproduced, using dummy credentials and a temporary
Git repository, a worker committing prohibited changes before the status check
and a Git hook executing with the later publisher token. Owner acceptance of
Bob's own-key exposure did not authorize repository-write credentials on that
worker. #36 now uses a separate clean publisher, constrained artifact validation
and restore-only post-worker caches; no worker Git state or executable is copied.

Both old jq extractors also lost `FLAGGED` when the answer body mentioned IBM Bob,
accepted an earlier success followed by terminal failure, and could publish
unmarked prose. #39/#44 replaced them with the shared tested extractor. Current
fixtures cover markers, final result, signatures, tool boundaries and byte limits.
#35 moves queueing behind the job gate and enables the documented bounded queue;
ordinary comments no longer replace queued real requests. The limit remains 100,
not an unbounded delivery guarantee.

#38 closes post-merge malformed instrument-filter and extreme funding-rate
precision findings on #21/#25. The funding rule still retains invalid records,
uses only records available by the observation time, rejects mixed cadence and
gaps, and recovers after three consecutive valid uniform records. Exactly at the
scheduled successor plus 60 seconds it is unavailable. An unseen shortened
interval before the old deadline remains the documented information limitation,
not a reason to substitute future data. G is still not wired into replay, so the
existing-grid/exit integration check remains future work.

## Independent verification and practical limits

- Original Windows Python 3.12.14 baseline at `1e87f05`: 256 tests and 436 subtests
  passed; lint, format, types, Bandit and dependency audit passed.
- Latest main `a5bb058`: 9,406 synthetic funding decisions across 250 generated
  histories (deterministic seed 741) match an independent linear reference,
  including NaN/sNaN/infinity,
  invalid intervals, publication boundaries, cadence changes and gaps.
- Latest main full Windows suite exposed the three failures described above;
  do not replace that result with the historical Linux green runs. Ruff/format
  (140 files), mypy (37 source files), Bandit, dependency audit and five embedded
  script-hash checks pass. The workflow fix's Windows run passes 355 tests and
  521 subtests, with two explicit symlink-privilege skips.
- All four workflow YAML files parsed and all 32 Bash blocks passed syntax checks.
  Exact publisher-step fixtures with fake Git/GitHub commands verified successful
  branch/PR output, successful branch fallback when PR creation fails, and failed
  push with no published-branch output. These are isolated tests, not live-run proof.
- The research reviewer independently recomputed all 40 published trace/count
  pairs, 107/82/99 repair totals, 14/58/seven/6,646 event totals, C1 failures (5/8),
  negative C2 medians, C5's `12517/7280` mean and C6's 8/8 wins from report tables.
  Rounded table inputs bound that arithmetic check. External archives, uncommitted
  raw result files and the full historical replay matrices were not regenerated.
- #52's reference-fee claims lack a published per-run table here, and the report's
  cost-filter causal guess was not verified from raw decision logs. Those claims
  remain limited, as Claude already noted in comment 5842630154; primary-fee
  arithmetic does not validate them. The actual report is unchanged between
  Bob-reviewed `5bfa55fe952976a1962e5079d24d775d920dfe66` and integrated
  `da281af30e39f24f8c4f3c65d7cf8372db0d1ef7`.
- Runtime review traced public GET-only market-data boundaries, replay timing and
  checks, paper execution, reserve/account transactions and storage idempotency.
  No live-order path or protected-reserve spending was found in that inspected
  scope. Tests/review are evidence, not a proof that every possible input is safe.

## Authority, strategy decisions and next owners

The historical merge commits and discussions explicitly record the owner's
temporary merge-on-Bob-positive-review exception while Codex was unavailable.
Some early approvals name a preceding implementation head followed by an index
merge or documented narrow correction (#21/#22/#27/#32 and some report branches);
they must not be presented as an exact-head approval if they were not. The current
startup rule requires current-head evidence. The return handoff ends the temporary
exception: Codex resumes review and merge responsibility. Agent agreement does not
substitute for owner approval of risk-policy choices.

Owner-approved residual risks remain accurately bounded: the command worker can
read its own Bob key and has open internet; the prompt/archive-name scan is not
technical prevention of all reserved-data access. No new restriction is imposed
as if those decisions did not exist. The separate publisher protects repository
write authority. Vendor tool-group/workspace behavior is still a dependency for
read-only Bob; a prompt and an approval comment are not a security boundary.

The 12% emergency stop and 10% C1 acceptance threshold are intentionally distinct
per #55. V0 continues to fail C1/C2; this audit does not retune it or relax criteria.
Parser adoption, a DOGE price tolerance, the outage/fold policy and confirming the
GPL instruction's owner provenance remain explicit policy items. Existing volume
tolerance does not authorize price tolerance.

**Next:** Codex publishes a point-by-point **AGREE WITH CHANGES** response to #33,
covering prior exposure, actual warm-up readiness, synchronized synthetic provenance,
DSR prerequisites and registration before experiments. Claude/Bob must acknowledge
substantive revisions before that PR merges. Claude fixes #70 and its return-note
count; Codex verifies new heads. Code fixes and this documentation PR require their
own green checks and review before merge. No task-file publication or reserved-window
approval is implied by this handoff.

## Integration checkpoint

#71 merged as `5b60dded5d94cb4a83e9a9c8937d9b268fdf10ac` after parent independent
review, Bob's exact-head NOTED and successful Linux `test-and-audit` job
108406003896. The optional automated Claude reviewer failed before producing a
verdict and was not counted as approval. The owner then confirmed Claude is
unavailable until 18:10, so Codex is also taking the #70 correction; the original
finding remains preserved above. #72 is integrating the workflow fix before its
final Windows check. The substantive #33 response is now published at
`ad66e12a019939f865d3b085b28f91ba3085ad2d`; Bob agreed to all four response sections
in comment 5846399230. Claude's acknowledgment of those revisions remains pending.
