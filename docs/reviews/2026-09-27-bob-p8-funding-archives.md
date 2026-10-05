# P8 archives for G and H: funding and daily, development months only

Index: PASS — 60 funding archives (2020-01 to 2024-12) fetched and verified, and 104 distinct daily files surveyed: 101 archives fetched and verified, plus SOLUSDT's 3 expected absences before its listing; all known values match; RESULT 0 problem(s); reserved window clean; proposed manifest additions in data/p8/practice-2022.additions.json and data/p8/verify-2024h1.additions.json.

Script: `data/p8_archives.py` 35a4ea2cf36cae67339784fada62063880a41455d1a60316902f93c52363c75e

Run on commit 344f9aeb01f182303b5b42145a08984c8c754195, Python 3.12.14, Tue Sep 29 11:12:08 UTC 2026.

## Steps 1 to 3

**Step 1:**

```text
$ date -u
Tue Sep 29 11:12:08 UTC 2026
$ git rev-parse HEAD
344f9aeb01f182303b5b42145a08984c8c754195
$ python --version
Python 3.12.14
```

**Step 2:**

```text
$ mkdir -p data
$ sed -n '423,900p' docs/tasks/2026-09-27-bob-p8-funding-archives.md > data/p8_archives.py
$ sha256sum data/p8_archives.py
35a4ea2cf36cae67339784fada62063880a41455d1a60316902f93c52363c75e  data/p8_archives.py
```

Hash matches the task-file pin exactly.

**Step 3:**

```text
$ python data/p8_archives.py --self-test > data/p8-selftest.log 2>&1; echo "exit $?"
exit 0
```

Self-test log follows in 6b.

```text
SELFTEST allowed('2024-12',) -> allowed (expected allowed)
SELFTEST allowed('2020-01',) -> allowed (expected allowed)
SELFTEST allowed('2025-01',) -> OutOfScope (expected OutOfScope)
SELFTEST allowed('2019-12',) -> OutOfScope (expected OutOfScope)
SELFTEST allowed('2024-1',) -> OutOfScope (expected OutOfScope)
SELFTEST kline_get('/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2024-12.zip',) -> network (expected network)
SELFTEST kline_get('/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2025-01.zip',) -> OutOfScope (expected OutOfScope)
SELFTEST kline_get('/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2025-01.zip.CHECKSUM',) -> OutOfScope (expected OutOfScope)
SELFTEST kline_get('/data/spot/monthly/klines/BTCUSDT/1d/',) -> OutOfScope (expected OutOfScope)
SELFTEST funding_get('/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-12.zip.CHECKSUM',) -> network (expected network)
SELFTEST funding_get('/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2025-01.zip',) -> OutOfScope (expected OutOfScope)
SELFTEST funding_get('/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2025-01.zip.CHECKSUM',) -> OutOfScope (expected OutOfScope)
SELFTEST funding_get('/data/futures/um/monthly/fundingRate/BTCUSDT/',) -> OutOfScope (expected OutOfScope)
SELFTEST funding_get('/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-12.zip?prefix=x',) -> OutOfScope (expected OutOfScope)
SELFTEST funding_file('2025-01',) -> OutOfScope (expected OutOfScope)
SELFTEST open_funding('2025-01',) -> OutOfScope (expected OutOfScope)
SELFTEST month_range('2024-11', '2025-02') -> OutOfScope (expected OutOfScope)
SELFTEST requests that reached the (disabled) network: 2
SELFTEST wrong outcomes: 0
```

## Steps 4 and 5

**Step 4:**

```text
$ python data/p8_archives.py > data/p8-run.log 2>&1; echo "exit $?"
exit 0
```

**Step 5:**

```text
$ sha256sum data/p8_archives.py data/p8-selftest.log data/p8-run.log data/p8/requests.txt data/p8/*.additions.json
35a4ea2cf36cae67339784fada62063880a41455d1a60316902f93c52363c75e  data/p8_archives.py
e8f80270b5da4d92428e1b9d16742fa38b3848f52565a4c58fb78d01bbd8a358  data/p8-selftest.log
919ea9f967e5e329d254ec712f5a54f1eedeaa3fefb28ccd2b2abc3cc552bf02  data/p8-run.log
4dda3006dff0517ce78aece7b13134dde2f5c943dcb2f062b4fe6d0afd23b951  data/p8/requests.txt
0ae06b5d4b0644ed455bb72e7eaf346d2e9c80625087b21bdc08e0f1abb1ba1e  data/p8/practice-2022.additions.json
10d35d4320397f8359e5b29d6b72eda399fc0e25aefbb017cb1d29c2e03b03d2  data/p8/verify-2024h1.additions.json

$ find data -type f | grep -cE -- '-20(2[5-9]|[3-9][0-9])-[0-9]{2}\.(zip|csv|zip\.CHECKSUM)$'
0
```

The `grep -c` exit status was 1 (expected: no matches). Reserved-window file count is 0.

The run log follows verbatim, including every table produced by the script.

```text
INPUT ok f259445fd78d840a5c758026c6ee6bd717ea47656cee228111a397d9fa1d7bdd  config/datasets/practice-2022.toml
INPUT ok e8665c9a9e2b3117f4e825989b81a0bfe98dfa42eca84ae81fd236d8092ae288  config/datasets/practice-2022.manifest.json
INPUT ok a5fda6c8a8c2a78fce986634279890314c94f46523ac8dd1356d0e991df653e4  config/datasets/verify-2024h1.toml
INPUT ok 48a239f4dfbe923b5a3c9c29336c884c40435617206d5c75b76b8461b0aaa9cf  config/datasets/verify-2024h1.manifest.json
INPUT ok b9d3ec73f3f2f7ac39ff1dc4ee85098388dea19659d9e881b91e40844b919d21  docs/reviews/2026-09-25-bob-funding-cadence.md
INPUT ok 9c3b6b5a84b3c58037c85bf32caadf7ae63622bfa612c10beb6f49f9f99150a5  src/crypto_grid_bot/backtest/dataset.py
INPUT ok 34b0558761c9861782351833df5d3f645730a4011fe3be90d70de36082357aee  src/crypto_grid_bot/backtest/funding.py
INPUT ok ce12820936efe09f55658c418e8ef65e393f2f56882b320077efef99408491cb  src/crypto_grid_bot/backtest/klines.py
INPUT ok c6ee5a25a1572957c1115bb56cdab2c5ba714d56d26036b59b6246e1dd8c97a7  src/crypto_grid_bot/market_data/client.py
INPUT ok 5dfb8e837b24e38a95beefccc4efddcc10571f786ee5b563e8f3a60e0bd587c9  src/crypto_grid_bot/market_data/parsing.py
PLAN practice-2022: 1d ['BTCUSDT', 'SOLUSDT', 'XRPUSDT'] 2020-05..2021-08 = 48 files, already in manifest 0; funding 2022-04..2023-01 = 10 months
PLAN verify-2024h1: 1d ['ADAUSDT', 'BTCUSDT'] 2020-05..2023-04 = 72 files, already in manifest 0; funding 2023-11..2024-06 = 8 months
PLAN funding months 60, unique 1d files 104, latest month 2024-12

## Funding archives, BTCUSDT, per month

| Month | Status | Records | Expected (3 per day) | First calc_time | Last calc_time | funding_interval_hours | Invalid | Max offset ms | Bytes | SHA-256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2020-01 | ok | 93 | 93 | 1577836800000 | 1580486400000 | {'8': 93} | 0 | 2 | 825 | 7f81b2f3694d13779e7e896b69d60cd61e9444d7b9f9e90df761935e1c1b76e2 |
| 2020-02 | ok | 87 | 87 | 1580515200000 | 1582992000000 | {'8': 87} | 0 | 15 | 885 | 6599466d108d120c64a078824326c063ed2d4335b3292e52c5e572f79166533a |
| 2020-03 | ok | 93 | 93 | 1583020800000 | 1585670400001 | {'8': 93} | 0 | 6 | 928 | eee845fde6336e29d25889563cba3d2cff2d4d640e51fb1f82ae9b28cedaee77 |
| 2020-04 | ok | 90 | 90 | 1585699200002 | 1588262400000 | {'8': 90} | 0 | 6 | 867 | d009ce034d08c3dcf3e7f874b0f8b0ec76ba507bc6bb4e007e541df537bafbce |
| 2020-05 | ok | 93 | 93 | 1588291200000 | 1590940800000 | {'8': 93} | 0 | 11 | 839 | 3f2b56dd6b9a42457009bb367d0adadd3cf7e2216cd325172d0089e3883125a8 |
| 2020-06 | ok | 90 | 90 | 1590969600000 | 1593532800002 | {'8': 90} | 0 | 9 | 791 | 30b3470ff98576578973d75e3c157a5cbf1778b11e4c26b4b4ff70a3cbb348ec |
| 2020-07 | ok | 93 | 93 | 1593561600002 | 1596211200000 | {'8': 93} | 0 | 6 | 712 | 18dae7b11075fc0fba79ad47df46683415cba5d027caa69c66bc2a5c9d9b459a |
| 2020-08 | ok | 93 | 93 | 1596240000005 | 1598889600001 | {'8': 93} | 0 | 17 | 854 | e6f6d1749f674c85d4766e0eb36af6ea40d91a0674234d30df80eb9876b094e3 |
| 2020-09 | ok | 90 | 90 | 1598918400000 | 1601481600000 | {'8': 90} | 0 | 45 | 838 | 7ae9a3b6afb2dc06e46080582908ec8c27063b707a14c7f1e679dc991ff48032 |
| 2020-10 | ok | 93 | 93 | 1601510400000 | 1604160000000 | {'8': 93} | 0 | 15 | 828 | 4c55b191c101f39c7fb193a6529665dd9e83302ca21876521e4c93b3902e9fb1 |
| 2020-11 | ok | 90 | 90 | 1604188800000 | 1606752000000 | {'8': 90} | 0 | 17 | 854 | 676356a2d075caa51b4f8ada026e9430dc320ffd23d2343b13b7aa25324ed6d1 |
| 2020-12 | ok | 93 | 93 | 1606780800000 | 1609430400010 | {'8': 93} | 0 | 33 | 852 | d7390f90edf54cc4ad9bbe78e2f6b291ae06ad9539f591a2d0fce445873bbd63 |
| 2021-01 | ok | 93 | 93 | 1609459200002 | 1612108800000 | {'8': 93} | 0 | 20 | 981 | cff916dc4b638ec3de97828e8911cd91cf7d7a3d0836ec0175869c374e66823d |
| 2021-02 | ok | 84 | 84 | 1612137600001 | 1614528000000 | {'8': 84} | 0 | 25 | 956 | 819a7b107443686adb313fc5fc223302a29f3981e1d1bd9828ad0ade65a8a8af |
| 2021-03 | ok | 93 | 93 | 1614556800000 | 1617206400000 | {'8': 93} | 0 | 30 | 918 | 2125fd300848938c7b992b8f7b7b5007d5b277a4ff1ebda7da083b40242729da |
| 2021-04 | ok | 90 | 90 | 1617235200025 | 1619798400003 | {'8': 90} | 0 | 25 | 914 | 9cd888e3b0a1954813d0062c2e60426fdc8e34a7f258f6838371ec67f535b028 |
| 2021-05 | ok | 93 | 93 | 1619827200002 | 1622476800000 | {'8': 93} | 0 | 43 | 960 | ed934afb9cf84df6ecae742e755147333a84244836a66b51523abc66dd5f63af |
| 2021-06 | ok | 90 | 90 | 1622505600001 | 1625068800005 | {'8': 90} | 0 | 44 | 883 | 7b8d9bfb8816636b800764dafb2aa2307d19166c695bfa245adbf7d01d61f766 |
| 2021-07 | ok | 93 | 93 | 1625097600000 | 1627747200003 | {'8': 93} | 0 | 46 | 973 | 8ab3df641d3bcf40527491f8e26d046ad2b662d1950ead9555ad32975571b7fe |
| 2021-08 | ok | 93 | 93 | 1627776000005 | 1630425600003 | {'8': 93} | 0 | 21 | 781 | 7eb681cc45b94176f4b9192a62c3a1925d79031ba001cea2d8dec6ff6e5b9c35 |
| 2021-09 | ok | 90 | 90 | 1630454400000 | 1633017600005 | {'8': 90} | 0 | 47 | 828 | 03f25a7c25eef18d5f5b5b7bb0b664cab7a210b409f37e95a54e141808a0752d |
| 2021-10 | ok | 93 | 93 | 1633046400012 | 1635696000001 | {'8': 93} | 0 | 22 | 951 | f25820d6add687addbca3ef43bee58f70853a6da53832a0c1bc22d00dc8ec64a |
| 2021-11 | ok | 90 | 90 | 1635724800009 | 1638288000000 | {'8': 90} | 0 | 19 | 919 | e2e6b2d7218607e7e4a38137d50f553c2cfb901275c19edf567024c1cc6de85f |
| 2021-12 | ok | 93 | 93 | 1638316800000 | 1640966400000 | {'8': 93} | 0 | 31 | 815 | bf3ce484faf41d7dccfd38c5cc3d8de34d8297df30ab10784e874cc10fd1b310 |
| 2022-01 | ok | 93 | 93 | 1640995200006 | 1643644800000 | {'8': 93} | 0 | 28 | 906 | 22ee19079b620f5c6d820e7d7f8bafa7fde866d89bd664863b8bd527749c12cb |
| 2022-02 | ok | 84 | 84 | 1643673600010 | 1646064000002 | {'8': 84} | 0 | 23 | 890 | fa95088258a905c79ab79e8984d2f6f66933ec2e814dbab4ef9da89b01ab484a |
| 2022-03 | ok | 93 | 93 | 1646092800002 | 1648742400015 | {'8': 93} | 0 | 28 | 904 | 4cf0883bc07f4ed4cdd3b0d8c0d166b4d15d21e666ab752f9f44401af4d6172f |
| 2022-04 | ok | 90 | 90 | 1648771200000 | 1651334400015 | {'8': 90} | 0 | 31 | 926 | 57e2776cc68b3169fc9f8632dad67278f470cd453407a8ebe6c87963c8a31357 |
| 2022-05 | ok | 93 | 93 | 1651363200000 | 1654012800000 | {'8': 93} | 0 | 25 | 915 | bced8a5013d09742b96682e6fd01ad4456213515a03d7586ec2b1f2689af5255 |
| 2022-06 | ok | 90 | 90 | 1654041600000 | 1656604800000 | {'8': 90} | 0 | 25 | 966 | 0cd0708f8903829eb46f98cf60f4b2516c986e1ccddf6620a5912b48e16baf93 |
| 2022-07 | ok | 93 | 93 | 1656633600001 | 1659283200019 | {'8': 93} | 0 | 22 | 917 | 29d58cce0cd45f74c6a112039835c6d9ee5a7e60e7c38c2503beb7930453a4fe |
| 2022-08 | ok | 93 | 93 | 1659312000010 | 1661961600013 | {'8': 93} | 0 | 21 | 997 | 6f4f0c6c84c05694b4b4a5c085776730fd4059723eecd98ee6ffeb3fde4da811 |
| 2022-09 | ok | 90 | 90 | 1661990400012 | 1664553600007 | {'8': 90} | 0 | 28 | 960 | d62cd4e13009de37add446dc4f63ead4c56dcc4955a1e60f6726bcadc5a68fa9 |
| 2022-10 | ok | 93 | 93 | 1664582400008 | 1667232000010 | {'8': 93} | 0 | 27 | 950 | ad9efed10d4ca1567b865d7a158790977cec1b925395634217069df6696c8bc9 |
| 2022-11 | ok | 90 | 90 | 1667260800000 | 1669824000015 | {'8': 90} | 0 | 27 | 1000 | 8febe5bec1a029e993bbf27490761f8c47c32849bf7dd13441b2b2f6ec1ffb51 |
| 2022-12 | ok | 93 | 93 | 1669852800001 | 1672502400000 | {'8': 93} | 0 | 27 | 982 | 4218c78331bcc4dbeb5768fa112242a880971c1f2cfd1d3f32aaa26ca34069af |
| 2023-01 | ok | 93 | 93 | 1672531200000 | 1675180800007 | {'8': 93} | 0 | 23 | 863 | 05e3df32f28d0d50f4c5a280adee9368b4a66fc68c6ddca1b3277087ac0d19f5 |
| 2023-02 | ok | 84 | 84 | 1675209600013 | 1677600000005 | {'8': 84} | 0 | 23 | 808 | 5227accd9aaa59f71f5e682abffb58be5f99573ed208ab968b1704c81ac11345 |
| 2023-03 | ok | 93 | 93 | 1677628800016 | 1680278400011 | {'8': 93} | 0 | 27 | 956 | ab022adff9b853d2f33cf80154e77c770f57c3392f0bbc36564b2e2cdbd0e872 |
| 2023-04 | ok | 90 | 90 | 1680307200000 | 1682870400010 | {'8': 90} | 0 | 27 | 952 | 2931039d26818edc65d4faefba84945fd1ba52989dd58fb127dc3cd7a12c7fbf |
| 2023-05 | ok | 93 | 93 | 1682899200004 | 1685548800000 | {'8': 93} | 0 | 29 | 983 | 5d026fece46df86293054c8c56c2c8de575d30161b82979b11831831217a246e |
| 2023-06 | ok | 90 | 90 | 1685577600008 | 1688140800001 | {'8': 90} | 0 | 16 | 845 | 3ffdde6f1dc9c3c065d77ae43f3ba64d19d4cb76512d4bc1d541933d4fb2e6f7 |
| 2023-07 | ok | 93 | 93 | 1688169600000 | 1690819200001 | {'8': 93} | 0 | 1 | 861 | 0304baed9fd407293a8a8040b30a1b68bd344803b630d33530375b421733a930 |
| 2023-08 | ok | 93 | 93 | 1690848000000 | 1693497600000 | {'8': 93} | 0 | 5 | 846 | 516a8f50631c6ede6a9642f6d1590b6a22c33ba09935501d2ace8dc1396501fd |
| 2023-09 | ok | 90 | 90 | 1693526400000 | 1696089600000 | {'8': 90} | 0 | 1 | 914 | 3fd9df6fd1eef33cf5fe625c27012359bc6d64a68c109305d7b44a0354f533c2 |
| 2023-10 | ok | 93 | 93 | 1696118400000 | 1698768000000 | {'8': 93} | 0 | 5 | 865 | 03105cc140150bffca834bcccbddc6cfee245e079d2df1759653243bd6e92448 |
| 2023-11 | ok | 90 | 90 | 1698796800000 | 1701360000000 | {'8': 90} | 0 | 1 | 696 | 8015d2997f8d5e757ff3707ee87800ca30a74da0129daa747b64117f07bcc186 |
| 2023-12 | ok | 93 | 93 | 1701388800000 | 1704038400000 | {'8': 93} | 0 | 1 | 810 | 8f02fdd2a2da261bbf13ab301c74bdb57fae005f19d5088e9ece5f8824c1a2a7 |
| 2024-01 | ok | 93 | 93 | 1704067200000 | 1706716800000 | {'8': 93} | 0 | 3 | 696 | 3e0d30870672aa8f0f937881056e3cfd55913ae5c780cd50b33f2763aa0ba58e |
| 2024-02 | ok | 87 | 87 | 1706745600000 | 1709222400000 | {'8': 87} | 0 | 4 | 776 | daf1e4901e3d6436d82ad60f90d007eb5300be8047cfef121007203a7212cde6 |
| 2024-03 | ok | 93 | 93 | 1709251200000 | 1711900800001 | {'8': 93} | 0 | 4 | 939 | 711dcaf2a341aedfd06447b4117b540f60adb0784c5e64a313c718e4cf092bc3 |
| 2024-04 | ok | 90 | 90 | 1711929600000 | 1714492800000 | {'8': 90} | 0 | 15 | 842 | 6d220b8e2815362a11d294d35dbca28568370d8295351937eceec10f2b359b85 |
| 2024-05 | ok | 93 | 93 | 1714521600000 | 1717171200000 | {'8': 93} | 0 | 4 | 830 | aef8c5fdce1493fd570b5829a72f2f17c7e459483390f25544d16c2a30be592e |
| 2024-06 | ok | 90 | 90 | 1717200000000 | 1719763200000 | {'8': 90} | 0 | 8 | 721 | 43fc4473820d1fb4fe340d1b1951a87555f6841aa352e684fa95d6adffce04c6 |
| 2024-07 | ok | 93 | 93 | 1719792000000 | 1722441600000 | {'8': 93} | 0 | 4 | 847 | acab0593c1452660ce74a6c239fb215c1192b0a9c6e8c1689e6495de40a0174b |
| 2024-08 | ok | 93 | 93 | 1722470400000 | 1725120000000 | {'8': 93} | 0 | 8 | 904 | 7003d29a43dd5f9357f838da8766834954939e22c1d80af682d9f33984f67b71 |
| 2024-09 | ok | 90 | 90 | 1725148800000 | 1727712000000 | {'8': 90} | 0 | 5 | 924 | 6ef23b02392b481ef9c3855434bf3644289fb6e228b4f7d9a0dfc6d3cdff1116 |
| 2024-10 | ok | 93 | 93 | 1727740800000 | 1730390400000 | {'8': 93} | 0 | 13 | 801 | 26db65ac8020d80ece35df79c254c5f7e24427529bcceeb2972748c4fe2d2707 |
| 2024-11 | ok | 90 | 90 | 1730419200000 | 1732982400000 | {'8': 90} | 0 | 10 | 746 | e1b19cccfe2cdcba48b022790789b7b01edd86c075f39bc152e44c267d43bd51 |
| 2024-12 | ok | 93 | 93 | 1733011200000 | 1735660800000 | {'8': 93} | 0 | 14 | 808 | 069409f525ebf6370ee1c7defe475167de4b97284c5ac8e68768652968cd3dc9 |

FUNDING months ok 60 of 60; records 5481; interval_hours {'8': 5481}; invalid 0
FUNDING steps 5480; not 8 h 0 []; not equal to the previous record's interval 0; duplicates 0
FUNDING largest offset past the hour 47 ms at calc_time 1631865600047; FundingSignal constructed; no duplicate scheduled time

## Comparison with PR #19 (docs/reviews/2026-09-25-bob-funding-cadence.md, 60 month rows)

| Month | Records | PR #19 rows | First equal | Last equal | Records = expected |
| --- | --- | --- | --- | --- | --- |
| 2020-01 | 93 | 93 | True | True | True |
| 2020-02 | 87 | 87 | True | True | True |
| 2020-03 | 93 | 93 | True | True | True |
| 2020-04 | 90 | 90 | True | True | True |
| 2020-05 | 93 | 93 | True | True | True |
| 2020-06 | 90 | 90 | True | True | True |
| 2020-07 | 93 | 93 | True | True | True |
| 2020-08 | 93 | 93 | True | True | True |
| 2020-09 | 90 | 90 | True | True | True |
| 2020-10 | 93 | 93 | True | True | True |
| 2020-11 | 90 | 90 | True | True | True |
| 2020-12 | 93 | 93 | True | True | True |
| 2021-01 | 93 | 93 | True | True | True |
| 2021-02 | 84 | 84 | True | True | True |
| 2021-03 | 93 | 93 | True | True | True |
| 2021-04 | 90 | 90 | True | True | True |
| 2021-05 | 93 | 93 | True | True | True |
| 2021-06 | 90 | 90 | True | True | True |
| 2021-07 | 93 | 93 | True | True | True |
| 2021-08 | 93 | 93 | True | True | True |
| 2021-09 | 90 | 90 | True | True | True |
| 2021-10 | 93 | 93 | True | True | True |
| 2021-11 | 90 | 90 | True | True | True |
| 2021-12 | 93 | 93 | True | True | True |
| 2022-01 | 93 | 93 | True | True | True |
| 2022-02 | 84 | 84 | True | True | True |
| 2022-03 | 93 | 93 | True | True | True |
| 2022-04 | 90 | 90 | True | True | True |
| 2022-05 | 93 | 93 | True | True | True |
| 2022-06 | 90 | 90 | True | True | True |
| 2022-07 | 93 | 93 | True | True | True |
| 2022-08 | 93 | 93 | True | True | True |
| 2022-09 | 90 | 90 | True | True | True |
| 2022-10 | 93 | 93 | True | True | True |
| 2022-11 | 90 | 90 | True | True | True |
| 2022-12 | 93 | 93 | True | True | True |
| 2023-01 | 93 | 93 | True | True | True |
| 2023-02 | 84 | 84 | True | True | True |
| 2023-03 | 93 | 93 | True | True | True |
| 2023-04 | 90 | 90 | True | True | True |
| 2023-05 | 93 | 93 | True | True | True |
| 2023-06 | 90 | 90 | True | True | True |
| 2023-07 | 93 | 93 | True | True | True |
| 2023-08 | 93 | 93 | True | True | True |
| 2023-09 | 90 | 90 | True | True | True |
| 2023-10 | 93 | 93 | True | True | True |
| 2023-11 | 90 | 90 | True | True | True |
| 2023-12 | 93 | 93 | True | True | True |
| 2024-01 | 93 | 93 | True | True | True |
| 2024-02 | 87 | 87 | True | True | True |
| 2024-03 | 93 | 93 | True | True | True |
| 2024-04 | 90 | 90 | True | True | True |
| 2024-05 | 93 | 93 | True | True | True |
| 2024-06 | 90 | 90 | True | True | True |
| 2024-07 | 93 | 93 | True | True | True |
| 2024-08 | 93 | 93 | True | True | True |
| 2024-09 | 90 | 90 | True | True | True |
| 2024-10 | 93 | 93 | True | True | True |
| 2024-11 | 90 | 90 | True | True | True |
| 2024-12 | 93 | 93 | True | True | True |

## Daily (1d) archives, 2020-05 up to each dataset's daily_warmup_start

| Pair | Month | Status | Rows | Expected | Missing | Gaps | First open ms | Last open ms | Bytes | SHA-256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ADAUSDT | 2020-05 | ok | 31 | 31 | 0 | 0 | 1588291200000 | 1590883200000 | 1917 | 9456be0db85be54892f4be04d32033b8cc703176ff56530c4e573f375e0b5695 |
| ADAUSDT | 2020-06 | ok | 30 | 30 | 0 | 0 | 1590969600000 | 1593475200000 | 1892 | 19a443bd329701a87e9145cd7e36d6a84248bdb8602f5f612fab8e9cc0a47a91 |
| ADAUSDT | 2020-07 | ok | 31 | 31 | 0 | 0 | 1593561600000 | 1596153600000 | 1963 | 41fc1ff4003843071ab49c829d3198fea20829481ea7a8679eef8799be931412 |
| ADAUSDT | 2020-08 | ok | 31 | 31 | 0 | 0 | 1596240000000 | 1598832000000 | 1965 | 44466fad1d7c04a665a00e7232bb7da68c65f9ddf90fd1382845a083ea2815d7 |
| ADAUSDT | 2020-09 | ok | 30 | 30 | 0 | 0 | 1598918400000 | 1601424000000 | 1895 | 2060ef4cd0d0e3126d1834f442793fffe423596b2257d419bcdfb226e37f7058 |
| ADAUSDT | 2020-10 | ok | 31 | 31 | 0 | 0 | 1601510400000 | 1604102400000 | 1927 | 007e73c2c8039be302c48ffac7dd5210ec5e3da07c61186c9e83e2bc8b2c21b3 |
| ADAUSDT | 2020-11 | ok | 30 | 30 | 0 | 0 | 1604188800000 | 1606694400000 | 1912 | e1ce0030a9847238d2cac9030eb7b0044fe307e4bed507b0341ca2a7dba66f69 |
| ADAUSDT | 2020-12 | ok | 31 | 31 | 0 | 0 | 1606780800000 | 1609372800000 | 1988 | dd1148cc29dbe91f7f0efda8cba755b0ef583a816ee2500ee2ed0b23b531b4e4 |
| ADAUSDT | 2021-01 | ok | 31 | 31 | 0 | 0 | 1609459200000 | 1612051200000 | 2064 | e6cb149267d1ed9436b06dcbd2f63ae8df5e2e8d4b2ed0930db6cb94d555f4fa |
| ADAUSDT | 2021-02 | ok | 28 | 28 | 0 | 0 | 1612137600000 | 1614470400000 | 1937 | 8dc416c42aeaa4987c8fdfbff43fd668b4123d94bff5229ca11b8d3174e171f2 |
| ADAUSDT | 2021-03 | ok | 31 | 31 | 0 | 0 | 1614556800000 | 1617148800000 | 2064 | a81828f23c438edc0349ab3c60e21fef1242452a794edcf9e8cf9f70ad92d4be |
| ADAUSDT | 2021-04 | ok | 30 | 30 | 0 | 0 | 1617235200000 | 1619740800000 | 2002 | 2dc93e94ff1b3f716ecf7e6830a7304e0e0dd6a824f4d9f061eafdbc81f0ba82 |
| ADAUSDT | 2021-05 | ok | 31 | 31 | 0 | 0 | 1619827200000 | 1622419200000 | 2097 | 949eebbef93599dc3cb9fc8072b89ee08de7d863a866c2a3fe105998e897d8b6 |
| ADAUSDT | 2021-06 | ok | 30 | 30 | 0 | 0 | 1622505600000 | 1625011200000 | 1997 | fc3edac91c25b86ec4f0ab5e77415c9f34f95593e1b5d1e42c02e8e7d8558f7d |
| ADAUSDT | 2021-07 | ok | 31 | 31 | 0 | 0 | 1625097600000 | 1627689600000 | 2007 | b536d0e07f303fb03d818dde96f808d7888418f317112ae900e351f3df66cea3 |
| ADAUSDT | 2021-08 | ok | 31 | 31 | 0 | 0 | 1627776000000 | 1630368000000 | 2055 | 0e6f6d470d981f6f3f3b484ccda86308580fe8bbcb6ac38736db600dcd54d6df |
| ADAUSDT | 2021-09 | ok | 30 | 30 | 0 | 0 | 1630454400000 | 1632960000000 | 1865 | 0b898a1e226dd6c3eb65aff2a158fcad0a67f2f413b3057cbf8eb654fa1b2b01 |
| ADAUSDT | 2021-10 | ok | 31 | 31 | 0 | 0 | 1633046400000 | 1635638400000 | 1841 | 98595c1a9944cfc277c055f5089e32bc8263b12a95be69cc54fa8370af5b5cee |
| ADAUSDT | 2021-11 | ok | 30 | 30 | 0 | 0 | 1635724800000 | 1638230400000 | 1827 | 57802e1be6587882587518f3c2be7eebf17ddf6830a893cd0e8e897c984b9e5b |
| ADAUSDT | 2021-12 | ok | 31 | 31 | 0 | 0 | 1638316800000 | 1640908800000 | 1839 | a13548ce249b853f52e93667b29c91093e556b47fa947c4ee60065b38e362ad3 |
| ADAUSDT | 2022-01 | ok | 31 | 31 | 0 | 0 | 1640995200000 | 1643587200000 | 1866 | 7e784aa282a3d7931d2ad901eb8492fecb7edec807d2208c6275dafd332071a5 |
| ADAUSDT | 2022-02 | ok | 28 | 28 | 0 | 0 | 1643673600000 | 1646006400000 | 1671 | 1efe9c311ab4c3d3e76edddf2052f2632c2a01e084ce8cdc746c5144c8b1d60d |
| ADAUSDT | 2022-03 | ok | 31 | 31 | 0 | 0 | 1646092800000 | 1648684800000 | 1828 | 64e689576b0e7a9adf2db055d5cdc4fb94c1d254d116b889940ee8808a5f2863 |
| ADAUSDT | 2022-04 | ok | 30 | 30 | 0 | 0 | 1648771200000 | 1651276800000 | 1782 | 402e223bbcc365bf79611c6e456ed4dd3f13a4bd673a297a0de1fd0a1ed7218c |
| ADAUSDT | 2022-05 | ok | 31 | 31 | 0 | 0 | 1651363200000 | 1653955200000 | 1961 | f4d2b5af22a57675a0a1f8dd415f38c2a873d76ee7b51b94b58dde60ca6d4fee |
| ADAUSDT | 2022-06 | ok | 30 | 30 | 0 | 0 | 1654041600000 | 1656547200000 | 1886 | e2036e0fd90a152ffadb6b7f3de3bc640d633ea28db88c10e182587500ade938 |
| ADAUSDT | 2022-07 | ok | 31 | 31 | 0 | 0 | 1656633600000 | 1659225600000 | 1902 | d4981dafd78a0e2e5d613aa8c1f167d37efbebf176831c5d7d35570b845ea2df |
| ADAUSDT | 2022-08 | ok | 31 | 31 | 0 | 0 | 1659312000000 | 1661904000000 | 1908 | b2b04e046dc68ecbc83f1c247e69c649f24080aaeb7e4f4c94699f7aca402d91 |
| ADAUSDT | 2022-09 | ok | 30 | 30 | 0 | 0 | 1661990400000 | 1664496000000 | 1825 | 20a754086b8c490eea4f40151db5178723ce39ed8a9af893f7e26f367d468074 |
| ADAUSDT | 2022-10 | ok | 31 | 31 | 0 | 0 | 1664582400000 | 1667174400000 | 1868 | 26d090c128a5f0dc7b321f7082e1e09b1e84a397dcdf5de1723bcaf2bf5cce7d |
| ADAUSDT | 2022-11 | ok | 30 | 30 | 0 | 0 | 1667260800000 | 1669766400000 | 1813 | 9428467f979ad3d0e6bd13bd40bacd5606e089fbea0c80c25de2a8d17678d97f |
| ADAUSDT | 2022-12 | ok | 31 | 31 | 0 | 0 | 1669852800000 | 1672444800000 | 1838 | 082c101dbd0da7c10f374c41187488bcfdcd8d83297d9aadb36b7d75e0344c8c |
| ADAUSDT | 2023-01 | ok | 31 | 31 | 0 | 0 | 1672531200000 | 1675123200000 | 1887 | ce3b8c0abee68832c1357ead66ce0816b14e411692cb1f3a844a8c97dadd8e43 |
| ADAUSDT | 2023-02 | ok | 28 | 28 | 0 | 0 | 1675209600000 | 1677542400000 | 1699 | 91e1b332ebcd2338555f501603baaaf4157bbf9725709b25e61b617c67fc6e0f |
| ADAUSDT | 2023-03 | ok | 31 | 31 | 0 | 0 | 1677628800000 | 1680220800000 | 1877 | 29d2e434243e7e4ea52dcbb68298e9d804525a16f268554926757c5e6a9d3398 |
| ADAUSDT | 2023-04 | ok | 30 | 30 | 0 | 0 | 1680307200000 | 1682812800000 | 1811 | 5f869873a022268c1eed837842cddc5e556a4e5bf3a811a5ffcd8573542ed0d2 |
| BTCUSDT | 2020-05 | ok | 31 | 31 | 0 | 0 | 1588291200000 | 1590883200000 | 2183 | 7ae5d56d12ce599fbceac80ae04bde51c7421b39f22f924f1f46a53e560a1f75 |
| BTCUSDT | 2020-06 | ok | 30 | 30 | 0 | 0 | 1590969600000 | 1593475200000 | 2103 | 19e9ffb7c77e0b8c7bc17d6c47fdc52eb50fcb61ac8d94d32b9c13eb17c700d6 |
| BTCUSDT | 2020-07 | ok | 31 | 31 | 0 | 0 | 1593561600000 | 1596153600000 | 2174 | 76fab627ce54ba1457c63e3906e2afd3162cf053283709672fb3eb676b3dde3b |
| BTCUSDT | 2020-08 | ok | 31 | 31 | 0 | 0 | 1596240000000 | 1598832000000 | 2197 | ff20895a43680f991fa26ee2c9b34376c17487404d57a22f088af8c7ed1fd9ec |
| BTCUSDT | 2020-09 | ok | 30 | 30 | 0 | 0 | 1598918400000 | 1601424000000 | 2148 | d6f9590a181d58a992e6a3ce2346a4dbc96ecf5310c12df66c57be4818bfc28a |
| BTCUSDT | 2020-10 | ok | 31 | 31 | 0 | 0 | 1601510400000 | 1604102400000 | 2210 | e240ecb14f1120af34290ed9c7e8937e7cd8a80f0d0bbc88a924f7e520e78cec |
| BTCUSDT | 2020-11 | ok | 30 | 30 | 0 | 0 | 1604188800000 | 1606694400000 | 2161 | 4a7b8bd36409c7ae92916489621e298d750e5dda7be5b7389dc814dffb16a29e |
| BTCUSDT | 2020-12 | ok | 31 | 31 | 0 | 0 | 1606780800000 | 1609372800000 | 2231 | 77e2c7fa9a940828b3f36f7212f6def777acfc1402d173bdfad958d2e37ea469 |
| BTCUSDT | 2021-01 | ok | 31 | 31 | 0 | 0 | 1609459200000 | 1612051200000 | 2295 | 6ff53d94f600e2a208882bfd5c00e2133cff8f07e57b7f373af29f85f86e0284 |
| BTCUSDT | 2021-02 | ok | 28 | 28 | 0 | 0 | 1612137600000 | 1614470400000 | 2103 | f18254dc4a70f396494be83a6081cfafd1935aaef42aef5a12f18b0244edeb27 |
| BTCUSDT | 2021-03 | ok | 31 | 31 | 0 | 0 | 1614556800000 | 1617148800000 | 2282 | f43e48b5efc8e0b06e0520b91aad4e5668844c766933c0c5cf403115dba03303 |
| BTCUSDT | 2021-04 | ok | 30 | 30 | 0 | 0 | 1617235200000 | 1619740800000 | 2189 | 3dd852f06608173dec98b7210f6a38728ef221f08717b362b4f3f09436e0a5fe |
| BTCUSDT | 2021-05 | ok | 31 | 31 | 0 | 0 | 1619827200000 | 1622419200000 | 2283 | 3122e1ebaa1376937d479964563dced19f850636a700bb7cb97d7872ea8c8f28 |
| BTCUSDT | 2021-06 | ok | 30 | 30 | 0 | 0 | 1622505600000 | 1625011200000 | 2204 | 9875e11e890f75ef6eb0188ef7f952e5c0ba6919bd6d72d3da4d6847b84c5ccf |
| BTCUSDT | 2021-07 | ok | 31 | 31 | 0 | 0 | 1625097600000 | 1627689600000 | 2264 | 636f588a6abb568f977aea3ae798f34ced4135f2f96fbc1493a2f9ab54a844eb |
| BTCUSDT | 2021-08 | ok | 31 | 31 | 0 | 0 | 1627776000000 | 1630368000000 | 2246 | 68612e3fb74c184f97e4d3b2e061dd3743156401a6813ab897014b0b35caedd7 |
| BTCUSDT | 2021-09 | ok | 30 | 30 | 0 | 0 | 1630454400000 | 1632960000000 | 2156 | 9f6535a0fe8a417b0909d230e4a02f6a9933eb23c770f54c9f6bf140e8d02257 |
| BTCUSDT | 2021-10 | ok | 31 | 31 | 0 | 0 | 1633046400000 | 1635638400000 | 2210 | ba50ff3dab5726ca8b9fa26065fe3a8f612aed4baa978ecdd9d39647cd108684 |
| BTCUSDT | 2021-11 | ok | 30 | 30 | 0 | 0 | 1635724800000 | 1638230400000 | 2166 | 64162d8ec11458e9d02f49d8569e47765517852bcf0a908cd4d71211e3912e62 |
| BTCUSDT | 2021-12 | ok | 31 | 31 | 0 | 0 | 1638316800000 | 1640908800000 | 2196 | 6231b57d3a3b71fb76a1a34078a01a01275a59870857bf60408ccd3ba4618e75 |
| BTCUSDT | 2022-01 | ok | 31 | 31 | 0 | 0 | 1640995200000 | 1643587200000 | 2183 | a4a2e0432a8f0b42e2da71ac26599b2e6385b579ca4feba692a95cb897decdcd |
| BTCUSDT | 2022-02 | ok | 28 | 28 | 0 | 0 | 1643673600000 | 1646006400000 | 2011 | faffa5eadb9ebf0b32742773777596d0dbf3f282e94a16dd05cf1eb7b53a3763 |
| BTCUSDT | 2022-03 | ok | 31 | 31 | 0 | 0 | 1646092800000 | 1648684800000 | 2206 | 452129b478585b18931f728f89daed9d2a19d4824b932af7a099366efd4db639 |
| BTCUSDT | 2022-04 | ok | 30 | 30 | 0 | 0 | 1648771200000 | 1651276800000 | 2117 | 70413f67212d012ebfd600a6ebf20c03a9c8311bf764ab6d21d1bfd2d21d1b19 |
| BTCUSDT | 2022-05 | ok | 31 | 31 | 0 | 0 | 1651363200000 | 1653955200000 | 2212 | 53eee1be2d5b461dabc67645ad706610b0465d8bbacd5f9cd99fc790c68f18f5 |
| BTCUSDT | 2022-06 | ok | 30 | 30 | 0 | 0 | 1654041600000 | 1656547200000 | 2169 | dd5047ce33c16231bcb01f534951a709937bbfe0c0667c61f20f188cf9b94de4 |
| BTCUSDT | 2022-07 | ok | 31 | 31 | 0 | 0 | 1656633600000 | 1659225600000 | 2245 | 216567f1a8bc1dbeaada097f7eddff12dafde177c16b26507c762a613a57eb5f |
| BTCUSDT | 2022-08 | ok | 31 | 31 | 0 | 0 | 1659312000000 | 1661904000000 | 2237 | fc8bd69e95141afb6f83c5a4450c3f6b49c4a1cb16e42d90eb960c3ffa9e766e |
| BTCUSDT | 2022-09 | ok | 30 | 30 | 0 | 0 | 1661990400000 | 1664496000000 | 2213 | 68a8357e23277ebd98842fd88d492b012d53dd578b5061cafb8c070c440b235e |
| BTCUSDT | 2022-10 | ok | 31 | 31 | 0 | 0 | 1664582400000 | 1667174400000 | 2219 | 5b086535cba596ef1b465f247a26385b4ccfd12673a76f225e2dd9e00dddadfd |
| BTCUSDT | 2022-11 | ok | 30 | 30 | 0 | 0 | 1667260800000 | 1669766400000 | 2191 | 142202b226078f54342c4a1d74c8c6081a98c655d7d6f6fba06314f9c101e2d9 |
| BTCUSDT | 2022-12 | ok | 31 | 31 | 0 | 0 | 1669852800000 | 1672444800000 | 2222 | aff24746afa9a3dbd355dd3462bcef80e59e96ed9aa55f79007532f9e07991bf |
| BTCUSDT | 2023-01 | ok | 31 | 31 | 0 | 0 | 1672531200000 | 1675123200000 | 2250 | a9fd53b75add7cc42fb4779a545811606260f79810f3826215d6ebecda11bb36 |
| BTCUSDT | 2023-02 | ok | 28 | 28 | 0 | 0 | 1675209600000 | 1677542400000 | 2072 | 13df1e3633f15be3eeba4768d0cc323ef221191002657b53936a6d0fb5e6556f |
| BTCUSDT | 2023-03 | ok | 31 | 31 | 0 | 0 | 1677628800000 | 1680220800000 | 2265 | 1cb1209700ec74fa4592048de2e4ea4a38ab2bd622dfe03f1d6195c249501381 |
| BTCUSDT | 2023-04 | ok | 30 | 30 | 0 | 0 | 1680307200000 | 1682812800000 | 2108 | 999e86be73731ebc347c6ada94abceb5e291b65e7f1b4df2ce390af1aa2a4a08 |
| SOLUSDT | 2020-05 | missing | None | None | None | None | None | None | None | None |
| SOLUSDT | 2020-06 | missing | None | None | None | None | None | None | None | None |
| SOLUSDT | 2020-07 | missing | None | None | None | None | None | None | None | None |
| SOLUSDT | 2020-08 | ok | 21 | 31 | 10 | 1 | 1597104000000 | 1598832000000 | 1319 | 40ddd9549f8c5901b3a049cba929c0c7fbb22c0d5b7c5f6152cf2e242db3220e |
| SOLUSDT | 2020-09 | ok | 30 | 30 | 0 | 0 | 1598918400000 | 1601424000000 | 1862 | aec220caed07ca9f97c7c441295023b5c01c4b1c4db16f16a9e76667f969b8a8 |
| SOLUSDT | 2020-10 | ok | 31 | 31 | 0 | 0 | 1601510400000 | 1604102400000 | 1891 | 852dce14c900a2c323e0563ab908b299fc52bd9399d20b27b3773056d6c4e8b8 |
| SOLUSDT | 2020-11 | ok | 30 | 30 | 0 | 0 | 1604188800000 | 1606694400000 | 1851 | ad9e4ae3b69ae8cec9425056fc581d9744cf31a923f477b3bad18714df0ccb10 |
| SOLUSDT | 2020-12 | ok | 31 | 31 | 0 | 0 | 1606780800000 | 1609372800000 | 1890 | f7c2981644bdd53b6d44dcf77879aef64e65c88f10b9fd6048c77a9cf27abc08 |
| SOLUSDT | 2021-01 | ok | 31 | 31 | 0 | 0 | 1609459200000 | 1612051200000 | 1937 | d7883e8cf9558b3735c2c36e27baccd1ee241d294e3ef85a6b3db5da36d7e040 |
| SOLUSDT | 2021-02 | ok | 28 | 28 | 0 | 0 | 1612137600000 | 1614470400000 | 1836 | 576f9b03c69a1c84566ec257a9663f3c0b71179192b10ebc021bc3d31f4c6988 |
| SOLUSDT | 2021-03 | ok | 31 | 31 | 0 | 0 | 1614556800000 | 1617148800000 | 1983 | 90f6c49b661828d6191292a4595c42fb2aaa96de34894d4e47ef147b4902d1f8 |
| SOLUSDT | 2021-04 | ok | 30 | 30 | 0 | 0 | 1617235200000 | 1619740800000 | 2008 | f81629c45bede0e7cc367dfe5609878359ffe202da39b97b419b36e276155026 |
| SOLUSDT | 2021-05 | ok | 31 | 31 | 0 | 0 | 1619827200000 | 1622419200000 | 2038 | 7787aabb922e9f6bef515697b3bd6e17aec223bda210f223d5df4ef4c2e73bb0 |
| SOLUSDT | 2021-06 | ok | 30 | 30 | 0 | 0 | 1622505600000 | 1625011200000 | 1979 | ceeff69afda85f0affd0d9f41d07297f3cb37c2225854d23e30d2a09bf939d6f |
| SOLUSDT | 2021-07 | ok | 31 | 31 | 0 | 0 | 1625097600000 | 1627689600000 | 1997 | b3526f1f04967f1f63810409eb0eefcb03154732faca5faea716d623576ec07c |
| SOLUSDT | 2021-08 | ok | 31 | 31 | 0 | 0 | 1627776000000 | 1630368000000 | 2040 | fbeda8e1117ee083ecaf6777a5134619ec635205848bba3af0713e84f736269b |
| XRPUSDT | 2020-05 | ok | 31 | 31 | 0 | 0 | 1588291200000 | 1590883200000 | 1923 | d9256ff5abfd7ae9c6991cda9c6bda4ead885da655d049aab19f28d578ecbddc |
| XRPUSDT | 2020-06 | ok | 30 | 30 | 0 | 0 | 1590969600000 | 1593475200000 | 1861 | 44162ba1ac5e7b31db76f5798ab2cad73b5e12de4084fdbd6547ce6fee602534 |
| XRPUSDT | 2020-07 | ok | 31 | 31 | 0 | 0 | 1593561600000 | 1596153600000 | 1939 | 75307a63512d929cdbfbc8ed220a8e813e8fc275e4258c55981e1030499b22be |
| XRPUSDT | 2020-08 | ok | 31 | 31 | 0 | 0 | 1596240000000 | 1598832000000 | 1988 | 493372b00d49d4ca0a4c78e0b30f4cefd4a14fec576a5bab8c89408a5f29efa7 |
| XRPUSDT | 2020-09 | ok | 30 | 30 | 0 | 0 | 1598918400000 | 1601424000000 | 1890 | 556c7a7c968ee8726d1af4436fd5d587118486dd90fb61f7b6791dc063b8c1ee |
| XRPUSDT | 2020-10 | ok | 31 | 31 | 0 | 0 | 1601510400000 | 1604102400000 | 1937 | 3c1c5f6def1060e10e8c1607cadfe426f765a5fb25421f44d433a7b727d78dda |
| XRPUSDT | 2020-11 | ok | 30 | 30 | 0 | 0 | 1604188800000 | 1606694400000 | 1961 | 2b861e841478996e54a260f3b818b937b7ffd9e3d008723f5263198a53a0b136 |
| XRPUSDT | 2020-12 | ok | 31 | 31 | 0 | 0 | 1606780800000 | 1609372800000 | 2094 | 56f6e592c1da5401af7082e345a937d3dc3157ee91e465e54f9f777ffdb077ab |
| XRPUSDT | 2021-01 | ok | 31 | 31 | 0 | 0 | 1609459200000 | 1612051200000 | 2040 | 53b2af75344e28cf5b87c6b88451cff0c5155c511ebd776a357a38b60aa7511b |
| XRPUSDT | 2021-02 | ok | 28 | 28 | 0 | 0 | 1612137600000 | 1614470400000 | 1887 | c307b2f377c74b15aaabc2fe147f4b6828a0347233ca73c6c263c46b55769119 |
| XRPUSDT | 2021-03 | ok | 31 | 31 | 0 | 0 | 1614556800000 | 1617148800000 | 2040 | 3c3e4b7aaa07ba8f43ffc5fe9b0079d56f00fafcd7848870ff5149571cf091f9 |
| XRPUSDT | 2021-04 | ok | 30 | 30 | 0 | 0 | 1617235200000 | 1619740800000 | 2075 | 9c7051467d928c789f00ecd81b417539e2d57252278f24a4b3075fbae5d9ca4f |
| XRPUSDT | 2021-05 | ok | 31 | 31 | 0 | 0 | 1619827200000 | 1622419200000 | 2091 | c21aade0e23847c36447bc7484bbb74f730d7e584779e5069e9b2d6e5a8db0db |
| XRPUSDT | 2021-06 | ok | 30 | 30 | 0 | 0 | 1622505600000 | 1625011200000 | 1984 | c6ea29b2ee938d6cd69355c5dc5651be1cd5b186f417a19c7660d1191b8564ae |
| XRPUSDT | 2021-07 | ok | 31 | 31 | 0 | 0 | 1625097600000 | 1627689600000 | 2018 | 6b7489a4ee06c0e8caa6c6895ef26d289c2f6f6a43169f177e85c90fca2ccc89 |
| XRPUSDT | 2021-08 | ok | 31 | 31 | 0 | 0 | 1627776000000 | 1630368000000 | 2064 | 9dd6d014a6b4e12e10fdec3d26197141a49d3a23bd5a451fe8abdf552062f611 |

DAILY files 104; by status {'ok': 101, 'missing': 3}
DAILY incomplete or unparsed (SOLUSDT's listing month excepted): 0

## Known values

| Figure | Measured | Known | Equal |
| --- | --- | --- | --- |
| funding months ok | 60 | 60 | True |
| funding records, all months | 5481 | 5481 | True |
| funding interval_hours values | {'8': 5481} | {'8': 5481} | True |
| funding invalid records | 0 | 0 | True |
| funding steps not 8 h | 0 | 0 | True |
| funding largest offset ms | 47 | 47 | True |
| funding largest offset calc_time | 1631865600047 | 1631865600047 | True |
| SOLUSDT 1d 2020-05..2020-07 status | ['missing', 'missing', 'missing'] | ['missing', 'missing', 'missing'] | True |
| SOLUSDT 1d 2020-08 first open ms | 1597104000000 | 1597104000000 | True |
| latest 1d month planned | 2023-04 | 2023-04 | True |
| 1d files missing other than SOLUSDT 2020-05..07 | 0 | 0 | True |

## Proposed manifest additions (the committed manifests are not changed)

| Dataset | 1d entries | 1d by status | 1d months | Funding entries | Funding months | Additions file SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| practice-2022 | 48 | {'ok': 45, 'missing': 3} | 2020-05..2021-08 | 10 | 2022-04..2023-01 | 0ae06b5d4b0644ed455bb72e7eaf346d2e9c80625087b21bdc08e0f1abb1ba1e |
| verify-2024h1 | 72 | {'ok': 72} | 2020-05..2023-04 | 8 | 2023-11..2024-06 | 10d35d4320397f8359e5b29d6b72eda399fc0e25aefbb017cb1d29c2e03b03d2 |

REQUESTS 328; latest month 2024-12; after 2024-12: 0; list in data/p8/requests.txt sha256 4dda3006dff0517ce78aece7b13134dde2f5c943dcb2f062b4fe6d0afd23b951
CONFIG config/datasets unchanged: True
CONFIG e8665c9a9e2b3117f4e825989b81a0bfe98dfa42eca84ae81fd236d8092ae288  config/datasets/practice-2022.manifest.json
CONFIG f259445fd78d840a5c758026c6ee6bd717ea47656cee228111a397d9fa1d7bdd  config/datasets/practice-2022.toml
CONFIG 48a239f4dfbe923b5a3c9c29336c884c40435617206d5c75b76b8461b0aaa9cf  config/datasets/verify-2024h1.manifest.json
CONFIG a5fda6c8a8c2a78fce986634279890314c94f46523ac8dd1356d0e991df653e4  config/datasets/verify-2024h1.toml
RESULT 0 problem(s)
```

## Results

`RESULT 0 problem(s)` (run log, last line before CONFIG lines).

**Validity check 1 — script hash:** `35a4ea2cf36cae67339784fada62063880a41455d1a60316902f93c52363c75e` (Step 2, sha256sum output). Matches the task-file pin. PASS.

**Validity check 2 — self-test:** exit 0; 17 SELFTEST case lines each showing its expected outcome; `SELFTEST requests that reached the (disabled) network: 2`; `SELFTEST wrong outcomes: 0` (self-test log, 6b). PASS.

**Validity check 3 — real run:** exit 0, `RESULT 0 problem(s)` (run log, 6d). All ten inputs `INPUT ok`. All 60 funding months `ok`, records match 3 per day and match PR #19. Known values all `True`. `DAILY incomplete or unparsed (SOLUSDT's listing month excepted): 0`. FundingSignal `constructed; no duplicate scheduled time`. No planned daily file already in a committed manifest. `REQUESTS 328; latest month 2024-12; after 2024-12: 0`. `CONFIG config/datasets unchanged: True`. PASS.

**Validity check 4 — reserved-window file check:** `find data -type f | grep -cE` printed `0` (Step 5). PASS.

`REQUESTS 328; latest month 2024-12; after 2024-12: 0` (run log).
`find | grep -c` count: `0` (Step 5).
`CONFIG config/datasets unchanged: True` (run log).

Additions file SHA-256 (from Step 5 sha256sum):
- `data/p8/practice-2022.additions.json`: `0ae06b5d4b0644ed455bb72e7eaf346d2e9c80625087b21bdc08e0f1abb1ba1e`
- `data/p8/verify-2024h1.additions.json`: `10d35d4320397f8359e5b29d6b72eda399fc0e25aefbb017cb1d29c2e03b03d2`

The manifest additions in these files are a **proposal only**; no manifest was changed. Funding entries carry a new `kind` field and no `interval` field, which the current `load_manifest` schema does not accept. An `unparsed` daily status (none occurred here, but the schema does not include it either) would also be rejected by `load_manifest` today.

## Ideas and proposals

**Manifest schema for funding entries.** The additions JSON uses `"kind": "fundingRate"` (as `fetch_funding_file` writes it) with no `"interval"` key. Claude and Codex need to decide: (a) whether to add `kind` as a discriminator to the manifest schema; (b) whether funding entries live in the same `files` list as kline entries or in a new top-level key; (c) whether `sha256` and `bytes` are required or optional. The script's output JSON is the concrete proposal to react to.

**Manifest schema for `unparsed` daily status.** No daily file was `unparsed` in this run, but the schema accepts only `"ok"` and `"missing"` statuses today. If a future run produces an `unparsed` file, the proposed additions JSON would still be written but would be rejected on import. Claude and Codex should decide whether to add `unparsed` now or wait until a real case arises.

**`practice-2022` SOLUSDT 2020-05 to 2020-07 missing entries.** The additions JSON records these three months with `"status": "missing"`, which the manifest schema already accepts; `verify_dataset` already skips the local-file checks for that status, so these entries need no schema change. The proposed entries are consistent: `"status": "missing"` with no bytes or hash. Only the funding entries need new schema work.

**BTCUSDT daily overlap between datasets.** BTCUSDT daily 2020-05 to 2021-08 appears in both `practice-2022` (16 months) and `verify-2024h1` (36 months), for 16 shared months fetched once (104 distinct files; 120 daily entries across the two additions, 48 + 72). A manifest schema that deduplicates shared files by path would avoid storing them twice. Not urgent for two datasets, but relevant if more are added.

Run completed at: Tue Sep 29 11:15:48 UTC 2026

## Appendix: `data/p8_archives.py`

```text
"""P8 archives for G and H, development months only.

Task: docs/tasks/2026-09-27-bob-p8-funding-archives.md. Run from the repository root:
python data/p8_archives.py --self-test, then python data/p8_archives.py
"""

import collections
import json
import re
import sys
import time
from pathlib import Path

from crypto_grid_bot.backtest.dataset import (
    ArchiveParseError,
    archive_get,
    fetch_file,
    fetch_funding_file,
    funding_archive_path,
    funding_local_path,
    load_manifest,
    load_spec,
    local_path,
    sha256_file,
)
from crypto_grid_bot.backtest.funding import FundingSignal, read_funding_archive
from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.market_data.client import FeedError
from crypto_grid_bot.market_data.parsing import DataError

LAST_MONTH = "2024-12"  # the reserved window starts 2025-01 and is out of scope
FIRST_MONTH = "2020-01"
H_FIRST = "2020-05"  # month of the 2020-05-11 halving (spec section 3 H)
DATASETS = ("practice-2022", "verify-2024h1")
DATA = Path("data")
OUT = DATA / "p8"
HOUR_MS = 3_600_000
KLINE = re.compile(
    r"/data/spot/monthly/klines/(ADAUSDT|BTCUSDT|SOLUSDT|XRPUSDT)/1d/"
    r"\1-1d-(\d{4}-\d{2})\.zip(?:\.CHECKSUM)?"
)
FUNDING = re.compile(
    r"/data/futures/um/monthly/fundingRate/BTCUSDT/"
    r"BTCUSDT-fundingRate-(\d{4}-\d{2})\.zip(?:\.CHECKSUM)?"
)
PR19 = Path("docs/reviews/2026-09-25-bob-funding-cadence.md")
PR19_ROW = re.compile(r"^\| (\d{4}-\d{2}) \| [^|]+ \| (\d+) \| (\d+) \| (\d+) \| (\S+) \|$", re.M)
REQUESTED: list[str] = []
# The reviewed inputs: main at 3b94378 (PR #116), with dataset.py as PR #113 merges it
# (its fetch_funding_file). Any other content stops the run before any request, so the
# evidence cannot come from specs, manifests or code nobody reviewed.
INPUTS = {
    "config/datasets/practice-2022.toml": (
        "f259445fd78d840a5c758026c6ee6bd717ea47656cee228111a397d9fa1d7bdd"
    ),
    "config/datasets/practice-2022.manifest.json": (
        "e8665c9a9e2b3117f4e825989b81a0bfe98dfa42eca84ae81fd236d8092ae288"
    ),
    "config/datasets/verify-2024h1.toml": (
        "a5fda6c8a8c2a78fce986634279890314c94f46523ac8dd1356d0e991df653e4"
    ),
    "config/datasets/verify-2024h1.manifest.json": (
        "48a239f4dfbe923b5a3c9c29336c884c40435617206d5c75b76b8461b0aaa9cf"
    ),
    "docs/reviews/2026-09-25-bob-funding-cadence.md": (
        "b9d3ec73f3f2f7ac39ff1dc4ee85098388dea19659d9e881b91e40844b919d21"
    ),
    "src/crypto_grid_bot/backtest/dataset.py": (
        "9c3b6b5a84b3c58037c85bf32caadf7ae63622bfa612c10beb6f49f9f99150a5"
    ),
    "src/crypto_grid_bot/backtest/funding.py": (
        "34b0558761c9861782351833df5d3f645730a4011fe3be90d70de36082357aee"
    ),
    "src/crypto_grid_bot/backtest/klines.py": (
        "ce12820936efe09f55658c418e8ef65e393f2f56882b320077efef99408491cb"
    ),
    "src/crypto_grid_bot/market_data/client.py": (
        "c6ee5a25a1572957c1115bb56cdab2c5ba714d56d26036b59b6246e1dd8c97a7"
    ),
    "src/crypto_grid_bot/market_data/parsing.py": (
        "5dfb8e837b24e38a95beefccc4efddcc10571f786ee5b563e8f3a60e0bd587c9"
    ),
}
# SOLUSDT was listed on 2020-08-11 (P8 survey): its first daily month is partial.
SOL_FIRST_OPEN_MS = 1597104000000


class OutOfScope(BaseException):
    """A BaseException, so no handler for Exception or DataError can swallow it."""


def allowed(month: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise OutOfScope(f"not a YYYY-MM month: {month!r}")
    if not FIRST_MONTH <= month <= LAST_MONTH:
        raise OutOfScope(f"month {month} is outside {FIRST_MONTH}..{LAST_MONTH}")
    return month


def month_range(first: str, last: str) -> list[str]:
    months, month = [], first
    while month <= last:
        months.append(allowed(month))
        year, number = int(month[:4]), int(month[5:])
        month = f"{year + number // 12}-{number % 12 + 1:02d}"
    return months


def previous(month: str) -> str:
    year, number = int(month[:4]), int(month[5:])
    return f"{year - (number == 1)}-{(number - 2) % 12 + 1:02d}"


def kline_get(path: str) -> bytes | None:
    found = KLINE.fullmatch(path)
    if found is None:
        raise OutOfScope(f"not a planned 1d archive path: {path}")
    allowed(found.group(2))
    REQUESTED.append(path)
    return archive_get(path)


def funding_get(path: str) -> bytes | None:
    found = FUNDING.fullmatch(path)
    if found is None:
        raise OutOfScope(f"not a planned funding archive path: {path}")
    allowed(found.group(1))
    REQUESTED.append(path)
    return archive_get(path)  # the project's fetcher: it refuses the month again itself


def funding_path(month: str) -> str:
    return funding_archive_path("BTCUSDT", allowed(month))


def funding_file(month: str) -> dict:
    """The project's fetch_funding_file (same rules as fetch_file), through funding_get."""
    return fetch_funding_file(DATA, "BTCUSDT", allowed(month), funding_get)


def open_funding(month: str) -> list:
    path = funding_local_path(DATA, "BTCUSDT", allowed(month))
    return read_funding_archive(path, "BTCUSDT", month)


def retried(call, *args):
    for attempt in (1, 2, 3):
        try:
            return call(*args)
        except FeedError as exc:
            print(f"RETRY attempt {attempt} of {call.__name__}{args[-2:]}: {exc}", flush=True)
            if attempt == 3:
                raise
            time.sleep(10)
    raise AssertionError("unreachable")


def self_test() -> int:
    class Network(Exception):
        pass

    def no_network(*_args, **_kwargs):
        raise Network

    globals()["archive_get"] = no_network
    kline = "/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-{}.zip"
    funding = "/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{}.zip"
    cases = [
        (allowed, "2024-12", "allowed"),
        (allowed, "2020-01", "allowed"),
        (allowed, "2025-01", "OutOfScope"),
        (allowed, "2019-12", "OutOfScope"),
        (allowed, "2024-1", "OutOfScope"),
        (kline_get, kline.format("2024-12"), "network"),
        (kline_get, kline.format("2025-01"), "OutOfScope"),
        (kline_get, kline.format("2025-01") + ".CHECKSUM", "OutOfScope"),
        (kline_get, "/data/spot/monthly/klines/BTCUSDT/1d/", "OutOfScope"),
        (funding_get, funding.format("2024-12") + ".CHECKSUM", "network"),
        (funding_get, funding.format("2025-01"), "OutOfScope"),
        (funding_get, funding.format("2025-01") + ".CHECKSUM", "OutOfScope"),
        (funding_get, "/data/futures/um/monthly/fundingRate/BTCUSDT/", "OutOfScope"),
        (funding_get, funding.format("2024-12") + "?prefix=x", "OutOfScope"),
        (funding_file, "2025-01", "OutOfScope"),
        (open_funding, "2025-01", "OutOfScope"),
        (month_range, "2024-11", "OutOfScope"),  # second argument below: 2025-02
    ]
    wrong = 0
    for call, argument, want in cases:
        args = (argument, "2025-02") if call is month_range else (argument,)
        try:
            call(*args)
            got = "allowed"
        except OutOfScope:
            got = "OutOfScope"
        except Network:
            got = "network"
        wrong += got != want
        print(f"SELFTEST {call.__name__}{args} -> {got} (expected {want})")
    print(f"SELFTEST requests that reached the (disabled) network: {len(REQUESTED)}")
    print(f"SELFTEST wrong outcomes: {wrong}")
    return 1 if wrong else 0


def config_hashes() -> dict:
    return {p.as_posix(): sha256_file(p) for p in sorted(Path("config/datasets").glob("*.*"))}


def inputs_match() -> bool:
    ok = True
    for path, expected in INPUTS.items():
        actual = sha256_file(Path(path)) if Path(path).is_file() else "absent"
        print(f"INPUT {'ok' if actual == expected else 'CHANGED'} {actual}  {path}")
        ok = ok and actual == expected
    return ok


def main() -> int:
    if not inputs_match():
        print("PROBLEM an input differs from the reviewed one; nothing was requested")
        print("RESULT 1 problem(s)")
        return 1
    problems: list[str] = []
    hashes_before = config_hashes()
    OUT.mkdir(parents=True, exist_ok=True)
    specs = {name: load_spec(Path(f"config/datasets/{name}.toml")) for name in DATASETS}
    funding_months = month_range(FIRST_MONTH, LAST_MONTH)
    plan_daily, plan_funding = {}, {}
    for name, spec in specs.items():
        pairs = sorted({*spec.traded, spec.market_proxy})
        months = month_range(H_FIRST, previous(spec.daily_warmup_start))
        plan_daily[name] = [(pair, month) for pair in pairs for month in months]
        plan_funding[name] = [allowed(month) for month in spec.months()]
        existing = {
            (f["symbol"], f["interval"], f["month"])
            for f in load_manifest(Path(f"config/datasets/{name}.manifest.json"))["files"]
        }
        overlap = [x for x in plan_daily[name] if (x[0], "1d", x[1]) in existing]
        print(
            f"PLAN {name}: 1d {pairs} {months[0]}..{months[-1]} = {len(plan_daily[name])} files, "
            f"already in manifest {len(overlap)}; funding {plan_funding[name][0]}.."
            f"{plan_funding[name][-1]} = {len(plan_funding[name])} months"
        )
        if overlap:
            problems.append(f"{name}: planned 1d files already in the manifest: {overlap}")
    unique_daily = sorted({x for plan in plan_daily.values() for x in plan})
    every = funding_months + [m for _, m in unique_daily]
    print(
        f"PLAN funding months {len(funding_months)}, unique 1d files {len(unique_daily)}, "
        f"latest month {max(every)}"
    )
    if max(every) > LAST_MONTH:
        raise OutOfScope(f"planned month {max(every)} is after {LAST_MONTH}")

    funding, records_all = {}, []
    for month in funding_months:
        entry = retried(funding_file, month)
        if entry["status"] != "ok":
            problems.append(f"funding {month}: {entry['status']}")
            funding[month] = entry
            continue
        records = open_funding(month)
        start, end = month_bounds_ms(month)
        intervals = collections.Counter(
            "empty" if r.interval_hours is None else str(r.interval_hours) for r in records
        )
        entry.update(
            records=len(records),
            expected_records=3 * (end - start) // 86_400_000,
            first_calc_time_ms=records[0].calc_time_ms if records else None,
            last_calc_time_ms=records[-1].calc_time_ms if records else None,
            interval_hours=dict(sorted(intervals.items())),
            invalid_records=sum(not r.valid for r in records),
            max_offset_ms=max((r.calc_time_ms - r.scheduled_ms for r in records), default=None),
        )
        funding[month] = entry
        records_all += records

    steps = [
        (a, b, b.scheduled_ms - a.scheduled_ms)
        for a, b in zip(records_all, records_all[1:], strict=False)
    ]
    not_8h = [
        (a.calc_time_ms, b.calc_time_ms, s // HOUR_MS) for a, b, s in steps if s != 8 * HOUR_MS
    ]
    not_previous = sum(
        a.interval_hours is None or s != a.interval_hours * HOUR_MS for a, _, s in steps
    )
    offset = max(records_all, key=lambda r: r.calc_time_ms - r.scheduled_ms)
    try:
        FundingSignal(records_all)
        signal = "constructed; no duplicate scheduled time"
    except DataError as exc:
        signal = f"DataError: {exc}"
        problems.append(f"FundingSignal: {exc}")

    daily = {}
    for symbol, month in unique_daily:
        try:
            daily[symbol, month] = retried(fetch_file, DATA, symbol, "1d", month, kline_get)
        except ArchiveParseError as exc:
            daily[symbol, month] = {
                "symbol": symbol,
                "interval": "1d",
                "month": month,
                "status": "unparsed",
                "error": str(exc),
                "sha256": sha256_file(local_path(DATA, symbol, "1d", month)),
            }

    print("\n## Funding archives, BTCUSDT, per month\n")
    print(
        "| Month | Status | Records | Expected (3 per day) | First calc_time | Last calc_time "
        "| funding_interval_hours | Invalid | Max offset ms | Bytes | SHA-256 |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for month, e in funding.items():
        print(
            f"| {month} | {e['status']} | {e.get('records')} | {e.get('expected_records')} | "
            f"{e.get('first_calc_time_ms')} | {e.get('last_calc_time_ms')} | "
            f"{e.get('interval_hours')} | {e.get('invalid_records')} | {e.get('max_offset_ms')} | "
            f"{e.get('bytes')} | {e.get('sha256')} |"
        )
    totals = collections.Counter()
    for e in funding.values():
        totals.update(e.get("interval_hours", {}))
    ok_months = sum(e["status"] == "ok" for e in funding.values())
    print(
        f"\nFUNDING months ok {ok_months} of {len(funding)}; "
        f"records {len(records_all)}; interval_hours {dict(totals)}; "
        f"invalid {sum(e.get('invalid_records', 0) for e in funding.values())}"
    )
    print(
        f"FUNDING steps {len(steps)}; not 8 h {len(not_8h)} {not_8h[:20]}; "
        f"not equal to the previous record's interval {not_previous}; "
        f"duplicates {sum(s == 0 for _, _, s in steps)}"
    )
    print(
        f"FUNDING largest offset past the hour {offset.calc_time_ms - offset.scheduled_ms} ms "
        f"at calc_time {offset.calc_time_ms}; FundingSignal {signal}"
    )

    pr19 = {
        m: (int(r), int(f), int(la)) for m, r, f, la, _ in PR19_ROW.findall(PR19.read_text("utf-8"))
    }
    print(f"\n## Comparison with PR #19 ({PR19}, {len(pr19)} month rows)\n")
    print("| Month | Records | PR #19 rows | First equal | Last equal | Records = expected |")
    print("| --- | --- | --- | --- | --- | --- |")
    for month, e in funding.items():
        mine = (e.get("records"), e.get("first_calc_time_ms"), e.get("last_calc_time_ms"))
        theirs = pr19.get(month, (None, None, None))
        row = (
            mine[0] == theirs[0],
            mine[1] == theirs[1],
            mine[2] == theirs[2],
            e.get("records") == e.get("expected_records"),
        )
        print(f"| {month} | {mine[0]} | {theirs[0]} | {row[1]} | {row[2]} | {row[3]} |")
        if not all(row):
            problems.append(
                f"funding {month} differs from PR #19 or from 3 per day: {mine} {theirs}"
            )

    print("\n## Daily (1d) archives, 2020-05 up to each dataset's daily_warmup_start\n")
    print(
        "| Pair | Month | Status | Rows | Expected | Missing | Gaps | First open ms | Last open ms "
        "| Bytes | SHA-256 |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for (symbol, month), e in daily.items():
        print(
            f"| {symbol} | {month} | {e['status']} | {e.get('rows')} | {e.get('expected_rows')} | "
            f"{e.get('missing_rows')} | {e.get('gaps')} | {e.get('first_open_ms')} | "
            f"{e.get('last_open_ms')} | {e.get('bytes')} | {e.get('sha256')} |"
        )
        if e["status"] == "unparsed":
            print(f"UNPARSED {symbol} {month}: {e['error']}")
    statuses = collections.Counter(e["status"] for e in daily.values())
    print(f"\nDAILY files {len(daily)}; by status {dict(statuses)}")
    # P3: every expected day present once and contiguous. The only allowed exceptions are
    # SOLUSDT before its listing: 2020-05..07 missing, 2020-08 starting on 2020-08-11.
    incomplete = []
    for (symbol, month), e in daily.items():
        if symbol == "SOLUSDT" and month in ("2020-05", "2020-06", "2020-07"):
            continue  # checked as known values below
        if symbol == "SOLUSDT" and month == "2020-08" and e["status"] == "ok":
            listing = e["first_open_ms"] == SOL_FIRST_OPEN_MS
            start_ms = month_bounds_ms(month)[0]
            if listing and e["missing_rows"] == (SOL_FIRST_OPEN_MS - start_ms) // 86_400_000:
                if e["gaps"] == 1:  # the leading absence before the listing only
                    continue
        if e["status"] != "ok" or e["missing_rows"] != 0 or e["gaps"] != 0:
            incomplete.append(
                f"{symbol} {month} {e['status']} "
                f"missing {e.get('missing_rows')} gaps {e.get('gaps')}"
            )
    for line in incomplete:
        print(f"INCOMPLETE {line}")
        problems.append(f"daily file incomplete or unparsed: {line}")
    print(f"DAILY incomplete or unparsed (SOLUSDT's listing month excepted): {len(incomplete)}")

    print("\n## Known values\n")
    sol_missing = [daily["SOLUSDT", m]["status"] for m in ("2020-05", "2020-06", "2020-07")]
    known = [
        ("funding months ok", ok_months, 60),
        ("funding records, all months", len(records_all), 5481),
        ("funding interval_hours values", dict(totals), {"8": 5481}),
        ("funding invalid records", sum(e.get("invalid_records", 0) for e in funding.values()), 0),
        ("funding steps not 8 h", len(not_8h), 0),
        ("funding largest offset ms", offset.calc_time_ms - offset.scheduled_ms, 47),
        ("funding largest offset calc_time", offset.calc_time_ms, 1631865600047),
        ("SOLUSDT 1d 2020-05..2020-07 status", sol_missing, ["missing"] * 3),
        (
            "SOLUSDT 1d 2020-08 first open ms",
            daily["SOLUSDT", "2020-08"].get("first_open_ms"),
            1597104000000,
        ),
        ("latest 1d month planned", max(m for _, m in unique_daily), "2023-04"),
        (
            "1d files missing other than SOLUSDT 2020-05..07",
            sum(e["status"] == "missing" for e in daily.values()) - sol_missing.count("missing"),
            0,
        ),
    ]
    print("| Figure | Measured | Known | Equal |")
    print("| --- | --- | --- | --- |")
    for figure, measured, expected in known:
        print(f"| {figure} | {measured} | {expected} | {measured == expected} |")
        if measured != expected:
            problems.append(f"known value differs: {figure}: {measured} != {expected}")

    print("\n## Proposed manifest additions (the committed manifests are not changed)\n")
    print(
        "| Dataset | 1d entries | 1d by status | 1d months | Funding entries | Funding months "
        "| Additions file SHA-256 |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for name in DATASETS:
        additions = {
            "dataset": name,
            "assumes": {"daily_warmup_start": H_FIRST},
            "manifest_sha256": hashes_before[f"config/datasets/{name}.manifest.json"],
            "daily": [daily[x] for x in plan_daily[name]],
            "funding": [funding[m] for m in plan_funding[name]],
        }
        path = OUT / f"{name}.additions.json"
        path.write_text(json.dumps(additions, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        by_status = dict(collections.Counter(e["status"] for e in additions["daily"]))
        months = sorted({m for _, m in plan_daily[name]})
        print(
            f"| {name} | {len(additions['daily'])} | {by_status} | {months[0]}..{months[-1]} | "
            f"{len(additions['funding'])} | {plan_funding[name][0]}..{plan_funding[name][-1]} | "
            f"{sha256_file(path)} |"
        )

    (OUT / "requests.txt").write_text("\n".join(REQUESTED) + "\n", encoding="utf-8")
    requested_months = [re.search(r"-(\d{4}-\d{2})\.zip", p).group(1) for p in REQUESTED]
    late = [p for p, m in zip(REQUESTED, requested_months, strict=True) if m > LAST_MONTH]
    print(
        f"\nREQUESTS {len(REQUESTED)}; latest month {max(requested_months)}; "
        f"after {LAST_MONTH}: {len(late)}; list in {OUT / 'requests.txt'} "
        f"sha256 {sha256_file(OUT / 'requests.txt')}"
    )
    if late:
        problems.append(f"requests after {LAST_MONTH}: {late}")
    unchanged = config_hashes() == hashes_before
    print(f"CONFIG config/datasets unchanged: {unchanged}")
    for path, digest in hashes_before.items():
        print(f"CONFIG {digest}  {path}")
    if not unchanged:
        problems.append("config/datasets changed during the run")
    for problem in problems:
        print(f"PROBLEM {problem}")
    print(f"RESULT {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(self_test() if sys.argv[1:] == ["--self-test"] else main())
```

sed -n '422,899p' docs/reviews/2026-09-27-bob-p8-funding-archives.md | sha256sum
35a4ea2cf36cae67339784fada62063880a41455d1a60316902f93c52363c75e  -

## Checks

```text
?? docs/reviews/2026-09-27-bob-p8-funding-archives.md
check_reports: verified 2026-09-26-bob-hourly-defect-calendar.md:data/calendar.py
check_reports: corrected 2026-09-26-bob-hourly-defect-calendar.md:data/events.py (states 53097095f39c.., appendix is 55f19293acc5..)
check_reports: verified 2026-09-26-bob-outage-calendar.md:data/outages.py
check_reports: verified 2026-09-26-bob-parser-anomaly-classes.md:data/anomalies.py
check_reports: verified 2026-09-26-bob-refined-parser-rule.md:data/refined_rule.py
check_reports: verified 2026-09-26-claude-open-mismatch-explained.md:data/open_mismatch.py
check_reports: verified 2026-09-26-claude-volume-field-provenance.md:data/volume_fields.py
check_reports: verified 2026-09-27-bob-combined-defect-census.md:data/defect_census.py
check_reports: verified 2026-09-27-bob-p8-funding-archives.md:data/p8_archives.py
check_reports: verified 2026-09-27-bob-rescued-month-masking.md:data/rescued_masking.py
check_reports: verified 2026-09-27-bob-rescued-month-masking.md:data/rescued_bands.py
check_reports: verified 2026-09-27-claude-defect-calendar-corrections.md:data/calendar_denominator.py
check_reports: verified 2026-09-27-claude-defect-calendar-corrections.md:data/eventwide_per_hour.py
check_reports: verified 2026-09-27-claude-eligibility-thresholds.md:data/masked_fraction.py
check_reports: verified 2026-09-27-claude-eligibility-thresholds.md:data/masked_bands.py
check_reports: verified 2026-09-27-claude-eligibility-thresholds.md:data/masked_corrections.py
check_reports: verified 2026-09-27-claude-fold-grid-and-eligibility.md:data/fold_eligibility.py
check_reports: verified 2026-09-27-claude-soft-drawdown-lockout.md:data/flat_stretches.py
check_reports: verified 2026-09-28-claude-v2-downtrend-research.md:data/v2_downtrend_research.py
check_reports: 33 stated hash(es): 18 verified, 1 corrected in place, 14 unverifiable
check_reports: 95 script mention(s) without a hash (information; a mention is not a pin)
check_reports: 0 problem(s)
exit 0
appendix problems: []
appendix checked: ['verified 2026-09-27-bob-p8-funding-archives.md:data/p8_archives.py']
Tue Sep 29 11:16:33 UTC 2026
```

**Corrections (Claude, 2026-10-05, from Codex's review of PR #164).** Four hand-written statements were corrected; the logs, tables and script above are unchanged. The `Index:` line now separates the 101 verified daily archives from SOLUSDT's 3 expected absences. The funding discriminator is `"fundingRate"`, as `fetch_funding_file` writes it, not `"funding"`. `"missing"` daily entries need no schema change. The two additions hold 120 daily entries (48 + 72), not 108.
