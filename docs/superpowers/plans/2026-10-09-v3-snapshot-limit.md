# V3 snapshot ceiling fix plan

Base: `7b8fce4abdf5694aecfa84580286fa4dc46715f3`.
Goal: allow bounded public exchange-info snapshots through the V3 collection and
verification path so the frozen experiment can obtain trustworthy inputs.

1. Trace the failed spot response and every downstream snapshot limit, including
   `trend/filters.py`; do not reproduce against any public endpoint.
2. Add synthetic tests for >8 MiB, exactly 32 MiB, and >32 MiB across transport,
   collection, saved-snapshot CLI, parser, verifier and loader. Observe old-code failures.
3. Define one 32 MiB ceiling in the offline filter module and import it at every
   boundary. Keep 64 MiB archives, 1 KiB checksums, fixed endpoints, no-retry behavior,
   strict parsing, content pins and reserved-window checks unchanged.
4. Run focused and repository checks; record the incident and verification limits.
   Commit locally for parent review; no push, retry, replacement, replay or download.

Evidence: initial new-test run had 10 expected failures and 6 passes. With the fix,
all 16 cases passed. The larger cap is a bounded compatibility change, not evidence
that a future live response will fit or parse. Parent owns independent review and
any separately approved recovery task; the old E: attempt remains untouched.
