# V3 spot benchmark cash ledger

Index: Spot settlement foundation with five synthetic tests; benchmark runner not yet implemented.

Implements Decimal60 spot settlement with 10,000 initial cash, 0.10% fee and 0.05%
slippage, doubled together in cost stress. Buys clip to cash including fees and
floor to quantity step. Minimum notional applies to buys and sells; unsellable dust
stays marked. Overselling and oversized single orders are rejected before mutation;
the later runner must split orders above the maximum. No borrowing or funding.

Five tests cover hand-calculated round trips at base/double cost, cash clipping,
dust, atomic rejection and detection of corrupted cash/quantity. Ruff and mypy
pass. Fill records retain requested/executed quantities, slipped price, fee and skip
reason. Cash and quantity audits replay the journal exactly.

Remaining plan work: max-order splitting in benchmark execution, further precision
and filter-boundary tests, continuous risk-matched benchmark runner, comparison
metrics and durable serialization. This ledger alone does not implement A5. No
historical source, live execution, new dependency or known security change.

Spot execution follow-up: balanced child quantities respect the maximum while
preserving the stepped total; spot settlement still enforces cash and notional on
each child, stopping when cash clips or a child cannot execute. Overselling is
rejected before any child settles. Seven tests now pass, including 13 split into
5/4/4 and low ambient precision. Ruff and mypy pass. Benchmark runner and broader
input/resource limits remain pending; this draft is not merge-ready.
