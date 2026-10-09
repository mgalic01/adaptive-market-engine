# V3 walk-forward calendar and rule selection

Index: Frozen 18-month training and quarterly test calendar plus deterministic
12-rule Sharpe selection; pure helpers, no data access or historical dispatch.

Purpose: make the experiment's training/test boundaries and selection reproducible.
Named writer: Codex Desktop. This branch is stacked on metrics; it must eventually
be retargeted to main, not merged into its dependency branch.

The validated manifest supplies BTCUSDT's first portfolio month. The first test
quarter starts at least 18 months later, rounded forward to a calendar quarter.
Each training window is exactly the preceding 18 months. Tests end at 2024-Q4;
2025-01 is only the exclusive end boundary, never a requested data month. Inputs
that are malformed, reserved or too late for a test quarter are rejected.

Rule selection requires all 12 frozen candidates and finite Decimal scores for
valid runs. None denotes strategy-invalid only, never missing evidence or an
engine error. Highest training Sharpe wins even if all scores are negative; ties
follow R1-R6, then R1L-R6L. All invalid selects flat for that quarter.

Validation: seven focused tests pass, including both spec calendar examples,
non-quarter starts, invalid dates, missing candidates, nonfinite scores, fixed tie
order and all-invalid behavior. Ruff and mypy pass. The full local suite completed
with one manifest-guard failure caused by resolving Windows' WSL stub as bash;
that exact test passed when rerun with installed Git Bash. No full-suite rerun is
claimed. Fresh PR CI and external review are required.

Still required: validated data adapter, fresh training accounts, signal/sizing
integration, continuous out-of-sample account, exclusion closures, scenario picks,
completion registration and result export. These helpers do not implement those
steps or claim the walk-forward experiment is ready. No data fetch/replay occurred.
