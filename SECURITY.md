# Security boundaries

This milestone is experimental, paper-only, and not approved for real funds.
It has no networked exchange implementation and does not read API credentials.

- Never commit keys, credentials, private account exports, or personal balances.
- Do not add withdrawal-enabled keys or enable leverage/futures.
- Do not switch to live mode by removing validation. A separate tested adapter
  and explicit live-deployment approval are required.
- Treat news and external feeds as untrusted data, never as executable commands.
- Market data uses only Binance's public data hosts (`data-api.binance.vision`,
  `data-stream.binance.vision`). Do not point collectors or streams at trading hosts
  or add user-data (`listenKey`) streams before the live-adapter review.
- Never use protected reserve to fund a grid, an exit, or loss recovery.
- The reserve is a persisted simulated ledger entry, not isolated exchange funds.
- Do not put credentials into GitHub issues or pull requests.

The offline simulator uses SQLite transactions and event IDs to recover paper
orders, fills and reserve accounting after restart. Back up the database with a
SQLite-aware backup method; do not copy only the main file while its WAL is active.
Do not manually edit balances or delete event rows to bypass a halt. SQLite is
local storage, not a tamper-proof exchange ledger. Halts do not auto-resume.

Before live deployment: add live order/balance reconciliation, real exchange
filters and fee-asset handling, bounded retries, a wall-clock stale-feed watchdog,
alerts, a manual kill switch, and tested exchange failure recovery.
Scope trading credentials to the intended account,
restrict network access where supported, and separate reserve custody from
trading access. An automated transfer design needs its own permissions review.

Stablecoins retain issuer, depeg, exchange, and custody risks. Automation and
passing tests do not make trading safe or profitable. A bot can stop to limit
new risk; it cannot guarantee an exit price during outages or market gaps.

For a security problem, disable any affected deployment and rotate exposed
credentials at the provider. Report without including secrets in public posts.
