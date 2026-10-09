"""Check the experiment connection without repeating individual replay arithmetic."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from crypto_grid_bot.backtest.klines import month_bounds_ms


@pytest.fixture
def harness(monkeypatch, tmp_path):
    from crypto_grid_bot.trend import experiment_runner as module

    names = (
        "run_walk_forward",
        "replay_sensitivities",
        "replay_fixed_rules",
        "replay_spot_recorded",
        "replay_full_size_hold_recorded",
        "build_experiment_report",
    )
    mocks = {name: Mock(name=name) for name in names}
    for name, mock in mocks.items():
        monkeypatch.setattr(module, name, mock)
    picks = {month_bounds_ms("2024-10")[0]: "R1"}
    mocks["run_walk_forward"].return_value = SimpleNamespace(picks=picks)
    args = dict(
        directory=tmp_path / "experiment",
        spot_bars={"BTCUSDT": []},
        first_months={"BTCUSDT": "2023-04"},
        spot_hourly={"BTCUSDT": []},
        hold_hourly={"BTCUSDT": []},
        futures_hourly={"BTCUSDT": []},
        spot_filters={"BTCUSDT": object()},
        futures_filters={"BTCUSDT": object()},
        funding={},
        spot_exclusions={"BTCUSDT": frozenset({"2024-11"})},
        futures_exclusions={"BTCUSDT": frozenset({"2024-12"})},
    )
    return module, mocks, args


def test_frozen_menu_uses_one_selection_and_market_specific_inputs(harness):
    module, calls, args = harness
    report = module.run_experiment(**args)
    assert report is calls["build_experiment_report"].return_value
    walk = calls["run_walk_forward"]
    walk.assert_called_once()
    source, filters, hourly, funding = walk.call_args.args
    assert filters is args["futures_filters"] and hourly is args["futures_hourly"]
    assert funding is args["funding"]
    assert source.excluded_months == {"BTCUSDT": frozenset({"2024-11", "2024-12"})}
    for name in ("replay_sensitivities", "replay_fixed_rules"):
        call = calls[name]
        call.assert_called_once()
        assert call.call_args.args[:4] == (source, filters, hourly, funding)
        assert call.call_args.args[4] == walk.return_value.picks
        assert call.call_args.kwargs["record"] is walk.call_args.kwargs["record"]
    spot = calls["replay_spot_recorded"].call_args_list
    assert [call.kwargs["cost_multiple"] for call in spot] == [1, 2]
    assert len({call.args[1] for call in spot}) == 2
    for call in spot:
        assert call.args[0] == args["directory"]
        assert call.args[3] is args["spot_filters"]
        assert call.args[4] is args["spot_hourly"]
        assert call.args[5] == min(walk.return_value.picks)
        assert call.args[6] == month_bounds_ms("2025-01")[0]
    assert (
        calls["build_experiment_report"].call_args.kwargs["spot_exclusions"]
        == args["spot_exclusions"]
    )
    full = calls["replay_full_size_hold_recorded"]
    full.assert_called_once()
    assert full.call_args.args[2] is args["hold_hourly"]
    assert full.call_args.args[3] is args["first_months"]
    assert full.call_args.args[4] is args["spot_filters"]
    assert full.call_args.args[5:] == (min(walk.return_value.picks), month_bounds_ms("2025-01")[0])
    assert calls["build_experiment_report"].call_args.kwargs["full_size_hold"] is full.return_value


@pytest.mark.parametrize(
    "phase",
    [
        "run_walk_forward",
        "replay_sensitivities",
        "replay_fixed_rules",
        "replay_spot_recorded",
        "replay_full_size_hold_recorded",
    ],
)
def test_component_failure_retains_directory_and_never_reports_or_retries(harness, phase):
    module, calls, args = harness
    calls[phase].side_effect = ValueError("synthetic failure")
    with pytest.raises(ValueError, match="synthetic failure"):
        module.run_experiment(**args)
    calls[phase].assert_called_once()
    calls["build_experiment_report"].assert_not_called()
    assert args["directory"].is_dir()
    with pytest.raises(FileExistsError):
        module.run_experiment(**args)
    calls[phase].assert_called_once()


def test_rejects_mismatched_universe_before_starting_any_attempt(harness):
    module, calls, args = harness
    args["spot_filters"] = {}
    with pytest.raises(ValueError, match="universe"):
        module.run_experiment(**args)
    assert not args["directory"].exists()
    for call in calls.values():
        call.assert_not_called()
