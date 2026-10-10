"""Offline, script-free HTML/SVG renderer over immutable report evidence."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from html import escape
from urllib.parse import quote, unquote, urlsplit

from crypto_grid_bot.combined.report import DimensionTotal, EquityPoint, Report

_CSS = """
:root{color-scheme:dark;
--bg:#0b1220;
--panel:#121d2d;
--line:#293a50;
--text:#e6eef8;
--muted:#a3b3c8;
--accent:#70e3c3;
--warn:#ffce85}

*{box-sizing:border-box}
body{margin:0;
background:var(--bg);
color:var(--text);
font:15px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}

a{color:var(--accent);
overflow-wrap:anywhere}
main{max-width:1440px;
padding:40px 28px 70px;
margin:auto}
header{border-bottom:1px solid var(--line);
padding-bottom:28px;
margin-bottom:28px}

h1{font-size:clamp(28px,4vw,44px);
line-height:1.15;
letter-spacing:-.035em;
margin:16px 0}
h2{font-size:20px;
margin:0 0 16px}
h3{font-size:16px;
margin:0 0 12px}
p{margin:8px 0}
.eyebrow{color:var(--accent);
font-size:12px;
font-weight:750;
letter-spacing:.13em;
text-transform:uppercase}
.muted,small{color:var(--muted)}

.badge{display:inline-block;
border:1px solid #4d6555;
background:#17352e;
color:var(--accent);
border-radius:30px;
padding:5px 12px;
font-size:12px;
font-weight:700}
.warning{color:var(--warn);
background:#33271c;
border-color:#6a4a23}
.note{padding:12px 16px;
border-left:3px solid var(--accent);
background:#152638;
margin:16px 0}
.warning-text{color:var(--warn)}

.grid{display:grid;
grid-template-columns:repeat(2,minmax(0,1fr));
gap:20px}
.cards{display:grid;
grid-template-columns:repeat(4,minmax(0,1fr));
gap:14px;
margin:22px 0}
.panel,.metric{min-width:0;
background:var(--panel);
border:1px solid var(--line);
border-radius:14px;
padding:22px}
.metric{padding:18px}
.metric strong{display:block;
font-size:26px;
line-height:1.25;
margin-top:7px;
overflow-wrap:anywhere}
.metric span{font-size:12px;
color:var(--muted);
text-transform:uppercase;
letter-spacing:.06em}
section{margin-top:22px}
.wide{grid-column:1/-1}

svg{width:100%;
height:auto;
display:block;
overflow:visible}
.chart text{font-family:system-ui,sans-serif;
font-size:11px;
fill:var(--muted)}
.legend{display:flex;
flex-wrap:wrap;
gap:16px;
font-size:12px;
color:var(--muted);
margin-top:10px}
.dot{display:inline-block;
width:9px;
height:9px;
border-radius:50%;
margin-right:6px}
.table-scroll{overflow-x:auto;
max-width:100%;
border-radius:6px}
table{border-collapse:collapse;
width:100%;
font-size:13px}
th,td{padding:11px 12px;
border-bottom:1px solid var(--line);
text-align:left;
vertical-align:top}
th{color:var(--muted);
font-size:11px;
text-transform:uppercase;
letter-spacing:.04em;
white-space:nowrap}
td{font-variant-numeric:tabular-nums;
overflow-wrap:anywhere}
tbody tr:hover{background:#1b2b40}
summary{cursor:pointer;
font-weight:650;
padding:7px 0}
details+details{margin-top:12px}
pre{overflow:auto;
max-height:440px;
background:#09101b;
padding:18px;
border-radius:8px;
font-size:12px;
white-space:pre-wrap;
overflow-wrap:anywhere}
code{font-family:ui-monospace,Consolas,monospace}
ul{padding-left:20px}
.empty{color:var(--muted);
padding:18px 0}
.download{display:inline-block;
padding:8px 14px;
border:1px solid var(--line);
border-radius:8px;
text-decoration:none;
margin:10px 0}
.footer{border-top:1px solid var(--line);
padding-top:18px;
margin-top:30px;
font-size:12px;
color:var(--muted)}

@media(max-width:900px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}
.grid{grid-template-columns:1fr}
}

@media(max-width:520px){main{padding:22px 14px 40px}
.panel,.metric{padding:16px}
.cards{gap:10px}
.metric strong{font-size:22px}
th,td{padding:9px 8px}
header{padding-bottom:20px}
}

"""


def _text(value: object) -> str:
    return escape("Unknown" if value is None else str(value), quote=True)


def _decimal(value: Fraction) -> Decimal:
    with localcontext(Context(prec=60)):
        return Decimal(value.numerator) / Decimal(value.denominator)


def _number(value: Decimal | None, *, percent: bool = False) -> str:
    if value is None:
        return "Unavailable"
    scaled = _decimal(Fraction(value) * (100 if percent else 1))
    return f"{scaled:,.2f}" + ("%" if percent else "")


def _time(timestamp: int | None) -> str:
    if timestamp is None:
        return "Open / unknown"
    try:
        return datetime.fromtimestamp(timestamp / 1000, UTC).isoformat(timespec="milliseconds")
    except (OverflowError, OSError, ValueError):
        return f"{timestamp} ms since Unix epoch"


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    if not rows:
        return '<p class="empty">Not supplied</p>'
    head = "".join(f'<th scope="col">{_text(value)}</th>' for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_text(value)}</td>" for value in row) + "</tr>" for row in rows
    )
    return (
        f'<div class="table-scroll"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _attribution(title: str, rows: tuple[DimensionTotal, ...]) -> str:
    body = _table(
        ("Category", "Net PnL", "Gross PnL", "Fees", "Funding ±", "Turnover"),
        [
            (
                row.key,
                _number(row.net_pnl),
                _number(row.gross_pnl),
                _number(row.fees),
                _number(row.funding_signed),
                _number(row.turnover),
            )
            for row in rows
        ],
    )
    return f'<section class="panel"><h2>{_text(title)}</h2>{body}</section>'


def _safe_reference(reference: str) -> bool:
    decoded = unquote(reference)
    if (
        reference != reference.strip()
        or decoded != decoded.strip()
        or "\\" in decoded
        or any(ord(char) < 32 for char in decoded)
        or decoded.startswith("//")
    ):
        return False
    try:
        parsed = urlsplit(decoded)
        if parsed.scheme:
            return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
        return not parsed.netloc
    except ValueError:
        return False


def _chart(
    series: list[tuple[str, list[tuple[int, Fraction]], str, str]],
    title: str,
    *,
    percent: bool = False,
) -> str:
    points = [point for _, values, _, _ in series for point in values]
    if not points:
        return '<p class="empty">Equity unavailable — no curve invented.</p>'
    x0, x1 = min(t for t, _ in points), max(t for t, _ in points)
    low, high = min(value for _, value in points), max(value for _, value in points)
    if low == high:
        low, high = low - 1, high + 1
    span = high - low
    lines = []
    for index in range(5):
        value = low + span * Fraction(index, 4)
        y = 240 - 210 * index / 4
        label = _number(_decimal(value), percent=percent)
        lines.append(
            f'<line x1="78" y1="{y}" x2="975" y2="{y}" stroke="#293a50"/>'
            f'<text x="68" y="{y + 4}" text-anchor="end">{_text(label)}</text>'
        )
    for name, values, color, key in series:
        coords = " ".join(
            f"{78 + 897 * float(Fraction(t - x0, x1 - x0)) if x1 != x0 else 526:.2f},"
            f"{240 - 210 * float((value - low) / span):.2f}"
            for t, value in values
        )
        dash = ' stroke-dasharray="5 5"' if key == "lifetime-peak" else ""
        lines.append(
            f'<polyline data-series="{key}" points="{coords}" fill="none" '
            f'stroke="{color}" stroke-width="2.5"{dash}><title>{_text(name)}</title></polyline>'
        )
    lines.append(
        f'<text x="78" y="270">{_text(_time(x0))}</text>'
        f'<text x="975" y="270" text-anchor="end">{_text(_time(x1))}</text>'
    )
    legend = "".join(
        f'<span><i class="dot" style="background:{color}"></i>{_text(name)}</span>'
        for name, _, color, _ in series
    )
    return (
        f'<svg class="chart" viewBox="0 0 1000 285" role="img" aria-label="{_text(title)}">'
        f'<title>{_text(title)}</title>{"".join(lines)}</svg><div class="legend">{legend}</div>'
    )


def render_report(
    report: Report,
    title: str = "Combined strategy evidence",
    benchmarks: Mapping[str, tuple[EquityPoint, ...]] | None = None,
    *,
    synthetic: bool = True,
) -> str:
    """Render exact evidence with rounded display only; make no run/edge claim.

    Provided comparison curves require identical timestamps and an initial mark
    equal to the report's starting capital. This does not verify data, fees, code
    or other comparability. Explicit marks remain the caller's evidence.
    """
    if type(synthetic) is not bool:
        raise ValueError("synthetic must be an explicit Boolean")
    supplied = dict(benchmarks or {})
    equity = [(point.timestamp_ms, Fraction(point.equity)) for point in report.equity_points]
    peak = Fraction(report.initial_equity)
    peaks, drawdowns = [], []
    for timestamp, value in equity:
        peak = max(peak, value)
        peaks.append((timestamp, peak))
        drawdowns.append((timestamp, (peak - value) / peak))
    series = [
        ("Combined equity", equity, "#70e3c3", "equity"),
        ("Lifetime peak (never reset)", peaks, "#a9b8ce", "lifetime-peak"),
    ]
    warnings = []
    colors = ("#83b7ff", "#dbacff", "#ffc783", "#f294bc")
    timestamps = tuple(point.timestamp_ms for point in report.equity_points)
    for index, (name, values) in enumerate(supplied.items()):
        valid = (
            bool(values)
            and bool(timestamps)
            and tuple(point.timestamp_ms for point in values) == timestamps
            and all(
                type(point.timestamp_ms) is int
                and isinstance(point.equity, Decimal)
                and point.equity.is_finite()
                for point in values
            )
            and values[0].equity == report.initial_equity
        )
        if valid:
            series.append(
                (
                    str(name),
                    [(point.timestamp_ms, Fraction(point.equity)) for point in values],
                    colors[index % len(colors)],
                    f"benchmark-{index}",
                )
            )
        else:
            warnings.append(
                f"Omitted comparison: {name} — timestamps or initial capital do not match, "
                "or values are invalid."
            )
    payload = {
        "synthetic": synthetic,
        "report": asdict(report),
        "provided_benchmarks": {
            str(name): [asdict(point) for point in values] for name, values in supplied.items()
        },
    }
    raw = json.dumps(payload, default=str, ensure_ascii=False, indent=2)
    download = "data:application/json;charset=utf-8," + quote(raw, safe="")
    badge = "Synthetic demonstration — not market performance" if synthetic else "Evidence review"
    status = "Structurally complete" if report.complete else "Incomplete evidence"
    status_class = "badge" if report.complete else "badge warning"
    cards = "".join(
        f'<div class="metric"><span>{_text(label)}</span><strong>{_text(value)}</strong></div>'
        for label, value in (
            ("Final equity · USDT", _number(report.final_equity)),
            ("Net return", _number(report.net_return, percent=True)),
            ("Lifetime drawdown", _number(report.max_drawdown, percent=True)),
            ("Net profit · USDT", _number(report.net_profit)),
        )
    )
    warning_html = "".join(f'<p class="warning-text">{_text(warning)}</p>' for warning in warnings)
    issues = "".join(f"<li>{_text(issue)}</li>" for issue in report.issues)
    unknown = ", ".join(report.unknown_fields) or "None reported"
    sources = []
    for reference in report.source_refs:
        label = _text(reference)
        sources.append(
            f'<li><a href="{_text(reference)}" rel="noopener noreferrer">{label}</a></li>'
            if _safe_reference(reference)
            else f"<li><code>{label}</code> (text only)</li>"
        )
    source_html = (
        "<ul>" + "".join(sources) + "</ul>" if sources else '<p class="empty">Not supplied</p>'
    )
    costs = _table(
        ("Measure", "USDT / count"),
        (
            ("Fees", _number(report.fees)),
            ("Funding · signed wallet change", _number(report.funding_signed)),
            ("Turnover · absolute traded notional", _number(report.turnover)),
            ("Closed lifecycles", report.closed_count),
            ("Open marked lifecycles", report.open_marked_count),
            (
                "Equity reconciliation residual",
                str(report.reconciliation_residual)
                if report.reconciliation_residual is not None
                else "Unavailable",
            ),
        ),
    )
    recovery = _table(
        ("Start UTC", "End UTC", "Marked change", "Return"),
        [
            (
                _time(change.episode.start_ms),
                _time(change.episode.end_ms),
                _number(change.marked_change),
                _number(change.return_fraction, percent=True),
            )
            for change in report.recovery_changes
        ],
    )
    opportunities = _table(
        ("Asset / direction", "Structure", "Start UTC", "Stages", "Reasons", "Entry delay"),
        [
            (
                f"{group.asset} / {group.direction}",
                group.structure,
                _time(group.start_ms),
                " → ".join(group.stages),
                ", ".join(group.reasons) or "None recorded",
                f"{group.entry_delay_ms / 1000:g} seconds"
                if group.entry_delay_ms is not None
                else "Unknown",
            )
            for group in report.opportunity_episodes
        ],
    )
    bad = _table(
        ("From UTC", "To UTC", "Net change", "Return"),
        [
            (
                _time(interval.start_ms),
                _time(interval.end_ms),
                _number(interval.net_change),
                _number(interval.return_fraction, percent=True),
            )
            for interval in report.bad_intervals
        ],
    )
    lifecycles = _table(
        ("ID / asset", "Status", "Exit reason", "Gross MFE", "Supplied giveback"),
        [
            (
                f"{row.id} / {row.asset}",
                row.status,
                row.exit_reason,
                _number(row.mfe),
                _number(row.giveback),
            )
            for row in report.contributions
        ],
    )
    attributions = "".join(
        _attribution(name, rows)
        for name, rows in (
            ("Strategy attribution", report.by_strategy),
            ("Asset attribution", report.by_asset),
            ("Direction attribution", report.by_direction),
            ("Regime attribution", report.by_regime),
        )
    )
    equity_chart = _chart(series, "Equity, lifetime peak and supplied comparisons")
    drawdown_chart = _chart(
        [("Drawdown from lifetime peak", drawdowns, "#ffb69b", "drawdown")],
        "Lifetime drawdown, with no recovery reset",
        percent=True,
    )
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';
script-src 'none'; base-uri 'none'; form-action 'none'">
<title>{_text(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<header>
<div class="eyebrow">Combined system / research evidence</div>
<h1>{_text(title)}</h1>
<span class="badge warning">{_text(badge)}</span> <span class="{status_class}">{status}</span>
<p class="muted">One account, visible costs, preserved losses.
Source validation is not implied.</p>
</header>
{cards}<section class="panel">
<h2>Equity and original lifetime peak</h2>
{equity_chart}{warning_html}
<p class="muted">Provided comparison curves only. Matching times and first capital do not
establish full comparability. No benchmark is invented.</p>
</section>
<section class="panel">
<h2>Lifetime drawdown</h2>{drawdown_chart}
<p class="muted">Measured from the original, non-resetting high-water mark. Recovery does not
erase an earlier loss.</p>
</section>
<div class="grid">{attributions}<section class="panel">
<h2>Costs and participation</h2>{costs}
<p class="muted">Open marked lifecycles include unrealized PnL; they are not closed trades.</p>
</section>
<section class="panel">
<h2>Winner concentration</h2>
<p style="font-size:30px">{_number(report.largest_positive_asset_share, percent=True)}</p>
<p class="muted">Largest positive asset contribution divided by all positive asset contributions.
Losing assets remain in the attribution tables.</p>
<h3>Metadata availability</h3>
<p>Unknown: {_text(unknown)}</p>
<p class="muted">MFE supplied for {report.mfe_available} lifecycles; giveback supplied for
{report.giveback_available}. Missing values are not inferred.</p>
</section>
</div>
<section class="panel">
<h2>Recovery episodes</h2>{recovery}<p class="muted">Observed end-minus-start marked equity,
assuming no external cash transfers. This is not a causal benefit estimate.</p>
</section>
<section class="panel">
<h2>Opportunities and entry delays</h2>
<p class="muted">{len(report.opportunity_episodes)} distinct observed episodes; observations
separated by more than {report.observation_gap_ms / 1000:g} seconds or changed direction/structure
start a new episode. Hourly samples are not independent
opportunities.</p>{opportunities}</section>
<section class="panel">
<h2>Unfavorable intervals</h2>
<p class="muted">Adjacent observed equity marks, not calendar-period returns or independent
trials.</p>{bad}</section>
<section class="panel">
<details>
<summary>Lifecycle exits, excursions and giveback</summary>{lifecycles}</details>
</section>
<section class="panel">
<h2>Source references and completeness</h2>
<p>{status}. References are not fetched or hash-verified by this renderer.</p>
<ul>{issues}</ul>{source_html}</section>
<section class="panel">
<details>
<summary>Exact evidence</summary>
<p class="muted">Display numbers are rounded only. Decimal values below and in the JSON download
retain their exact supplied text.</p>
<a class="download" download="combined-evidence.json" href="{download}">Download exact JSON</a>
<pre>
<code>{_text(raw)}</code>
</pre>
</details>
</section>
<p class="footer">Offline report · no scripts, remote assets or telemetry · historical evidence
is not live profit or execution authorization.</p>
</main>
</body>
</html>'''
