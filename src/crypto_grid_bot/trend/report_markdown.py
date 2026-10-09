"""Readable tables for a supplied account report; no execution or verdict."""

import html
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.trend.run_report import FuturesRunReport, report_json


def _cell(value: object) -> str:
    return html.escape(str(value)).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def _number(value: Decimal | int | None, *, percent: bool = False) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, int):
        return str(value)
    if value.is_infinite():
        return "-Infinity" if value.is_signed() else "+Infinity"
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        text = format(value * 100 if percent else value, ".6f").rstrip("0").rstrip(".")
    return text + ("%" if percent else "")


def _table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows),
        ]
    )


def _utc(stamp: int) -> str:
    return datetime.fromtimestamp(stamp / 1000, UTC).isoformat()


def report_markdown(report: FuturesRunReport) -> str:
    """Render six-decimal display values; exact JSON remains the companion.

    The supplied report must come from the audited builder. This renderer does
    not certify source data, experiment completeness or historical performance.
    """
    report_json(report)  # Reject unsupported/NaN values consistently with JSON.
    status = "completed" if report.reason is None else f"invalid ({_cell(report.reason)})"
    parts = [
        "# V3 futures account report",
        f"Account status: {status}. Experiment verdict: not evaluated.",
        f"Size multiple: {report.multiple}; cost multiple: {report.cost_multiple}.",
        "Supplied account evidence only. Source provenance, complete experiment coverage "
        "and registration require separate verification. Display numbers use up to six "
        "decimal places; the JSON companion preserves exact values.",
        f"Signed reconciliation residual: `{report.reconciliation_residual}` USDT.",
        "## Performance",
    ]
    metric = report.performance
    if metric is None:
        parts.append("Completed-run metrics unavailable for this invalid account.")
    else:
        parts.append(
            _table(
                ("Metric", "Value"),
                [
                    ("Net profit (USDT)", _number(metric.net_pnl)),
                    ("Sharpe", _number(metric.sharpe)),
                    ("Trade profit factor", _number(metric.trade_profit_factor)),
                    ("Daily profit factor (diagnostic)", _number(metric.daily_profit_factor)),
                    ("Calmar", _number(metric.calmar)),
                    ("CAGR", _number(metric.cagr, percent=True)),
                    ("Maximum drawdown", _number(metric.max_drawdown, percent=True)),
                    ("Lifecycles, including censored", metric.trade_count),
                    ("Wins / losses", f"{metric.wins} / {metric.losses}"),
                    ("Win rate", _number(metric.win_rate, percent=True)),
                ],
            )
        )
    parts.append("## Monthly returns and economics")
    monthly = report.monthly
    if monthly is None:
        parts.append(
            "Monthly results unavailable as completed-run metrics; partial samples remain in JSON."
        )
    else:
        parts.append(
            _table(
                ("Month", "Return", "Start (UTC)", "End (UTC)"),
                [
                    (
                        row.month,
                        _number(row.return_fraction, percent=True),
                        _utc(row.start_ms),
                        _utc(row.end_ms),
                    )
                    for row in monthly.months
                ],
            )
        )
        hosting = (
            _number(monthly.hosting_capital_eur_proxy)
            if monthly.hosting_capital_eur_proxy is not None
            else "Not reachable"
        )
        parts.append(
            f"Mean month: {_number(monthly.mean_return, percent=True)}. "
            f"Months reaching 20%: {monthly.months_at_least_20_percent}; "
            f"30%: {monthly.months_at_least_30_percent}. "
            f"Capital proxy for €5/month hosting: {hosting} EUR. "
            "This assumes USDT returns represent EUR returns and ignores changed "
            "order-filter behavior at another account size; own-PC hosting is €0. "
            "These monthly targets are diagnostics, not promised returns."
        )
    costs = report.costs
    parts.extend(
        [
            "## Costs",
            _table(
                ("Measure", "USDT unless stated"),
                [
                    ("Fill count", costs.fill_count),
                    ("Fees", _number(costs.fees)),
                    ("Funding paid", _number(costs.funding_paid)),
                    ("Funding received", _number(costs.funding_received)),
                    ("Slippage already included in PnL", _number(costs.slippage_cost)),
                    ("Gross traded notional", _number(costs.traded_notional)),
                ],
            ),
        ]
    )
    exposure = report.exposure
    parts.extend(
        [
            "## Exposure and risk",
            _table(
                ("Measure", "Value"),
                [
                    (
                        "Observed / sampled hours",
                        f"{exposure.observed_hours} / {exposure.sampled_hours}",
                    ),
                    ("Undefined equity hours", exposure.undefined_equity_hours),
                    ("Time invested", _number(exposure.invested_fraction, percent=True)),
                    ("Mean gross exposure", _number(exposure.mean_gross_exposure, percent=True)),
                    ("Mean net exposure", _number(exposure.mean_net_exposure, percent=True)),
                    (
                        "Minimum margin ratio (1% threshold)",
                        _number(exposure.minimum_margin_ratio, percent=True),
                    ),
                    (
                        "Realized / target volatility",
                        f"{_number(report.realized_volatility, percent=True)} / "
                        f"{_number(report.target_volatility, percent=True)}",
                    ),
                    (
                        "Cap-bound / decision days",
                        f"{report.caps.bound_days} / {report.caps.decision_days}",
                    ),
                    ("Cap-bound share", _number(report.caps.bound_share, percent=True)),
                ],
            ),
        ]
    )
    episode = report.worst_drawdown
    if episode is None:
        parts.append("No drawdown episode in the supplied path.")
    else:
        parts.append(
            f"Worst drawdown: {_number(episode.fraction, percent=True)}; "
            f"peak {_utc(episode.peak_ms)} "
            f"({_cell(episode.peak_kind)}, index {episode.peak_index}); "
            f"trough {_utc(episode.trough_ms)} "
            f"({_cell(episode.trough_kind)}, index {episode.trough_index})."
        )
    parts.append("## Profit by coin and side")
    if not report.trades.by_coin_side:
        parts.append("No lifecycles in the supplied account.")
    else:
        parts.append(
            _table(
                (
                    "Coin",
                    "Side",
                    "Count",
                    "Censored",
                    "Realized USDT",
                    "Unrealized USDT",
                    "Net USDT",
                ),
                [
                    (
                        coin,
                        side,
                        row.count,
                        row.censored_count,
                        _number(row.realized),
                        _number(row.unrealized),
                        _number(row.net),
                    )
                    for (coin, side), row in report.trades.by_coin_side.items()
                ],
            )
        )
    return "\n\n".join(parts) + "\n"
