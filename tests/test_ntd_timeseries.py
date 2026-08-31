from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from diy_transit_analysis.config import NtdTimeSeriesSource
from diy_transit_analysis.ntd.timeseries import NtdDataError, fetch_time_series, fetched_path, read_agency_series


def _write_csv(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


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


def test_read_agency_series_reads_xlsx(tmp_path: Path):
    path = tmp_path / "upt.xlsx"
    pd.DataFrame([{"NTD ID": 90019, "2021": 5.0}]).to_excel(path, index=False)

    assert read_agency_series(path, "90019") == {2021: 5.0}


@patch("diy_transit_analysis.ntd.timeseries.requests.get")
def test_fetch_time_series_downloads_each_source(mock_get, tmp_path: Path):
    response = MagicMock()
    response.iter_content.return_value = [b"NTD ID,2021\n90019,5\n"]
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    mock_get.return_value = response

    sources = [
        NtdTimeSeriesSource(name="Unlinked Passenger Trips", category="service", url="https://example.org/upt.csv"),
        NtdTimeSeriesSource(name="Operating Expenses", category="expenditure", url="https://example.org/opex.xlsx"),
    ]

    written = fetch_time_series(sources, tmp_path)

    assert [p.name for p in written] == ["unlinked-passenger-trips.csv", "operating-expenses.xlsx"]
    assert all(p.exists() for p in written)
    assert fetched_path(sources[0], tmp_path) == written[0]
