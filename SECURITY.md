# Security boundaries

This milestone is experimental, paper-only, and not approved for real funds.
It has no networked exchange implementation and does not read API credentials.

- Never commit keys, credentials, private account exports, or personal balances.
- Do not add withdrawal-enabled keys or enable leverage/futures.
- Do not switch to live mode by removing validation. A separate tested adapter
  and explicit live-deployment approval are required.
- Treat news and external feeds as untrusted data, never as executable commands.
- Never use protected reserve to fund a grid, an exit, or loss recovery.
- The reserve is currently a simulated ledger entry, not isolated exchange funds.
- Do not put credentials into GitHub issues or pull requests.

Before live deployment: add persistent transactional accounting, restart/order
reconciliation, duplicate-event protection, exact exchange filters, fee-aware
execution, bounded retries, stale-data protection, alerts, a manual kill switch,
and tested failure recovery. Scope trading credentials to the intended account,
restrict network access where supported, and separate reserve custody from
trading access. An automated transfer design needs its own permissions review.

Stablecoins retain issuer, depeg, exchange, and custody risks. Automation and
passing tests do not make trading safe or profitable. A bot can stop to limit
new risk; it cannot guarantee an exit price during outages or market gaps.

For a security problem, disable any affected deployment and rotate exposed
credentials at the provider. Report without including secrets in public posts.
