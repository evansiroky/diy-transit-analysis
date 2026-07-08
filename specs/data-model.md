# Data Model

Config schema, intermediate data shapes, and report output shape. See
[architecture.md](architecture.md) for the tech decisions these shapes sit
on top of.

## Config file

Top-level YAML document, loaded by `diy_transit_analysis.config`.

| Field                              | Type   | Required | Notes |
|-------------------------------------|--------|----------|-------|
| `output_dir`                        | string | yes      | Root dir for all fetched data + reports. Relative paths resolve from the config file's own directory. |
| `agencies.<name>`                   | map    | yes, ≥1  | Key is a free-form agency identifier, e.g. `SacRT`. Used to namespace output paths. |
| `agencies.<name>.gtfs_schedule_url` | string | yes      | Public URL to a GTFS Schedule `.zip`. |
| `agencies.<name>.tides.gcs_bucket`  | string | yes      | GCS bucket (or bucket+prefix) holding this agency's TIDES data. **Assumed shape — see architecture.md "TIDES historic data access".** |
| `agencies.<name>.tides.gcp_billing_project` | string | yes | The *user's own* GCP project ID, billed for requester-pays egress. Never committed with real credentials — this is a project ID, not a secret, but the config file itself should still not be treated as safe to publish if it contains a real project ID tied to billing. |
| `agencies.<name>.tides.agency_prefix` | string | no     | Object-key prefix within the bucket, if the bucket is shared across agencies. |
| `agencies.<name>.date_range.start`  | date (`YYYY-MM-DD`) | yes | Inclusive start of the reporting window. |
| `agencies.<name>.date_range.end`    | date (`YYYY-MM-DD`) | yes | Inclusive end of the reporting window. |

See [behaviors/config-validation.md](behaviors/config-validation.md) for
validation rules.

## GTFS Schedule (in-memory)

Parsed via `gtfs-kit` into its standard `Feed` object (a bundle of pandas
DataFrames keyed by GTFS table name — `routes`, `trips`, `stop_times`,
`calendar`, `calendar_dates`, etc). This project does not redefine that
shape; it consumes `gtfs-kit`'s own schema as documented upstream. No
custom GTFS data model is maintained here — avoids a second source of
truth for a spec (GTFS) this project doesn't own.

## TIDES historic data (on disk, fetched)

Fetched TIDES files are saved verbatim under
`<output_dir>/<agency>/tides/raw/` with their original object names from
the bucket, unmodified. This project does not currently re-model TIDES
fields — see architecture.md's flagged assumption that TIDES ships trip
performance / stop event records as CSV. Once the live bucket layout is
verified, this section should grow a table of the actual TIDES columns
this project reads (at minimum: scheduled vs. actual trip start/end time,
trip/stop identifiers, and a cancelled/completed flag, since those are
what on-time-performance and cancellation-rate calculations need).

## On-time performance report (output)

CSV, one row per **route** for the configured date range (the MVP's
grain — see `plans/otp-report.md` for why route-level, not
trip-level, is the MVP scope).

| Column                  | Type    | Meaning |
|--------------------------|---------|---------|
| `agency`                 | string  | Agency name from config. |
| `route_id`                | string  | GTFS `route_id`. |
| `route_short_name`        | string  | GTFS `route_short_name` (falls back to `route_id` if blank). |
| `date_range_start`        | date    | From config. |
| `date_range_end`          | date    | From config. |
| `scheduled_trip_count`     | integer | Count of scheduled trips for this route in the window, from GTFS Schedule + service calendar. |
| `performed_trip_count`     | integer | Count of trips TIDES reports as performed (not cancelled) for this route in the window. |
| `on_time_trip_count`       | integer | Count of performed trips within the on-time threshold (see below). |
| `on_time_percent`          | float   | `on_time_trip_count / performed_trip_count`, `null` if `performed_trip_count == 0`. |
| `cancellation_percent`     | float   | `1 - (performed_trip_count / scheduled_trip_count)`, `null` if `scheduled_trip_count == 0`. |

**On-time threshold**: a performed trip is on-time if its actual departure
from its scheduled timepoints is within **-1 to +5 minutes** of scheduled
time (early is worse than late, matching common US transit-agency OTP
convention — e.g. WMATA/MBTA-style windows). This is a fixed constant for
the MVP, not yet configurable; see `plans/otp-report.md` Follow-ups if it
needs to become one.

Every value in this table must be reproducible from the same GTFS +
TIDES inputs (per
[principles.md#reproducibility-over-cleverness](principles.md#reproducibility-over-cleverness))
— no randomness, no unlogged interpolation of missing data.
