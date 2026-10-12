import functools
import json
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
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
    from crypto_grid_bot.combined.dashboard import exact_evidence, render_bundle_report

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
    # Its exact JSON is above the inline limit: only the bundle path renders it.
    with pytest.raises(ValueError, match="render_bundle_report"):
        render_report(evidence)
    html, separate = render_bundle_report(evidence)
    assert separate == exact_evidence(evidence)
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


def test_recovery_records_show_their_kind_and_what_ended_them() -> None:
    from test_combined_replay_records import REFS, SEQUENCE, trace_of

    from crypto_grid_bot.combined.replay_records import recovery_episodes

    trace = trace_of(*SEQUENCE)
    points = tuple(
        EquityPoint(o.timestamp_ms, o.snapshot.account.equity, o.id, REFS)
        for o in trace.observations
    )
    evidence = analyze(D(100), points, (), (), recovery_episodes(trace), REFS)
    html = render_report(evidence)
    section = html.split("<h2>Recovery episodes</h2>", 1)[1].split("</section>", 1)[0]
    cells = [text for text in Elements(section).text if text.strip()]
    assert cells[:7] == [
        "ID",
        "Kind",
        "Start UTC",
        "End UTC",
        "Ended by",
        "Marked change",
        "Return",
    ]
    rows = [tuple(cells[i : i + 7]) for i in range(7, 7 + 5 * 7, 7)]
    assert [(row[1], row[4], row[5]) for row in rows] == [
        ("liquidation", "liquidated", "-2.00"),
        ("cooldown", "restarted", "0.00"),
        ("episode", "episode_stop", "9.60"),
        ("cooldown", "restarted", "0.00"),
        ("episode", "normal_restored", "13.40"),
    ]


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


def section(html: str, heading: str) -> str:
    return html.split(f"<h2>{heading}</h2>", 1)[1].split("</section>", 1)[0]


def table_rows(html: str, columns: int) -> list[tuple[str, ...]]:
    """The body rows of the first table in ``html``, as cell texts."""
    table = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    cells = [text for text in Elements(table).text if text.strip()]
    return [tuple(cells[i : i + columns]) for i in range(0, len(cells), columns)]


@functools.cache
def compared():
    """Acceptance over the synthetic matrix, V2 beating the full arm on return."""
    from test_combined_experiment import V2, change, outcomes, registration

    from crypto_grid_bot.combined.experiment import SCENARIOS, cell_comparison, evaluate

    reg = registration()
    rows = change(outcomes(reg), arm=V2, final_equity=D(15000))
    result = evaluate(reg, rows)
    full = next(
        r.report_evidence.report
        for r in rows
        if (r.identity.arm, r.identity.window, r.identity.capital, r.identity.cost_multiple)
        == ("combined", "window", "research", 1)
        and r.identity.scenario == SCENARIOS[0]
    )
    cell = cell_comparison(
        reg, result, window="window", capital="research", cost_multiple=1, scenario=SCENARIOS[0]
    )
    return reg, full, cell


def comparison_rows(html: str) -> dict[str, tuple[str, ...]]:
    """The comparison table's rows by baseline: both measures of both arms, then verdicts."""
    rows = table_rows(section(html, "Cross-version comparison"), 7)
    return {row[0]: row[1:] for row in rows}


def with_row(cell, baseline, **changes):
    return replace(
        cell,
        rows=tuple(replace(r, **changes) if r.baseline == baseline else r for r in cell.rows),
    )


V3 = "unchanged_v3_selector"
UNAVAILABLE = ("Unavailable",) * 6


def test_the_comparison_lists_every_baseline_with_both_measures_and_each_verdict() -> None:
    from test_combined_experiment import V2

    reg, full, cell = compared()
    html = render_report(full, comparison=cell)
    rows = comparison_rows(html)
    assert list(rows) == list(reg.baseline_arms)
    assert rows[V3] == ("10.00%", "20.00%", "40.00%", "20.00%", "Pass", "Pass")
    assert rows[V2] == ("50.00%", "20.00%", "40.00%", "20.00%", "Fail", "Fail")
    text = " ".join(Elements(section(html, "Cross-version comparison")).text)
    assert "common hourly" in text and "research" in text and "open_low_high_close" in text


def test_the_acceptance_status_and_this_cell_s_reasons_are_shown() -> None:
    from test_combined_experiment import V2

    _, full, cell = compared()
    part = section(render_report(full, comparison=cell), "Cross-version comparison")
    text = " ".join(Elements(part).text)
    assert "Acceptance: fail" in text and "This cell: fail" in text
    (reason,) = [f for f in cell.failures if V2 in f and "full return does not" in f]
    assert reason in text
    passing = replace(cell, cell_status="pass", failures=(), incomplete_reasons=())
    text = " ".join(Elements(render_report(full, comparison=passing)).text)
    # A passing cell never reads as a passing acceptance.
    assert "Acceptance: fail" in text and "This cell: pass" in text


def test_a_registered_baseline_without_a_row_is_listed_unavailable() -> None:
    _, full, cell = compared()
    rows = comparison_rows(render_report(full, comparison=replace(cell, rows=cell.rows[1:])))
    assert rows[V3] == UNAVAILABLE and len(rows) == len(cell.baselines)


def test_a_verdict_without_all_four_measured_values_is_unavailable() -> None:
    _, full, cell = compared()
    # Acceptance's own verdicts stay on the row (both Pass): they must not show.
    stale = with_row(cell, V3, baseline_return=None, baseline_max_drawdown=None)
    assert comparison_rows(render_report(full, comparison=stale))[V3] == (
        "Unavailable",
        "Unavailable",
        "40.00%",
        "20.00%",
        "Unavailable",
        "Unavailable",
    )


def test_indeterminate_is_shown_only_at_an_actual_zero_drawdown() -> None:
    _, full, cell = compared()
    zero = with_row(cell, V3, baseline_max_drawdown=Fraction(0), beats_return_drawdown=None)
    assert comparison_rows(render_report(full, comparison=zero))[V3][4:] == (
        "Pass",
        "Indeterminate: zero drawdown",
    )
    missing = with_row(cell, V3, beats_return_drawdown=None)
    assert comparison_rows(render_report(full, comparison=missing))[V3][5] == "Unavailable"
    contradicted = with_row(cell, V3, baseline_max_drawdown=Fraction(0))
    assert comparison_rows(render_report(full, comparison=contradicted))[V3][5] == "Unavailable"


def test_a_baseline_held_frozen_at_a_native_stop_is_named() -> None:
    _, full, cell = compared()
    frozen = with_row(cell, V3, baseline_native_stop="liquidation")
    text = " ".join(Elements(render_report(full, comparison=frozen)).text)
    assert (
        "Held frozen at a native stop's equity on the schedule: " + V3 + " (liquidation)." in text
    )


def test_no_comparison_supplied_says_so() -> None:
    _, full, _ = compared()
    part = section(render_report(full), "Cross-version comparison")
    compared_part = part.split("<h3>Native baseline diagnostics</h3>", 1)[0]
    assert "Not supplied" in " ".join(Elements(compared_part).text)
    assert "<table>" not in compared_part


def test_comparison_rows_of_another_cell_are_omitted_with_a_warning() -> None:
    _, full, cell = compared()
    foreign_row = replace(cell.rows[0], scenario="open_high_low_close")
    foreign_cell = replace(
        cell,
        scenario="open_high_low_close",
        rows=tuple(replace(r, scenario="open_high_low_close") for r in cell.rows),
    )
    for comparison in (
        replace(cell, rows=(foreign_row, *cell.rows[1:])),  # a row of another cell
        foreign_cell,  # another scenario than this report's
        replace(cell, rows=(*cell.rows, cell.rows[0])),  # a baseline twice
    ):
        part = section(render_report(full, comparison=comparison), "Cross-version comparison")
        compared_part = part.split("<h3>Native baseline diagnostics</h3>", 1)[0]
        assert "Omitted comparison" in " ".join(Elements(compared_part).text)
        assert "<table>" not in compared_part


def test_a_comparison_of_another_capital_than_the_report_s_is_refused() -> None:
    _, full, cell = compared()
    research = replace(full, capital_label="research_10000_usdt")
    owner_small = replace(
        full, capital_label=f"owner_small:EUR:100:usdt_per_eur=1.1:fx_pin={'a' * 64}"
    )
    rows = comparison_rows(render_report(research, comparison=cell))
    assert len(rows) == len(cell.baselines)
    with pytest.raises(ValueError, match="capital"):
        render_report(owner_small, comparison=cell)
    small_cell = replace(
        cell,
        capital="owner_small",
        rows=tuple(replace(r, capital="owner_small") for r in cell.rows),
    )
    with pytest.raises(ValueError, match="capital"):
        render_report(research, comparison=small_cell)
    assert comparison_rows(render_report(owner_small, comparison=small_cell))


def test_native_baseline_diagnostics_are_shown_under_their_version_label() -> None:
    from crypto_grid_bot.combined.baseline_records import NativeDiagnostics

    _, full, cell = compared()
    native = (
        NativeDiagnostics(
            "unchanged_v3_selector",
            "v3-native",
            5,
            0,
            7_200_000,
            Fraction(9, 200),
            Fraction(1, 5),
            None,
        ),
        NativeDiagnostics(
            "matched_v2_grid_high_first", "<b>minute</b>", 0, None, None, None, None, "no_input"
        ),
    )
    html = render_report(full, comparison=cell, native=native)
    part = section(html, "Cross-version comparison").split(
        "<h3>Native baseline diagnostics</h3>", 1
    )[1]
    rows = table_rows(part, 8)
    assert rows[0] == (
        "unchanged_v3_selector",
        "v3-native",
        "5",
        "1970-01-01T00:00:00.000+00:00",
        "1970-01-01T02:00:00.000+00:00",
        "4.50%",
        "20.00%",
        "Completed",
    )
    assert rows[1][1] == "<b>minute</b>" and rows[1][5:] == (
        "Unavailable",
        "Unavailable",
        "no_input",
    )
    assert "&lt;b&gt;minute" in html
    text = " ".join(Elements(part).text)
    assert "never compared" in text


def test_bad_periods_list_the_three_deepest_drawdown_episodes() -> None:
    from test_combined_report import episode_report

    html = render_report(episode_report())
    part = section(html, "Bad periods")
    episodes = part.split("<h3>Largest drawdown episodes</h3>", 1)[1]
    rows = table_rows(episodes, 6)
    assert [(row[1], row[3], row[4]) for row in rows] == [
        ("120.00", "90.00", "25.00%"),
        ("130.00", "104.00", "20.00%"),
        ("125.00", "115.00", "8.00%"),
    ]
    assert rows[1][5].startswith("Not recovered by the window end")
    assert "<h3>Unfavorable intervals</h3>" in part


def test_excursion_and_profit_surrendered_name_the_marks_they_use() -> None:
    text = " ".join(" ".join(Elements(render_report(report())).text).split())
    assert "Profit surrendered" in text
    assert "intrabar" in text and "valuation marks, not observed ticks" in text


def test_a_large_report_is_saved_as_the_bundle_s_report_json(tmp_path) -> None:
    import hashlib

    from test_combined_artifacts import journal

    from crypto_grid_bot.combined.artifacts import read_bundle, write_bundle
    from crypto_grid_bot.combined.dashboard import exact_evidence, render_bundle_report

    points = tuple(
        EquityPoint(index * 3_600_000, D(100) + D(index % 7), f"mark-{index}", ("synthetic",))
        for index in range(6000)
    )
    evidence = analyze(D(100), points, (), (), (), ("synthetic",))
    html, raw = render_bundle_report(evidence)
    assert raw == exact_evidence(evidence) and len(raw.encode()) > 1_000_000
    digest = hashlib.sha256(raw.encode()).hexdigest()
    parsed = Elements(html)
    assert any(attrs.get("href") == "report.json" for _, attrs in parsed.elements)
    assert digest in " ".join(parsed.text)
    # The page names report.json: it is never saved without that exact file.
    with pytest.raises(ValueError, match="report.json"):
        write_bundle(tmp_path, "unbound", journal(), {}, html)
    with pytest.raises(ValueError, match="report.json"):
        write_bundle(tmp_path, "other", journal(), {}, html, report_json=exact_evidence(report()))
    receipt = write_bundle(tmp_path, "large", journal(), {}, html, report_json=raw)
    assert [path.name for path in tmp_path.iterdir()] == ["large"]
    bundle = read_bundle(receipt.directory, expected_receipt_sha256=receipt.receipt_sha256)
    assert bundle.report_json == raw and bundle.report_html == html
    assert ("report.json", digest) in receipt.file_hashes
    assert len(json.loads(bundle.report_json)["report"]["equity_points"]) == 6000
    # A report small enough to embed needs no separate file.
    small_html, small_raw = render_bundle_report(report())
    assert small_raw is None and small_html == render_report(report())
