from copy import copy, deepcopy
from dataclasses import replace
from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.orchestration import TrainingScore, WalkForwardResult
from crypto_grid_bot.trend.replay import replay_window
from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, replay_spot_benchmark
from crypto_grid_bot.trend.walk_forward import RULES


@pytest.fixture(scope="module")
def bundle():
    start, end = month_bounds_ms("2024-10")[0], month_bounds_ms("2025-01")[0]
    first, daily = {"BTCUSDT": "2023-04"}, {"BTCUSDT": []}
    filters = {"BTCUSDT": OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))}
    source, hourly = DailyDecisions(daily, first), {"BTCUSDT": []}

    def replay(rule="R1", multiple=2, cost=1):
        return replay_window(
            source,
            filters,
            hourly,
            {},
            start,
            end,
            {start: rule},
            multiple=multiple,
            cost_multiple=cost,
        )

    training = tuple(TrainingScore(f"run-{r}", "2024-10", r, D(0), None) for r in RULES)
    return dict(
        walk=WalkForwardResult(training, {start: "R1"}, replay()),
        sensitivities={
            (m, c): replay(multiple=m, cost=c) for m, c in ((1, 1), (3, 1), (1, 2), (2, 2), (3, 2))
        },
        fixed_rules={rule: replay(rule) for rule in RULES},
        holds={
            c: replay_spot_benchmark(
                HoldDecisions(daily, first), filters, hourly, start, end, cost_multiple=c
            )
            for c in (1, 2)
        },
        spot_bars=daily,
        first_months=first,
    )


@pytest.fixture(autouse=True)
def fast_intervals(monkeypatch):
    from crypto_grid_bot.trend import bootstrap, spot_report

    # Bootstrap arithmetic has its own full-resample tests; exercise wiring here.
    monkeypatch.setattr(bootstrap, "sharpe_interval", lambda _: (D(0), D(0)))
    monkeypatch.setattr(spot_report, "sharpe_interval", lambda _: (D(0), D(0)))


def test_complete_menus_render_without_fabricating_experiment_verdict(bundle):
    import json

    from crypto_grid_bot.trend.experiment_report import (
        build_experiment_report,
        experiment_json,
        experiment_markdown,
    )

    report = build_experiment_report(**bundle)
    assert len(report.futures) == 6 and len(report.fixed_rules) == 12 and len(report.holds) == 2
    assert report.minimum_account_size is None
    assert not any(c.passed for c in report.account_checks)
    assert report.verdict is None and report.required_before_verdict
    assert set(report.intervals) == {"main", "m1", "hold"}
    value = json.loads(experiment_json(report))
    assert value["verdict"] is None
    assert value["futures"]["m2-cost1"]["performance"]["sharpe"] == "0"
    text = experiment_markdown(report)
    assert "not evaluated" in text and "R6L" in text and "2024-10" in text
    assert "Full-size" in text and "registration" in text
    assert report.variant_d.mean_return_percent == D("-1.1720")
    assert "differ from V3" in text and "4.6615" in text


def test_full_size_unavailable_is_reported_without_changing_acceptance(bundle):
    from crypto_grid_bot.trend.experiment_report import build_experiment_report, experiment_markdown
    from crypto_grid_bot.trend.full_size_hold import replay_full_size_hold

    start = min(bundle["walk"].picks)
    full = replay_full_size_hold(
        {"BTCUSDT": []},
        bundle["first_months"],
        bundle["holds"][1].filters,
        start,
        month_bounds_ms("2025-01")[0],
    )
    original = build_experiment_report(**bundle)
    report = build_experiment_report(**bundle, full_size_hold=full)
    assert report.account_checks == original.account_checks
    assert report.invalid_criterion_accounts == original.invalid_criterion_accounts
    assert report.full_size_hold.reason == "unavailable_first_purchase"
    assert report.full_size_hold.max_drawdown is None
    assert not any("Full-size" in item for item in report.required_before_verdict)
    text = experiment_markdown(report)
    assert "unavailable_first_purchase" in text and "BTCUSDT" in text
    assert report.verdict is None
    full.start_ms += 3600000
    with pytest.raises(ValueError, match="period"):
        build_experiment_report(**bundle, full_size_hold=full)


@pytest.mark.parametrize("multiple", [1, 2, 3])
def test_actual_liquidation_retains_diagnostics_and_only_m1_blocks_checks(bundle, multiple):
    from crypto_grid_bot.trend.experiment_report import build_experiment_report
    from crypto_grid_bot.trend.orders import OrderIntent
    from crypto_grid_bot.trend.replay import ReplayResult
    from crypto_grid_bot.trend.runner import TrendRunner

    start = min(bundle["walk"].picks)
    runner = TrendRunner(bundle["walk"].out_of_sample.runner.filters, multiple=multiple)
    runner.account.fill("BTCUSDT", OrderIntent(D(10), False), D(100), start)
    bars = {"BTCUSDT": (D(100), D(100), D(100))}
    runner.step(start, bars, {}, {})
    runner.step(start + 3600000, bars, {}, {start + 3600000: {"BTCUSDT": D(100)}})
    decision = DailyDecisions(bundle["spot_bars"], bundle["first_months"]).at(
        start, "R1", multiple=multiple
    )
    result = ReplayResult(runner, "liquidation", (), daily_decisions=((start, "R1", decision),))
    args = dict(bundle)
    if multiple == 2:
        args["walk"] = replace(bundle["walk"], out_of_sample=result)
    else:
        args["sensitivities"] = {**bundle["sensitivities"], (multiple, 1): result}
    report = build_experiment_report(**args)
    assert report.futures[f"m{multiple}-cost1"].performance is None
    assert report.futures[f"m{multiple}-cost1"].costs.funding_paid == 100000
    assert report.invalid_criterion_accounts == {1: ("m1",), 2: ("main",), 3: ()}[multiple]
    assert bool(report.account_checks) == (multiple == 3)
    assert report.verdict is None
    if multiple == 2:
        from crypto_grid_bot.trend.experiment_report import experiment_markdown

        assert report.minimum_account_size is None
        assert "Unavailable: main account is invalid" in experiment_markdown(report)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_size",
        "extra_size",
        "missing_rule",
        "missing_hold",
        "wrong_size",
        "wrong_rule",
        "engine",
        "truncated",
        "runtime_exclusion",
        "missing_decision",
    ],
)
def test_incomplete_or_inconsistent_scenarios_abort(bundle, damage):
    from crypto_grid_bot.trend.experiment_report import build_experiment_report

    args = dict(bundle)
    args["sensitivities"] = dict(bundle["sensitivities"])
    args["fixed_rules"] = dict(bundle["fixed_rules"])
    args["holds"] = dict(bundle["holds"])
    if damage == "missing_size":
        args["sensitivities"].pop((3, 2))
    elif damage == "extra_size":
        args["sensitivities"][(2, 1)] = bundle["walk"].out_of_sample
    elif damage == "missing_rule":
        args["fixed_rules"].pop("R6L")
    elif damage == "missing_hold":
        args["holds"].pop(2)
    elif damage == "wrong_size":
        args["sensitivities"][(1, 1)] = bundle["walk"].out_of_sample
    elif damage == "wrong_rule":
        args["fixed_rules"]["R6L"] = args["fixed_rules"]["R1"]
    elif damage == "engine":
        args["sensitivities"][(3, 2)] = replace(
            args["sensitivities"][(3, 2)], reason="engine_failure"
        )
    elif damage == "runtime_exclusion":
        from crypto_grid_bot.trend.exclusions import ExclusionCalendar

        original = args["sensitivities"][(3, 2)]
        damaged = replace(original, runner=copy(original.runner))
        damaged.runner.exclusions = ExclusionCalendar({"BTCUSDT": frozenset({"2024-10"})})
        args["sensitivities"][(3, 2)] = damaged
    elif damage == "missing_decision":
        args["sensitivities"][(3, 2)] = replace(args["sensitivities"][(3, 2)], daily_decisions=())
    else:
        damaged = deepcopy(args["holds"][2])
        damaged.equity_path[-1] = replace(
            damaged.equity_path[-1], timestamp_ms=damaged.equity_path[-1].timestamp_ms - 3600000
        )
        args["holds"][2] = damaged
    with pytest.raises(ValueError):
        build_experiment_report(**args)
