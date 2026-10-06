"""The byte-identity check (scripts/byte_identity.py) builds the same data every time.

Only the dataset builder and the pure helpers are tested here: a full ``check`` replays
dozens of runs and takes minutes, so it is run by hand (``python scripts/byte_identity.py
check``) and not by the suite.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.models import MarketRules
from crypto_grid_bot.simulation.runner import PaperSimulator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import byte_identity  # noqa: E402


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` by relative path, with its bytes."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture(scope="module")
def nod_builds(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, dict[str, bytes], dict[str, bytes]]:
    """The `nod` dataset built twice, in two directories."""
    first, second = tmp_path_factory.mktemp("first"), tmp_path_factory.mktemp("second")
    byte_identity.build_dataset(first, "nod")
    byte_identity.build_dataset(second, "nod")
    return first, snapshot(first), snapshot(second)


def test_byte_identity_dataset_builder_is_deterministic(
    nod_builds: tuple[Path, dict[str, bytes], dict[str, bytes]],
) -> None:
    _, first, second = nod_builds
    assert first == second
    assert "synth.manifest.json" in first
    assert any(name.endswith(".zip") for name in first)


def test_dataset_manifest_is_stamped_with_the_fixed_clock_and_lists_the_funding_month(
    nod_builds: tuple[Path, dict[str, bytes], dict[str, bytes]],
) -> None:
    root, _, _ = nod_builds
    manifest = json.loads((root / "synth.manifest.json").read_text(encoding="utf-8"))
    assert manifest["created_at"] == "2024-03-01T00:00:00+00:00"
    funding = [f for f in manifest["files"] if f.get("kind") == "fundingRate"]
    assert [(f["symbol"], f["month"], f["status"]) for f in funding] == [
        ("BTCUSDT", "2024-01", "ok")
    ]


def test_the_nod_dataset_has_no_daily_history(
    nod_builds: tuple[Path, dict[str, bytes], dict[str, bytes]],
) -> None:
    _, first, _ = nod_builds
    assert not any("/1d/" in name for name in first)
    assert any("/1h/" in name for name in first) and any("/1m/" in name for name in first)


def test_identity_keys_are_set_aside_at_any_depth_and_nothing_else() -> None:
    document = {
        "spec_sha256": "a",
        "results": [{"code_commit": "b", "return_pct": 1, "nested": {"config_sha256": "c"}}],
        "manifest_sha256": "d",
        "code_sha256": "e",
        "valid": True,
    }
    assert byte_identity.set_aside(document) == {
        "results": [{"return_pct": 1, "nested": {}}],
        "valid": True,
    }
    assert byte_identity.document_sha256(document) == byte_identity.document_sha256(
        {**document, "spec_sha256": "other", "code_commit": "other"}
    )
    assert byte_identity.document_sha256(document) != byte_identity.document_sha256(
        {**document, "valid": False}
    )


def fill(order_id: str = "o1", side: str = "buy", price: str = "100", quantity: str = "1") -> Any:
    return {"order_id": order_id, "side": side, "price": price, "quantity": quantity, "fee": "0.1"}


def trace_of(*steps: tuple[list[Any], str | None, list[tuple[str, str, str, str]]]) -> str:
    """The digest of ``steps``, each (fills, exit_reason, resting orders)."""
    trace, simulator = byte_identity.StepTrace(), object()
    for fills, reason, resting in steps:
        orders = {
            key: SimpleNamespace(order_id=key, side=side, price=price, remaining=remaining)
            for key, side, price, remaining in resting
        }
        report: dict[str, Any] = {"fills": fills}
        if reason is not None:
            report["exit_reason"] = reason
        trace.record(simulator, SimpleNamespace(orders=orders), report)
    return trace.hexdigest()


def test_the_step_trace_sees_every_fill_exit_reason_and_resting_order_in_order() -> None:
    book = [("o1", "buy", "99", "1"), ("o2", "sell", "101", "1")]
    base = trace_of(([fill("o1"), fill("o2", "sell")], "range_exit", book), ([], None, book))
    assert base == trace_of(
        ([fill("o1"), fill("o2", "sell")], "range_exit", book), ([], None, book)
    )
    for changed in (
        # fills reordered, relabelled, or moved to another price, quantity or fee
        ([fill("o2", "sell"), fill("o1")], "range_exit", book),
        ([fill("o1"), fill("o2", "buy")], "range_exit", book),
        ([fill("o1", price="100.5"), fill("o2", "sell")], "range_exit", book),
        ([fill("o1", quantity="2"), fill("o2", "sell")], "range_exit", book),
        ([{**fill("o1"), "fee": "0.2"}, fill("o2", "sell")], "range_exit", book),
        # the exit reason, the resting orders, or the order they rest in
        ([fill("o1"), fill("o2", "sell")], "liquidation", book),
        ([fill("o1"), fill("o2", "sell")], None, book),
        ([fill("o1"), fill("o2", "sell")], "range_exit", [("o1", "buy", "99", "0.5"), book[1]]),
        ([fill("o1"), fill("o2", "sell")], "range_exit", [book[1], book[0]]),
    ):
        assert trace_of(changed, ([], None, book)) != base


def test_the_step_trace_counts_steps_and_marks_each_new_simulator() -> None:
    one = byte_identity.StepTrace()
    account = SimpleNamespace(orders={})
    for simulator in (object(), object()):
        one.record(simulator, account, {"fills": []})
    same = byte_identity.StepTrace()
    simulator = object()
    for _ in range(2):
        same.record(simulator, account, {"fills": []})
    assert (one.steps, same.steps) == (2, 2)
    # Two replays of one step each are not one replay of two.
    assert one.hexdigest() != same.hexdigest()


def test_the_step_trace_wrapper_traces_a_real_simulator_and_changes_nothing() -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config" / "default.toml")

    def reports() -> list[dict[str, Any]]:
        simulator = PaperSimulator(Path(":memory:"), config, MarketRules())
        account = simulator.store.read()
        simulator.close()  # a replay steps an in-memory account, as here
        return [simulator.step(account, frame) for frame in demo_frames(2)]

    original = PaperSimulator.step
    plain = reports()
    with byte_identity.step_trace() as trace:
        traced = reports()
    assert PaperSimulator.step is original
    assert traced == plain
    assert any(report["fills"] for report in plain)
    assert trace.steps == 8


def test_a_run_is_identical_only_when_document_trace_and_step_count_all_match() -> None:
    outcome = byte_identity.Outcome("run", {}, "doc", "trace", 5)
    recorded = {"sha256": "doc", "trace_sha256": "trace", "steps": 5}
    assert byte_identity.differences(outcome, recorded) == []
    assert byte_identity.differences(outcome, None) == ["not in the baseline"]
    # Aggregates that agree are not enough: the trace alone can differ.
    assert byte_identity.differences(outcome, {**recorded, "trace_sha256": "x"}) == [
        "step trace differs"
    ]
    assert byte_identity.differences(outcome, {"sha256": "x", "trace_sha256": "y", "steps": 6}) == [
        "output document differs",
        "step trace differs",
        "step count differs",
    ]


def test_the_recorded_baseline_covers_exactly_the_runs_the_script_makes() -> None:
    baseline = json.loads(byte_identity.BASELINE.read_text(encoding="utf-8"))
    assert list(baseline["runs"]) == [run.name for run in byte_identity.RUNS]
    for entry in baseline["runs"].values():
        assert set(entry) == {"sha256", "trace_sha256", "steps"}
        assert len(entry["sha256"]) == len(entry["trace_sha256"]) == 64
        assert entry["steps"] > 0
