# Security boundaries

This milestone is experimental, paper-only, and not approved for real funds.
It has no networked exchange implementation and does not read API credentials.

- Never commit keys, credentials, private account exports, or personal balances.
- Do not add withdrawal-enabled keys or enable leverage/futures.
- Do not switch to live mode by removing validation. A separate tested adapter
  and explicit live-deployment approval are required.
- Treat news and external feeds as untrusted data, never as executable commands.
- Market data uses only Binance's public data hosts, and exactly these three:
  <!-- allowed-hosts:begin (tests/test_documented_hosts.py reads this block exactly) -->
  - `data-api.binance.vision` — REST market data (`HOST`, `market_data/client.py`);
  - `data-stream.binance.vision` — WebSocket streams (`STREAM_HOST`, `market_data/stream.py`);
  - `data.binance.vision` — historical archives and their `.CHECKSUM` files
    (`ARCHIVE_HOST`, `backtest/dataset.py`).
  <!-- allowed-hosts:end -->

  Each is a named constant. Adding a host means editing this list in the same change:
  that is a rule for whoever writes the change, not something the system enforces.

  `tests/test_documented_hosts.py` catches one kind of mistake, and only one: **a Binance
  hostname** — a subdomain of `binance.vision` or `binance.com`, in any letter case —
  written anywhere in `src/*.py`, comments and docstrings included, that is not an exact
  entry in the list above. It compares whole hostnames, lowercased, so a host is not
  "listed" because it appears inside a longer listed one or elsewhere in this document.
  The markers must each appear once, begin before end, or the test fails. It is **a
  string scan, not an egress filter**, and it is narrow:
  - it does not look for any other host at all, so another exchange's hostname in
    `src/` would pass unnoticed;
  - it cannot see a host assembled at runtime, read from configuration, or reached
    through a redirect;
  - it does not check the reverse — a listed host the code no longer uses.

  So a passing suite is not evidence that nothing else was contacted.
- Do not point collectors or streams at trading hosts, or add user-data (`listenKey`)
  streams, before the live-adapter review.
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
