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
│       └── report/
│           ├── __init__.py
│           └── on_time_performance.py
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
agencies:
  SacRT:
    gtfs_schedule_url: "https://gtfs.sacrt.com/current/google_transit.zip"
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
change required (config-driven onboarding principle).

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
diy-transit-analysis report otp            --config config/example.yaml --agency SacRT
diy-transit-analysis report schedule-stats --config config/example.yaml --agency SacRT
diy-transit-analysis report html           --config config/example.yaml --agency SacRT
diy-transit-analysis run                   --config config/example.yaml --agency SacRT
```

Each subcommand reads the same config file and an `--agency` selector.
`report otp` (on-time performance), `report schedule-stats` (GTFS-only
scheduled-service stats, see
[data-model.md#gtfs-schedule-stats-report-output](data-model.md#gtfs-schedule-stats-report-output)),
and `report html` (a static HTML dashboard combining schedule and, when
available, TIDES stats — see
[data-model.md#static-html-dashboard-report-output](data-model.md#static-html-dashboard-report-output))
are the MVP's three report types.

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
with JavaScript disabled.

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

`run` never partially fails silently: every step it takes or skips is
printed, and any step it does attempt fails loudly the same way the
equivalent standalone subcommand would (see
[behaviors/config-validation.md](behaviors/config-validation.md)).

## Testing

`pytest`, tests under `tests/`, no live network calls in the default test
run — network-touching code is exercised against small local fixture
files (a trimmed real GTFS zip, a sample TIDES CSV) rather than hitting
live endpoints in CI.
