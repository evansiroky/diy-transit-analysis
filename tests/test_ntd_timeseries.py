from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from diy_transit_analysis.config import NtdTimeSeriesSource
from diy_transit_analysis.ntd.timeseries import (
    NtdDataError,
    fetch_time_series,
    fetched_path,
    read_agency_series,
    resolve_download_url,
)

_LANDING_PAGE_HTML = """
<html><body>
<a href="/sites/fta.dot.gov/files/2026-01/UPT_Time_Series.xlsx"
   type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet">Download</a>
</body></html>
"""


def _write_csv(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _source(name="Unlinked Passenger Trips", category="service", product_url=None, sheet=None):
    return NtdTimeSeriesSource(
        name=name,
        category=category,
        product_url=product_url or "https://www.transit.dot.gov/ntd/data-product/ts21-service-data",
        sheet=sheet,
    )


# --- landing-page scraping -------------------------------------------------


@patch("diy_transit_analysis.ntd.timeseries.requests.get")
def test_resolve_download_url_finds_xlsx_link(mock_get):
    response = MagicMock()
    response.text = _LANDING_PAGE_HTML
    response.raise_for_status.return_value = None
    mock_get.return_value = response

    url = resolve_download_url("https://www.transit.dot.gov/ntd/data-product/ts21-service-data")

    assert url == "https://www.transit.dot.gov/sites/fta.dot.gov/files/2026-01/UPT_Time_Series.xlsx"


@patch("diy_transit_analysis.ntd.timeseries.requests.get")
def test_resolve_download_url_resolves_relative_href_against_landing_page(mock_get):
    response = MagicMock()
    response.text = _LANDING_PAGE_HTML
    response.raise_for_status.return_value = None
    mock_get.return_value = response

    url = resolve_download_url("https://www.transit.dot.gov/ntd/data-product/ts21-service-data")

    assert url.startswith("https://www.transit.dot.gov/")


@patch("diy_transit_analysis.ntd.timeseries.requests.get")
def test_resolve_download_url_raises_when_no_link_found(mock_get):
    response = MagicMock()
    response.text = "<html><body>no download here</body></html>"
    response.raise_for_status.return_value = None
    mock_get.return_value = response

    with pytest.raises(NtdDataError, match="no.*download link found"):
        resolve_download_url("https://www.transit.dot.gov/ntd/data-product/bogus")


# --- fetch_time_series: dedup by product_url --------------------------------


@patch("diy_transit_analysis.ntd.timeseries.resolve_download_url")
@patch("diy_transit_analysis.ntd.timeseries.requests.get")
def test_fetch_time_series_dedupes_sources_sharing_a_product_url(mock_get, mock_resolve, tmp_path: Path):
    mock_resolve.return_value = "https://www.transit.dot.gov/sites/fta.dot.gov/files/x.xlsx"
    response = MagicMock()
    response.iter_content.return_value = [b"fake xlsx bytes"]
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    mock_get.return_value = response

    shared_url = "https://www.transit.dot.gov/ntd/data-product/ts21-service-data"
    sources = [
        _source(name="UPT", product_url=shared_url, sheet="UPT"),
        _source(name="VRH", product_url=shared_url, sheet="VRH"),
        _source(name="Active Fleet", product_url="https://www.transit.dot.gov/ntd/data-product/ts41-assets"),
    ]

    written = fetch_time_series(sources, tmp_path)

    assert len(written) == 2  # one per unique product_url, not per source
    assert mock_resolve.call_count == 2
    assert written[0] == fetched_path(sources[0], tmp_path) == fetched_path(sources[1], tmp_path)
    assert written[1] == fetched_path(sources[2], tmp_path)


def test_fetched_path_keys_by_landing_page_slug_not_name():
    a = _source(name="UPT", product_url="https://www.transit.dot.gov/ntd/data-product/ts21-service-data")
    b = _source(name="VRH", product_url="https://www.transit.dot.gov/ntd/data-product/ts21-service-data")
    c = _source(name="Active Fleet", product_url="https://www.transit.dot.gov/ntd/data-product/ts41-assets")

    dest_dir = Path("/tmp/fake")
    assert fetched_path(a, dest_dir) == fetched_path(b, dest_dir)
    assert fetched_path(a, dest_dir) != fetched_path(c, dest_dir)
    assert fetched_path(a, dest_dir).name == "ts21-service-data.xlsx"


# --- read_agency_series: multi-sheet + resilient sheet matching ------------


def test_read_agency_series_selects_named_sheet_from_multi_sheet_workbook(tmp_path: Path):
    path = tmp_path / "ts21.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([{"NTD ID": 90019, "2021": 100.0}]).to_excel(writer, sheet_name="UPT", index=False)
        pd.DataFrame([{"NTD ID": 90019, "2021": 50.0}]).to_excel(writer, sheet_name="VRH", index=False)

    assert read_agency_series(path, "90019", sheet="UPT") == {2021: 100.0}
    assert read_agency_series(path, "90019", sheet="VRH") == {2021: 50.0}


def test_read_agency_series_sheet_matching_is_case_and_punctuation_insensitive(tmp_path: Path):
    path = tmp_path / "ts21.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([{"NTD ID": 90019, "2021": 900.0}]).to_excel(writer, sheet_name="OpExp_Total", index=False)

    assert read_agency_series(path, "90019", sheet="opexp total") == {2021: 900.0}
    assert read_agency_series(path, "90019", sheet="OPEXP-TOTAL") == {2021: 900.0}


def test_read_agency_series_defaults_to_first_sheet_when_none_configured(tmp_path: Path):
    path = tmp_path / "single.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([{"NTD ID": 90019, "2021": 5.0}]).to_excel(writer, sheet_name="OnlySheet", index=False)

    assert read_agency_series(path, "90019") == {2021: 5.0}


def test_read_agency_series_raises_with_available_sheets_when_sheet_not_found(tmp_path: Path):
    path = tmp_path / "ts21.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([{"NTD ID": 90019, "2021": 100.0}]).to_excel(writer, sheet_name="UPT", index=False)
        pd.DataFrame([{"NTD ID": 90019, "2021": 50.0}]).to_excel(writer, sheet_name="VRH", index=False)

    with pytest.raises(NtdDataError, match=r"UPT.*VRH|VRH.*UPT"):
        read_agency_series(path, "90019", sheet="NoSuchSheet")


# --- read_agency_series: NTD ID / year-column parsing (unchanged behavior) -


def test_read_agency_series_sums_multiple_matching_rows(tmp_path: Path):
    path = tmp_path / "upt.csv"
    _write_csv(
        path,
        [
            {"NTD ID": 90019, "Mode": "MB", "2021": 100.0, "2022": 110.0},
            {"NTD ID": 90019, "Mode": "LR", "2021": 50.0, "2022": None},
            {"NTD ID": 12345, "Mode": "MB", "2021": 999.0, "2022": 999.0},
        ],
    )

    series = read_agency_series(path, "90019")

    assert series == {2021: 150.0, 2022: 110.0}


def test_read_agency_series_omits_year_with_no_numeric_value_from_any_matching_row(tmp_path: Path):
    path = tmp_path / "upt.csv"
    _write_csv(
        path,
        [
            {"NTD ID": 90019, "2020": None, "2021": 5.0},
            {"NTD ID": 90019, "2020": None, "2021": 6.0},
        ],
    )

    assert read_agency_series(path, "90019") == {2021: 11.0}


def test_read_agency_series_returns_empty_for_unmatched_id_not_an_error(tmp_path: Path):
    path = tmp_path / "upt.csv"
    _write_csv(path, [{"NTD ID": 12345, "2021": 999.0}])

    assert read_agency_series(path, "90019") == {}


def test_read_agency_series_normalizes_float_looking_id(tmp_path: Path):
    path = tmp_path / "upt.csv"
    _write_csv(path, [{"NTD ID": "90019.0", "2021": 42.0}])

    assert read_agency_series(path, "90019") == {2021: 42.0}


@pytest.mark.parametrize("alias", ["NTD ID", "5 Digit NTD ID", "ntdid", "  NTD Id  "])
def test_read_agency_series_matches_known_id_column_aliases(tmp_path: Path, alias: str):
    path = tmp_path / "upt.csv"
    _write_csv(path, [{alias: 90019, "2021": 5.0}])

    assert read_agency_series(path, "90019") == {2021: 5.0}


def test_read_agency_series_raises_when_no_id_column_found(tmp_path: Path):
    path = tmp_path / "bad.csv"
    _write_csv(path, [{"Agency": "SacRT", "2021": 5.0}])

    with pytest.raises(NtdDataError, match="no column matching a known NTD ID alias"):
        read_agency_series(path, "90019")


def test_read_agency_series_ignores_non_year_columns(tmp_path: Path):
    path = tmp_path / "upt.csv"
    _write_csv(path, [{"NTD ID": 90019, "Agency": "SacRT", "UZA Name": "Sacramento", "2021": 5.0}])

    assert read_agency_series(path, "90019") == {2021: 5.0}
