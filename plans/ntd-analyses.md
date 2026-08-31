---
status: done
depends: [package-scaffold, html-dashboard-report]
specs:
  - specs/architecture.md
  - specs/data-model.md
  - specs/behaviors/config-validation.md
issues: []
pr:
---

# Plan: NTD Time Series analyses

## Scope

In scope: a config-driven way to fetch FTA National Transit Database
(NTD) "Time Series" data files and chart them per agency (identified by
`ntd_id`), producing a self-contained HTML report (`report ntd`) with
service, expenditure, funding, and asset sections — per
`specs/data-model.md#ntd-time-series-report-output` and
`specs/architecture.md#ntd-time-series-data-access`. New `ntd/` fetch
module, new `report/ntd.py`, a `report/html_charts.py` extraction shared
with `report/dashboard.py`, `fetch-ntd`/`report ntd` CLI subcommands, and
`run` integration.

Out of scope:
- Verifying the assumed NTD Time Series file/column shape against a real
  download — network access to `transit.dot.gov` was unavailable while
  writing this plan (egress-blocked in this session); the parsing rule is
  built to be resilient to header-text drift (alias matching + numeric
  year-column detection) rather than hard-coding exact FTA column names,
  but it is unverified. Tracked as a Follow-up, same shape as the
  existing TIDES-bucket-verification follow-up in `plans/data-fetch.md`.
- Per-mode/per-TOS breakdowns in the report — every chart is an
  agency-total annual series (mode/TOS rows summed), matching how NTD's
  own summary stats aggregate. A per-mode drill-down is a future
  enhancement, not MVP.
- A user-configurable year range for `report ntd` — the report always
  shows every year found in the fetched data for the configured
  `ntd_id`, mirroring `report schedule-stats`' anchor on the feed's own
  representative week rather than requiring extra config.
- Caching/re-use of previously fetched NTD files across agencies beyond
  what "fetch once, filter per agency at report time" already gives for
  free (no incremental/delta fetch).

## Implements

- `specs/architecture.md#ntd-time-series-data-access` — config-driven
  metric-source list, agency-independent fetch, assumed file shape.
- `specs/architecture.md#cli-entrypoint-shape` — `fetch-ntd`/`report ntd`
  subcommands and `run` step 6.
- `specs/data-model.md#config-file` — `agencies.<name>.ntd_id`, top-level
  `ntd.time_series[]`.
- `specs/data-model.md#ntd-time-series-data-on-disk-fetched` — fetch
  destination + generic parsing rule (NTD ID alias matching, year-column
  detection, per-agency sum).
- `specs/data-model.md#ntd-time-series-report-output` — report structure,
  sections, chart-per-entry, filename convention.
- `specs/behaviors/config-validation.md` — validation rules for the new
  fields, and the fetch-ntd-vs-report-ntd requirement split.

## Approach

1. `config.py`:
   - `NtdTimeSeriesSource` frozen dataclass: `name: str`, `category: str`,
     `url: str`.
   - `NtdConfig` frozen dataclass: `time_series: list[NtdTimeSeriesSource]`.
   - `Config` gains `ntd: NtdConfig | None`.
   - `AgencyConfig` gains `ntd_id: str | None = None`.
   - `_parse_ntd()` mirrors `_parse_tides()`'s whole-block-optional
     pattern but at the document root; validates `category` against the
     fixed allowed set, `url` against the same `http(s)://` rule as
     `gtfs_schedule_url`.
2. `ntd/timeseries.py`:
   - `fetch_time_series(sources: list[NtdTimeSeriesSource], dest_dir: Path) -> list[Path]`:
     plain `requests.get` per entry (mirrors `gtfs/schedule.py`'s fetch
     shape), writing to `dest_dir/<slugify(name)>.<ext-from-url>`.
   - `read_agency_series(path: Path, ntd_id: str) -> dict[int, float]`:
     reads csv/xlsx (`pandas.read_csv`/`read_excel`, first sheet),
     detects the NTD ID column via case-insensitive alias matching
     (`"ntd id"`, `"5 digit ntd id"`, `"ntdid"`), raises `NtdDataError` if
     none found; detects year columns via a regex/int-parse test on
     stripped headers; filters rows where the ID column (normalized:
     strip whitespace, strip a trailing `.0` float artifact) equals
     `ntd_id`; sums matching rows per year column; drops years with no
     numeric value from any matching row. Empty (zero matching rows) is a
     valid, non-error result — an empty dict.
   - `NtdDataError(RuntimeError)`: raised only for "file couldn't be
     parsed at all" (no NTD ID column found), not for "no data for this
     agency" — mirrors `TidesAccessError`'s loud-vs-quiet distinction.
3. `report/html_charts.py`: extract `_nice_ticks`, `_thin_indices`,
   `_area_chart_svg`, `_stat_tile`, `_data_table`, `_percent`, and the
   shared `<style>` block's chart/table/stat-tile CSS out of
   `report/dashboard.py` verbatim (rename without leading underscore
   where they become this module's public surface: `area_chart_svg`,
   `stat_tile`, `data_table`, `percent`, `nice_ticks`, `thin_indices`,
   plus a `BASE_CSS` constant for the shared style rules). Update
   `dashboard.py` to import and call these instead of its own copies —
   behavior-preserving refactor, no output change (covered by the
   existing dashboard tests still passing unmodified).
4. `report/ntd.py`:
   - `NtdChartData` frozen dataclass: `name: str`, `category: str`,
     `series: list[tuple[int, float]]` (sorted by year), `note: str |
     None` (set when `series` is empty).
   - `NtdReportData` frozen dataclass: `agency: str`, `ntd_id: str`,
     `min_year: int | None`, `max_year: int | None`, `charts_by_category:
     dict[str, list[NtdChartData]]`.
   - `build_ntd_report_data(sources, raw_dir, agency, ntd_id) ->
     NtdReportData`: for each configured source whose fetched file exists
     under `raw_dir`, calls `read_agency_series`, builds an `NtdChartData`
     per entry, groups by category preserving config order within each
     category. Computes `min_year`/`max_year` across every non-empty
     series (both `None` if every series is empty).
   - `render_html(data: NtdReportData) -> str`: fixed section order
     (Service, Expenditure, Funding, Asset), each section omitted
     entirely if it has zero entries; each chart rendered via
     `html_charts.area_chart_svg` + `html_charts.data_table`, using the
     shared CSS from `html_charts.BASE_CSS`. Page header states agency +
     `ntd_id`.
   - `write_html(html, output_dir, agency, min_year, max_year) -> Path`:
     writes to `<output_dir>/reports/<agency>/ntd-<min_year>-<max_year>.html`
     (falls back to `ntd-no-data` in the filename if both are `None` —
     every configured source came back empty for this `ntd_id`).
5. `cli.py`:
   - `_require_ntd(config, config_path, command)`: command-level error if
     `config.ntd is None`.
   - `_require_ntd_id(agency, config_path, command)`: command-level error
     if `agency.ntd_id is None`.
   - `cmd_fetch_ntd`: `_load` + `_require_ntd`, fetches to
     `<output_dir>/ntd/raw/`, prints count written. No `_require_ntd_id`
     — agency-independent per spec.
   - `cmd_report_ntd`: `_load`, `_require_ntd`, `_require_ntd_id`, fails
     loudly if `<output_dir>/ntd/raw/` doesn't exist (same "run fetch-X
     first" pattern as `cmd_report_otp`/`cmd_report_html`), else builds +
     writes the report.
   - `cmd_run`: after the existing dashboard step, add step 6 — if
     `config.ntd` and `agency.ntd_id` are both set, fetch + report ntd
     (printing what it did); otherwise print which of the two is missing
     and skip, mirroring the existing tides/otp skip-message shape
     exactly (reuse the same phrasing pattern: "Skipped NTD fetch and the
     NTD Time Series report: ...").
   - `build_parser`: add `fetch-ntd` and `report ntd` subparsers.
6. `config/example.yaml`: add SacRT's `ntd_id: "90019"` and a top-level
   `ntd:` block with a small illustrative set of entries covering all
   four categories (service ×2-3, expenditure ×1, funding ×1, asset ×1),
   URLs clearly commented as placeholders pointing at
   `transit.dot.gov`'s NTD Data page, matching the TIDES config's
   existing "ASSUMED, verify" commenting convention.
7. `pyproject.toml`/`requirements.txt`: add `openpyxl` (pandas' xlsx
   read engine) to `[project.dependencies]`.
8. `README.md`: document `fetch-ntd`/`report ntd`, the `ntd_id` +
   top-level `ntd:` config, and flag the same "assumed, not verified"
   caveat the Status section already carries for TIDES.

## Validation

- [x] `diy-transit-analysis fetch-ntd --config <cfg> --agency SacRT` downloads every configured `ntd.time_series[]` entry to `<output_dir>/ntd/raw/`, named by slugified `name`. Verified via `test_fetch_ntd_then_report_ntd_standalone` and a manual `run` smoke test against a copy of `config/example.yaml` (network calls mocked — the real FTA URLs are unverified placeholders, see Risks).
- [x] `diy-transit-analysis report ntd --config <cfg> --agency SacRT` (after fetch) produces `<output_dir>/reports/SacRT/ntd-<min>-<max>.html` with one section per category present in config, one chart per configured entry, every chart's data also present in an on-page table. Verified the same way, plus `tests/test_ntd_report.py`.
- [x] Unit test: an entry whose file has zero rows matching the configured `ntd_id` renders its chart slot as a "no data" note, not an error, and doesn't affect other entries/sections. `test_build_ntd_report_data_groups_by_category_and_computes_year_range`, `test_render_html_includes_sections_charts_and_notes`.
- [x] Unit test: a file with no column matching any NTD-ID alias raises `NtdDataError` (loud failure, not silently skipped). `test_read_agency_series_raises_when_no_id_column_found`, `test_build_ntd_report_data_raises_ntddataerror_for_unparseable_file`.
- [x] Unit test: two rows for the same `ntd_id` in one file (mode/TOS breakdown) sum per year into one series value. `test_read_agency_series_sums_multiple_matching_rows`.
- [x] Unit test: a year column with a blank/NaN value for every matching row is omitted from that metric's series (not shown as `0`). `test_read_agency_series_omits_year_with_no_numeric_value_from_any_matching_row`.
- [x] Unit test: `run` on an agency with neither `ntd_id` nor a top-level `ntd:` block configured prints a skip message and succeeds (mirrors the existing GTFS-only `run` test). Extended `test_run_on_gtfs_only_agency_produces_schedule_stats_and_dashboard_only` with NTD-skip assertions.
- [x] Unit test: `run` on an agency with both configured produces the `ntd-*.html` report alongside the existing reports. `test_run_on_full_agency_with_ntd_produces_ntd_report`.
- [x] `dashboard.py`'s existing test suite (`tests/test_dashboard.py`) passes unmodified after the `html_charts.py` extraction — confirms the refactor is behavior-preserving. One test (`test_nice_ticks_never_produces_duplicate_labels`) had to move to a new `tests/test_html_charts.py` since it reached into the function directly and that function moved; every other dashboard test file was untouched and passes as-is.
- [x] `pytest` passes in full. 73 passed (`pytest -q`).

## Risks / unknowns

- **NTD Time Series file/column shape is unverified** — `transit.dot.gov`
  was unreachable (egress-blocked) while researching this plan, so the
  assumed structure (wide table, NTD-ID column + year columns, one file
  per metric) is based on general familiarity with NTD's long-published
  data-product conventions, not a live download. The alias-matching +
  numeric-year-column detection approach is deliberately resilient to
  header-text drift, but if FTA's real files group multiple metrics into
  one workbook (multiple sheets) rather than one metric per file, this
  plan's "read first sheet only" assumption would need a follow-up fix
  to scan all sheets.
- **`openpyxl` dependency** — new transitive requirement for `.xlsx`
  reads; CSV-only NTD sources (if a user re-hosts/converts files) work
  without it, but the default `pandas.read_excel` path needs it
  installed.

## Notes

- No PR was opened for this plan — the task didn't ask for one, and repo
  instructions are to only open a PR when explicitly requested. Work is
  committed and pushed to `claude/ntd-data-analyses-yxv9rv`; `pr:` stays
  unset above until/unless one is opened later.
- `www.transit.dot.gov` (and every `*.transportation.gov` host tried as an
  alternative) was egress-blocked in this session, so none of the NTD
  file/column assumptions could be checked against a live download — this
  plan's Scope already called that out as expected going in, not a
  surprise discovered mid-plan.
- The `report/html_charts.py` extraction turned out larger than a typical
  "share one helper" refactor — effectively all of `dashboard.py`'s chart
  rendering moved, since `report ntd` needed the exact same page shell
  (CSS, hover script, stat tiles, tables) to look consistent, not just the
  SVG math. `dashboard.py`'s own behavior is unchanged (its full test
  suite passes unmodified except for the one test that reached into a
  moved private function — see Validation).
- `ntd.time_series[].url` values in `config/example.yaml` are
  illustrative placeholders (clearly commented as such), not real current
  FTA download links — same treatment as `config/example.yaml`'s existing
  `tides.gcs_bucket` placeholder for the same reason (unverifiable this
  session).
- Added `ntd/timeseries.fetched_path()` as a small public seam (not in
  the original Approach) so `report/ntd.py` could locate an
  already-fetched file without reaching into `ntd/timeseries.py`'s
  private slug/extension helpers — a natural extension of the Approach's
  fetch/read split, not a scope change.

## Follow-ups

- Tracked as: verifying the NTD Time Series file/column shape against a
  real FTA download once `transit.dot.gov` is reachable, and updating
  `specs/architecture.md#ntd-time-series-data-access` +
  `specs/data-model.md#ntd-time-series-data-on-disk-fetched` accordingly
  — same shape as `plans/data-fetch.md`'s still-open TIDES-bucket-
  verification follow-up. Until then, treat `config/example.yaml`'s
  `ntd.time_series[].url` values as placeholders to replace with real
  links from FTA's NTD Data page.
- Tracked as: a per-mode/per-TOS breakdown view, if a user wants more
  than the agency-total annual series this MVP charts (out of scope per
  this plan's Scope).
