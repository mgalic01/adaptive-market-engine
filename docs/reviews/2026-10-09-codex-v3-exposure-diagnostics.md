# V3 exposure and margin diagnostics

Index: Retained signed net notional in account marks and implemented frozen post-fill exposure/minimum-margin diagnostics; synthetic-only, full CI and external review pending.

The frozen report needs signed net exposure, but retained account marks contained
only gross notional. Production marks now also store the signed sum of quantity
times mark price. This field is appended with an explicit None default for older
positional constructors; actual account marks always fill it, including zero for
flat books. Diagnostics reject missing net evidence instead of calling it zero.
The dataclass evidence serializer retains this additive field automatically.

`trend.exposure.exposure_diagnostics` consumes retained hourly `HourResult` records.
It uses the final step-4 mark: `post_fill_delevered` when present, otherwise
`post_fill`. Funding, funding-driven delevering and intrabar extremes occur later
and cannot replace that hour's exposure sample. The arithmetic mean includes flat
hours. Shorts have negative net exposure; gross exposure remains nonnegative.

The lowest margin ratio is calculated from all retained liquidation-check marks:
open, post-fill, funding, their delevered marks, and adverse. Favourable marks are
not liquidation checks and are excluded. Flat checks have no margin ratio.

For an early terminal hour that never reaches step 4, observed and sampled counts
expose the missing sample. No flat observation is invented. A sampled nonpositive
equity makes mean gross/net ratios explicitly unavailable, with an undefined-hour
count; the invested fraction can still be reported. These are diagnostic results,
not strategy-validity or whole-experiment verdicts. The enclosing report must
establish source provenance, hourly continuity and accounting integrity.

Four initial tests failed before implementation. The combined 83 exposure,
account, execution, replay and evidence-writer checks pass, as do Ruff lint/format
and mypy. Independent review found no actionable defect and ran 47 focused checks.
Full CI and exact-head Bob/Claude review remain required before merge.

No trading arithmetic, order sequence, risk threshold, dependency or network
permission changed. Compatibility impact: serialized account marks gain nullable
`net_notional`; old artifacts cannot support this diagnostic without reconstructing
the missing quantity evidence. No historical data was fetched or replayed.

Codex owns incorporation into the eventual report, with coverage counts and
unavailable values displayed. Never silently drop invalid-run hours or substitute
gross exposure for net exposure when comparing risk and return.
