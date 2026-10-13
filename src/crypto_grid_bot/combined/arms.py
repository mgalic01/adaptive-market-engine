"""Fixed component-arm switches; never authorize or launch an experiment."""

from dataclasses import dataclass, replace

from crypto_grid_bot.combined.routing import RoutingContext


@dataclass(frozen=True, slots=True)
class ArmSettings:
    routing: RoutingContext
    trailing: bool = True
    funding_admission: bool = True
    automatic_recovery: bool = True


def arm_settings(arm: str) -> ArmSettings:
    """Resolve only the reviewed component arms; baselines need their own adapters.

    Runtime quote executability and flow qualification must still be supplied by
    the causal adapter. No switch exists for accounting or liquidation safeguards.
    """
    base = ArmSettings(RoutingContext())
    if arm == "combined":
        return base
    if arm in {"spot_trend", "futures_trend", "futures_trend_long_only", "spot_grid"}:
        return replace(
            base,
            routing=RoutingContext(
                spot_trend=arm == "spot_trend",
                futures_trend=arm.startswith("futures_trend"),
                spot_grid=arm == "spot_grid",
                futures_long_only=arm == "futures_trend_long_only",
            ),
        )
    if arm == "combined_without_continuation":
        return replace(base, routing=replace(base.routing, continuation=False))
    if arm == "combined_without_full_short_qualification":
        return replace(base, routing=replace(base.routing, short_qualification=False))
    if arm == "combined_without_discretionary_trailing":
        return replace(base, trailing=False)
    if arm == "combined_without_funding_admission":
        return replace(base, funding_admission=False)
    if arm == "combined_without_recovery":
        return replace(base, automatic_recovery=False)
    if arm.startswith(("unchanged_v3_", "matched_spot_")):
        raise ValueError("unchanged baseline adapter required")
    raise ValueError("unknown component arm")
