"""Build the V3 input pack (Rulings P9, P15) with V3's own frozen assembly.

V3's registered run (``scripts/v3_dispatch.py``) loaded its hash-pinned collection with
``v3_inventory_loader.load_inventory_inputs`` and joined it against its registered calendar
with ``v3_replay_assembly.assemble_replay_inputs``. ``build_v3_pack`` makes exactly those
two calls, then writes the assembled fields the frozen V3 arms read with
``combined.driver.v3_pack.write_v3_pack``. Nothing is re-implemented and the frozen
scripts are unchanged. Offline: the loader reads local files only.
"""

from collections.abc import Mapping
from pathlib import Path

from v3_inventory_loader import load_inventory_inputs
from v3_replay_assembly import ReplayInputs, assemble_replay_inputs

from crypto_grid_bot.combined.driver.v3_pack import V3PackFields, write_v3_pack


def build_v3_pack(
    inventory_root: Path, manifest_sha256: str, first_months: Mapping[str, str], path: Path
) -> str:
    """Write the V3 input pack to a new file at ``path`` and return its pin (the SHA-256
    of its canonical JSON, the run-manifest's ``v3_pack_sha256``).

    ``inventory_root`` and ``manifest_sha256`` name V3's verified collection, which
    ``load_inventory_inputs`` re-verifies; ``first_months`` is the calendar V3's run was
    registered with, ``config/v3-development-run.json``'s ``first_months``. Whatever the
    loader or the assembly refuses is refused, and no pack is written.
    """
    inventory = load_inventory_inputs(inventory_root, manifest_sha256)
    return write_v3_pack(pack_fields(assemble_replay_inputs(inventory, first_months)), path)


def pack_fields(inputs: ReplayInputs) -> V3PackFields:
    """The fields of V3's assembled inputs that ``V3Inputs`` is rebuilt from."""
    return V3PackFields(
        first_months=inputs.first_months,
        spot_bars=inputs.spot_bars,
        spot_exclusions=inputs.spot_exclusions,
        futures_exclusions=inputs.futures_exclusions,
        futures_filters=inputs.futures_filters,
        futures_hourly=inputs.futures_hourly,
        funding=inputs.funding,
    )
