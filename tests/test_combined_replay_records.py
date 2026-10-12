"""Recovery records of one replay: the liquidation, each cooldown, each restart's episode.

The traces carry recovery states produced by the real controller from scripted equity,
so the records are judged against the transitions the engine can actually make.
"""

from decimal import Decimal as D

from crypto_grid_bot.combined.account import AccountSnapshot
from crypto_grid_bot.combined.engine import EngineSnapshot
from crypto_grid_bot.combined.recovery import Recovery, RecoveryState
from crypto_grid_bot.combined.replay_records import recovery_episodes
from crypto_grid_bot.combined.report import EquityPoint, analyze
from crypto_grid_bot.combined.strategy_replay import NativeObservation, ReplayRun, StrategyTrace

HOUR = 3_600_000
REFS = ("sha256:run",)


def step(hours, equity, *, flat=True, ok=True):
    """One scripted mark: when, equity, whether positions are flat, accounting integrity."""
    return hours * HOUR, D(equity), flat, ok


def trace_of(*steps):
    controller = Recovery()
    observations = []
    for index, (stamp, equity, flat, ok) in enumerate(steps):
        decision = controller.update(stamp, equity, flat, True, ok)
        account = AccountSnapshot(equity, (), equity, D(0), D(0), D(0), D(0), ok, ())
        snapshot = EngineSnapshot(stamp, account, decision, (), (), False, equity)
        observations.append(
            NativeObservation(stamp, f"obs-{index}", "frame", "phase", f"event-{index}", snapshot)
        )
    run = ReplayRun("combined", "synthetic", D(100), 0, steps[-1][0], REFS)
    return StrategyTrace(
        run, tuple(observations), (), (), (), (), (), (), (), (), (), (), (), (), (), (), (), None
    )


# Two restarts: a 30% trigger with positions open, their liquidation, a 24h cooldown,
# a restart whose 3% stop falls from its own peak, another cooldown and restart, then
# a half allowance and normal restoration.
SEQUENCE = (
    step(0, 100),  # obs-0 Normal; the lifetime peak
    step(1, 90),  # obs-1 Normal
    step(2, 70, flat=False),  # obs-2 lifetime drawdown 30%: Closing
    step(3, 69, flat=False),  # obs-3 still liquidating
    step(4, 68),  # obs-4 flat: Cooldown begins
    step(16, 68),  # obs-5 Cooldown
    step(28, 68),  # obs-6 24 hours flat, qualified: restart at the 25% allowance
    step(29, 80),  # obs-7 the episode's own peak
    step(30, "77.6"),  # obs-8 3% below that peak: stop, Cooldown
    step(40, "77.6"),  # obs-9 Cooldown
    step(54, "77.6"),  # obs-10 restart at the 25% allowance
    step(55, 86),  # obs-11 lifetime drawdown 14%: half allowance
    step(56, 91),  # obs-12 lifetime drawdown 9%: normal restored
    step(57, 92),  # obs-13 Normal
)


def shape(rows):
    return [
        (r.kind, r.start_observation_id, r.end_observation_id, r.end_reason)
        for r in recovery_episodes(trace_of(*rows))
    ]


def test_each_restart_is_its_own_episode_beside_the_liquidation_and_both_cooldowns():
    assert shape(SEQUENCE) == [
        ("liquidation", "obs-2", "obs-4", "liquidated"),
        ("cooldown", "obs-4", "obs-6", "restarted"),
        ("episode", "obs-6", "obs-8", "episode_stop"),
        ("cooldown", "obs-8", "obs-10", "restarted"),
        ("episode", "obs-10", "obs-12", "normal_restored"),
    ]


def test_every_record_is_priced_from_its_start_to_its_end_observation():
    trace = trace_of(*SEQUENCE)
    rows = recovery_episodes(trace)
    assert [(r.start_ms // HOUR, r.end_ms // HOUR) for r in rows] == [
        (2, 4),
        (4, 28),
        (28, 30),
        (30, 54),
        (54, 56),
    ]
    points = tuple(
        EquityPoint(o.timestamp_ms, o.snapshot.account.equity, o.id, REFS)
        for o in trace.observations
    )
    report = analyze(D(100), points, (), (), rows, REFS)
    assert not [issue for issue in report.issues if "recovery" in issue]
    assert [(c.episode.kind, c.marked_change) for c in report.recovery_changes] == [
        ("liquidation", D(-2)),
        ("cooldown", D(0)),
        ("episode", D("9.6")),
        ("cooldown", D(0)),
        ("episode", D("13.4")),
    ]


def test_the_half_allowance_stays_inside_the_episode_that_earned_it():
    trace = trace_of(*SEQUENCE)
    assert trace.observations[11].snapshot.recovery.state == RecoveryState.RECOVERY50
    episodes = [r for r in recovery_episodes(trace) if r.kind == "episode"]
    assert len(episodes) == 2
    second = episodes[1]
    assert (second.start_observation_id, second.end_observation_id) == ("obs-10", "obs-12")
    assert (second.equity_start, second.equity_end) == (D("77.6"), D(91))


def test_records_have_unique_ids_and_cite_the_run_sources():
    rows = recovery_episodes(trace_of(*SEQUENCE))
    ids = [r.id for r in rows]
    assert len(set(ids)) == len(ids) == 5
    assert ids[0] == "recovery:liquidation:obs-2" and ids[2] == "recovery:episode:obs-6"
    assert all(r.source_refs == REFS for r in rows)


def test_an_episode_running_at_the_window_end_ends_at_the_last_observation():
    rows = recovery_episodes(trace_of(*SEQUENCE[:12]))
    last = rows[-1]
    assert (last.kind, last.start_observation_id, last.end_observation_id) == (
        "episode",
        "obs-10",
        "obs-11",
    )
    assert last.end_reason == "window_end"
    assert (last.end_ms, last.equity_end) == (55 * HOUR, D(86))


def test_a_stretch_begun_at_the_last_observation_is_still_a_record():
    rows = recovery_episodes(trace_of(*SEQUENCE[:3]))
    assert [(r.kind, r.start_observation_id, r.end_observation_id) for r in rows] == [
        ("liquidation", "obs-2", "obs-2")
    ]
    assert rows[0].end_reason == "window_end" and rows[0].equity_end == rows[0].equity_start


def test_a_trigger_while_flat_has_nothing_to_liquidate():
    rows = recovery_episodes(trace_of(step(0, 100), step(1, 70), step(2, 70)))
    assert [(r.kind, r.start_observation_id, r.end_reason) for r in rows] == [
        ("cooldown", "obs-1", "window_end")
    ]


def test_positions_reappearing_in_a_cooldown_start_another_liquidation():
    rows = shape(
        (step(0, 100), step(1, 70, flat=False), step(2, 70), step(3, 70, flat=False), step(4, 70))
    )
    assert rows == [
        ("liquidation", "obs-1", "obs-2", "liquidated"),
        ("cooldown", "obs-2", "obs-3", "liquidation_incomplete"),
        ("liquidation", "obs-3", "obs-4", "liquidated"),
        ("cooldown", "obs-4", "obs-4", "window_end"),
    ]


def test_a_terminal_failure_ends_what_it_interrupts_and_stays_recorded():
    rows = shape(
        (step(0, 100), step(1, 70, flat=False), step(2, 69, flat=False, ok=False), step(3, 69))
    )
    assert rows == [
        ("liquidation", "obs-1", "obs-2", "terminal"),
        ("terminal", "obs-2", "obs-3", "window_end"),
    ]


def test_a_run_that_never_left_normal_has_no_recovery_records():
    assert recovery_episodes(trace_of(step(0, 100), step(1, 99), step(2, 100))) == ()
