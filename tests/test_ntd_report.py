from pathlib import Path

import pandas as pd
import pytest

from diy_transit_analysis.config import NtdTimeSeriesSource
from diy_transit_analysis.ntd.timeseries import NtdDataError, fetched_path
from diy_transit_analysis.report import ntd


def _sources() -> list[NtdTimeSeriesSource]:
    return [
        NtdTimeSeriesSource(
            name="Unlinked Passenger Trips", category="service", product_url="https://example.org/data-product/upt"
        ),
        NtdTimeSeriesSource(
            name="Vehicle Revenue Hours", category="service", product_url="https://example.org/data-product/vrh"
        ),
        NtdTimeSeriesSource(
            name="Operating Expenses",
            category="expenditure",
            product_url="https://example.org/data-product/opex",
        ),
        NtdTimeSeriesSource(
            name="Total Funding", category="funding", product_url="https://example.org/data-product/funding"
        ),
        NtdTimeSeriesSource(
            name="Total Fleet Vehicles", category="asset", product_url="https://example.org/data-product/fleet"
        ),
    ]


def _write(source: NtdTimeSeriesSource, raw_dir: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_excel(fetched_path(source, raw_dir), index=False)


def test_build_ntd_report_data_groups_by_category_and_computes_year_range(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sources = _sources()

    _write(sources[0], raw_dir, [{"NTD ID": 90019, "2020": 100.0, "2021": 120.0}])
    _write(sources[1], raw_dir, [{"NTD ID": 90019, "2020": 50.0, "2021": 55.0}])
    _write(sources[2], raw_dir, [{"NTD ID": 90019, "2019": 900.0}])
    # funding.csv exists but has no row for 90019
    _write(sources[3], raw_dir, [{"NTD ID": 55555, "2020": 1.0}])
    # fleet.csv (sources[4]) is never fetched — no file at all

    data = ntd.build_ntd_report_data(sources, raw_dir, agency="SacRT", ntd_id="90019")

    assert data.agency == "SacRT"
    assert data.ntd_id == "90019"
    assert data.min_year == 2019
    assert data.max_year == 2021
    assert [c.name for c in data.charts_by_category["service"]] == [
        "Unlinked Passenger Trips",
        "Vehicle Revenue Hours",
    ]
    assert data.charts_by_category["service"][0].series == [(2020, 100.0), (2021, 120.0)]
    assert data.charts_by_category["expenditure"][0].series == [(2019, 900.0)]

    funding_chart = data.charts_by_category["funding"][0]
    assert funding_chart.series == []
    assert "no data for NTD ID 90019" in funding_chart.note

    asset_chart = data.charts_by_category["asset"][0]
    assert asset_chart.series == []
    assert "not yet fetched" in asset_chart.note


def test_build_ntd_report_data_all_empty_yields_none_year_range(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sources = [_sources()[0]]
    _write(sources[0], raw_dir, [{"NTD ID": 12345, "2020": 1.0}])

    data = ntd.build_ntd_report_data(sources, raw_dir, agency="SacRT", ntd_id="90019")

    assert data.min_year is None
    assert data.max_year is None


def test_build_ntd_report_data_raises_ntddataerror_for_unparseable_file(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sources = [_sources()[0]]
    pd.DataFrame([{"Agency": "SacRT", "2020": 1.0}]).to_excel(fetched_path(sources[0], raw_dir), index=False)

    with pytest.raises(NtdDataError):
        ntd.build_ntd_report_data(sources, raw_dir, agency="SacRT", ntd_id="90019")


def test_render_html_includes_sections_charts_and_notes(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sources = _sources()
    _write(sources[0], raw_dir, [{"NTD ID": 90019, "2020": 100.0}])
    _write(sources[1], raw_dir, [{"NTD ID": 90019, "2020": 50.0}])
    _write(sources[2], raw_dir, [{"NTD ID": 90019, "2020": 900.0}])
    _write(sources[3], raw_dir, [{"NTD ID": 55555, "2020": 1.0}])

    data = ntd.build_ntd_report_data(sources, raw_dir, agency="SacRT", ntd_id="90019")
    html = ntd.render_html(data)

    assert "<!doctype html>" in html
    assert "SacRT" in html
    assert "90019" in html
    assert "Unlinked Passenger Trips" in html
    assert "Vehicle Revenue Hours" in html
    assert "Operating Expenses" in html
    assert "no data for NTD ID 90019" in html
    assert "not yet fetched" in html
    # Asset section has zero configured entries with data written -> chart still renders as "not fetched"
    assert "Total Fleet Vehicles" in html


def test_render_html_omits_categories_with_zero_entries(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sources = [_sources()[0]]  # service only
    _write(sources[0], raw_dir, [{"NTD ID": 90019, "2020": 100.0}])

    data = ntd.build_ntd_report_data(sources, raw_dir, agency="SacRT", ntd_id="90019")
    html = ntd.render_html(data)

    assert ">Service<" in html
    assert ">Funding<" not in html
    assert ">Asset<" not in html
    assert ">Expenditure<" not in html


def test_write_html_uses_year_range_in_filename(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    sources = [_sources()[0]]
    _write(sources[0], raw_dir, [{"NTD ID": 90019, "2020": 100.0, "2021": 110.0}])

    data = ntd.build_ntd_report_data(sources, raw_dir, agency="SacRT", ntd_id="90019")
    html = ntd.render_html(data)
    dest = ntd.write_html(html, tmp_path, "SacRT", data.min_year, data.max_year)

    assert dest == tmp_path / "reports" / "SacRT" / "ntd-2020-2021.html"
    assert dest.exists()


def test_write_html_falls_back_to_no_data_filename_when_year_range_is_none(tmp_path: Path):
    dest = ntd.write_html("<html></html>", tmp_path, "SacRT", None, None)

    assert dest == tmp_path / "reports" / "SacRT" / "ntd-no-data.html"
    assert dest.exists()
