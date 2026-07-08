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
diy-transit-analysis fetch-gtfs   --config config/example.yaml --agency SacRT
diy-transit-analysis fetch-tides  --config config/example.yaml --agency SacRT
diy-transit-analysis report otp   --config config/example.yaml --agency SacRT
```

Each subcommand reads the same config file and an `--agency` selector;
`report otp` (on-time performance) is the MVP's one report type.

## Testing

`pytest`, tests under `tests/`, no live network calls in the default test
run — network-touching code is exercised against small local fixture
files (a trimmed real GTFS zip, a sample TIDES CSV) rather than hitting
live endpoints in CI.
