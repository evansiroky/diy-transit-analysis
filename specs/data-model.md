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
| `agencies.<name>.tides`             | map    | no       | Whole block is optional — omit it entirely for a GTFS-only agency (see [behaviors/config-validation.md](behaviors/config-validation.md)). An agency without `tides:` supports `fetch-gtfs`, `report schedule-stats`, and the GTFS-only portion of `run`, but not `fetch-tides` or `report otp`. |
| `agencies.<name>.tides.gcs_bucket`  | string | yes, if `tides:` present | GCS bucket (or bucket+prefix) holding this agency's TIDES data. **Assumed shape — see architecture.md "TIDES historic data access".** |
| `agencies.<name>.tides.gcp_billing_project` | string | yes, if `tides:` present | The *user's own* GCP project ID, billed for requester-pays egress. Never committed with real credentials — this is a project ID, not a secret, but the config file itself should still not be treated as safe to publish if it contains a real project ID tied to billing. |
| `agencies.<name>.tides.agency_prefix` | string | no     | Object-key prefix within the bucket, if the bucket is shared across agencies. |
| `agencies.<name>.date_range`        | map    | no       | Whole block is optional, independently of `tides:`. Required only for `report otp`, which needs a reporting window; `report schedule-stats` needs no date range at all (see [below](#gtfs-schedule-stats-report-output)). |
| `agencies.<name>.date_range.start`  | date (`YYYY-MM-DD`) | yes, if `date_range:` present | Inclusive start of the reporting window. |
| `agencies.<name>.date_range.end`    | date (`YYYY-MM-DD`) | yes, if `date_range:` present | Inclusive end of the reporting window. |

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

## GTFS Schedule stats report (output)

CSV, one row per **route**, computed entirely from a fetched GTFS Schedule
feed — no TIDES data and no user-configured `date_range` required (unlike
the on-time-performance report above). This is what `report
schedule-stats` and the GTFS-only portion of `run` produce for an agency
that has configured nothing beyond `gtfs_schedule_url`.

Since GTFS feeds don't carry a natural "reporting window" of their own,
this report scopes its per-route trip/frequency stats to the feed's own
**representative week**: the first Monday–Sunday week (or initial segment
thereof) for which the feed's calendar is valid. This keeps the report
fully reproducible from the feed alone (per
[principles.md#reproducibility-over-cleverness](principles.md#reproducibility-over-cleverness))
— it never depends on the wall-clock date the report happens to be run.

| Column                       | Type    | Meaning |
|-------------------------------|---------|---------|
| `agency`                      | string  | Agency name from config. |
| `feed_start_date`              | date    | Earliest date the feed's calendar (`calendar`/`calendar_dates`) is valid for. |
| `feed_end_date`                | date    | Latest such date. |
| `route_id`                     | string  | GTFS `route_id`. |
| `route_short_name`             | string  | GTFS `route_short_name` (falls back to `route_id` if blank). |
| `route_type`                   | integer | GTFS `route_type` (e.g. `3` = bus, `2` = rail). |
| `stop_count`                   | integer | Count of distinct stops served by any trip on this route, across the whole feed. |
| `representative_week_start`    | date    | Start (Monday) of the representative week used for the columns below. |
| `service_day_count`            | integer | Number of days within the representative week (0–7) on which the route has at least one scheduled trip. |
| `trip_count`                   | integer | Total scheduled trips for the route across the representative week. |
| `avg_trips_per_service_day`    | float   | `trip_count / service_day_count`, `null` if `service_day_count == 0`. |
| `first_departure_time`         | string (`HH:MM:SS`) | Earliest scheduled departure time-of-day for the route, across the whole feed. Per GTFS convention, hours may exceed `24:00:00` for a trip that departs after midnight relative to its service day. |
| `last_departure_time`          | string (`HH:MM:SS`) | Latest scheduled departure time-of-day for the route, across the whole feed. Same `HH` convention as above. |

If the feed has no calendar information at all (`calendar` and
`calendar_dates` both empty), the report cannot be computed — this fails
loudly per
[principles.md#fail-loud-on-unverified-assumptions](principles.md#fail-loud-on-unverified-assumptions)
rather than emitting a report of nulls.
