import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from test_v3_replay_assembly import inputs as synthetic_inputs  # noqa: E402
from trial_register import RegisteredDocuments  # noqa: E402


@pytest.fixture
def inputs():
    return synthetic_inputs.__wrapped__()


def documents(loaded, first):
    config = json.dumps({"schema_version": 1, "experiment": "v3", "first_months": first}).encode()
    manifest = b'{"schema_version":1,"experiment":"v3"}'
    digest = hashlib.sha256(manifest).hexdigest()
    docs = RegisteredDocuments(
        "trial",
        "1" * 40,
        "registered",
        "completed",
        "2" * 40,
        "3" * 64,
        loaded.spec_sha256,
        "config/inventory.json",
        digest,
        manifest,
        "config/run.json",
        hashlib.sha256(config).hexdigest(),
        config,
    )
    return docs, replace(loaded, manifest_sha256=digest)


def test_binds_only_matching_supplied_objects_without_authorizing_dispatch(inputs):
    from v3_registered_inputs import bind_registered_inputs

    loaded, first = inputs
    docs, loaded = documents(loaded, first)
    result = bind_registered_inputs(docs, loaded)
    assert result.documents == docs
    assert result.inputs.first_months == first
    assert result.inputs.manifest_sha256 == docs.manifest_sha256
    assert result.inputs.replay_ready is False
    assert set(result.inputs.hold_hourly) == set(first)


@pytest.mark.parametrize("damage", ["config_bytes", "manifest_bytes", "inventory", "spec"])
def test_identity_mismatch_is_rejected(inputs, damage):
    from v3_registered_inputs import bind_registered_inputs

    loaded, first = inputs
    docs, loaded = documents(loaded, first)
    if damage == "config_bytes":
        docs = replace(docs, config=docs.config + b" ")
    elif damage == "manifest_bytes":
        docs = replace(docs, manifest=docs.manifest + b" ")
    elif damage == "inventory":
        loaded = replace(loaded, manifest_sha256="f" * 64)
    else:
        loaded = replace(loaded, spec_sha256="f" * 64)
    with pytest.raises(ValueError, match="identity"):
        bind_registered_inputs(docs, loaded)


@pytest.mark.parametrize(
    "damage", ["extra", "duplicate", "type", "reserved", "calendar", "version"]
)
def test_no_unregistered_configuration_overrides(inputs, damage):
    from v3_registered_inputs import bind_registered_inputs

    loaded, first = inputs
    docs, loaded = documents(loaded, first)
    config = json.loads(docs.config)
    if damage == "extra":
        config["leverage"] = 100
    elif damage == "type":
        config["first_months"] = []
    elif damage == "reserved":
        config["first_months"]["BTCUSDT"] = "2025-01"
    elif damage == "calendar":
        config["first_months"]["BTCUSDT"] = "2023-05"
    elif damage == "version":
        config["schema_version"] = True
    raw = json.dumps(config).encode()
    if damage == "duplicate":
        raw = raw[:-1] + b',"experiment":"v3"}'
    docs = replace(docs, config=raw, config_sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):
        bind_registered_inputs(docs, loaded)
