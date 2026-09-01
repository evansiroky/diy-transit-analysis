# Architecture

Foundational tech decisions for `diy-transit-analysis`. This is a Python
CLI/library toolkit, not a service — see
[principles.md#local-files-as-the-unit-of-state](principles.md#local-files-as-the-unit-of-state).

## Language & packaging

- **Python 3.11+.** Matches the sibling `gtfs-rt-to-tides` project's
  ecosystem (protobuf/pandas-heavy transit tooling) for consistency across
  this user's transit projects.
- **Standard `src/` layout**, packaged with `pyproject.toml` (PEP 621,
  setuptools backend). Package name/import root: `diy_transit_analysis`.
- Dependencies are pinned in `pyproject.toml` `[project.dependencies]` and
  mirrored into `requirements.txt` for users who prefer
  `pip install -r requirements.txt` without an editable install (matches
  the `requirements.txt` convention used in `gtfs-rt-to-tides`).

```
diy-transit-analysis/
├── pyproject.toml
├── requirements.txt
├── README.md
├── config/
│   └── example.yaml
├── src/
│   └── diy_transit_analysis/
│       ├── __init__.py
│       ├── cli.py                 # CLI entrypoint (argparse subcommands)
│       ├── config.py              # config loading + validation
│       ├── gtfs/
│       │   ├── __init__.py
│       │   └── schedule.py        # fetch + parse GTFS Schedule feeds
│       ├── tides/
│       │   ├── __init__.py
│       │   └── historic.py        # fetch historic TIDES data
│       ├── ntd/
│       │   ├── __init__.py
│       │   └── timeseries.py      # fetch + parse NTD Time Series data files
│       └── report/
│           ├── __init__.py
│           ├── on_time_performance.py
│           ├── html_charts.py     # shared inline-SVG chart/table rendering, used by dashboard.py and ntd.py
│           ├── dashboard.py
│           └── ntd.py
├── tests/
├── specs/
└── plans/
```

## Config file format

**YAML, keyed by agency name** — the same shape as `gtfs-rt-to-tides`'s
`config/example_download_config.json` (JSON there; YAML here for
human-editable comments, but the *shape* — a top-level map keyed by
agency/feed name, each value holding source URLs — is intentionally
preserved for cross-project consistency, per
[principles.md#config-driven-agency-onboarding](principles.md#config-driven-agency-onboarding)).

```yaml
output_dir: output

# National, agency-independent NTD Time Series source files — see "NTD Time
# Series data access" below. Whole block optional; each entry is one sheet
# of one landing page's workbook, becoming one chart, grouped into the
# `report ntd` HTML report by its category. Entries sharing a product_url
# are fetched once (the download is the same file for both).
ntd:
  time_series:
    - name: "Unlinked Passenger Trips"
      category: service
      product_url: "https://www.transit.dot.gov/ntd/data-product/ts21-service-data-and-operating-expenses-time-series-mode-2"
      sheet: "UPT"
    - name: "Vehicle Revenue Hours"
      category: service
      product_url: "https://www.transit.dot.gov/ntd/data-product/ts21-service-data-and-operating-expenses-time-series-mode-2"
      sheet: "VRH"

agencies:
  SacRT:
    gtfs_schedule_url: "https://gtfs.sacrt.com/current/google_transit.zip"
    ntd_id: "90019"  # FTA's 5-digit NTD ID for this agency — see data-model.md#config-file
    tides:
      # See "TIDES data access" below — this shape is our best current
      # understanding of the live portal, not a verified API contract.
      gcs_bucket: "tides-prod-<agency-bucket-suffix>"       # ASSUMED, verify
      gcp_billing_project: "your-own-gcp-project-id"        # user-provisioned
      agency_prefix: "SacRT"
    date_range:
      start: "2026-01-01"
      end: "2026-03-31"

  # A GTFS-only agency: `tides:` and `date_range:` are both optional blocks
  # (see specs/behaviors/config-validation.md). This agency supports
  # `fetch-gtfs`, `report schedule-stats`, and the GTFS-only portion of
  # `run` — but not `fetch-tides` or `report otp`, since those need a
  # requester-pays GCP project and a reporting window this agency hasn't
  # configured.
  SmallTownTransit:
    gtfs_schedule_url: "https://example.org/gtfs/current.zip"
```

Adding an agency is adding a new top-level key under `agencies:` — no code
change required (config-driven onboarding principle). Adding an NTD metric
to chart is likewise adding one entry to the top-level `ntd.time_series:`
list — no code change required, per
[principles.md#config-driven-agency-onboarding](principles.md#config-driven-agency-onboarding)
(generalized here from "agency" to "metric source": the `report ntd`
output is entirely a function of what's listed in config, not of anything
hard-coded about which NTD files exist).

## GTFS Schedule feed fetch + parse

- **Library: [`gtfs-kit`](https://github.com/mrcagney/gtfs_kit)** (built on
  `pandas` + `shapely`). Chosen over hand-rolled `zipfile` + `csv`/`pandas`
  because this project needs standard GTFS derived metrics (route/trip
  lookups, calendar-aware service dates) that `gtfs-kit` already implements
  correctly and tests against edge cases (overlapping calendars,
  calendar_dates exceptions) that are easy to get subtly wrong by hand.
  Trade-off accepted: an extra dependency, in exchange for not
  re-implementing GTFS calendar logic — consistent with
  [principles.md#reproducibility-over-cleverness](principles.md#reproducibility-over-cleverness).
- Fetch: plain HTTP GET (`requests`) of `gtfs_schedule_url` to a temp file,
  then `gtfs_kit.read_feed(path, dist_units="km")`.
- No caching layer in the MVP — every run re-downloads. Revisit if/when
  repeated runs against the same feed snapshot become a real cost.

## TIDES historic data access

**Caltrans' TIDES portal (`tides.dds.dot.ca.gov`) publishes historical
transit operations data (vehicle locations, passenger counts, fare
transactions, and — per the TIDES spec suite at tides-transit.org — trip
performance / stop event data) as files in a Google Cloud Storage
requester-pays bucket.** There is no conventional REST download API; a
caller supplies their *own* GCP project (with billing enabled) to cover
small egress costs, and reads objects directly out of the bucket (via
`gsutil`/`google-cloud-storage`, using `userProject=<your project>` on each
request).

**This is based on published TIDES/Caltrans documentation review, not a
working integration test against the live bucket — verify the actual
bucket name, path/partitioning scheme, and file format against the live
endpoint before relying on it for real reporting.** The MVP's
`tides/historic.py` module is written against this assumption and says so
at the point of use (see
[principles.md#fail-loud-on-unverified-assumptions](principles.md#fail-loud-on-unverified-assumptions)).

Working assumptions, all flagged for verification:

- Data is partitioned per-agency, likely per-bucket-or-prefix-per-agency
  (config's `tides.gcs_bucket` / `tides.agency_prefix` fields capture this
  uncertainty rather than assuming one universal bucket layout).
- File format within TIDES is CSV (matches the `gtfs-rt-to-tides` sibling
  project's own TIDES CSV output, e.g. `tides_output/output.csv`, which
  this toolkit is a natural downstream consumer of/analogue to).
- Access library: `google-cloud-storage` Python client, with
  `Bucket(..., user_project=<gcp_billing_project>)` to satisfy
  requester-pays billing.

## NTD Time Series data access

**The Federal Transit Administration publishes "Time Series" data
products** on `transit.dot.gov`'s NTD Data page — downloadable
spreadsheets, each covering every NTD-reporting agency across every year
the metric has been collected (service, financial, and asset/fleet
metrics going back to 1991 for the oldest series). Unlike GTFS or TIDES,
this data is **agency-independent at fetch time**: one file covers every
agency, and per-agency reporting is a filter applied at analysis time by
the agency's **NTD ID** (a 5-digit code FTA assigns per reporting
agency — SacRT's is `90019`).

**There is no stable direct download URL for an NTD Time Series
file.** Each data product lives at a stable *landing page* URL (e.g.
`https://www.transit.dot.gov/ntd/data-product/ts21-service-data-and-
operating-expenses-time-series-mode-2`), but the actual `.xlsx` file
linked from that page moves on every FTA release (a
`/sites/fta.dot.gov/files/<release-date>/<Title>_<version>.xlsx`-style
path). So fetching means **scraping the landing page for the current
download link**, not requesting a fixed file URL. Confirmed via
[cal-itp/data-infra](https://github.com/cal-itp/data-infra)'s production
NTD ingestion pipeline (`airflow/plugins/hooks/ntd_xlsx_hook.py`,
`airflow/dags/download_and_parse_ntd_xlsx.py`) — Caltrans' own transit
data team, which runs this exact scrape weekly against the real
endpoint. This project's `ntd/timeseries.py` follows the same mechanism:
GET the landing page, find the `<a>` tag whose
`type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"`,
and download its `href` — a plain HTTP GET each time, no auth, matching
[principles.md#public-data-only](principles.md#public-data-only).

**Each data product is one workbook with multiple sheets**, one sheet
per metric (also confirmed via cal-itp/data-infra's ingestion, which
reads every sheet with `pandas.read_excel(..., sheet_name=None)` and
loads each as its own table). A config entry therefore names both the
landing page (`product_url`) and which `sheet` within that workbook it
wants — see [data-model.md#config-file](data-model.md#config-file).
Multiple entries sharing the same `product_url` are fetched **once**
(deduplicated by landing page) since they're genuinely the same
download.

**Every metric to chart is still a config entry**: `name` (chart title),
`category` (`service`/`funding`/`expenditure`/`asset` — which `report
ntd` section it lands in), `product_url`, and `sheet`. This is the same
config-driven-onboarding principle GTFS/TIDES agencies already follow,
generalized from "agency" to "metric source" — see
[architecture.md#config-file-format](#config-file-format) above. Four
`product_url` landing pages, confirmed live and hard-coded in
cal-itp/data-infra's own DAG, cover this project's default chart set
(`config/example.yaml`):

| Landing page slug | Category of its sheets |
|---|---|
| `ts21-service-data-and-operating-expenses-time-series-mode-2` | service (`UPT`, `VRH`, `VOMS`, `VRM`, `PMT`, `DRM`) + expenditure (`OpExp_Total`, and the `OpExp_*` breakdowns) |
| `ts12-operating-funding-time-series-3` | funding (`Operating_Total`, `Capital_Total`, and the federal/state/local/other breakdowns) |
| `ts31-capital-expenditures-time-series-2` | expenditure (`Total`, and the facilities/rolling-stock/other breakdowns) |
| `ts41-asset-inventory-time-series-4` | asset (`Active_Fleet`, `Avg_Fleet_Age`, and related fleet breakdowns) |

**What's confirmed vs. still assumed** (per
[principles.md#fail-loud-on-unverified-assumptions](principles.md#fail-loud-on-unverified-assumptions)):
the base URL, the four landing-page slugs above, the scrape-the-landing-
page mechanism, and "one workbook, many sheets" are all confirmed by
reading a real, actively-run production consumer's source and recorded
HTTP-interaction test fixtures (`transit.dot.gov` itself was
egress-blocked in this session, so this project still hasn't made its
own live request against it). **Not confirmed**: the exact literal sheet
tab names (`config/example.yaml`'s `sheet:` values are inferred from
cal-itp's BigQuery-safe column/table names, e.g. a dbt model named
`..._time_series_by_mode__upt` implies a sheet along the lines of
`UPT`, but the precise capitalization/spacing wasn't observed directly).
Sheet-name matching in `ntd/timeseries.py` is therefore
case/punctuation-insensitive (normalizes to lowercase alphanumerics
before comparing) rather than exact-string, and fails loudly — listing
every sheet the workbook actually has — when nothing matches, so a wrong
guess surfaces immediately instead of misreading the wrong sheet
silently.

- Within a sheet, the shape is a **wide** table: one row per reporting
  agency (further broken out by mode/type-of-service in some files), one
  column identifying the agency by **NTD ID**, and one column per
  **year** holding that metric's value for that agency in that year.
- The NTD ID column is found by matching a small set of known header
  aliases (case-insensitive) — column header text is unconfirmed too.
  Year columns are found by testing whether a header parses as a bare
  4-digit year, not by hard-coding an exact expected column list. See
  [data-model.md#ntd-time-series-data-on-disk-fetched](data-model.md#ntd-time-series-data-on-disk-fetched)
  for the full parsing rule.
- A sheet may have more than one row for the configured NTD ID (e.g. one
  row per mode or type-of-service); these are summed per year to produce
  one agency-total annual series, matching how NTD's own summary
  statistics aggregate mode/TOS breakdowns into agency totals.
- Before relying on this for real public reporting, run `fetch-ntd`
  against the live endpoint and verify actual downloaded/parsed sheets
  against this assumed shape, updating this section accordingly.

## Output format

- **CSV** for report output — matches `gtfs-rt-to-tides`'s own output
  convention and is directly shareable with journalists/advocates without
  extra tooling.
- Reports land under `<output_dir>/reports/<agency>/<report-name>-<date
  range>.csv`, per
  [principles.md#local-files-as-the-unit-of-state](principles.md#local-files-as-the-unit-of-state).
- Parquet is not used in the MVP — CSV's universal readability outweighs
  the size/type-fidelity benefits of Parquet at this project's data
  volumes (single-agency, single-quarter runs). Revisit if multi-agency,
  multi-year runs make CSV file size or type round-tripping a real
  problem.

## CLI entrypoint shape

Single console-script entrypoint `diy-transit-analysis`, argparse
subcommands, one per pipeline stage — mirrors `gtfs-rt-to-tides`'s
pattern of one script per stage, but collapsed into subcommands of one
installed console script rather than separate top-level scripts, since
this project is packaged (`pip install`-able) rather than run in place:

```
diy-transit-analysis fetch-gtfs            --config config/example.yaml --agency SacRT
diy-transit-analysis fetch-tides           --config config/example.yaml --agency SacRT
diy-transit-analysis fetch-ntd             --config config/example.yaml --agency SacRT
diy-transit-analysis report otp            --config config/example.yaml --agency SacRT
diy-transit-analysis report schedule-stats --config config/example.yaml --agency SacRT
diy-transit-analysis report html           --config config/example.yaml --agency SacRT
diy-transit-analysis report ntd            --config config/example.yaml --agency SacRT
diy-transit-analysis run                   --config config/example.yaml --agency SacRT
```

Each subcommand reads the same config file and an `--agency` selector
(`fetch-ntd`'s fetch step itself is agency-independent — see
[architecture.md#ntd-time-series-data-access](#ntd-time-series-data-access)
— but it still takes `--agency` for CLI-shape consistency and to validate
the selector). `report otp` (on-time performance), `report schedule-stats`
(GTFS-only scheduled-service stats, see
[data-model.md#gtfs-schedule-stats-report-output](data-model.md#gtfs-schedule-stats-report-output)),
`report html` (a static HTML dashboard combining schedule and, when
available, TIDES stats — see
[data-model.md#static-html-dashboard-report-output](data-model.md#static-html-dashboard-report-output)),
and `report ntd` (a static HTML report of NTD Time Series trend charts —
see
[data-model.md#ntd-time-series-report-output](data-model.md#ntd-time-series-report-output))
are the MVP's four report types.

### The `report html` dashboard's rendering approach

`report html` renders its own charts as inline SVG built directly by
Python string formatting — no charting library, no JavaScript framework,
no CDN font or script. This keeps the output file self-contained per
[principles.md#local-files-as-the-unit-of-state](principles.md#local-files-as-the-unit-of-state):
it opens correctly from a `file://` URL or an email attachment with zero
network requests. A small amount of inline, dependency-free `<script>` is
used only for hover/crosshair affordances on the two charts — every value
it can show is also present in a plain HTML `<table>` on the same page
(inside a collapsed `<details>`), so nothing is reachable only by
hovering, and the page degrades to fully static (still fully readable)
with JavaScript disabled. `report ntd` renders with the same approach,
via the shared helpers in `report/html_charts.py` (see
[data-model.md#ntd-time-series-report-output](data-model.md#ntd-time-series-report-output)).

### The `run` subcommand

`run` is the one-command entry point most users reach for: it composes the
individual fetch/report subcommands above so a user doesn't have to know
the pipeline order or which reports their config supports. For the
selected `--agency`, it:

1. Always fetches the GTFS Schedule feed (`fetch-gtfs`'s behavior).
2. Fetches TIDES historic data (`fetch-tides`'s behavior) **only if** the
   agency has a `tides:` block configured.
3. Always generates the `schedule-stats` report — it only needs the GTFS
   feed just fetched, per
   [behaviors/config-validation.md](behaviors/config-validation.md)'s
   optional-`tides`/`date_range` rule.
4. Generates the `otp` report **only if** the agency has both `tides:`
   and `date_range:` configured (both are required for that report's
   join). Otherwise `run` prints which report(s) it skipped and why,
   rather than failing the whole command — an agency that only configured
   `gtfs_schedule_url` gets a complete, successful `run` that produces its
   one available report.
5. Always generates the `html` dashboard report — its schedule section
   needs only the GTFS feed, same as `schedule-stats`; its TIDES
   benchmarks section is included automatically when step 4 ran, and
   omitted (with a note) otherwise.
6. Fetches NTD Time Series data (`fetch-ntd`'s behavior) and generates the
   `ntd` report **only if** the config has a top-level `ntd:` block *and*
   the agency has `ntd_id:` configured (both are required — the shared
   source files without an agency selector to filter by are useless, and
   vice versa). Otherwise `run` prints which step(s) it skipped and why,
   same as step 4.

`run` never partially fails silently: every step it takes or skips is
printed, and any step it does attempt fails loudly the same way the
equivalent standalone subcommand would (see
[behaviors/config-validation.md](behaviors/config-validation.md)).

## Testing

`pytest`, tests under `tests/`, no live network calls in the default test
run — network-touching code is exercised against small local fixture
files (a trimmed real GTFS zip, a sample TIDES CSV, small hand-built NTD
Time Series CSV/xlsx fixtures) rather than hitting live endpoints in CI.
