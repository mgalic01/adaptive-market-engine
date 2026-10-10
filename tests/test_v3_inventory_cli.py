"""The default planning command is offline; fetch requires explicit content pins."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_plan_cli_is_offline_and_reports_discovery_scope(monkeypatch, capsys):
    import v3_inventory

    def forbidden():
        pytest.fail("offline plan constructed transport")

    monkeypatch.setattr(v3_inventory, "V3Transport", forbidden)
    assert v3_inventory.main(["plan"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["request_count"] == 2710
    assert plan["last_month"] == "2024-12"
    assert len(plan["request_plan_sha256"]) == 64


def test_fetch_cli_checks_spec_pin_before_transport(monkeypatch, tmp_path):
    import v3_inventory

    def forbidden():
        pytest.fail("bad content pin must fail before transport")

    monkeypatch.setattr(v3_inventory, "V3Transport", forbidden)
    spec = tmp_path / "spec.md"
    spec.write_text("changed spec")
    with pytest.raises(ValueError, match="hash"):
        v3_inventory.main(
            [
                "fetch",
                "--output",
                str(tmp_path / "output"),
                "--cache-dir",
                str(tmp_path / "cache"),
                "--spec-file",
                str(spec),
                "--spec-sha256",
                "a" * 64,
                "--spot-manifest",
                str(tmp_path / "manifest.json"),
                "--spot-manifest-sha256",
                "b" * 64,
            ]
        )
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("mode", ["missing_hash", "wrong_hash", "invalid_content"])
@pytest.mark.parametrize("market", ["spot", "futures"])
def test_saved_snapshot_is_validated_before_any_transport(tmp_path, monkeypatch, mode, market):
    import hashlib

    import v3_inventory

    def forbidden():
        pytest.fail("invalid recovery input constructed transport")

    monkeypatch.setattr(v3_inventory, "V3Transport", forbidden)
    saved = tmp_path / f"{market}.json"
    saved.write_bytes(b'{"symbols": []}')
    args = [
        "fetch",
        "--output",
        str(tmp_path / "out"),
        "--cache-dir",
        str(tmp_path / "cache"),
        "--spec-file",
        str(tmp_path / "spec"),
        "--spec-sha256",
        "a" * 64,
        "--spot-manifest",
        str(tmp_path / "source"),
        "--spot-manifest-sha256",
        "b" * 64,
        f"--reuse-{market}-snapshot",
        str(saved),
    ]
    if mode != "missing_hash":
        digest = (
            "c" * 64 if mode == "wrong_hash" else hashlib.sha256(saved.read_bytes()).hexdigest()
        )
        args.extend([f"--{market}-snapshot-sha256", digest])
    with pytest.raises(ValueError):
        v3_inventory.main(args)
    assert not (tmp_path / "out").exists()
