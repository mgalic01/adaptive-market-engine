"""DIAGNOSTIC replay of a V3.1 cell with one runtime fix (owner decision v31-d34).
Not part of V3.1's registered verdict; its outputs are labelled diagnostic.

Root cause of the 8 crashed W1 research cells (2026-10-17): inside `Engine._settle`,
the settlement batch's own "before" mark runs routine cap management, which can cancel
the very pending spot-grid order whose fill is being settled (order close reason
`portfolio_cap_reduction`, simulated-venue finality). `_settle` then raises
"novel fill contradicts acknowledged finality", marks an integrity failure, and the
replay stops (`replay_failure:execution_failure:ValueError`).

The fix, applied to an in-memory copy of `combined/engine.py` (the file on disk is the
pinned code, unchanged): an increase whose order was given finality by this same batch's
pre-fill check counts as canceled before the fill and is not booked. A fill against an
order that was already final before the batch still raises. Two exact text
replacements, each asserted to occur once.

Usage (cwd = the d4a4f09 checkout, PYTHONPATH=src;scripts):
    python v31_run_cell_patched.py run-cell --mode registered ...
"""

import importlib
import importlib.util
import os
import sys

OLD_1 = '            self._batch_observations[batch_id] = ()\n            mark("before", batch_id)\n'
NEW_1 = (
    '            self._batch_observations[batch_id] = ()\n'
    '            finality_at_start = frozenset(self._finality)\n'
    '            mark("before", batch_id)\n'
)
OLD_2 = (
    '                if key in self._finality:\n'
    '                    raise ValueError("novel fill contradicts acknowledged finality")\n'
)
NEW_2 = (
    '                if key in self._finality:\n'
    '                    if key not in finality_at_start:\n'
    '                        continue  # DIAGNOSTIC FIX: canceled by this batch\'s pre-fill check\n'
    '                    raise ValueError("novel fill contradicts acknowledged finality")\n'
)

package = importlib.import_module("crypto_grid_bot.combined")
path = os.path.join(os.path.dirname(package.__file__), "engine.py")
with open(path, encoding="utf-8") as f:
    source = f.read()
assert source.count(OLD_1) == 1 and source.count(OLD_2) == 1, "engine.py is not the pinned text"
patched = source.replace(OLD_1, NEW_1).replace(OLD_2, NEW_2)
spec = importlib.util.spec_from_file_location("crypto_grid_bot.combined.engine", path)
module = importlib.util.module_from_spec(spec)
sys.modules["crypto_grid_bot.combined.engine"] = module
exec(compile(patched, path, "exec"), module.__dict__)
package.engine = module
print("DIAGNOSTIC: combined/engine.py patched in memory (pre-fill cancel = no fill)", file=sys.stderr, flush=True)

import v31_driver  # noqa: E402

raise SystemExit(v31_driver.main())
