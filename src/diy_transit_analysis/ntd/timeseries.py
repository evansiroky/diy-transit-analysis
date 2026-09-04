"""Fetch and parse FTA National Transit Database (NTD) Time Series data files.

FTA doesn't publish a stable direct download URL for a Time Series
workbook — the file linked from a data product's landing page changes on
every release. This module scrapes the landing page for the current
download link (an `<a>` whose `type` is the xlsx MIME type) the same way
Caltrans' own cal-itp/data-infra NTD ingestion pipeline does
(`airflow/plugins/hooks/ntd_xlsx_hook.py` in that repo) — see
specs/architecture.md#ntd-time-series-data-access for the evidence this
rests on.

Which metrics get fetched/charted (DEFAULT_TIME_SERIES_SOURCES below) is
a fixed catalog here in code, not something read from a user's config
file — see specs/architecture.md#ntd-time-series-data-access for why:
unlike an agency's GTFS/TIDES URLs, this isn't per-agency data, so
putting it in every user's config would just shift this project's own
data-source integration work onto them. Adding/fixing a catalog entry is
a spec change (specs/architecture.md's catalog table) followed by
editing this list, like any other spec-led behavior change.

What's confirmed via cal-itp/data-infra's reference implementation: the
base URL, the landing-page-scrape mechanism, and "one workbook, many
sheets". What's still an ASSUMPTION, NOT VERIFIED AGAINST A LIVE
DOWNLOAD in this project (transit.dot.gov was unreachable while writing
this): the exact literal sheet-tab names and column header text. Per
specs/principles.md#fail-loud-on-unverified-assumptions, both are
matched structurally rather than pinned to exact strings — sheet names
case/punctuation-insensitively, the NTD-ID column by alias, year columns
by a numeric-header test — and a failure to match anything raises
NtdDataError with what was actually found, rather than silently reading
the wrong data. Before relying on this for real public reporting, run
fetch-ntd against the live endpoint and verify against
specs/data-model.md#ntd-time-series-data-on-disk-fetched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

_NTD_ID_COLUMN_ALIASES = {"ntd id", "5 digit ntd id", "ntdid"}
_YEAR_RE = re.compile(r"^(\d{4})(\.0)?$")
_XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_NTD_BASE_URL = "https://www.transit.dot.gov/ntd/data-product"


@dataclass(frozen=True)
class NtdTimeSeriesSource:
    name: str
    category: str  # "service" | "funding" | "expenditure" | "asset"
    product_url: str  # the data product's landing page, not a direct file link
    sheet: str | None = None  # workbook tab to read; None = first sheet


def _product_url(slug: str) -> str:
    return f"{_NTD_BASE_URL}/{slug}"


# The built-in NTD Time Series catalog — see specs/architecture.md#ntd-
# time-series-data-access for the source table this must match and the
# evidence behind each product_url. Four landing pages, deduplicated at
# fetch time by fetch_time_series, covering nine charts.
_SERVICE_URL = _product_url("ts21-service-data-and-operating-expenses-time-series-mode-2")
_CAPITAL_EXPENDITURES_URL = _product_url("ts31-capital-expenditures-time-series-2")
_FUNDING_URL = _product_url("ts12-operating-funding-time-series-3")
_ASSET_URL = _product_url("ts41-asset-inventory-time-series-4")

DEFAULT_TIME_SERIES_SOURCES: list[NtdTimeSeriesSource] = [
    NtdTimeSeriesSource(name="Unlinked Passenger Trips", category="service", product_url=_SERVICE_URL, sheet="UPT"),
    NtdTimeSeriesSource(name="Vehicle Revenue Hours", category="service", product_url=_SERVICE_URL, sheet="VRH"),
    NtdTimeSeriesSource(
        name="Vehicles Operated in Maximum Service", category="service", product_url=_SERVICE_URL, sheet="VOMS"
    ),
    NtdTimeSeriesSource(
        name="Operating Expenses", category="expenditure", product_url=_SERVICE_URL, sheet="OpExp_Total"
    ),
    NtdTimeSeriesSource(
        name="Capital Expenditures", category="expenditure", product_url=_CAPITAL_EXPENDITURES_URL, sheet="Total"
    ),
    NtdTimeSeriesSource(
        name="Total Operating Funding", category="funding", product_url=_FUNDING_URL, sheet="Operating_Total"
    ),
    NtdTimeSeriesSource(
        name="Total Capital Funding", category="funding", product_url=_FUNDING_URL, sheet="Capital_Total"
    ),
    NtdTimeSeriesSource(name="Active Fleet Size", category="asset", product_url=_ASSET_URL, sheet="Active_Fleet"),
    NtdTimeSeriesSource(name="Average Fleet Age", category="asset", product_url=_ASSET_URL, sheet="Avg_Fleet_Age"),
]

# Mirrors the User-Agent cal-itp/data-infra sends — some government sites
# block requests with no browser-like User-Agent at all.
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


class NtdDataError(RuntimeError):
    """Raised when an NTD Time Series product/file/sheet can't be resolved or parsed.

    Covers: a landing page with no discoverable xlsx download link, a
    configured `sheet` matching nothing in the workbook, or a sheet with
    no recognizable NTD ID column. A sheet that parses fine but has zero
    rows for the configured ntd_id is a normal, non-error outcome (see
    read_agency_series), not this.
    """


def _landing_page_slug(product_url: str) -> str:
    """A filesystem-safe slug from a data product's landing-page URL path.

    e.g. ".../ntd/data-product/ts21-service-data-and-operating-expenses-
    time-series-mode-2" -> "ts21-service-data-and-operating-expenses-
    time-series-mode-2" — these slugs are how FTA and cal-itp/data-infra
    both stably identify a product, unlike the download link itself.
    """
    segment = Path(urlparse(product_url).path).name
    slug = re.sub(r"[^a-z0-9]+", "-", segment.lower()).strip("-")
    return slug or "product"


def fetched_path(source: NtdTimeSeriesSource, dest_dir: Path) -> Path:
    """The local path fetch_time_series writes (or would write) this source's workbook to.

    Keyed by product_url's landing-page slug, not by source.name — every
    entry sharing a product_url resolves to the same file (see
    specs/data-model.md#ntd-time-series-data-on-disk-fetched). Public so
    callers (report/ntd.py) can locate an already-fetched file without
    reaching into this module's private slug logic.
    """
    return dest_dir / f"{_landing_page_slug(source.product_url)}.xlsx"


def resolve_download_url(product_url: str, *, timeout: float = 60.0) -> str:
    """Scrape an NTD data-product landing page for its current xlsx download link.

    See the module docstring — FTA doesn't publish a stable direct URL,
    so this is the fetch mechanism cal-itp/data-infra's production NTD
    pipeline uses against the real endpoint.
    """
    response = requests.get(product_url, headers=_REQUEST_HEADERS, timeout=timeout)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    link = soup.find("a", type=_XLSX_MIME_TYPE)
    if link is None or not link.get("href"):
        raise NtdDataError(
            f"{product_url}: no <a type=\"{_XLSX_MIME_TYPE}\"> download link found on this landing page — "
            "either this isn't an NTD data-product page, or FTA changed the page structure this project's "
            "scrape assumption relies on (see ntd/timeseries.py module docstring)."
        )
    return urljoin(product_url, link["href"])


def fetch_time_series(sources: list[NtdTimeSeriesSource], dest_dir: Path, *, timeout: float = 60.0) -> list[Path]:
    """Download every uniquely-configured NTD Time Series product to dest_dir.

    Agency-independent — these files cover every NTD-reporting agency, so
    unlike fetch_schedule/fetch_historic this isn't namespaced under one
    agency's output directory (specs/architecture.md#ntd-time-series-
    data-access). Sources sharing a product_url are fetched once, not
    once per source, since they're the same workbook.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    seen_product_urls: set[str] = set()
    for source in sources:
        if source.product_url in seen_product_urls:
            continue
        seen_product_urls.add(source.product_url)

        download_url = resolve_download_url(source.product_url, timeout=timeout)
        dest_path = fetched_path(source, dest_dir)
        with requests.get(download_url, headers=_REQUEST_HEADERS, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with dest_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
        written.append(dest_path)

    return written


def _normalize_sheet_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _select_sheet(sheets: dict[str, pd.DataFrame], *, sheet: str | None, path: Path) -> pd.DataFrame:
    if sheet is None:
        return next(iter(sheets.values()))

    wanted = _normalize_sheet_name(sheet)
    for sheet_name, df in sheets.items():
        if _normalize_sheet_name(sheet_name) == wanted:
            return df

    raise NtdDataError(
        f"{path}: no sheet matching {sheet!r} found — this workbook has sheets {list(sheets.keys())!r}. "
        "Sheet-name matching is case/punctuation-insensitive but the configured sheet still didn't match "
        "any of them (see specs/data-model.md#ntd-time-series-data-on-disk-fetched)."
    )


def _read_table(path: Path, *, sheet: str | None) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    sheets = pd.read_excel(path, sheet_name=None)
    return _select_sheet(sheets, sheet=sheet, path=path)


def _find_ntd_id_column(df: pd.DataFrame, *, path: Path) -> str:
    for column in df.columns:
        if str(column).strip().lower() in _NTD_ID_COLUMN_ALIASES:
            return column
    raise NtdDataError(
        f"{path}: no column matching a known NTD ID alias "
        f"({', '.join(sorted(_NTD_ID_COLUMN_ALIASES))}) found among columns {list(df.columns)!r} — "
        "either this isn't an NTD Time Series sheet, or its real header text doesn't match this "
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


def read_agency_series(path: Path, ntd_id: str, *, sheet: str | None = None) -> dict[int, float]:
    """Read one fetched NTD Time Series workbook's sheet, filtered + summed for one agency.

    Returns {year: value}, summing every row whose NTD ID column matches
    `ntd_id` (a sheet broken out by mode/type-of-service contributes
    multiple rows per year — see specs/data-model.md#ntd-time-series-
    data-on-disk-fetched). A year with no numeric value from any matching
    row is omitted. An empty return value means this agency legitimately
    has zero matching rows in this sheet — not an error. Raises
    NtdDataError when the sheet itself can't be resolved (no matching
    sheet name, or no NTD ID column found at all).
    """
    df = _read_table(path, sheet=sheet)
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
