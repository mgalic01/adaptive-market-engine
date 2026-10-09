# Assemble verified monthly inventory for replay

Goal: connect the offline monthly loader to the supplied-input runner without
changing the frozen strategy or granting historical dispatch permission.

Inputs are the already verified InventoryInputs and explicitly supplied portfolio
join months. Require the fixed complete identity set, ten-symbol filters and exact
agreement with the collection's candidate join calendar. That calendar still needs
human review and committed registration; agreement is not approval.

Assemble each market's sorted hourly bars independently. Preserve raw funding
timestamps, group simultaneous cross-coin events, and reject duplicates. Derive
separate spot and futures/funding exclusions after each coin joins. Signal daily
bars exclude only spot-ineligible months; futures-only exclusions retain signal
updates (section 4). Retain spot warmup from the first full spot month, not an
eligible partial listing month, before joining.
Do not substitute futures daily bars for spot signals. No fetching, market-file
access, runs, full-size hold or final verdict.

Test first: warmup, funding-only exclusion, spot-only exclusion, independent prices,
raw funding offsets, duplicate/partial inventories, invalid join calendar. Then
implement, run related offline tests and static checks, and obtain independent
review and current-head Bob/CI before merge.

Review focus: masking across markets, warmup truncation, timestamp rounding and
mistaking the supplied reviewed-calendar parameter for authorization.
