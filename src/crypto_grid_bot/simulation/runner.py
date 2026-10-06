"""Persistent, single-symbol offline strategy-to-fill loop."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from crypto_grid_bot.config import BotConfig
from crypto_grid_bot.domain import (
    CandidateMetrics,
    CandidateScore,
    MarketRegime,
    MarketSignals,
    PortfolioSnapshot,
    RegimeAssessment,
    RiskAction,
    RiskDecision,
)
from crypto_grid_bot.portfolio.profit_vault import ProfitVault, ProfitVaultState
from crypto_grid_bot.risk.engine import RiskEngine
from crypto_grid_bot.simulation.execution import (
    Reduction,
    buy_price,
    exit_state,
    exitable,
    liquidate,
    market_buy,
    marketable,
    match,
    place,
    reduce_unreserved,
    unpaired_inventory,
)
from crypto_grid_bot.simulation.inventory_cap import capped_quantity
from crypto_grid_bot.simulation.models import (
    ONE,
    ZERO,
    Account,
    D,
    LimitOrder,
    MarketRules,
    Quote,
    floor_step,
    nonnegative,
    seconds_between,
    timestamp,
)
from crypto_grid_bot.simulation.store import StateStore, encode
from crypto_grid_bot.simulation.trend_switch import (
    DOWN_DEADLINE_SECONDS,
    UNAVAILABLE,
    UP,
    TrendSignal,
    effective_state,
    starts_down_sequence,
)
from crypto_grid_bot.simulation.uptrend import (
    UptrendPosition,
    entry_limits,
    initial_stop,
    stop_distance,
    trailed_stop,
)
from crypto_grid_bot.strategy.cycle import (
    H2,
    H2_OUTSIDE_RANGE_SECONDS,
    H3,
    H3_SCORE_RELAXATION,
    CycleSignal,
    phase,
)
from crypto_grid_bot.strategy.grid import GridBuilder, GridNotViable
from crypto_grid_bot.strategy.mode_selector import Mode, select_mode
from crypto_grid_bot.strategy.opportunity import OpportunityScorer
from crypto_grid_bot.strategy.order_flow import flow_blocked
from crypto_grid_bot.strategy.perception import Snapshot, TrendState
from crypto_grid_bot.strategy.regime import RegimeClassifier, thresholds_from_config
from crypto_grid_bot.strategy.structure import ResistanceZones, nearest_resistance
from crypto_grid_bot.strategy.volume_exit import DEADLINE as VOLUME_DEADLINE
from crypto_grid_bot.strategy.volume_exit import DECISION as VOLUME_DECISION
from crypto_grid_bot.strategy.volume_exit import VolumeHistory

DEFAULT_CAPITAL = D("100")
# The share of unprotected quote a new grid may commit; the rest absorbs fees and rounding.
GRID_BUDGET_FRACTION = D("0.8")
# V2 (D19): a sell target sits at this fraction of the nearest resistance above its buy
# level, then floored to the tick: just below it (the owner's example: 0.355 -> 0.354).
RESISTANCE_TARGET = D("0.999")
# 5 (2026-09-27, engine "exit-residue-v1"): a residue the exchange filters forbid
# selling no longer blocks settlement or a new grid, and a validation halt holding
# inventory arms liquidation. A schema-4 database was written under the old lifecycle,
# so reopening it here would mix two semantics in one event history; the identity
# mismatch refuses it instead.
# 6 (2026-09-28, engine "drawdown-recovery-v1", spec v1 amendment 1): a soft-drawdown
# episode rebases ``risk_high`` after a cool-off; a ``drawdown`` halt restarts by itself
# after a cool-off; a manual resume admits a residue below the exchange minimum; the
# account carries the halt's start and category, the episode and the C1(b) reference.
# Schema 1-5 databases are refused: their halts were final and their state lacks these
# fields.
# 7 (2026-10-05, code audit #159): the journal records each fill's remaining quantity
# and lists an order that filled in part and was then cancelled on the same frame as
# cancelled; a flat frame's no-op settlement is neither counted nor journaled. A
# schema-6 database holds events in the old shape, so it is refused rather than
# continued under the new one (Codex review of #159).
# 8 (2026-10-05, strategy audit #160): V2 market structure is a policy flag, off by
# default. Code from #150/#151 up to this change, schema 7 included, ran every account
# with structure on (the six-signal regime vote and the FTA cap) under the same identity
# as the V0 accounts before it, so such a database cannot say which semantics produced
# its history; it is refused rather than reopened under either (Codex review of #160).
# 9 (2026-10-05, engine "drawdown-recovery-v2", owner decisions of 2026-10-02): a soft
# episode already back under the soft limit when its rebase falls due closes without one
# (D7); a flat account with no orders and no range exit pending clears its grid bounds
# and outside-range clock (amendment 2); the clock stands still while halted (amendment
# 3); and the risk limits compare the balances exactly, so an equity exactly on a limit
# is on it (moved here from #159, Codex review). Schema-8 accounts ran without these
# rules, so a saved reference, bounds or clock may hold what they forbid; such a
# database is refused rather than reopened under them.
# 10 (2026-10-05, owner decisions D17 and D18): a manual resume of an emergency or
# integrity halt that only the drawdown blocks rebases ``risk_high`` as the automatic
# restart does and journals it as ``restart``; an exhaustion halt is refused by name.
# Replay never resumes, so the engine stays "drawdown-recovery-v2". A schema-9 journal
# holds resumes in the old shape, and may hold an admitted exhaustion halt, so it is
# refused rather than continued under the new rules.
SCHEMA = 10
# Spec v1 sections 3 and 4: the variants a policy may run ("" is V0). E and F stand
# alone; G and H run alone or with C as the declared interactions C+G and C+H. The full
# stack C+F+G+H+V2 (test-plan amendment, owner decision 2026-10-05) is C+F+G+H with the
# V2 structure flag, and is declared only with it. V2 alone is V0 with that flag.
# Spec v2's mode switcher, "MS", runs with F's block and nothing else.
FULL_STACK = "C+F+G+H"
MODE_SWITCH = "MS"
VARIANTS = ("", "A", "B", "C", "E", "F", "G", "H", "C+G", "C+H", FULL_STACK, MODE_SWITCH)
# The policy's on/off flags: each is off in V0, and left out of the identity when off.
POLICY_FLAGS = (
    "trend_switch",
    "volume_exit",
    "flow_block_entry",
    "funding_gate",
    "cycle_gate",
    "structure",
    "mode_switch",
)
# Why a variant's own rule forbids a new grid (spec v1 §3), journaled with the variant.
ENTRY_VETOES = {
    "F": "order flow: buys blocked",
    "G": "funding gate: funding high or unavailable",
    "H2": "cycle H2: overextended",
}
# The four halt categories (spec v1 amendment 1); only ``drawdown`` restarts by itself.
DRAWDOWN, EMERGENCY, EXHAUSTION, INTEGRITY = "drawdown", "emergency", "exhaustion", "integrity"
RESTART_PAUSE = "automatic restart after drawdown halt: awaiting confirmed eligible data"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_HOUR_MS = 3_600_000
_DAY_MS = 24 * _HOUR_MS


def _epoch_ms(observed_at: str) -> int:
    """An observation's time in whole milliseconds since the Unix epoch, without a float."""
    delta = timestamp(observed_at) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000


class TransientFrame(ValueError):
    """Unusable observation: cancel entries and wait for confirmed fresh recovery."""


@dataclass(frozen=True)
class SimulationPolicy:
    recovery_frames: int = 2
    # Continuity between fresh observations, independent of per-frame delivery age.
    maximum_frame_gap_seconds: int = 180
    # Observed outside-range time (valid frames only) before exiting a grid to cash.
    outside_range_seconds: int = 21600
    # After a range exit, allow a new grid centred on current fair value once this
    # cooldown has passed and eligibility is reconfirmed. False = wait in cash until
    # price re-enters the old band (an explicit, documented terminal-until-return state).
    recenter_after_exit: bool = True
    recenter_cooldown_seconds: int = 86400
    # Experiment variant B (spec v1, section 3 B): committed exposure may not exceed this
    # fraction of prospective active equity when a buy is created. None = off (V0).
    inventory_cap: Decimal | None = None
    # Experiment variant A (spec v1, section 3 A): the daily SMA50/SMA200 trend switch.
    # False = off (V0). The daily state arrives on each Frame as ``trend``.
    trend_switch: bool = False
    # Experiment variant E (spec v1, section 3 E): on low volume at t0 + 6 h, the range
    # exit waits until t0 + 12 h, both on the clock from the episode's first outside
    # observation t0 (volume_exit.py; its volumes come from ``PaperSimulator.volumes``).
    # Not eligible for selection until Codex has reviewed it. False = off (V0).
    volume_exit: bool = False
    # Experiment variant F (spec v1, section 3 F): a low taker-buy share blocks every new
    # buy (order_flow.py; the share arrives on each Frame as ``flow_share``). False = off.
    flow_block_entry: bool = False
    # Experiment variant G (spec v1, section 3 G): high or unavailable BTCUSDT funding
    # blocks a new grid (backtest/funding.py; the decision arrives on each Frame as
    # ``funding_blocks``). False = off (V0).
    funding_gate: bool = False
    # Experiment variant H (spec v1, section 3 H): the halving-cycle rules H2 and H3
    # (cycle.py; the daily values arrive on each Frame as ``cycle``). False = off (V0).
    cycle_gate: bool = False
    # V2 market structure (#147-#151), off by default: the regime vote's sixth signal
    # ``structure_alignment`` with the trend weight lowered from 0.35 to 0.25, and sell
    # targets just below resistance (D19). Spec v1 section 3: new behaviour sits behind a
    # flag that defaults to off, so V0 and existing paper accounts are unaffected. Every
    # V2 rule is frozen in docs/STRUCTURE_PREREGISTRATION.md.
    structure: bool = False
    # Spec v1 amendment 1 (owner decision 2026-09-27): the soft-drawdown cool-off before
    # ``risk_high`` may be rebased, and the hard-drawdown cool-off H before a ``drawdown``
    # halt restarts. Both are part of the account identity and fixed for all v1 runs.
    soft_cooloff_seconds: int = 86400
    hard_cooloff_seconds: int = 86400
    # Spec v2 (docs/EXPERIMENT_SPEC_V2.md, sections 4-7): the mode switcher, which chooses
    # Grid (V0's grid with F's block), Uptrend or Cash each hour. Its runtime state is never
    # saved, so it runs in replay only. False = off (V0 and every v1 variant).
    mode_switch: bool = False

    def __post_init__(self) -> None:
        if type(self.recovery_frames) is not int or not 2 <= self.recovery_frames <= 100:
            raise ValueError("recovery requires 2-100 distinct eligible frames")
        if type(self.outside_range_seconds) is not int or self.outside_range_seconds <= 0:
            raise ValueError("outside-range timeout must be a positive integer")
        if type(self.recenter_after_exit) is not bool:
            raise ValueError("recenter_after_exit must be a boolean")
        if type(self.recenter_cooldown_seconds) is not int or self.recenter_cooldown_seconds <= 0:
            raise ValueError("recentering cooldown must be a positive integer")
        if (
            type(self.maximum_frame_gap_seconds) is not int
            or not 1 <= self.maximum_frame_gap_seconds <= 3600
        ):
            raise ValueError("maximum frame gap must be 1-3600 seconds")
        if self.inventory_cap is not None:
            nonnegative(self.inventory_cap)
            if not ZERO < self.inventory_cap < ONE:
                raise ValueError("inventory cap must be above zero and below one")
        for name in POLICY_FLAGS:
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        for name in ("soft_cooloff_seconds", "hard_cooloff_seconds"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        others = [name for name in POLICY_FLAGS if name not in ("mode_switch", "flow_block_entry")]
        if self.mode_switch and (
            not self.flow_block_entry
            or self.inventory_cap is not None
            or any(getattr(self, name) for name in others)
        ):
            raise ValueError("spec v2's mode switcher runs with F's block and nothing else")
        if self.variant not in VARIANTS:
            raise ValueError(f"spec v1 declares no variant {self.variant}")
        if self.variant == FULL_STACK and not self.structure:
            raise ValueError(f"spec v1 declares no variant {FULL_STACK} without V2's structure")

    @property
    def variant(self) -> str:
        """The spec v1 variant this policy runs, such as "C+G"; "" for V0; "MS" for spec v2's
        mode switcher."""
        if self.mode_switch:
            return MODE_SWITCH
        trend, cap = self.trend_switch, self.inventory_cap is not None
        added = (self.volume_exit, self.flow_block_entry, self.funding_gate, self.cycle_gate)
        names = ["C" if trend and cap else "A" if trend else "B" if cap else ""]
        names += [name for name, on in zip("EFGH", added, strict=True) if on]
        return "+".join(name for name in names if name)

    def identity(self) -> dict[str, Any]:
        """Persisted form; omits unset variants so existing paper identities still match."""
        value = asdict(self)
        if self.inventory_cap is None:
            del value["inventory_cap"]
        for name in POLICY_FLAGS:
            if not value[name]:
                del value[name]
        return value


@dataclass(frozen=True)
class Frame:
    quote: Quote
    signals: MarketSignals
    candidate: CandidateMetrics
    fair_value: Decimal
    atr: Decimal
    allow_new_grid: bool = True
    # Historical replay only: frames sharing an epoch replay one bar (see match()).
    epoch: str | None = None
    # Variant A only: the daily trend state for this observation (see trend_switch.py).
    trend: TrendSignal | None = None
    # V2: each timeframe's resistance zones (structure.py); () when unavailable.
    resistance: tuple[ResistanceZones, ...] = ()
    # Variant F only: the taker-buy share of the 15 minutes before this one
    # (order_flow.py); None when it is unavailable, which blocks, or F is off.
    flow_share: Decimal | None = None
    # Variant G only: whether the funding gate blocks a new grid at this observation;
    # None when G is off. Under G, anything but False blocks (it fails closed).
    funding_blocks: bool | None = None
    # Variant H only: the daily values of the latest completed daily bar (cycle.py).
    cycle: CycleSignal | None = None
    # Spec v2's mode switcher only: the three timeframes as they stand at this observation
    # (perception.py, completed bars only); None when it is off.
    perception: Snapshot | None = None

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["signals"]["observed_at"] = self.signals.observed_at.isoformat()
        if value["epoch"] is None:
            del value["epoch"]  # Keeps journals written before this field byte-identical.
        if value["trend"] is None:
            del value["trend"]  # Likewise for journals without variant A.
        if not value["resistance"]:
            del value["resistance"]  # Omit from journals when structure unavailable.
        for name in ("flow_share", "funding_blocks", "cycle", "perception"):
            if value[name] is None:
                del value[name]  # Likewise for journals without variants F, G, H and MS.
        return value


class PaperSimulator:
    def __init__(
        self,
        path: Path,
        config: BotConfig,
        rules: MarketRules,
        initial_cash: Decimal = DEFAULT_CAPITAL,
        policy: SimulationPolicy | None = None,
    ) -> None:
        if config.mode != "paper":
            raise ValueError("only paper mode is supported")
        self.config, self.rules = config, rules
        self.policy = policy or SimulationPolicy()
        # Replay measurement hook: sees (active equity, risk high-water mark, C1(b)
        # measurement reference, decision) at every risk evaluation the engine performs.
        # A tentative evaluation for a rebase or a restart is not one. It observes only
        # and must not change the account.
        self.risk_observer: Callable[[Decimal, Decimal, Decimal, RiskDecision], None] | None = None
        # Replay input for variant E: the pair's volumes its range-exit check reads. Unset,
        # the check is unavailable and the exit happens as in V0; replay() sets it.
        self.volumes: VolumeHistory | None = None
        identity = encode(
            {
                "schema": SCHEMA,
                "policy": self.policy.identity(),
                "config": asdict(config),
                "rules": rules.identity(),
                "initial_cash": initial_cash,
            }
        )
        self.store = StateStore(path, Account.start(initial_cash), rules, identity)
        self.risk = RiskEngine(
            daily_loss_pause_pct=config.daily_loss_pause_pct,
            soft_drawdown_pct=config.soft_drawdown_pct,
            hard_drawdown_pct=config.hard_drawdown_pct,
            maximum_data_age_seconds=config.maximum_data_age_seconds,
        )
        self.classifier = RegimeClassifier(
            thresholds_from_config(config), structure=self.policy.structure
        )
        self.scorer = OpportunityScorer(
            minimum_score=config.minimum_opportunity_score,
            maximum_news_risk=config.maximum_news_risk,
            maximum_spread_pct=config.maximum_spread_pct,
            minimum_depth_multiple=config.minimum_depth_multiple,
        )
        self.builder = GridBuilder(
            minimum_levels=config.minimum_levels,
            maximum_levels=config.maximum_levels,
            minimum_cost_multiple=config.minimum_grid_cost_multiple,
            range_atr_multiple=config.range_atr_multiple,
        )
        self.vault = ProfitVault(
            reserve_fraction=D(str(config.reserve_fraction)),
            minimum_transfer_quote=D(str(config.minimum_transfer_quote)),
        )
        # Config floats as the exact Decimals the per-frame and per-level checks use.
        self._maximum_spread_pct = D(str(config.maximum_spread_pct))
        self._minimum_grid_cost_multiple = D(str(config.minimum_grid_cost_multiple))
        # Variant H3's opportunity-score minimum for new grids (0.70 lowered to 0.60).
        self._h3_minimum = config.minimum_opportunity_score - H3_SCORE_RELAXATION

    def close(self) -> None:
        self.store.close()

    def process(self, frame: Frame) -> dict[str, Any]:
        self._refuse_runtime_variants()
        return self.store.transact(
            frame.quote.event_id, frame.payload(), lambda account: self._step(account, frame)
        )

    def _refuse_runtime_variants(self) -> None:
        """Variants E and F, and spec v2's mode switcher, keep account state that is never
        saved (``Account.to_dict``), so a persisted account would lose it at every frame: they
        run in replay only."""
        if self.policy.mode_switch:
            raise ValueError("spec v2's mode switcher runs in historical replay only")
        if self.policy.volume_exit or self.policy.flow_block_entry:
            raise ValueError("variants E and F run in historical replay only")

    def step(self, account: Account, frame: Frame) -> dict[str, Any]:
        """Advance an in-memory account by one frame, without the event journal.

        Historical replay only: the same decision logic, Decimal context and final
        invariant check as ``process``, but nothing is persisted or deduplicated. That
        final check is the frame's one full account validation (the execution calls
        inside the step skip theirs, see ``execution``); the account arrives validated
        by the previous step or by the store's read.
        """
        with localcontext() as context:
            context.prec = 50
            report = self._step(account, frame)
            account.validate(self.rules)
        return report

    @staticmethod
    def _cancel_buys(account: Account) -> list[str]:
        cancelled = [key for key, order in account.orders.items() if order.side == "buy"]
        for key in cancelled:
            del account.orders[key]
        return cancelled

    def _halt(
        self,
        account: Account,
        reason: str,
        *,
        category: str,
        observed: str,
        exit_requested: bool = False,
        report: dict[str, Any] | None = None,
    ) -> None:
        """Halt, or keep halted. The start, category and reason are captured once, on the
        transition from not halted to halted, and no later call changes them (spec v1
        amendment 1: an ``integrity`` or ``emergency`` halt past 12% is never
        re-categorised as ``drawdown``, and an invalid frame during a ``drawdown`` halt
        does not make it ``integrity``). Later calls may still clear orders and arm the
        exit. A halt of any category ends an open soft-drawdown episode.

        Under spec v2's mode switcher, every halt starts here, so here the mode becomes Cash
        (section 7: "While halted, the mode is Cash"), and the same frame reports it; a grid
        winding down has lost its orders. An uptrend entry or position starts exit 3 unless an
        exit has begun: it never buys again, the liquidation sells it, and ``_finish_uptrend``
        ends it once that has sold it (a halt on a run's last frame leaves an exit owed)."""
        account.orders.clear()
        if not account.halt:
            account.halt = reason
            account.halt_since = observed
            account.halt_category = category
            account.episode_since, account.episode_count = "", 0
        account.pause = ""
        account.recovery_count = 0
        account.liquidating = account.liquidating or exit_requested
        if self.policy.mode_switch:
            self._set_mode(account, Mode.CASH.value)
            account.winding_down = False
            if account.uptrend is not None:
                self._begin_exit(account.uptrend, "risk", report)

    @staticmethod
    def _halt_time(account: Account, quote: Quote) -> str:
        """The halt start for an invalid frame: its own time if parseable, else the last
        valid observation. Empty only when neither exists."""
        try:
            timestamp(quote.observed_at)
        except (TypeError, ValueError):
            return account.last_observed
        return quote.observed_at

    def _resolved(self, account: Account, quote: Quote) -> bool:
        """True when no position is left that the account could still trade out of.

        Either flat, or holding only a residue the market filters forbid selling: the
        engine has no way to reduce that residue, so no recovery step may wait for it.

        Deliberately scoped differently from ``unpaired_inventory``: this asks "is
        anything sellable held", so it counts the filled part of a resting buy, while the
        drain and the end-of-run verdict ask "what does this exit owe" and exclude it.
        The range-exit and settlement callers are gated on an empty order book
        (``liquidate``'s precondition, and ``_settle``'s own check). The harvest gate is
        not: a partly filled buy may still rest there, and then ``exitable`` counts its
        filled part while ``unpaired_inventory`` does not. That disagreement is the
        point. This is the stricter test, so a harvest never sells inventory a resting
        buy's child sell will pair, and it is never True while ``exit_state`` is
        ``incomplete``. Keeping them distinct is what stops a partly filled buy being
        drained out from under its own child sell.

        Under spec v2's mode switcher, an uptrend entry or position that is still entering or
        holding is never resolved, whatever its size, so no harvest settles or moves the
        reserves while it is held (section 6). Its dust ends only in its exit
        (``_finish_uptrend``).
        """
        position = account.uptrend
        if self.policy.mode_switch and position is not None and position.phase != "exiting":
            return False
        return not account.reserved_base() and not exitable(account, quote, self.rules)

    def _pause(self, account: Account, reason: str) -> None:
        self._cancel_buys(account)
        account.pause = reason
        account.recovery_count = 0
        account.draining = True

    def _risk_action(
        self,
        account: Account,
        quote: Quote,
        emergency: bool,
        report: dict[str, Any] | None = None,
    ) -> RiskAction:
        """Evaluate the risk limits and act: EXIT halts, any other refusal pauses and drains.

        Under spec v2's mode switcher a drain (PAUSE or REDUCE) is a risk drain (section 7): it
        sells the uptrend position, so the position starts exit 3 unless an exit has begun,
        whatever its phase, and a new entry then waits for the recovery confirmations."""
        equity = account.equity(quote, self.rules)
        result = self.risk.evaluate(
            PortfolioSnapshot(equity, account.day_start, account.risk_high, 0, emergency=emergency)
        )
        if self.risk_observer is not None:
            self.risk_observer(equity, account.risk_high, account.measure_high, result)
        if result.action == RiskAction.EXIT:
            # The engine checks the emergency flag before the drawdown, so a frame with
            # both is an emergency halt (spec v1 amendment 1).
            self._halt(
                account,
                "; ".join(result.reasons),
                category=EMERGENCY if emergency else DRAWDOWN,
                observed=quote.observed_at,
                exit_requested=True,
                report=report,
            )
        elif result.action != RiskAction.ALLOW and not account.halt:
            self._pause(account, "; ".join(result.reasons))
            if result.action == RiskAction.REDUCE and not account.episode_since:
                # The first REDUCE outside an episode starts one (amendment 1, soft
                # drawdown, item 1); its cool-off runs from this observation.
                account.episode_since, account.episode_count = quote.observed_at, 0
            if self.policy.mode_switch:
                account.risk_recovery, account.risk_recovery_count = True, 0
                if account.uptrend is not None:
                    self._begin_exit(account.uptrend, "risk", report)
        return result.action

    def _tentative_allow(self, account: Account, quote: Quote, emergency: bool) -> bool:
        """Would the risk engine ALLOW with ``risk_high`` rebased to this frame's active
        equity? By construction this tests the daily loss, the emergency flag and the
        input checks, and nothing about drawdown (amendment 1). Not an engine evaluation:
        the observer does not see it and the account is untouched."""
        equity = account.equity(quote, self.rules)
        result = self.risk.evaluate(
            PortfolioSnapshot(equity, account.day_start, equity, 0, emergency=emergency)
        )
        return result.action == RiskAction.ALLOW

    def _rebase(
        self, account: Account, frame: Frame, eligible: bool, report: dict[str, Any]
    ) -> None:
        """Soft drawdown, option C (amendment 1): on each valid frame of an open episode,
        before any other state change, count the confirmations and end the episode once
        the cool-off has passed: closed as it stands if the account has already recovered
        (D7), otherwise by the rebase. Runs first in the step, after the mark."""
        if not account.episode_since or account.halt:
            return
        quote = frame.quote
        confirmed = eligible and self._tentative_allow(account, quote, frame.signals.emergency)
        account.episode_count = account.episode_count + 1 if confirmed else 0
        if not (
            confirmed
            and account.episode_count >= self.policy.recovery_frames
            and seconds_between(account.episode_since, quote.observed_at)
            >= self.policy.soft_cooloff_seconds
        ):
            return
        # D7 (owner decision 2026-10-02): an account already back under the soft limit is
        # closed without a rebase, so partial recoveries cannot ratchet risk_high down. The
        # tentative check passed on this frame, so against the existing risk_high only the
        # drawdown can deny ALLOW, by the risk engine's own exact comparison: a drawdown of
        # exactly 8% is still soft, and rebases.
        snapshot = PortfolioSnapshot(account.last_equity, account.day_start, account.risk_high, 0)
        if self.risk.evaluate(snapshot).action == RiskAction.ALLOW:
            report["episode_closed"] = {
                "episode_since": account.episode_since,
                "closed_at": quote.observed_at,
                "equity": account.last_equity,
                "reference": account.risk_high,
            }
        else:
            report["rebase"] = {
                "episode_since": account.episode_since,
                "old_reference": account.risk_high,
                "new_reference": account.last_equity,
            }
            account.risk_high = account.last_equity
        account.episode_since, account.episode_count = "", 0

    def _clear_halt(self, account: Account, reason: str) -> None:
        """End the halt of a flat account with no orders and pause it for confirmed
        eligible data: the one place an automatic restart and a manual ``resume()``
        clear state, so the two cannot drift apart (spec v1 amendment 1)."""
        account.halt, account.liquidating = "", False
        account.halt_since, account.halt_category = "", ""
        # _halt already closed any episode; cleared here as well so both paths match.
        account.episode_since, account.episode_count = "", 0
        # Flat with no orders: no grid remains, so clear its bounds and range timers.
        account.range_exit, account.range_exit_since = False, ""
        account.grid_lower = account.grid_upper = ZERO
        account.outside_seconds, account.outside_last = ZERO, ""
        account.down_since = ""  # a flat account has ended any variant A sequence
        self._pause(account, reason)
        if self.policy.mode_switch:
            # Spec v2 section 7: a new uptrend entry waits for the recovery confirmations.
            account.risk_recovery, account.risk_recovery_count = True, 0

    def _rebase_halted(self, account: Account, quote: Quote) -> dict[str, Any]:
        """Rebase a halted account's ``risk_high`` to this frame's active equity and return
        the ``restart`` journal record: the halt's start, category and reason, and the old
        and new reference. Shared by the automatic restart and a manual resume that only
        the drawdown blocks (owner decision D17); never the C1 references (amendment 1)."""
        reference = account.equity(quote, self.rules)
        record = {
            "halt_since": account.halt_since,
            "category": account.halt_category,
            "halt": account.halt,
            "old_reference": account.risk_high,
            "new_reference": reference,
        }
        account.risk_high = reference
        return record

    def _restart(
        self, account: Account, frame: Frame, eligible: bool, report: dict[str, Any]
    ) -> bool:
        """Hard drawdown, automatic restart (amendment 1). Evaluated on a halted frame after
        this frame's liquidation attempt. Only a ``drawdown`` halt restarts; it changes
        exactly the fields a manual ``resume()`` changes, and never the daily baseline,
        the C1 references, the reserves or the vault."""
        quote = frame.quote
        if account.halt_category != DRAWDOWN or not account.halt_since or account.orders:
            return False
        if (
            seconds_between(account.halt_since, quote.observed_at)
            < self.policy.hard_cooloff_seconds
        ):
            return False
        # "Flat" is PR #122's liquidation-complete: nothing the market would still accept.
        # A residue below the exchange minimum stays held and marked.
        if exit_state(account, quote, self.rules)[0] == "incomplete" or not eligible:
            return False
        try:
            account.validate(self.rules)
        except ValueError:
            return False
        if not self._tentative_allow(account, quote, frame.signals.emergency):
            return False
        report["restart"] = self._rebase_halted(account, quote)
        self._clear_halt(account, RESTART_PAUSE)
        return True

    def _validate_frame(self, account: Account, frame: Frame) -> None:
        quote = frame.quote
        quote.validate(self.rules)
        observed, received = timestamp(quote.observed_at), timestamp(quote.received_at)
        age = (received - observed).total_seconds()
        signal_age = (received - timestamp(frame.signals.observed_at.isoformat())).total_seconds()
        if not 0 <= age <= self.config.maximum_data_age_seconds:
            raise TransientFrame("stale or future-dated quote")
        if not 0 <= signal_age <= self.config.maximum_data_age_seconds:
            raise TransientFrame("stale or future-dated strategy inputs")
        if account.last_observed and observed <= timestamp(account.last_observed):
            raise TransientFrame("out-of-order quote")
        if account.last_received and received < timestamp(account.last_received):
            raise TransientFrame("receive clock moved backwards")
        actual_spread_pct = (quote.ask - quote.bid) / quote.ask * 100
        if actual_spread_pct > self._maximum_spread_pct:
            raise TransientFrame("observed spread exceeds the eligibility limit")
        nonnegative(frame.fair_value)
        nonnegative(frame.atr)
        if frame.fair_value == ZERO or frame.atr == ZERO:
            raise ValueError("fair value and ATR must be positive")
        if frame.candidate.symbol != self.rules.symbol:
            raise ValueError("candidate does not match configured market")
        if self.policy.trend_switch and frame.trend is not None:
            # A daily bar that had not closed at this observation is lookahead: fail closed.
            frame.trend.validate(quote.observed_at)
        if self.policy.cycle_gate and frame.cycle is not None:
            frame.cycle.validate(observed)  # likewise for variant H's daily values
        if self.policy.mode_switch:
            self._check_perception(self._snapshot(frame), observed_at=quote.observed_at)

    def _clear_flat_bounds(self, account: Account, quote: Quote, report: dict[str, Any]) -> None:
        """Amendment 2 (owner decision 2026-10-02, D15): flat, no orders and no range exit
        pending, so no grid is left to protect; its bounds and outside-range clock go, so
        an empty account can no longer time out of a stale band into a range exit and its
        recentre cooldown. Flat includes a residue below the exchange minimum (``_resolved``;
        owner decision 2026-10-05). A genuine exit keeps both; range_exit and
        range_exit_since are already clear here."""
        if (
            account.grid_lower
            and not account.orders
            and not account.range_exit
            and self._resolved(account, quote)
        ):
            report["bounds_cleared"] = {"lower": account.grid_lower, "upper": account.grid_upper}
            account.grid_lower = account.grid_upper = ZERO
            account.outside_seconds, account.outside_last = ZERO, ""

    def _track_range(
        self, account: Account, quote: Quote, cycle: str | None, report: dict[str, Any]
    ) -> None:
        """Accumulate observed outside-range time; call before updating last_observed.

        Amendment 3 (owner decision 2026-10-02, D16): while the account is halted,
        whatever the category, nothing here advances or resets the clock (amendment 2
        still clears it once the account is flat); a range exit already triggered is
        not affected. ``outside_last`` keeps the last observation before the halt, so
        the halted span is never counted: an interval counts only between two
        consecutive valid observations."""
        if not account.grid_lower or account.range_exit or account.halt:
            return
        observed = quote.observed_at
        if account.grid_lower <= quote.bid <= account.grid_upper:
            account.outside_seconds, account.outside_last = ZERO, ""
            return
        if self.policy.volume_exit and not account.outside_last:
            # Variant E: the episode's first outside observation is its t0.
            account.volume_since, account.volume_check = observed, ""
        # Count only intervals bracketed by two consecutive valid outside observations
        # within the continuity limit. Gaps do not prove time outside the range, but they
        # do not erase time already observed; only a valid inside frame resets the clock.
        if account.outside_last and account.outside_last == account.last_observed:
            elapsed = seconds_between(account.outside_last, observed)
            if elapsed <= self.policy.maximum_frame_gap_seconds:
                account.outside_seconds += elapsed
        account.outside_last = observed
        if self._outside_expired(account, quote, cycle, report):
            account.orders.clear()
            account.range_exit = True
            account.range_exit_since = observed
            account.outside_seconds, account.outside_last = ZERO, ""
            self._pause(account, "outside-range timeout: exit to cash")

    def _outside_expired(
        self, account: Account, quote: Quote, cycle: str | None, report: dict[str, Any]
    ) -> bool:
        """Whether this outside observation ends the grid: once V0's 6 h of observed
        outside time have accumulated, or 2 h while variant H2 is in force.

        Variant E (spec v1 §3 E) keeps its milestones on the clock from the episode's
        t0, whatever gaps paused the accumulated time: it decides once, at the first
        valid observation at or after t0 + 6 h, on the fixed span from t0
        (``VolumeHistory.extends``), and journals the decision. An extended episode ends
        at the first valid observation at or after t0 + 12 h; otherwise V0's own exit
        applies unchanged, as it does on an unavailable comparison."""
        if cycle == H2:
            return account.outside_seconds >= H2_OUTSIDE_RANGE_SECONDS
        expired = account.outside_seconds >= self.policy.outside_range_seconds
        if not self.policy.volume_exit:
            return expired
        since, observed = timestamp(account.volume_since), timestamp(quote.observed_at)
        elapsed = observed - since
        if not account.volume_check and elapsed >= VOLUME_DECISION:
            extends = None if self.volumes is None else self.volumes.extends(since, observed)
            account.volume_check = (
                "unavailable" if extends is None else "extended" if extends else "exit"
            )
            report["volume_check"] = account.volume_check
        return elapsed >= VOLUME_DEADLINE if account.volume_check == "extended" else expired

    @staticmethod
    def _record_exit(report: dict[str, Any], result: Reduction, reason: str) -> None:
        """Journal an exit attempt, including a refusal that sold nothing.

        A refused exit used to leave no trace at all, so an account that could make no
        progress looked identical to one with nothing left to sell.
        """
        report["fills"].extend(asdict(fill) for fill in result.fills)
        if result.fills:
            report["exit_reason"] = reason
        # Always recorded, so a frame that attempted an exit and was not refused is
        # distinguishable from one that attempted none: a rejected or halting frame
        # returns before this and carries no key at all.
        report["exit_blocked"] = result.blocked if result.blocked in ("depth", "dust") else ""
        report["exit_blocked_notional"] = result.outstanding_notional

    @staticmethod
    def _mark(account: Account, quote: Quote, rules: MarketRules) -> None:
        account.last_equity = account.equity(quote, rules)
        account.risk_high = max(account.risk_high, account.last_equity)
        account.measure_high = max(account.measure_high, account.last_equity)

    def _step(self, account: Account, frame: Frame) -> dict[str, Any]:
        quote = frame.quote
        report: dict[str, Any] = {
            "event_id": quote.event_id,
            "fills": [],
            "opened": [],
            "cancelled": [],
            "decision": "hold",
            "allocation": None,
        }
        previous_orders = set(account.orders)
        placed: set[str] = set()  # orders the fills place on this frame
        capped: list[dict[str, Any]] = []
        if self.policy.inventory_cap is not None:
            # On every frame of a capped run, rejected frames included.
            report["capped"] = capped
        restarted = False
        try:
            self._validate_frame(account, frame)
            regime = self.classifier.classify(frame.signals)
            score = self.scorer.score(frame.candidate, regime)
        except TransientFrame as exc:
            # Unusable data pauses the outside-range clock but never erases time already
            # observed outside; otherwise a flapping feed could postpone the exit forever.
            if not account.halt:
                self._pause(account, str(exc))
            account.episode_count = 0  # a TransientFrame breaks the confirmations
            if self.policy.mode_switch:
                account.risk_recovery_count = 0  # and the uptrend entry's (spec v2 section 7)
            report.update(
                decision="halt" if account.halt else "pause",
                reason=account.halt or account.pause,
                cancelled=sorted(previous_orders - account.orders.keys()),
            )
            return report  # No marking, fills, liquidation or recovery on unusable data.
        except ValueError as exc:
            # A validation halt cancels the resting sells that were the inventory's only
            # exit, so held inventory must be armed for liquidation. Nothing is traded on
            # this invalid frame: the return below precedes the liquidation branch, so the
            # exit runs on the next frame that validates.
            self._halt(
                account,
                str(exc),
                category=INTEGRITY,
                observed=self._halt_time(account, quote),
                exit_requested=account.inventory != ZERO,
                report=report,
            )
            if self.policy.mode_switch:
                # An entry that bought nothing ends with the halt; a position waits for the
                # next valid frame's liquidation, since this frame's quote prices nothing.
                self._finish_uptrend(account, None, report)
            report.update(decision="halt", reason=str(exc), cancelled=sorted(previous_orders))
            return report

        observed = timestamp(quote.observed_at)
        day = observed.date().isoformat()
        if account.day != day:
            account.day, account.day_start = day, account.last_equity
        # A frame that ended early (a transient frame's pause cancelling the last buys)
        # may have left the account flat: clear it before the clock can run (Codex review
        # of #163), as the end of this step would have.
        self._clear_flat_bounds(account, quote, report)
        cycle = self._cycle_rule(frame, observed, report) if self.policy.cycle_gate else None
        was_halted = bool(account.halt)
        clock = (
            account.range_exit,
            account.range_exit_since,
            account.outside_seconds,
            account.outside_last,
        )
        self._track_range(account, quote, cycle, report)
        # A gap or a new ineligible frame breaks the recovery streak.
        if (
            account.last_observed
            and (observed - timestamp(account.last_observed)).total_seconds()
            > self.policy.maximum_frame_gap_seconds
        ):
            account.recovery_count = account.episode_count = 0
            if self.policy.mode_switch:
                account.risk_recovery_count = 0  # spec v2 section 7: as in v1
        account.last_observed, account.last_received = quote.observed_at, quote.received_at
        self._mark(account, quote, self.rules)
        report.update(regime=regime.regime.value, opportunity_score=score.score)
        self._rebase(account, frame, score.eligible, report)
        if self.policy.mode_switch and not account.halt:
            # Spec v2 section 5: a stop or a fade already true on this quote is recorded
            # before the risk layer acts on it, so a drain or a halt keeps its label.
            self._uptrend_exits(account, frame, report)
        action = self._risk_action(account, quote, frame.signals.emergency, report)
        if account.halt and not was_halted and account.range_exit and not clock[0]:
            # The observation that timed the range out also halted the account. The
            # halt owns the exit and the clock stands still from it (amendment 3), so
            # this observation starts no range exit, which would stay pending through
            # the halt, be counted, and keep amendment 2 from clearing the flat
            # account's bounds (Codex review of #163).
            (
                account.range_exit,
                account.range_exit_since,
                account.outside_seconds,
                account.outside_last,
            ) = clock
        trend = self._apply_trend(account, frame) if self.policy.trend_switch else None
        if self.policy.flow_block_entry:
            account.flow_block = flow_blocked(account.flow_block, frame.flow_share)
        h3_only = False  # whether only variant H3's relaxed score made this frame eligible
        if account.halt:
            if account.liquidating:
                self._record_exit(
                    report,
                    liquidate(account, quote, self.rules, check=False),
                    self._exit_label(account, "liquidation"),
                )
            # Preconditions read after the liquidation attempt, so a restart can happen
            # on the frame that completes it. Its settlement and any new grid follow on
            # the next frame, exactly as after a manual resume.
            restarted = self._restart(account, frame, score.eligible, report)
            if account.halt:
                report.update(decision="halt", reason=account.halt)
        elif account.range_exit:
            if self.policy.mode_switch:
                # Spec v2 section 6: decisions go on through v1's re-centring cooldown, which
                # holds back new grids only, so the uptrend entry may start here.
                decided = self._decide_mode(account, frame, regime)
                if decided is not None:
                    report["mode_decision"] = decided.value  # journal only
                self._uptrend_step(account, frame, action, report, decided=decided)
            held = self.uptrend_held(account)
            if self.policy.mode_switch and held > ZERO:
                # The range exit leaves the uptrend position alone (section 6), and sells
                # only what else is held; a bound of zero would make reduce_unreserved raise.
                bound = account.inventory - held
                if bound > ZERO:
                    self._record_exit(
                        report,
                        reduce_unreserved(account, quote, self.rules, maximum=bound, check=False),
                        "range_exit",
                    )
                    self.held_fragments(account)  # drop F's fragments if this sale sold them
            else:
                self._record_exit(
                    report,
                    liquidate(account, quote, self.rules, check=False),
                    self._exit_label(account, "range_exit"),
                )
            back_inside = account.grid_lower <= quote.bid <= account.grid_upper
            cooled = (
                self.policy.recenter_after_exit
                and seconds_between(account.range_exit_since, quote.observed_at)
                >= self.policy.recenter_cooldown_seconds
            )
            self._pause(
                account,
                "outside-range timeout: waiting in cash for range recovery"
                + (
                    " or recentering after cooldown"
                    if self.policy.recenter_after_exit
                    else " (recentering disabled)"
                ),
            )
            # _resolved counts the whole unreserved inventory; safe here because
            # liquidate() above required an empty order book.
            if (
                self._resolved(account, quote)
                and action == RiskAction.ALLOW
                and self._entry_eligible(account, frame, regime, score, cycle)
                and (back_inside or cooled)
            ):
                # Leave the exit only after liquidation; the normal recovery confirmations
                # still apply and the next grid is built around the current fair value.
                account.range_exit, account.range_exit_since = False, ""
                account.grid_lower = account.grid_upper = ZERO
                report["range_exit_cleared"] = "returned inside" if back_inside else "recenter"
        else:
            if self.policy.mode_switch:
                # Spec v2 sections 4 and 5: the hourly decision, then the uptrend entry, before
                # this branch's own selling.
                decided = self._decide_mode(account, frame, regime)
                if decided is not None:
                    report["mode_decision"] = decided.value  # journal only
                self._uptrend_step(account, frame, action, report, decided=decided)
            eligible = self._entry_eligible(account, frame, regime, score, cycle)
            h3_only = eligible and not score.eligible
            if not eligible:
                self._pause(account, "; ".join(score.reasons))
            elif account.pause and action == RiskAction.ALLOW:
                account.recovery_count += 1
                if account.recovery_count >= self.policy.recovery_frames:
                    account.pause = ""
                    account.recovery_count = 0
            # Variant A deadline (spec v1, section 3 A): T0 + 24 h, not reset by further
            # Down days. The remaining sells are cancelled BEFORE this observation's
            # matching, so a quote that would have filled them cannot (Codex, PR #114);
            # what is left is then exited under the bid-size limit, retried at each later
            # valid observation.
            trend_due = bool(account.down_since) and (
                seconds_between(account.down_since, quote.observed_at) >= DOWN_DEADLINE_SECONDS
            )
            if trend_due:
                account.orders.clear()
            if self._buys_blocked(account) or self._winding_down(account):
                self._block_buys(account, frame)  # before matching, so none can fill
            refused: list[dict[str, Any]] = []
            # Extended, not assigned: an uptrend buy may already be in the list (spec v2); in
            # every v1 run it is empty here.
            report["fills"].extend(
                [
                    asdict(fill)
                    for fill in match(
                        account,
                        quote,
                        self.rules,
                        # A running variant A Down sequence places no new buy (reentries too),
                        # and neither does variant F's block, nor a grid winding down (spec v2).
                        recycle=not account.pause
                        and not account.draining
                        and frame.allow_new_grid
                        and not account.down_since
                        and not self._buys_blocked(account)
                        and not self._winding_down(account),
                        epoch=frame.epoch,
                        reentry_quantity=(
                            None
                            if self.policy.inventory_cap is None
                            else lambda order_id, price, quantity: self._cap(
                                account, quote, capped, order_id, price, quantity
                            )
                        ),
                        refused=refused,
                        check=False,
                    )
                ]
            )
            placed = set(account.orders) - previous_orders  # child sells, reentry buys
            if refused:
                # A reentry buy the balance or minimum-notional check declined: that level
                # has left the grid, which the journal must show.
                report["reentry_refused"] = refused
            # Unpaired inventory: neither reserved by a resting sell nor the filled part
            # of a buy still resting, whose own sell will pair it once it fills. Cancelled
            # partial buys leave it, and so does a residue a harvest tolerated. Exit it
            # using only remaining bid capacity, never inventory reserved by a sell, and
            # never the part of a resting buy that has already filled. Variant F's held
            # fragments wait for their own sell instead.
            unpaired = unpaired_inventory(account)
            if self.policy.flow_block_entry:
                unpaired -= self.held_fragments(account)
            if self.policy.mode_switch:
                unpaired -= self.uptrend_held(account)  # spec v2 section 6: not grid inventory
            if unpaired > ZERO:
                consumed = sum(
                    (D(fill["quantity"]) for fill in report["fills"] if fill["side"] == "sell"),
                    ZERO,
                )
                self._record_exit(
                    report,
                    reduce_unreserved(
                        account,
                        quote,
                        self.rules,
                        consumed=consumed,
                        maximum=unpaired,
                        check=False,
                    ),
                    # Same-step labelling (spec v1, section 3 A): drain outranks trend_exit.
                    self._exit_label(
                        account, "drain" if account.draining or not trend_due else "trend_exit"
                    ),
                )

        if self.policy.mode_switch:
            # After the branch's selling: an uptrend exit that has sold the position ends it.
            self._finish_uptrend(account, quote, report)
            if account.winding_down and not account.orders:
                account.winding_down = False  # the grid has ended (spec v2 section 6)
        # Recheck risk after any fills, but never reuse this event's liquidity for an exit.
        if report["fills"]:
            self._risk_action(account, quote, frame.signals.emergency, report)
        # Buys may still rest here, so _resolved (whole unreserved inventory) is the
        # stricter gate: a partly filled buy's inventory blocks the harvest until its own
        # child sell has paired it. See _resolved.
        if not account.halt and not restarted and self._resolved(account, quote):
            self._harvest(account, frame, report, capped, trend, regime, cycle)
            if h3_only and report["opened"]:
                report["cycle"]["h3_only"] = True  # a grid opened only because of H3
        if account.halt:
            report.update(decision="halt", reason=account.halt)
        elif account.pause:
            report.update(decision="pause", reason=account.pause)
        if trend is not None:
            # The sequence ends once nothing sellable is left: flat, or holding only a
            # residue the market filters forbid selling (PR #122's rule; waiting for
            # inventory == 0 looped forever on such a residue, Bob's F1). Only a later
            # observation can then open a grid, and only in the Up state.
            if account.down_since and not account.orders and self._resolved(account, quote):
                report["down_sequence_ended"] = account.down_since
                account.down_since = ""
                # The grid this sequence ended left no orders behind: amendment 2, below,
                # clears its bounds and outside-range clock (Codex's PR #114 fix was this
                # special case of it).
            report["trend"] = {
                "state": trend,
                "day": frame.trend.day if frame.trend is not None else None,
                "down_since": account.down_since or None,
            }
        # After this frame's fills, exits, settlement and any new grid.
        self._clear_flat_bounds(account, quote, report)
        # An order is cancelled if it left the book without completing, so one that
        # filled in part and was then cancelled on this frame is listed too, and so is
        # one its fills placed and a halt then cleared: a completed buy's child sell
        # (Codex review of #159).
        completed = {fill["order_id"] for fill in report["fills"] if fill["remaining"] == ZERO}
        gone = (previous_orders | placed) - account.orders.keys() - completed
        report["cancelled"] = sorted(gone)
        self._mark(account, quote, self.rules)
        report.update(
            active_equity=account.last_equity,
            pending_reserve=account.pending,
            secured_reserve=account.secured,
            cash=account.cash,
            inventory=account.inventory,
            fees=account.fees,
            open_orders=len(account.orders),
            total_equity=account.last_equity + account.pending + account.secured,
            recovery_count=account.recovery_count,
            draining=account.draining,
            halt_category=account.halt_category,
            episode_since=account.episode_since or None,
            risk_high=account.risk_high,
            measure_high=account.measure_high,
            range_exit=account.range_exit,
            outside_seconds=account.outside_seconds,
            unreserved_inventory=account.inventory - account.reserved_base(),
        )
        return report

    def _harvest(
        self,
        account: Account,
        frame: Frame,
        report: dict[str, Any],
        capped: list[dict[str, Any]],
        trend: str | None,
        regime: RegimeAssessment,
        cycle: str | None,
    ) -> None:
        """Harvest an account with nothing sellable left: cancel its unused buys, then
        halt on exhausted capital, or settle profit and open the next grid unless a
        pause, a range exit, the frame or variant A, F, G or H2 forbids one.

        Ordering: the caller runs this after the frame's fills and their risk recheck,
        only on a frame neither halted nor just restarted, and only once ``_resolved``
        holds; variant A's end-of-sequence bookkeeping follows it."""
        quote = frame.quote
        # A flat account is a safe harvest point even with unused deeper buys.
        # Do this only after sells, draining, or when all orders are already gone.
        sold = any(fill["side"] == "sell" for fill in report["fills"])
        if not (sold or account.draining or not account.orders):
            return
        self._cancel_buys(account)
        # The grid has ended (a range exit or a drain has run its course, or it sold
        # out): variant F's fragments, all below the minimum here, are ordinary unpaired
        # inventory from now on, sold once a price makes them sellable (spec v1 §3 F).
        account.flow_fragments.clear()
        if account.cash - account.pending <= ZERO:
            # Arm the exit for any residue, as the other halt sites do, so the stuck
            # inventory is reported from the next frame rather than only once the risk
            # engine re-halts a frame later.
            self._halt(
                account,
                "active capital exhausted",
                category=EXHAUSTION,
                observed=quote.observed_at,
                exit_requested=account.inventory != ZERO,
                report=report,
            )
            return
        report["allocation"] = self._settle(account, quote)
        account.draining = False
        if account.pause or account.range_exit or not frame.allow_new_grid:
            return
        if self.policy.mode_switch and account.mode != Mode.GRID.value:
            return  # spec v2 section 4: a new grid opens in Grid mode only
        if trend is not None and (trend != UP or account.down_since):
            # Variant A: a new grid needs Up and no running Down sequence.
            report.update(
                decision="cash",
                reason=f"trend switch: {trend}"
                + ("; Down sequence running" if account.down_since else ""),
            )
            return
        if veto := self._entry_veto(account, frame, cycle):
            report.update(decision="cash", reason=ENTRY_VETOES[veto], entry_veto=veto)
            return
        try:
            report["opened"] = self._open_grid(account, frame, capped, regime)
            report["decision"] = "open_grid"
        except GridNotViable as exc:
            report.update(decision="cash", reason=str(exc))

    def resume(self, frame: Frame, *, event_id: str, reason: str) -> dict[str, Any]:
        """Audited paper-only control; never erase losses or place/fill orders."""
        self._refuse_runtime_variants()
        if not event_id.strip() or not reason.strip():
            raise ValueError("resume requires a unique event ID and an operator reason")

        def operation(account: Account) -> dict[str, Any]:
            self._validate_frame(account, frame)
            account.validate(self.rules)
            if not account.halt or account.orders:
                raise ValueError("resume requires a halted, reconciled flat paper account")
            if account.halt_category == EXHAUSTION:
                # Owner decision D18 (2026-10-05): refused by name, before any risk check.
                raise ValueError(
                    "resume refused: an 'active capital exhausted' halt is final; the active "
                    "account cannot fund a grid level, and resume cannot return the reserve "
                    "to it (owner decision D18)"
                )
            if exit_state(account, frame.quote, self.rules)[0] == "incomplete":
                # Liquidation-complete, PR #122's criterion (spec v1 amendment 1): a
                # remainder below the exchange minimum is admitted, stays held and marked,
                # and is drained or settled as after any resume; inventory the market
                # would still accept is not. For a drawdown halt the plain risk check
                # below still decides: a held residue marked to the bid can move the
                # measured drawdown by at most one minimum notional against risk_high.
                raise ValueError(
                    "resume requires a flat paper account: "
                    f"{account.inventory} base units are still held, so the exit is "
                    "incomplete; the halt stands until the liquidation completes"
                )
            regime = self.classifier.classify(frame.signals)
            if not self.scorer.score(frame.candidate, regime).eligible:
                raise ValueError("resume eligibility checks failed")
            day = timestamp(frame.quote.observed_at).date().isoformat()
            if account.day != day:
                account.day, account.day_start = day, account.last_equity
            result: dict[str, Any] = {
                "decision": "resume_pending",
                "previous_halt": account.halt,
                "operator_reason": reason,
                "fills": [],
                "opened": [],
            }
            if self._risk_action(account, frame.quote, frame.signals.emergency) != RiskAction.ALLOW:
                # Owner decision D17 (2026-10-05): an emergency or integrity halt that only
                # the drawdown blocks, at any depth, resumes as the automatic restart does;
                # the tentative check passes exactly when the drawdown is all that refuses.
                # A drawdown halt still waits for that restart (amendment 1).
                if account.halt_category == DRAWDOWN or not self._tentative_allow(
                    account, frame.quote, frame.signals.emergency
                ):
                    raise ValueError(
                        "resume blocked by current risk limits; baselines are preserved. A "
                        "hard-drawdown halt cannot be resumed by hand: a flat account's "
                        "drawdown against risk_high is frozen, and the halt restarts "
                        "automatically once its cool-off has passed (spec v1 amendment 1). An "
                        "emergency or integrity halt resumes at any drawdown once the "
                        "emergency signal has cleared and the day's loss is under the daily "
                        "limit (owner decision D17)"
                    )
                result["restart"] = self._rebase_halted(account, frame.quote)
            self._clear_halt(account, "operator resume: awaiting confirmed eligible data")
            account.last_observed = frame.quote.observed_at
            account.last_received = frame.quote.received_at
            self._mark(account, frame.quote, self.rules)
            return result

        return self.store.transact(
            "control/resume/" + event_id, {"frame": frame.payload(), "reason": reason}, operation
        )

    def _apply_trend(self, account: Account, frame: Frame) -> str:
        """Variant A at a valid observation: return the gating state.

        A Down classification that became effective since the last applied signal
        starts a Down sequence (T0 = this observation) unless one is running. Resting
        buys are cancelled at once; resting sells stay. Only a usable signal acts: a
        stale or missing one gates as Unavailable and must neither start a sequence nor
        advance ``trend_day`` (Bob's F2 and C2 on PR #114).
        """
        signal, observed = frame.trend, frame.quote.observed_at
        state = effective_state(signal, observed)
        if signal is not None and state != UNAVAILABLE:
            if starts_down_sequence(signal, account.trend_day) and not account.down_since:
                account.down_since = observed
                self._cancel_buys(account)
            account.trend_day = max(account.trend_day, signal.day)
        return state

    @staticmethod
    def _cycle_rule(frame: Frame, observed: datetime, report: dict[str, Any]) -> str | None:
        """Variant H at a valid observation: the rule in force (H2, H3 or None), from the
        frame's daily values and this observation's own phase, both journaled."""
        signal = frame.cycle
        rule = signal.rule(observed) if signal is not None else None
        report["cycle"] = {
            "day": signal.day if signal is not None else None,
            "phase": phase(observed),
            "rule": rule,
        }
        return rule

    def _entry_eligible(
        self,
        account: Account,
        frame: Frame,
        regime: RegimeAssessment,
        score: CandidateScore,
        cycle: str | None,
    ) -> bool:
        """V0's eligibility, or under variant H3 its relaxed opportunity-score minimum
        (0.60) for the decision to open a new grid, which applies only while the account
        holds no grid: no order and nothing sellable held. A grid's own pause and drain
        thus stay exactly V0's ("for new grids only", spec v1 §3 H), so a grid only H3
        opened pauses at its next frame scored below V0's minimum."""
        if score.eligible or cycle != H3 or account.orders:
            return score.eligible
        if not self._resolved(account, frame.quote):
            return False
        return self.scorer.score(frame.candidate, regime, minimum_score=self._h3_minimum).eligible

    def _buys_blocked(self, account: Account) -> bool:
        """Whether variant F's block is on: no new grid, reentry or resting buy."""
        return self.policy.flow_block_entry and account.flow_block

    def _entry_veto(self, account: Account, frame: Frame, cycle: str | None) -> str:
        """The variant (F, G or H2) whose own rule forbids a new grid at this frame, or ""
        (spec v1 §3)."""
        if self._buys_blocked(account):
            return "F"
        if self.policy.funding_gate and frame.funding_blocks is not False:
            return "G"
        return "H2" if cycle == H2 else ""

    def held_fragments(self, account: Account) -> Decimal:
        """Variant F's fragments waiting for their target's minimum notional (spec v1 §3
        F), which the ordinary unpaired exit and the end-of-run verdict leave alone. A
        drain, a range exit and a halt's liquidation sell them like any inventory.

        They belong to their grid and are ordinary unpaired inventory once it ends. The
        harvest that ends it, after a range exit or a drain, drops them (``_harvest``).
        They are dropped here when F no longer blocks and no order is left, since the
        account then re-centres, and when an exit has sold them. Under spec v2's mode
        switcher an uptrend position held beside them is not grid inventory, so it is left
        out of what they are compared with, and a range exit that sold them drops them."""
        fragments = account.flow_fragments
        total = sum(fragments.values(), ZERO)
        unpaired = unpaired_inventory(account)
        if self.policy.mode_switch:
            unpaired -= self.uptrend_held(account)
        if total > unpaired or not (account.flow_block or account.orders):
            fragments.clear()
            return ZERO
        return ZERO if account.draining else total

    def _block_buys(self, account: Account, frame: Frame) -> None:
        """Variant F: cancel the resting buys (spec v1 §3 F). A cancelled buy's filled part
        gets a resting sell at the buy's target, as a complete fill's child sell would;
        a part below the minimum notional there joins that target's fragment, which gets
        its one sell once it reaches the minimum (``held_fragments``)."""
        self.held_fragments(account)  # first drop what an exit has sold
        fragments, rules = account.flow_fragments, self.rules
        for key, order in list(account.orders.items()):
            if order.side != "buy":
                continue
            del account.orders[key]
            target = order.target
            if target is None or order.quantity == order.remaining:
                continue
            held = fragments.pop(target, ZERO) + order.quantity - order.remaining
            quantity = floor_step(held, rules.quantity_step)
            if target * quantity >= rules.minimum_notional:
                sell = LimitOrder(
                    f"{key}/fragment",
                    "sell",
                    target,
                    quantity,
                    quantity,
                    reentry=order.price,
                    epoch=frame.epoch,  # like a child sell, it cannot fill within this bar
                )
                place(account, sell, rules, check=False)
                held -= quantity
            if held:
                fragments[target] = held

    # --- Spec v2's mode switcher (docs/EXPERIMENT_SPEC_V2.md, sections 4-7) -----------------
    # Every method below runs only when ``policy.mode_switch`` is on: the account's mode,
    # its hourly decision, the uptrend engine and its exits. The uptrend position is not grid
    # inventory: v1's per-frame exit, range exit, settlement and grid drains leave it alone
    # (``uptrend_held``, ``_resolved``), and only its own exits and the risk layer sell it.

    @staticmethod
    def _snapshot(frame: Frame) -> Snapshot:
        """The frame's perception, which the mode switcher cannot run without."""
        if frame.perception is None:
            raise ValueError("the mode switcher needs a perception snapshot on every frame")
        return frame.perception

    @staticmethod
    def _check_perception(snapshot: Snapshot, *, observed_at: str) -> None:
        """Fail closed on a perception that reads a daily bar not yet closed at this
        observation (lookahead), or whose latest daily bar and its open time disagree. The
        uptrend engine walks ``d1_points`` up to ``d1_index``, so an index a day ahead would
        read a future close."""
        index, points = snapshot.d1_index, snapshot.d1_points
        if index is None:
            if snapshot.d1_open_ms is not None:
                raise ValueError("the perception names a daily bar but no daily point")
            return
        if not 0 <= index < len(points) or points[index].open_ms != snapshot.d1_open_ms:
            raise ValueError("the perception's latest daily point and its open time disagree")
        if points[index].open_ms + _DAY_MS > _epoch_ms(observed_at):
            raise ValueError("the perception reads a daily bar that had not closed (lookahead)")

    @staticmethod
    def _set_mode(account: Account, mode: str) -> None:
        """Every assignment of the mode goes through here, so ``mode_switches`` counts each
        change of it, a halt's included; a decision that keeps the mode is not a switch."""
        if account.mode != mode:
            account.mode = mode
            account.mode_switches += 1

    def _winding_down(self, account: Account) -> bool:
        """Whether a grid is winding down (section 6): it places no buy, as under F's block."""
        return self.policy.mode_switch and account.winding_down

    def uptrend_held(self, account: Account) -> Decimal:
        """The uptrend position's quantity while it is entering or holding, which v1's own
        selling leaves alone; ZERO otherwise. Once its exit has begun (a stop, a fade, a risk
        drain or a halt), v1's selling sells it as v1 drains. Public, like
        ``held_fragments``: the end-of-run verdict reads it too."""
        position = account.uptrend
        if position is None or position.phase not in ("entering", "holding"):
            return ZERO
        return position.quantity

    def _exit_label(self, account: Account, reason: str) -> str:
        """The journal label of an exit's sale: ``reason``, or ``"uptrend_" + exit_reason``
        while an uptrend position is exiting, until ``_finish_uptrend`` ends it, so the
        realised P&L by reason keeps the two apart."""
        position = account.uptrend
        if self.policy.mode_switch and position is not None and position.phase == "exiting":
            return "uptrend_" + position.exit_reason
        return reason

    @staticmethod
    def _begin_exit(position: UptrendPosition, reason: str, report: dict[str, Any] | None) -> None:
        """Begin the position's exit, unless one has begun: it never buys again, its reason
        ("stop", "fade" or "risk") is set once, and only the frame it begins on reports it,
        so each exit counts once."""
        if position.phase == "exiting":
            return
        position.phase, position.exit_reason = "exiting", reason
        if report is not None:
            report["uptrend_exit"] = reason

    def _stop_out(
        self, account: Account, position: UptrendPosition, quote: Quote, report: dict[str, Any]
    ) -> None:
        """Exit 1: the 24-hour re-entry pause runs from this, its first trigger (section 5),
        whatever the entry had bought."""
        account.uptrend_stopped_ms = _epoch_ms(quote.observed_at)
        self._begin_exit(position, "stop", report)

    @staticmethod
    def _end_entry(account: Account, position: UptrendPosition, report: dict[str, Any]) -> None:
        """The entry stops buying: the position holds what it bought (section 5, "Partial
        fills"). An entry that bought nothing holds nothing, so it ends here, as an entry an
        exit ends would: no position and no trade."""
        if position.quantity > ZERO:
            position.phase = "holding"
        else:
            account.uptrend = None
            report["uptrend_abandoned"] = True

    def _flat(self, account: Account, quote: Quote) -> bool:
        """Section 6's flat: no resting order, and nothing the market would still buy once
        F's held fragments are set aside, as v1's unpaired exit sets them aside. Dust is flat,
        and so are several fragments that together exceed the minimum."""
        if account.orders:
            return False
        rest = unpaired_inventory(account) - self.held_fragments(account)
        return marketable(rest, quote, self.rules) == ZERO

    def _decide_mode(self, account: Account, frame: Frame, regime: RegimeAssessment) -> Mode | None:
        """Section 4's hourly decision, at the first valid frame of an account not halted at
        or after each UTC hour boundary: the mode this frame decided, or None when it made no
        decision.

        While an uptrend position exists the pair stays in Uptrend and nothing is decided
        ("Entering versus staying"); the hour is still taken and the RANGE count restarts,
        so a position that ends later in the hour leaves the next decision to the next hour,
        which counts RANGE hours afresh. Otherwise the count goes on only from the hour
        before, and the mode is ``select_mode``'s. Leaving Grid with the grid's orders
        resting winds the grid down; a decision back to Grid lifts that, as F's block lifts.
        """
        observed = _epoch_ms(frame.quote.observed_at)
        hour = observed // _HOUR_MS * _HOUR_MS
        if hour <= account.decision_hour_ms:
            return None
        consecutive = account.decision_hour_ms == hour - _HOUR_MS
        account.decision_hour_ms = hour
        if account.uptrend is not None:
            account.range_decisions = 0
            return None
        if regime.regime == MarketRegime.RANGE:
            account.range_decisions = account.range_decisions + 1 if consecutive else 1
        else:
            account.range_decisions = 0
        mode = select_mode(
            self._snapshot(frame),
            regime.regime,
            regime.input_quality_ok,
            account.range_decisions,
            observed,
            account.uptrend_stopped_ms,
        )
        was_grid = account.mode == Mode.GRID.value
        self._set_mode(account, mode.value)
        if mode is Mode.GRID:
            account.winding_down = False
        elif was_grid and account.orders:
            account.winding_down = True
        return mode

    def _uptrend_exits(self, account: Account, frame: Frame, report: dict[str, Any]) -> None:
        """Section 5's exits 1 and 2 at a valid frame of an account not halted, after the mark
        and before the pre-fill risk check, so a stop or a fade already true on this quote is
        recorded first and exit 3 then keeps its label:

        1. exit 1 when the bid is at or below the stop;
        2. each daily close not yet processed, in order: the points after ``stop_day_ms`` up
           to ``d1_index``, usually one at the first frame after midnight, and every close a
           quote gap crossed. An entry still buying ends at the first. A close that is not Up
           is exit 2; any other raises the highest close and trails the stop, and the bid is
           checked against that stop before the next. The first exit ends the processing;
        3. exit 2 whenever the daily bar due is missing (``d1_state`` UNAVAILABLE), which
           step 2 cannot see, since no point arrives (it fails closed).
        """
        position = account.uptrend
        if position is None or position.phase == "exiting":
            return
        quote, snapshot = frame.quote, self._snapshot(frame)
        if quote.bid <= position.stop:
            self._stop_out(account, position, quote, report)
            return
        if snapshot.d1_index is not None:
            points = snapshot.d1_points
            start = bisect_right(points, position.stop_day_ms, key=lambda point: point.open_ms)
            for point in points[start : snapshot.d1_index + 1]:
                if position.phase == "entering":
                    position.phase = "holding"  # the stop never trails while the entry buys
                if point.state != TrendState.UP or point.atr is None:
                    self._begin_exit(position, "fade", report)
                    break
                position.highest_close = max(position.highest_close, point.close)
                position.stop = trailed_stop(position.stop, position.highest_close, point.atr)
                position.stop_day_ms = point.open_ms
                if quote.bid <= position.stop:
                    self._stop_out(account, position, quote, report)
                    break
        if position.phase != "exiting" and snapshot.d1_state == TrendState.UNAVAILABLE:
            self._begin_exit(position, "fade", report)
        if position.phase == "holding" and position.quantity == ZERO:
            self._end_entry(account, position, report)  # a close ended an entry with nothing

    def _uptrend_step(
        self,
        account: Account,
        frame: Frame,
        action: RiskAction,
        report: dict[str, Any],
        *,
        decided: Mode | None,
    ) -> None:
        """Section 5's entry, after this frame's decision and before the branch's own selling,
        and section 7's recovery count. ``decided`` is the mode this frame's decision set, or
        None when the frame made none (``_decide_mode``).

        The count: after a risk drain or a restart, ``recovery_frames`` consecutive valid
        frames whose action is ALLOW end the recovery, V0's eligibility aside (a transient
        frame or a frame gap restarts it, in ``_step``).

        An entry starts only on a decision frame that chose Uptrend, with ALLOW, no recovery
        and a flat pair, when the buy price is above the initial stop (``s > 0``) and the bid
        is too; otherwise nothing starts before the next decision, and nothing is stopped
        out. It takes its limits once, and buys on each quote, the first included, while the
        action is ALLOW: a "budget" refusal ends it, holding what it bought; a "depth" one
        waits for the next quote. Each buy goes in the report's fills, as any fill does.
        """
        if account.risk_recovery:
            if action == RiskAction.ALLOW:
                account.risk_recovery_count += 1
                if account.risk_recovery_count >= self.policy.recovery_frames:
                    account.risk_recovery, account.risk_recovery_count = False, 0
            else:
                account.risk_recovery_count = 0
        quote, rules = frame.quote, self.rules
        position = account.uptrend
        if position is None:
            if (
                decided is not Mode.UPTREND
                or action != RiskAction.ALLOW
                or account.risk_recovery
                or not self._flat(account, quote)
            ):
                return
            snapshot = self._snapshot(frame)
            close, atr, day_ms = snapshot.d1_close, snapshot.d1_atr, snapshot.d1_open_ms
            if close is None or atr is None or day_ms is None:
                return  # unreachable: Uptrend needs the daily close and ATR
            stop = initial_stop(close, atr)
            if stop_distance(buy_price(quote, rules), stop) <= ZERO or quote.bid <= stop:
                return
            cash_cap, risk_allowance = entry_limits(
                account.cash - account.pending, account.equity(quote, rules)
            )
            position = account.uptrend = UptrendPosition(
                cash_cap=cash_cap,
                risk_allowance=risk_allowance,
                stop=stop,
                highest_close=close,
                stop_day_ms=day_ms,
                entered_at=quote.observed_at,
            )
        if position.phase != "entering":
            return
        if action != RiskAction.ALLOW or account.risk_recovery:
            # Cannot happen: on an account not halted, a refusing action other than EXIT is a
            # drain, which made the position "exiting" (``_risk_action``); EXIT halts, and the
            # halt branch never comes here; and the recovery starts only at a drain or at a
            # restart, which no position survives. So an entry meeting either is a defect.
            raise RuntimeError(
                f"an entering uptrend position met risk action {action} "
                f"(recovery {account.risk_recovery}): a drain or a halt should have ended it"
            )
        result = market_buy(
            account,
            quote,
            rules,
            cash_left=position.cash_cap - position.spent,
            risk_left=position.risk_allowance - position.risk_used,
            stop=position.stop,
        )
        fill = result.fill
        if fill is not None:
            position.quantity += fill.quantity
            position.spent += fill.price * fill.quantity + fill.fee
            position.risk_used += fill.quantity * (fill.price - position.stop)
            report["fills"].append(asdict(fill))
        elif result.refusal == "budget":
            self._end_entry(account, position, report)

    def _finish_uptrend(
        self, account: Account, quote: Quote | None, report: dict[str, Any]
    ) -> None:
        """End an exiting position once what remains of it is zero or below the minimum
        notional, after the frame's selling (the unpaired exit, the range-exit sale or the
        halt's liquidation), leaving any remainder as dust, as in v1. A position that bought
        something reports ``uptrend_ended``, a completed trade (section 8, C5); one that bought
        nothing reports ``uptrend_abandoned``, which is not a trade (section 5).

        What remains is the position's quantity, at most: the sales take it out of the
        unpaired inventory, F's held fragments set aside, as the end-of-run verdict does.
        Without a quote (an invalid frame's halt) only an entry that bought nothing can end."""
        position = account.uptrend
        if position is None or position.phase != "exiting":
            return
        if position.quantity > ZERO:
            if quote is None:
                return
            pool = unpaired_inventory(account) - self.held_fragments(account)
            if marketable(min(position.quantity, pool), quote, self.rules) > ZERO:
                return
        account.uptrend = None
        report["uptrend_ended" if position.spent > ZERO else "uptrend_abandoned"] = True

    def _settle(self, account: Account, quote: Quote) -> dict[str, Any] | None:
        # An unsellable residue is left out of the allocation base, which understates
        # profit; it is never counted as settled cash.
        # No orders is checked first, so _resolved here sees the whole inventory.
        if account.orders or not self._resolved(account, quote):
            raise ValueError("profit settlement requires no orders and no sellable inventory")
        active_before = account.cash - account.pending
        if active_before <= ZERO:
            raise ValueError("cannot settle an exhausted active account")
        # A held residue is excluded from the allocation base but IS in day_start,
        # risk_high and every later active-equity reading, so it must sit on both sides
        # of the rescaling ratio. Leaving it out of both depresses the baselines and can
        # move a later drawdown or daily-loss reading across its threshold. Marked exactly
        # as Account.equity marks it, since that is what populated those baselines: the
        # unrounded liquidation price, not the tick-floored price an order would use.
        marked_residue = (
            account.inventory
            * quote.bid
            * (ONE - self.rules.slippage_rate)
            * (ONE - self.rules.taker_fee)
        )
        state = ProfitVaultState(
            account.reserve_high,
            account.pending,
            account.secured,
            dict(account.confirmed_transfers),
        )
        allocation = self.vault.allocate(
            state, account.cash, positions_flat=True, orders_reconciled=True
        )
        account.pending, account.reserve_high = state.pending_reserve, state.active_high_water_mark
        if allocation.new_profit == ZERO and allocation.transfer_due == ZERO:
            # Nothing settled: the factor below would be exactly 1 and no transfer is due,
            # so the baselines, the count and the transfer journal stay as they are, and
            # the journal's allocation stays null. A flat account reaches this on every
            # frame it waits in cash. The pending write above stays: its value is unchanged,
            # but replay results print its exact digits.
            return None
        account.settlement_count += 1
        # Proportional adjustment preserves returns even when reserve exceeds the
        # original capital; subtracting could make a baseline zero or negative.
        factor = (allocation.active_capital_after_allocation + marked_residue) / (
            active_before + marked_residue
        )
        account.day_start *= factor
        # The C1(b) reference is scaled in the same statement as risk_high, by the same
        # factor, and nowhere else (amendment 1).
        account.risk_high *= factor
        account.measure_high *= factor
        if allocation.transfer_due:
            self.vault.confirm_transfer(
                state, allocation.transfer_due, f"simulated-checkpoint/{account.settlement_count}"
            )
            account.cash -= allocation.transfer_due
            account.pending, account.secured = state.pending_reserve, state.secured_reserve
        account.confirmed_transfers = state.confirmed_transfers
        return asdict(allocation)

    def _cap(
        self,
        account: Account,
        quote: Quote,
        capped: list[dict[str, Any]],
        order_id: str,
        price: Decimal,
        quantity: Decimal,
    ) -> Decimal:
        """Variant B check for one new buy; records any resize or skip."""
        cap = self.policy.inventory_cap
        if cap is None:
            return quantity
        allowed = capped_quantity(account, quote, self.rules, cap, price, quantity)
        if allowed != quantity:
            capped.append(
                {
                    "order_id": order_id,
                    "price": price,
                    "requested": quantity,
                    "placed": allowed,
                    "action": "resized" if allowed else "skipped",
                }
            )
        return allowed

    def _open_grid(
        self,
        account: Account,
        frame: Frame,
        capped: list[dict[str, Any]],
        regime: RegimeAssessment | None = None,
    ) -> list[str]:
        rules, quote = self.rules, frame.quote
        spread = (quote.ask - quote.bid) / quote.ask
        cost = 2 * (rules.fee_rate + rules.slippage_rate) + spread
        budget = account.available_quote(rules) * GRID_BUDGET_FRACTION
        plan = self.builder.build(
            symbol=rules.symbol,
            fair_value=float(frame.fair_value),
            atr=float(frame.atr),
            capital=float(budget),
            min_notional=float(rules.minimum_notional * (ONE + rules.fee_rate)),
            round_trip_cost_pct=float(cost * 100),
        )
        levels = tuple(floor_step(D(str(level)), rules.tick_size) for level in plan.levels)
        pairs = [
            (low, high)
            for low, high in zip(levels, levels[1:], strict=False)
            if low < min(quote.bid, frame.fair_value)
        ]
        if not pairs or len(set(levels)) != len(levels):
            raise GridNotViable("no distinct, passive buy levels after tick rounding")
        required = cost * self._minimum_grid_cost_multiple
        # Sized over every candidate level, so a level V2 skips below resistance leaves its
        # share unspent: a skip never enlarges the orders that remain.
        per_order = budget / len(pairs)
        # V2 (policy.structure) sells just below resistance, in a ranging market only: the
        # owner's source idea targets resistance in consolidation. The RANGE-only rule was
        # first chosen after seeing development results that were later found invalid
        # (D20); docs/STRUCTURE_PREREGISTRATION.md registers it with every other V2 rule.
        if self.policy.structure and (regime is None or regime.regime == MarketRegime.RANGE):
            pairs = self._below_resistance(pairs, frame.resistance, required)
        orders: list[LimitOrder] = []
        for index, (low, high) in enumerate(pairs):
            quantity = floor_step(per_order / (low * (ONE + rules.fee_rate)), rules.quantity_step)
            if low * quantity < rules.minimum_notional:
                raise GridNotViable("rounded quantity cannot satisfy minimum notional")
            if (high - low) / low < required:
                raise GridNotViable("rounded spacing cannot cover conservative costs")
            orders.append(
                LimitOrder(
                    f"{quote.event_id}/buy/{index}",
                    "buy",
                    low,
                    quantity,
                    quantity,
                    target=high,
                    epoch=frame.epoch,
                )
            )
        if self.policy.inventory_cap is None:
            for order in orders:
                place(account, order, rules, check=False)
        else:
            orders = self._place_capped(account, quote, orders, capped)
        # A sell target raised to a resistance above the top level stays inside the range
        # the outside-range clock watches.
        targets = [order.target for order in orders if order.target is not None]
        account.grid_lower, account.grid_upper = levels[0], max([levels[-1], *targets])
        account.outside_seconds, account.outside_last = ZERO, ""
        account.cycles += 1
        return [order.order_id for order in orders]

    def _below_resistance(
        self,
        pairs: list[tuple[Decimal, Decimal]],
        resistance: tuple[ResistanceZones, ...],
        required: Decimal,
    ) -> list[tuple[Decimal, Decimal]]:
        """V2 sell targets (D19), below the nearest known resistance above each buy level
        (``nearest_resistance``): a zone in reach sets the target just below it, raised or
        lowered from the geometric next level; one out of reach only lowers the geometric
        level to there if it would reach it. A target a zone moved that cannot clear costs
        (spacing below ``required``) gets no buy: it may not sit higher and cannot profit
        lower. A geometric target left standing keeps V0's rule. Fixed at grid open, from
        completed bars only."""
        tick = self.rules.tick_size
        kept: list[tuple[Decimal, Decimal]] = []
        blocked: set[Decimal] = set()  # the zones that left a level no buy, to the tick
        for low, high in pairs:
            nearest = nearest_resistance(float(low), resistance)
            if nearest is None:
                kept.append((low, high))
                continue
            zone, in_reach = nearest
            cap = floor_step(D(str(zone)) * RESISTANCE_TARGET, tick)
            target = cap if in_reach else min(high, cap)
            if target != high and (target - low) / low < required:
                blocked.add(floor_step(D(str(zone)), tick))
            else:
                kept.append((low, target))
        if not kept:
            zones = ", ".join(str(zone) for zone in sorted(blocked))
            raise GridNotViable(
                f"no buy level can sell below resistance at {zones} and clear costs"
            )
        return kept

    def _place_capped(
        self,
        account: Account,
        quote: Quote,
        orders: list[LimitOrder],
        capped: list[dict[str, Any]],
    ) -> list[LimitOrder]:
        """Place buys from the highest price down. The first that does not fit whole is
        resized (or skipped below the minimum notional), and every lower level is skipped.
        """
        placed: list[LimitOrder] = []
        descending = sorted(orders, key=lambda order: order.price, reverse=True)
        for index, order in enumerate(descending):
            requested = order.quantity
            quantity = self._cap(account, quote, capped, order.order_id, order.price, requested)
            if quantity:
                order.quantity = order.remaining = quantity
                place(account, order, self.rules, check=False)
                placed.append(order)
            if quantity != requested:
                capped.extend(
                    {
                        "order_id": lower.order_id,
                        "price": lower.price,
                        "requested": lower.quantity,
                        "placed": ZERO,
                        "action": "skipped",
                    }
                    for lower in descending[index + 1 :]
                )
                break
        if not placed:
            raise GridNotViable("inventory cap leaves room for no buy level")
        return placed
