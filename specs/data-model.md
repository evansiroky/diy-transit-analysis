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
| `agencies.<name>.ntd_id`            | string | no       | FTA's 5-digit NTD ID for this agency (e.g. `"90019"` for SacRT), used to filter the national NTD Time Series files down to this agency. Independent of `tides:`/`date_range:`. `report ntd` and the NTD portion of `run` require both this *and* the top-level `ntd:` block below; `fetch-ntd` needs only the top-level block (it fetches agency-independent files — see [architecture.md#ntd-time-series-data-access](architecture.md#ntd-time-series-data-access)). |
| `ntd`                                | map    | no       | Top-level (not per-agency) — whole block optional. Configures the national NTD Time Series source files, shared across every agency. |
| `ntd.time_series`                    | list   | yes, if `ntd:` present | List of metric sources to fetch and chart. Each entry becomes exactly one chart in `report ntd`'s output — see [below](#ntd-time-series-report-output). Adding/removing a metric is purely a config change, per [architecture.md#config-file-format](architecture.md#config-file-format). |
| `ntd.time_series[].name`             | string | yes      | Human-readable metric name — used verbatim as the chart title. |
| `ntd.time_series[].category`         | string, one of `service`/`funding`/`expenditure`/`asset` | yes | Which `report ntd` section this metric's chart is grouped into (see [below](#ntd-time-series-report-output)). |
| `ntd.time_series[].product_url`      | string | yes      | Public URL of the NTD data product's **landing page** (e.g. `https://www.transit.dot.gov/ntd/data-product/ts21-...`) — not a direct file link; the actual `.xlsx` download link is scraped from this page at fetch time, since FTA doesn't publish a stable one (see [architecture.md#ntd-time-series-data-access](architecture.md#ntd-time-series-data-access)). Entries sharing the same `product_url` are fetched once, since it's the same workbook. |
| `ntd.time_series[].sheet`            | string | no       | Which sheet/tab of the (possibly multi-sheet) downloaded workbook holds this metric. Matched case/punctuation-insensitively (see [below](#ntd-time-series-data-on-disk-fetched)). Omit for a workbook with a single relevant sheet — defaults to the first sheet. |

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

**ASSUMED, NOT VERIFIED** — the "trips performed" CSV consumed by
`report otp` and `report html`'s `trips_performed` stat is read against
this column set:

| Column | Required | Meaning |
|--------|----------|---------|
| `route_id`, `trip_id` | yes | Identify the trip, matched against GTFS `route_id`. |
| `scheduled_departure`, `actual_departure` | yes | Used for the on-time-performance join (see below). |
| `cancelled` | yes | Excludes the row from `performed_trip_count`/`trips_performed` when true. |

A fetched TIDES directory may hold more than one distinct CSV shape (see
the two additional shapes below) — a file is read as "trips performed"
only if it carries every column in this table; a `.csv` file missing one
is skipped for this read (not an error), since it likely belongs to one
of the other shapes. Every shape this project reads is identified purely
by which columns a file has — there's no filename convention to rely on
(per [principles.md#fail-loud-on-unverified-assumptions](principles.md#fail-loud-on-unverified-assumptions),
this is still "loud" in the sense that a file is only ever claimed by a
shape it exactly matches; nothing is coerced or guessed).

### TIDES data for the ETA benchmarks (assumed, separate files)

`report html`'s two ETA benchmarks — `realtime_completeness_percent` and
`eta_accuracy_percent` — implement the published, agency-neutral
methodologies of the
[ETA Completeness Benchmark](https://github.com/SwiftlyInc/ETA-Completeness-Benchmark)
and the
[ETA Accuracy Benchmark](https://github.com/TransitApp/ETA-Accuracy-Benchmark)
exactly (formulas and thresholds below are quoted from those specs, not
invented here). Both operate at **trip-stop** grain and need multiple
timestamped prediction samples per trip-stop — a materially richer shape
than the trip-level "trips performed" CSV above, which cannot represent
either benchmark. This project therefore assumes TIDES exposes two
**additional, separate** CSV shapes for this purpose, identified by which
columns a fetched file has (same duck-typing convention as every other
TIDES read in this project — a file can be either shape, and a TIDES
fetch directory may contain any mix of all three). **Both shapes are
entirely unverified against a real TIDES sample** — more so than the
"trips performed" columns above, which at least share their trip/route
identifiers with a verified-live GTFS fetch; see
[principles.md#fail-loud-on-unverified-assumptions](principles.md#fail-loud-on-unverified-assumptions).

**`trip_stop_outcomes`** — one row per scheduled trip-stop actually
observed by TIDES on a given service day:

| Column | Required | Meaning |
|--------|----------|---------|
| `service_date` | yes | `YYYY-MM-DD`. The specific calendar day this row happened on (GTFS-rt is dated real-world activity, unlike static GTFS Schedule). |
| `trip_id`, `stop_id` | yes | Identify the scheduled trip-stop, matched against GTFS `trips.txt` and `stop_times.txt`. |
| `vehicle_assigned` | yes | Boolean-ish — whether an AVL vehicle was assigned to the trip. |
| `trip_cancelled` | yes | Boolean-ish — the GTFS-rt `CANCELED` designation for the trip. |
| `stop_skipped` | yes | Boolean-ish — the GTFS-rt `SKIPPED` designation for the stop. |
| `actual_arrival` | no | Timestamp — when the vehicle actually reached the stop. Absent/blank if the trip never served this stop (cancelled, skipped, or otherwise didn't run). |

**`predictions`** — one row per GTFS-Realtime TripUpdate prediction
*sample* (a trip-stop can and typically will have many rows, one per time
the feed was polled/observed while the prediction was live):

| Column | Required | Meaning |
|--------|----------|---------|
| `service_date`, `trip_id`, `stop_id` | yes | Same meaning as above — which scheduled trip-stop this prediction was for. |
| `sampled_at` | yes | Timestamp — when this prediction was recorded/observed. |
| `predicted_arrival` | yes | Timestamp — the ETA predicted as of `sampled_at`. |

Once real TIDES data is fetchable, both shapes (and the formulas in
[the dashboard report section](#static-html-dashboard-report-output)
below) need re-verification against it, same as every other TIDES
assumption in this project (see `plans/data-fetch.md`'s still-open
bucket-verification Follow-up).

## NTD Time Series data (on disk, fetched)

Fetching a `ntd.time_series[]` entry is two steps, per
[architecture.md#ntd-time-series-data-access](architecture.md#ntd-time-series-data-access):

1. **Resolve the download link**: GET `product_url` (an HTML landing
   page), find the `<a>` element whose `type` attribute is
   `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`,
   and take its `href` as the real, current `.xlsx` download URL. A page
   with no such link is a loud failure (`NtdDataError`) — the landing
   page structure has changed and this project's scrape assumption needs
   revisiting.
2. **Download that link** and save the workbook to
   `<output_dir>/ntd/raw/<slug-of-product_url's-landing-page-path>.xlsx`
   — **not** namespaced under an agency directory, since these files are
   national/agency-independent. Every `ntd.time_series[]` entry sharing a
   `product_url` resolves to the same local file — the download happens
   once per unique `product_url`, not once per entry.

`report ntd` reads from this shared directory and filters to one agency
(and one sheet) at analysis time.

**Confirmed** (see
[architecture.md#ntd-time-series-data-access](architecture.md#ntd-time-series-data-access)
for the cal-itp/data-infra evidence this rests on): the workbook has
**multiple sheets**, one per metric. `ntd.time_series[].sheet` selects
which one — matched against the workbook's actual sheet names
**case/punctuation-insensitively** (both sides normalized to lowercase
alphanumerics before comparing, e.g. configured `"OpExp Total"` matches
an actual tab named `"OpExp_Total"`), since the exact literal tab-name
casing/spacing is unconfirmed. No `sheet:` configured means "use the
first sheet" (fine for a workbook with only one relevant tab). A
`sheet:` that matches nothing in the workbook is a loud failure
(`NtdDataError`) listing every sheet name the workbook actually has, so
a wrong guess is immediately visible rather than silently reading the
wrong tab.

**ASSUMED, NOT VERIFIED against a live download this session** — within
a resolved sheet, the table is read with this structure:

| Column | Required | Meaning |
|--------|----------|---------|
| An NTD ID column | yes | Identifies the reporting agency. Detected by header, case-insensitively, against a small set of known aliases (`"ntd id"`, `"5 digit ntd id"`, `"ntdid"`) — not by an exact expected name, since the real header text is unverified. A sheet with no column matching any alias cannot be parsed for this metric — that's a loud failure (`NtdDataError`), not a skipped/empty result. |
| One or more year columns | yes, ≥1 | One column per reporting year, header parsing as a bare 4-digit integer between 1900–2100 (e.g. `2019`, `"2019"`, or a float-like `2019.0` header from a spreadsheet export). Any other column (agency name, mode, type-of-service, UZA, etc.) is ignored — this project does not need or model those breakdowns. |

**Per-agency annual series**: for a configured `ntd_id`, every row whose
NTD ID column matches (after stripping whitespace and any trailing `.0`
float artifact from a numeric-typed Excel column) contributes to that
metric's per-year value; when more than one row matches (e.g. a sheet
broken out by mode or type-of-service), values are **summed** per year
to produce one agency-total series — matching how NTD's own published
summary statistics aggregate mode/TOS breakdowns into agency totals. A
year column with no numeric value for any matching row is omitted from
the series for that year (not shown as zero), same convention as the
dashboard's "scheduled trips per service day" series
([above](#static-html-dashboard-report-output)). If the `ntd_id` matches
zero rows in a sheet, that metric's series is empty and its chart is
omitted with a note in `report ntd`'s output (see
[below](#ntd-time-series-report-output)) — this is a normal, non-error
outcome (a valid NTD ID legitimately absent from one particular sheet),
unlike the "no NTD ID column found at all" or "no matching sheet" cases
above, which mean the file/sheet couldn't be resolved and fail loudly
instead.

Before relying on this for real public reporting, run `fetch-ntd`
against the live endpoint and verify actual downloaded/parsed sheets
against this assumed shape, updating this section accordingly.

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

## Static HTML dashboard report (output)

A single self-contained `.html` file — no external stylesheet, script, or
font requests, so it renders correctly opened straight from disk or
emailed as an attachment (per
[principles.md#local-files-as-the-unit-of-state](principles.md#local-files-as-the-unit-of-state)).
Produced by `report html` and by `run` (always — its GTFS-only sections
need nothing beyond `gtfs_schedule_url`, matching `report
schedule-stats`'s config requirements). Written to
`<output_dir>/reports/<agency>/dashboard-<feed_start>-<feed_end>.html`.

The page has two parts:

### Schedule section (always present)

- **Feed overview**: agency name, `feed_start_date`/`feed_end_date` (same
  meaning as in [the schedule stats report](#gtfs-schedule-stats-report-output)),
  route/trip/stop counts.
- **Vehicles in service by time of day**, for the busiest date within the
  feed's [representative week](#gtfs-schedule-stats-report-output) (the
  same representative week the schedule stats report uses, so the two
  reports agree on which week is "representative"): a time-of-day series
  of the number of trips concurrently in service, plus the two headline
  numbers — `peak_vehicles` (the maximum concurrent count that day) and
  `peak_time` (when it's first reached).
- **Scheduled trips per service day**, across every date in
  `[feed_start_date, feed_end_date]` on which the feed schedules at least
  one trip: a `date -> trip_count` series (count of trips starting that
  date). Dates with zero scheduled service are omitted, not shown as
  zero-height points.

Both series are computed straight from the fetched GTFS feed, so — like
the schedule stats report — they're fully reproducible from the feed
alone and never depend on the wall-clock date the report is run.

### TIDES benchmarks section (conditional)

Present only when the agency has both `tides:` and `date_range:`
configured *and* TIDES data has already been fetched (same precondition
`report otp` already enforces — see
[behaviors/config-validation.md](behaviors/config-validation.md)). When
the agency didn't configure `tides:`/`date_range:` at all, the section is
omitted with a note saying so (matching `run`'s "skip and say why"
behavior); when it's configured but not yet fetched, `report html` fails
the same way `report otp` does (run `fetch-tides` first) rather than
silently omitting a section the user did ask for.

All values are computed over the configured `date_range` (filtering on
each source's `service_date`/`scheduled_departure`, as applicable).

| Stat | Meaning |
|------|---------|
| `trips_performed` | Count of performed (non-cancelled) trips in the window, system-wide (not per-route) — from the "trips performed" CSV `report otp` reads, per [above](#tides-historic-data-on-disk-fetched). |
| `realtime_completeness_percent` | The [ETA Completeness Benchmark](https://github.com/SwiftlyInc/ETA-Completeness-Benchmark) score — see formula below. |
| `eta_accuracy_percent` | The [ETA Accuracy Benchmark](https://github.com/TransitApp/ETA-Accuracy-Benchmark) score — see formula below. |

`trips_performed` is independent of the two benchmarks below — it's read
from a different assumed TIDES file (the trip-level "trips performed"
CSV), while the two benchmarks are read from the `trip_stop_outcomes` and
`predictions` files described
[above](#tides-data-for-the-eta-benchmarks-assumed-separate-files). Each
is `null` (with an on-page note) independently if its own required data
isn't present, rather than one missing file blanking the whole section.

#### ETA Completeness

Quoting the
[ETA Completeness Benchmark](https://github.com/SwiftlyInc/ETA-Completeness-Benchmark)
methodology exactly:

> ETA Completeness Score = (Complete trip-stops) / (All scheduled
> trip-stops)
>
> A scheduled trip-stop combination is considered **complete** if it
> meets either of the following conditions:
> 1. The trip had an assigned vehicle **and** at least one prediction
>    between 0–15 minutes out for that stop, OR
> 2. The trip had a `CANCELED` designation for the trip ID, or a
>    `SKIPPED` designation for the stop ID in the GTFS-rt trip updates
>    feed.
>
> All other scheduled trip-stop combinations are considered
> **incomplete**.

Applied to this project's data model:

- **All scheduled trip-stops** (the denominator) comes entirely from the
  fetched GTFS feed, not TIDES: for every date in `date_range`, every
  `(trip_id, stop_id)` pair for a trip actually scheduled that date (via
  GTFS Schedule + service calendar, the same calendar-aware expansion
  `scheduled_trip_count` uses in [the OTP report](#on-time-performance-report-output)).
  A `(date, trip_id, stop_id)` combination with **no** matching
  `trip_stop_outcomes` row at all is correctly counted here and, having
  no row, cannot be complete — this is exactly how a trip-stop that
  "silently disappeared" from TIDES gets caught.
- "**≥1 prediction between 0–15 minutes out for that stop**" is
  evaluated from the `predictions` file: for a given `(service_date,
  trip_id, stop_id)`, take every prediction's `sampled_at` and that
  trip-stop's `actual_arrival` (from `trip_stop_outcomes`); the prediction
  qualifies if `0 <= (actual_arrival - sampled_at) < 15 minutes`
  (half-open, matching the accuracy benchmark's own stated bucket-boundary
  convention below). A trip-stop with no `actual_arrival` (didn't run)
  cannot have a qualifying prediction under condition 1 — it can only be
  complete via condition 2.
- `null` if the denominator (scheduled trip-stops in the window) is `0`.

#### ETA Accuracy

Quoting the
[ETA Accuracy Benchmark](https://github.com/TransitApp/ETA-Accuracy-Benchmark)
methodology exactly (the "IBI Group" time-bucket / asymmetric-threshold
approach):

> 1. Creating a sample of predictions and actual arrivals
> 2. Bucketing each prediction into one of four time buckets depending on
>    how far away the vehicle was when the prediction was sampled
> 3. Categorizing each prediction ... as "accurate" or "inaccurate"
>    according to where it falls within the permitted accuracy thresholds
> 4. Calculating the accuracy percentage of each bucket ...
> 5. Calculating an overall prediction accuracy percentage by taking an
>    equally weighted average of the four buckets

| Time bucket (time-to-actual at sample time) | Accuracy threshold (actual − predicted) |
|---|---|
| 10–15 min away | −1.5 to +4.5 min |
| 6–10 min away | −1 to +3.5 min |
| 3–6 min away | −1 to +2.5 min |
| 0–3 min away | −0.5 to +1.5 min |

Applied to this project's data model, using the `predictions` and
`trip_stop_outcomes` files:

- For each prediction with a matching, non-null `actual_arrival`
  (predictions for a trip-stop that never ran have no ground truth and
  are excluded): `time_to_actual = actual_arrival - sampled_at` places it
  in a bucket. Per the source spec, **"time buckets exclude boundaries"**
  — `>= bucket start, < bucket end` — and a prediction whose
  `time_to_actual` is negative or `>= 15 minutes` falls in no bucket and
  is excluded.
- Accuracy: `variance = actual_arrival - predicted_arrival`; the
  prediction is accurate if `variance` falls within its bucket's
  threshold **inclusive on both ends**, per the source spec ("both a
  30-seconds early and a 90-seconds late prediction are considered
  accurate" for the 0–3 minute bucket).
- Per-bucket accuracy = accurate ÷ total predictions in that bucket, for
  buckets with at least one prediction.
- Overall `eta_accuracy_percent` = the straight (unweighted) average of
  the per-bucket accuracies across buckets that have at least one
  prediction. **Unstated by the source spec, decided here**: a bucket
  with zero predictions is excluded from the average entirely — it does
  not contribute a `0%` — since the source spec doesn't address the
  zero-sample case. `null` if every bucket is empty.

## NTD Time Series report (output)

A single self-contained `.html` file, same rendering approach (inline SVG
charts, no external requests) and same reasons as
[the static HTML dashboard](#static-html-dashboard-report-output) — see
[architecture.md#the-report-html-dashboards-rendering-approach](architecture.md#the-report-html-dashboards-rendering-approach).
Produced by `report ntd` and, when configured, by `run`. Requires the
selected agency to have `ntd_id:` configured, the top-level `ntd:` block
configured, and NTD Time Series data already fetched (`fetch-ntd`) — see
[behaviors/config-validation.md](behaviors/config-validation.md). Written
to `<output_dir>/reports/<agency>/ntd-<min_year>-<max_year>.html`, where
`min_year`/`max_year` are the earliest and latest years found across
every configured metric's data for this agency (not a user-configured
date range — NTD Time Series data has no natural "reporting window" of
its own beyond whatever years each file actually contains, so — like the
schedule-stats report anchoring on the feed's own representative week —
this report anchors on the fetched data's own year coverage rather than
requiring separate config, per
[principles.md#reproducibility-over-cleverness](principles.md#reproducibility-over-cleverness)).

**Structure**: one section per `category` (fixed order: **Service**,
**Expenditure**, **Funding**, **Asset**), each containing one chart per
`ntd.time_series[]` entry configured with that category, in config order.
A section with zero configured entries of its category is omitted
entirely; an entry whose fetched file yielded an empty series for this
agency's `ntd_id` (see
[above](#ntd-time-series-data-on-disk-fetched)) still gets its chart
slot, rendered as an on-page note ("no data for NTD ID `<id>` in this
file") rather than a broken/empty chart — same graceful-per-item-omission
convention as the dashboard's independently-optional TIDES stats.

Each chart is a year-on-the-x-axis line/area chart (the same
`_area_chart_svg` component the dashboard uses, via the shared
`report/html_charts.py` helpers) titled with the entry's configured
`name`, plus a collapsed data table beneath it (`year -> value`) with the
same "every value also reachable without hovering" rule as the dashboard.

The page's title bar states the agency name and the `ntd_id` used to
filter every chart on the page, so a reader can immediately see which
NTD ID's numbers they're looking at.

## Principles

**Inherited** — project principles from `principles.md` that especially
bite here:
- [Fail loud on unverified assumptions](principles.md#fail-loud-on-unverified-assumptions)
  — the TIDES benchmark columns above are the newest, least-verified part
  of this project's data model; every value derived from them says so
  (`null` + a note) rather than presenting a confident-looking number.
  The [NTD Time Series data shape](#ntd-time-series-data-on-disk-fetched)
  carries the same flag, for the same reason (network access to verify a
  live download wasn't available while this was written).
- [Reproducibility over cleverness](principles.md#reproducibility-over-cleverness)
  — both the schedule stats report and the HTML dashboard's schedule
  section anchor on the feed's own representative week rather than
  today's date, so re-running against the same fetched feed always
  produces the same numbers. The [NTD report](#ntd-time-series-report-output)'s
  filename does the equivalent: it anchors on the fetched data's own year
  range rather than a user-supplied or wall-clock date.
- [Config-driven agency onboarding](principles.md#config-driven-agency-onboarding)
  — generalized by the [NTD Time Series config](architecture.md#ntd-time-series-data-access)
  from "onboarding an agency" to "onboarding a chart": which NTD metrics
  get fetched and charted, and which report section each lands in, is
  entirely config (`ntd.time_series[]`), never a code change.
