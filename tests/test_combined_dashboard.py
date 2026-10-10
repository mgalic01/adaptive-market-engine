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
