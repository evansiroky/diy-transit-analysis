"""Fetch and parse FTA National Transit Database (NTD) Time Series data files.

ASSUMPTION, NOT VERIFIED AGAINST A LIVE DOWNLOAD: as of this writing,
network access to transit.dot.gov (where NTD publishes its Time Series
data products) was unavailable in this session. This module is written
against a documented best-understanding of the published file shape —
one wide table per configured metric, with an NTD-ID column and one
column per reporting year — not a working integration test. Per
specs/principles.md#fail-loud-on-unverified-assumptions, parsing is
deliberately structural (column-alias matching, numeric year-column
detection) rather than pinned to exact column header text, so it's
resilient to header wording this project hasn't verified. Before relying
on this for real public reporting, verify a real downloaded file against
specs/data-model.md#ntd-time-series-data-on-disk-fetched and update that
section accordingly.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

from diy_transit_analysis.config import NtdTimeSeriesSource

_NTD_ID_COLUMN_ALIASES = {"ntd id", "5 digit ntd id", "ntdid"}
_YEAR_RE = re.compile(r"^(\d{4})(\.0)?$")
_DEFAULT_EXTENSION = ".xlsx"
_SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".xls")


class NtdDataError(RuntimeError):
    """Raised when a fetched NTD Time Series file can't be parsed at all.

    Reserved for "this file has no recognizable NTD ID column" — a file
    that parses fine but has zero rows for the configured ntd_id is a
    normal, non-error outcome (see read_agency_series), not this.
    """


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "source"


def _extension_for(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in _SUPPORTED_EXTENSIONS else _DEFAULT_EXTENSION


def fetched_path(source: NtdTimeSeriesSource, dest_dir: Path) -> Path:
    """The local path fetch_time_series writes (or would write) this source to.

    Public so callers (report/ntd.py) can locate an already-fetched file
    without reaching into this module's private slug/extension logic.
    """
    return dest_dir / f"{_slugify(source.name)}{_extension_for(source.url)}"


def fetch_time_series(sources: list[NtdTimeSeriesSource], dest_dir: Path, *, timeout: float = 60.0) -> list[Path]:
    """Download every configured NTD Time Series source to dest_dir.

    Agency-independent — these files cover every NTD-reporting agency, so
    unlike fetch_schedule/fetch_historic this isn't namespaced under one
    agency's output directory (specs/architecture.md#ntd-time-series-
    data-access). Each file is named by its slugified `name`, e.g.
    "Unlinked Passenger Trips" -> unlinked-passenger-trips.xlsx.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for source in sources:
        dest_path = fetched_path(source, dest_dir)
        with requests.get(source.url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with dest_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
        written.append(dest_path)

    return written


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path, sheet_name=0)


def _find_ntd_id_column(df: pd.DataFrame, *, path: Path) -> str:
    for column in df.columns:
        if str(column).strip().lower() in _NTD_ID_COLUMN_ALIASES:
            return column
    raise NtdDataError(
        f"{path}: no column matching a known NTD ID alias "
        f"({', '.join(sorted(_NTD_ID_COLUMN_ALIASES))}) found among columns {list(df.columns)!r} — "
        "either this isn't an NTD Time Series file, or its real header text doesn't match this "
        "project's assumed aliases (see ntd/timeseries.py module docstring)."
    )


def _year_columns(df: pd.DataFrame) -> dict[object, int]:
    """Map each column whose header parses as a bare 4-digit year to that year (int)."""
    years = {}
    for column in df.columns:
        match = _YEAR_RE.match(str(column).strip())
        if match:
            years[column] = int(match.group(1))
    return years


def _normalize_id(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def read_agency_series(path: Path, ntd_id: str) -> dict[int, float]:
    """Read one fetched NTD Time Series file, filtered + summed for one agency.

    Returns {year: value}, summing every row whose NTD ID column matches
    `ntd_id` (a file broken out by mode/type-of-service contributes
    multiple rows per year — see specs/data-model.md#ntd-time-series-
    data-on-disk-fetched). A year with no numeric value from any matching
    row is omitted. An empty return value means this agency legitimately
    has zero matching rows in this file — not an error. Raises
    NtdDataError only when the file itself can't be parsed (no NTD ID
    column found at all).
    """
    df = _read_table(path)
    id_column = _find_ntd_id_column(df, path=path)
    year_columns = _year_columns(df)

    matching = df[df[id_column].map(_normalize_id) == ntd_id.strip()]
    if matching.empty or not year_columns:
        return {}

    series: dict[int, float] = {}
    for column, year in year_columns.items():
        values = pd.to_numeric(matching[column], errors="coerce").dropna()
        if not values.empty:
            series[year] = float(values.sum())

    return series
