# V3 Sharpe uncertainty diagnostic

Index: Frozen stationary bootstrap implemented on synthetic returns; no historical interval.

Implements section 8's 10,000 stationary resamples, mean block length 20, circular
wrap, exact random draw order, fresh CPython Random(20261008) per series, and
nearest ranks 250/9750. Fewer than 60 returns gives no interval; malformed values
raise. Every resample uses the existing Decimal60 Sharpe calculation.

Four synthetic tests cover short/invalid input, constant-series interval, sample
count/ranks/fresh seed, and a hand-scripted restart/wrap draw sequence. Ruff and
mypy pass. No new dependency, source fetch, historical run or strategy change.
This estimates Sharpe uncertainty, not liquidation probability. Historical reporting
integration remains pending. Stacked on orchestration; merge only to main after
dependencies, exact-head external review and CI.
