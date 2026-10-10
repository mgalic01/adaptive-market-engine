"""Bind committed documents to verified supplied inventory; no dispatch or I/O."""

import hashlib
import json
from dataclasses import dataclass

from trial_register import RegisteredDocuments
from v3_inventory import _object
from v3_inventory_loader import InventoryInputs
from v3_replay_assembly import ReplayInputs, assemble_replay_inputs


@dataclass(frozen=True, slots=True)
class RegisteredReplayInputs:
    documents: RegisteredDocuments
    inputs: ReplayInputs


def bind_registered_inputs(
    documents: RegisteredDocuments, inventory: InventoryInputs
) -> RegisteredReplayInputs:
    """Require exact pins and a closed configuration schema before assembly.

    Caller obtains documents from read_registered_documents and inventory from
    load_inventory_inputs. This checks their linkage, not whether fabricated or
    subsequently mutated objects came from those validators. Runtime attestation,
    owner authorization, coverage review and result certification stay upstream.
    The returned inputs deliberately remain replay_ready=False.
    """
    if (
        len(documents.config) > 1024 * 1024
        or len(documents.manifest) > 32 * 1024 * 1024
        or hashlib.sha256(documents.config).hexdigest() != documents.config_sha256
        or hashlib.sha256(documents.manifest).hexdigest() != documents.manifest_sha256
        or documents.manifest_sha256 != inventory.manifest_sha256
        or documents.spec_sha256 != inventory.spec_sha256
    ):
        raise ValueError("registered input identity mismatch")
    config = json.loads(documents.config, object_pairs_hook=_object)
    if (
        not isinstance(config, dict)
        or set(config) != {"schema_version", "experiment", "first_months"}
        or type(config["schema_version"]) is not int
        or config["schema_version"] != 1
        or config["experiment"] != "v3"
        or not isinstance(config["first_months"], dict)
        or any(type(month) is not str for month in config["first_months"].values())
    ):
        raise ValueError("unsupported registered V3 configuration")
    return RegisteredReplayInputs(
        documents, assemble_replay_inputs(inventory, config["first_months"])
    )
