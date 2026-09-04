from diy_transit_analysis.report import html_charts


def test_nice_ticks_never_produces_duplicate_labels():
    for max_value in [0, 1, 2, 3, 5, 7, 9, 42, 100, 4953]:
        ticks = html_charts.nice_ticks(max_value)
        assert len(ticks) == len(set(ticks))
        assert ticks[-1] >= max_value


def test_thin_indices_always_includes_first_and_last():
    for n in [1, 2, 3, 8, 9, 50]:
        indices = html_charts.thin_indices(n)
        assert indices[0] == 0
        assert indices[-1] == n - 1
        assert indices == sorted(set(indices))


def test_area_chart_svg_renders_a_point_per_input():
    svg = html_charts.area_chart_svg(chart_id="test-chart", points=[("a", 1), ("b", 5), ("c", 3)])
    assert svg.count("hit-point") == 3
    assert 'id="test-chart"' in svg


def test_data_table_escapes_values():
    table = html_charts.data_table(["Col"], [("<script>",)])
    assert "<script>" not in table
    assert "&lt;script&gt;" in table


def test_percent_formats_or_reports_na():
    assert html_charts.percent(None) == "n/a"
    assert html_charts.percent(12.345) == "12.3%"
