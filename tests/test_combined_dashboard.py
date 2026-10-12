import json
from dataclasses import replace
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import unquote

import pytest
from test_combined_report import contributions, curve

from crypto_grid_bot.combined.dashboard import render_report
from crypto_grid_bot.combined.report import EquityPoint, analyze

D = Decimal


class Elements(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__()
        self.elements = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def report():
    return analyze(D(100), curve(), contributions(), (), (), ("https://example.com/evidence",))


def test_offline_document_contains_required_data_and_synthetic_label() -> None:
    parsed = Elements(render_report(report(), "Test report"))
    text = " ".join(parsed.text)
    assert "Synthetic demonstration" in text
    for expected in (
        "Lifetime drawdown",
        "Funding",
        "Turnover",
        "Strategy",
        "Asset",
        "Direction",
        "Regime",
        "Recovery",
        "Opportunities",
        "Unfavorable intervals",
        "Winner concentration",
        "Source references",
        "Exact evidence",
    ):
        assert expected in text
    assert not any(tag == "script" for tag, _ in parsed.elements)
    assert not any("src" in attrs for _, attrs in parsed.elements)
    assert any(tag == "meta" and attrs.get("name") == "viewport" for tag, attrs in parsed.elements)
    assert any(tag == "svg" and attrs.get("viewbox") for tag, attrs in parsed.elements)
    assert any(tag == "details" for tag, _ in parsed.elements)
    assert "url(" not in render_report(report()).lower()


def test_all_untrusted_text_is_literal_and_unsafe_source_links_never_executable() -> None:
    attack = "<img src=x onerror=alert(1)>"
    row = replace(contributions()[0], strategy=attack, asset=attack, exit_reason=attack)
    source = (
        "javascript:alert(1)",
        "//evil.test/x",
        "data:text/html,bad",
        "\\evil.test\\x",
        "%6aavascript%3Aalert(1)",
        "docs/report.md",
        'https://example.com/?x="<bad>',
    )
    evidence = analyze(D(100), curve(), (row, contributions()[1]), (), (), source)
    document = render_report(evidence, attack, {attack: curve()})
    parsed = Elements(document)
    assert not any(tag in {"img", "script"} for tag, _ in parsed.elements)
    assert all(not any(key.startswith("on") for key in attrs) for _, attrs in parsed.elements)
    hrefs = [attrs["href"] for _, attrs in parsed.elements if "href" in attrs]
    assert "docs/report.md" in hrefs
    assert not any(href.startswith(("javascript:", "//", "\\", "%6a")) for href in hrefs)
    assert attack in " ".join(parsed.text)
    assert "&lt;img" in document


def test_missing_equity_and_sources_are_visible_without_fabricated_curves() -> None:
    missing = analyze(D(100), (), (), (), (), ())
    parsed = Elements(render_report(missing))
    text = " ".join(parsed.text)
    assert "Incomplete" in text and "Equity unavailable" in text
    assert "missing_source_refs" in text and "missing_equity_observations" in text
    assert not any(tag == "polyline" for tag, _ in parsed.elements)
    assert "Not supplied" in text


def test_benchmark_requires_same_timestamps_and_initial_capital() -> None:
    valid = curve()
    wrong_times = (EquityPoint(0, D(100)), EquityPoint(3, D(105)))
    wrong_capital = (EquityPoint(0, D(200)), *curve()[1:])
    document = render_report(
        report(),
        benchmarks={
            "Matched": valid,
            "Different times": wrong_times,
            "Different capital": wrong_capital,
        },
    )
    text = " ".join(Elements(document).text)
    assert "Matched" in text
    assert "Omitted comparison: Different times" in text
    assert "Omitted comparison: Different capital" in text
    assert "comparability" in text


def test_exact_decimal_export_is_not_rounded_to_display_precision() -> None:
    amount = D("105.12345678901234567890123456789")
    points = (*curve()[:-1], EquityPoint(2, amount))
    evidence = analyze(D(100), points, contributions(), (), (), ("pin",))
    parsed = Elements(render_report(evidence))
    link = next(
        attrs["href"] for tag, attrs in parsed.elements if tag == "a" and "download" in attrs
    )
    raw = json.loads(unquote(link.split(",", 1)[1]))
    assert raw["report"]["final_equity"] == str(amount)
    assert raw["synthetic"] is True


def test_original_lifetime_peak_is_shown_and_drawdown_not_reset() -> None:
    evidence = analyze(
        D(100),
        (EquityPoint(0, D(100)), EquityPoint(1, D(200)), EquityPoint(2, D(100))),
        (),
        (),
        (),
        ("pin",),
    )
    parsed = Elements(render_report(evidence))
    assert any(
        tag == "polyline" and attrs.get("data-series") == "lifetime-peak"
        for tag, attrs in parsed.elements
    )
    assert "50.00%" in " ".join(parsed.text)
    assert any(
        tag == "polyline" and attrs.get("data-series") == "drawdown"
        for tag, attrs in parsed.elements
    )


def test_responsive_tables_and_accessible_charts_have_bounded_containers() -> None:
    parsed = Elements(render_report(report()))
    assert all(
        attrs.get("role") == "img" and attrs.get("aria-label")
        for tag, attrs in parsed.elements
        if tag == "svg"
    )
    assert any(attrs.get("class") == "table-scroll" for _, attrs in parsed.elements)
    text = " ".join(parsed.text)
    assert "@media" in text and "min-width:0" in text.replace(" ", "")


def test_synthetic_flag_requires_real_boolean_and_false_does_not_claim_live_results() -> None:
    with pytest.raises(ValueError):
        render_report(report(), synthetic="false")
    text = " ".join(Elements(render_report(report(), synthetic=False)).text)
    assert "Evidence review" in text
    assert "Source validation is not implied" in text


def test_required_metrics_and_sampling_definitions_are_visible_even_when_unknown():
    html = render_report(report())
    text = " ".join(" ".join(Elements(html).text).split())
    for label in (
        "CAGR",
        "Return / drawdown",
        "Sharpe",
        "Capital utilization",
        "sample standard deviation",
        "365.25",
        "daily_samples_unavailable",
        "utilization_unavailable",
        "Required report metrics incomplete",
    ):
        assert label in text
    assert "Structurally complete</span>" not in html


def test_per_record_provenance_is_visible_linked_and_preserved_in_download():
    row = replace(
        contributions()[0], source_refs=("https://example.com/trades#closed", "javascript:bad")
    )
    evidence = analyze(D(100), curve(), (row, contributions()[1]), (), (), ("global",))
    html = render_report(evidence)
    parsed = Elements(html)
    assert "Record provenance" in " ".join(parsed.text)
    assert any(
        attrs.get("href") == "https://example.com/trades#closed" for _, attrs in parsed.elements
    )
    assert not any(attrs.get("href") == "javascript:bad" for _, attrs in parsed.elements)
    download = next(attrs["href"] for _, attrs in parsed.elements if attrs.get("download"))
    data = json.loads(unquote(download.split(",", 1)[1]))
    assert data["report"]["contributions"][0]["source_refs"] == list(row.source_refs)
    assert data["report"]["equity_points"][0]["id"] == "mark-0"


def test_capital_observation_phase_and_interval_link_are_visible_and_exported():
    from test_combined_report import capital_fixture, capital_report

    points, observation, interval, later, second, terminal = capital_fixture()
    evidence = capital_report(points, (observation, later, terminal), (interval, second))
    parsed = Elements(render_report(evidence))
    text = " ".join(parsed.text)
    assert "Capital observations" in text and observation.phase_id in text
    assert "equity-0" in text and "capital-0" in text
    download = next(attrs["href"] for _, attrs in parsed.elements if attrs.get("download"))
    data = json.loads(unquote(download.split(",", 1)[1]))["report"]
    assert data["capital_observations"][0]["equity_observation_id"] == "equity-0"
    assert data["utilization"][0]["observation_id"] == "capital-0"


def test_a_long_run_page_stays_bounded_and_keeps_extremes() -> None:
    from crypto_grid_bot.combined.dashboard import exact_evidence

    # 6,000 marks, oscillating with one deep trough: far beyond every display bound.
    points = tuple(
        EquityPoint(
            index * 3_600_000,
            D(50) if index == 4321 else D(100) + D(index % 7) - D(3),
            f"mark-{index}",
            ("synthetic",),
        )
        for index in range(6000)
    )
    points = (EquityPoint(0, D(100), "mark-0", ("synthetic",)), *points[1:])
    evidence = analyze(D(100), points, (), (), (), ("synthetic",))
    html = render_report(evidence)
    parsed = Elements(html)
    text = " ".join(parsed.text)
    assert len(html) < 1_000_000
    assert "Display shows" in text and "extremes are kept" in text
    # The trough's drawdown (53 / 103) survives sampling as the chart's top label.
    assert f"{evidence.max_drawdown * 100:.2f}%" == "51.46%"
    drawdown_svg = html.split('aria-label="Lifetime drawdown')[1].split("</svg>")[0]
    assert "51.46%" in drawdown_svg
    assert "unfavorable intervals by net change" in text
    assert "Summarized per record type" in text
    assert "inline limit, so it is not embedded" in text
    assert not any(attrs.get("download") for _, attrs in parsed.elements)
    exact = json.loads(exact_evidence(evidence))
    assert len(exact["report"]["equity_points"]) == 6000
    assert min(Decimal(p["equity"]) for p in exact["report"]["equity_points"]) == 50


def test_benchmark_is_compared_on_the_approved_hourly_schedule() -> None:
    import combined_market_fixtures as fx

    from crypto_grid_bot.combined.replay_records import strategy_report
    from crypto_grid_bot.combined.strategy_replay import replay_strategy

    trace = replay_strategy(fx.run("spot_trend", 2), (fx.market("BTCUSDT", fx.uptrend, 2),))
    evidence = strategy_report(trace, adapter_pin="0" * 64)
    schedule = [b.timestamp_ms for b in evidence.policy_evidence.boundaries]
    assert len(evidence.equity_points) > len(schedule)  # several native marks per hour
    flat = tuple(EquityPoint(t, D(10000), f"hold-{t}", ("synthetic",)) for t in schedule)
    html = render_report(evidence, benchmarks={"Synthetic flat hold": flat})
    parsed = Elements(html)
    assert any(attrs.get("data-series") == "benchmark-0" for _, attrs in parsed.elements)
    assert "Omitted comparison" not in " ".join(parsed.text)
    mismatched = flat[:-1]
    assert "Omitted comparison" in render_report(evidence, benchmarks={"short": mismatched})


def disclosure_section(html: str) -> str:
    return html.split("<h2>Disclosures</h2>", 1)[1].split("</section>", 1)[0]


def test_disclosures_and_the_capital_label_are_rendered_escaped() -> None:
    attack = "<img src=x onerror=alert(1)>"
    label = "owner_small:EUR:100:usdt_per_eur=1.08:fx_pin=" + "a" * 64
    evidence = analyze(
        D(108),
        curve(),
        contributions(),
        (),
        (),
        ("pin",),
        disclosures=("data_gap:BTCUSDT:spot: hours=1", attack),
        capital_label=label,
    )
    html = render_report(evidence)
    parsed = Elements(html)
    section = " ".join(Elements(disclosure_section(html)).text)
    assert "data_gap:BTCUSDT:spot: hours=1" in section and attack in section
    assert label in section
    header = " ".join(Elements(html.split("</header>", 1)[0]).text)
    assert label in header
    assert not any(tag == "img" for tag, _ in parsed.elements)
    assert "&lt;img" in html
    download = next(attrs["href"] for _, attrs in parsed.elements if attrs.get("download"))
    data = json.loads(unquote(download.split(",", 1)[1]))["report"]
    assert data["disclosures"] == [*evidence.disclosures]
    assert data["capital_label"] == label


def test_a_report_without_disclosures_says_so() -> None:
    section = " ".join(Elements(disclosure_section(render_report(report()))).text)
    assert "None recorded" in section and "not stated" in section
