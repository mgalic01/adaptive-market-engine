"""The byte-identity check (scripts/byte_identity.py) builds the same data every time.

Only the dataset builder, the step trace and the output contract of ``check`` and
``record`` (with the runs replaced by fixed outcomes) are tested here: a full ``check``
replays 15 runs and takes the better part of an hour, so it is run by hand
(``python scripts/byte_identity.py check``) and not by the suite.
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
from crypto_grid_bot.simulation.runner import VARIANTS, PaperSimulator

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


def test_the_step_trace_wrapper_forwards_any_arguments_and_finds_the_account_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, object, object, int]] = []

    def step(self: object, account: object, frame: object, *, scale: int = 1) -> dict[str, Any]:
        calls.append((self, account, frame, scale))
        return {"fills": [fill()], "exit_reason": "range_exit"}

    # A step with another parameter, called with the account as a keyword.
    monkeypatch.setattr(PaperSimulator, "step", step)
    simulator, account = object(), SimpleNamespace(orders={})
    with byte_identity.step_trace() as trace:
        report = PaperSimulator.step(simulator, account=account, frame="frame", scale=2)
    assert report == {"fills": [fill()], "exit_reason": "range_exit"}
    assert calls == [(simulator, account, "frame", 2)]
    assert trace.steps == 1
    reference = byte_identity.StepTrace()
    reference.record(simulator, account, report)
    assert trace.hexdigest() == reference.hexdigest()


def test_the_run_table_covers_every_registered_variant() -> None:
    # A newly registered variant must be added to the runs, or this fails.
    assert {run.variant for run in byte_identity.RUNS if run.variant} == set(VARIANTS[1:])


def test_run_names_are_unique() -> None:
    names = [run.name for run in byte_identity.RUNS]
    assert len(set(names)) == len(names)


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


def outcome(name: str, letter: str, steps: int = 3) -> Any:
    """A run's outcome with made-up digests (a letter repeated to 64 hex digits)."""
    return byte_identity.Outcome(name, {}, letter * 64, letter.upper() * 64, steps)


@pytest.fixture
def baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The path ``check`` and ``record`` use for the baseline, in a temporary directory."""
    path = tmp_path / "baseline.json"
    monkeypatch.setattr(byte_identity, "BASELINE", path)
    return path


def baseline_of(*outcomes: Any, format: int = 1) -> str:
    runs = {o.name: o.entry() for o in outcomes}
    return json.dumps({"format": format, "runs": runs})


def make_runs(monkeypatch: pytest.MonkeyPatch, *outcomes: Any) -> None:
    """Replace the replays by fixed outcomes: no run executes."""
    monkeypatch.setattr(byte_identity, "outcomes", lambda root, workers=1: iter(outcomes))


def test_check_prints_a_line_per_run_and_exits_zero_when_every_run_matches(
    baseline: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = outcome("run-a", "a"), outcome("run-b", "b")
    baseline.write_text(baseline_of(a, b))
    make_runs(monkeypatch, a, b)
    assert byte_identity.check(1) == 0
    printed = capsys.readouterr()
    assert printed.out.splitlines() == [
        f"run-a {'a' * 64} IDENTICAL",
        f"run-b {'b' * 64} IDENTICAL",
        "ALL IDENTICAL",
    ]
    assert printed.err == ""


def test_check_exits_one_and_says_what_differs_when_a_run_does_not_match(
    baseline: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = outcome("run-a", "a"), outcome("run-b", "b")
    baseline.write_text(baseline_of(a, b))
    # run-a's trace moved and its document did not; the line shows the document's hash.
    moved = byte_identity.Outcome("run-a", {}, a.sha256, "c" * 64, a.steps)
    make_runs(monkeypatch, moved, b)
    assert byte_identity.check(1) == 1
    printed = capsys.readouterr()
    assert printed.out.splitlines() == [
        f"run-a {'a' * 64} DIFFERENT",
        f"run-b {'b' * 64} IDENTICAL",
        "SOME DIFFER",
    ]
    assert printed.err.splitlines() == ["  run-a: step trace differs"]


def test_check_fails_a_run_the_baseline_does_not_list(
    baseline: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a, extra = outcome("run-a", "a"), outcome("run-new", "n")
    baseline.write_text(baseline_of(a))
    make_runs(monkeypatch, a, extra)
    assert byte_identity.check(1) == 1
    printed = capsys.readouterr()
    assert printed.out.splitlines() == [
        f"run-a {'a' * 64} IDENTICAL",
        f"run-new {'n' * 64} DIFFERENT",
        "SOME DIFFER",
    ]
    assert printed.err.splitlines() == ["  run-new: not in the baseline"]


def test_check_fails_a_baseline_run_the_script_no_longer_makes_with_a_placeholder_hash(
    baseline: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a, gone, also = outcome("run-a", "a"), outcome("run-old", "o"), outcome("run-ancient", "z")
    baseline.write_text(baseline_of(a, gone, also))
    make_runs(monkeypatch, a)
    assert byte_identity.check(1) == 1
    printed = capsys.readouterr()
    # Still three fields, the hash a dash; sorted by name, after the runs made.
    assert printed.out.splitlines() == [
        f"run-a {'a' * 64} IDENTICAL",
        "run-ancient - DIFFERENT",
        "run-old - DIFFERENT",
        "SOME DIFFER",
    ]
    assert printed.err.splitlines() == [
        "  run-ancient: not run by this script",
        "  run-old: not run by this script",
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (None, "run `record` first"),
        (baseline_of(format=2), "is not format 1"),
    ],
)
def test_check_without_a_usable_baseline_exits_with_a_message_and_replays_nothing(
    baseline: Path, monkeypatch: pytest.MonkeyPatch, text: str | None, message: str
) -> None:
    if text is not None:
        baseline.write_text(text)

    def replay_nothing(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no run may start without a baseline")

    monkeypatch.setattr(byte_identity, "outcomes", replay_nothing)
    with pytest.raises(SystemExit) as stopped:
        byte_identity.check(1)
    assert isinstance(stopped.value.code, str)
    assert message in stopped.value.code
    assert str(baseline) in stopped.value.code


def test_record_writes_every_run_in_order_and_check_then_accepts_it(
    baseline: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    b, a = outcome("run-b", "b"), outcome("run-a", "a")
    make_runs(monkeypatch, b, a)
    assert byte_identity.record(1) == 0
    recorded = json.loads(baseline.read_text(encoding="utf-8"))
    assert recorded["format"] == 1
    assert recorded["runs"] == {"run-b": b.entry(), "run-a": a.entry()}
    assert list(recorded["runs"]) == ["run-b", "run-a"]
    capsys.readouterr()
    assert byte_identity.check(1) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "ALL IDENTICAL"


def test_main_runs_the_named_command_with_the_jobs_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        byte_identity, "check", lambda workers: calls.append(("check", workers)) or 0
    )
    monkeypatch.setattr(
        byte_identity, "record", lambda workers: calls.append(("record", workers)) or 0
    )
    assert byte_identity.main(["check", "--jobs", "3"]) == 0
    assert byte_identity.main(["record"]) == 0
    assert calls == [("check", 3), ("record", 1)]


def test_the_recorded_baseline_covers_exactly_the_runs_the_script_makes() -> None:
    baseline = json.loads(byte_identity.BASELINE.read_text(encoding="utf-8"))
    assert list(baseline["runs"]) == [run.name for run in byte_identity.RUNS]
    for entry in baseline["runs"].values():
        assert set(entry) == {"sha256", "trace_sha256", "steps"}
        assert len(entry["sha256"]) == len(entry["trace_sha256"]) == 64
        assert entry["steps"] > 0
