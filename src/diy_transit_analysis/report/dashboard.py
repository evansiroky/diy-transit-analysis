"""Build the static HTML dashboard report.

Spec: specs/data-model.md#static-html-dashboard-report-output

Combines schedule-based stats (always available, GTFS-only) with
TIDES-based benchmark stats (only when the agency has tides: +
date_range: configured and TIDES has been fetched). Renders as a single
self-contained HTML file — inline SVG charts, no JS framework, no CDN —
per specs/architecture.md#the-report-html-dashboards-rendering-approach.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

import gtfs_kit as gk
import pandas as pd

from diy_transit_analysis.report import html_charts
from diy_transit_analysis.report import on_time_performance as otp
from diy_transit_analysis.report import schedule_stats

# ETA Accuracy Benchmark (https://github.com/TransitApp/ETA-Accuracy-Benchmark):
# four time-to-arrival buckets, each with its own asymmetric early/late
# tolerance. Order matches the source spec's own presentation (farthest
# out first). (label, bucket_low_min, bucket_high_min, early_tolerance,
# late_tolerance) — bucket range is [low, high) minutes-to-actual-arrival
# at the moment the prediction was sampled; tolerance is inclusive on
# both ends, per specs/data-model.md#eta-accuracy.
_ACCURACY_BUCKETS = [
    ("10-15 min away", 10, 15, timedelta(minutes=1.5), timedelta(minutes=4.5)),
    ("6-10 min away", 6, 10, timedelta(minutes=1), timedelta(minutes=3.5)),
    ("3-6 min away", 3, 6, timedelta(minutes=1), timedelta(minutes=2.5)),
    ("0-3 min away", 0, 3, timedelta(minutes=0.5), timedelta(minutes=1.5)),
]

# ETA Completeness Benchmark's "0-15 minutes out" qualifying window for a
# prediction — the union of the four accuracy buckets above.
# https://github.com/SwiftlyInc/ETA-Completeness-Benchmark
_COMPLETENESS_PREDICTION_WINDOW = (timedelta(minutes=0), timedelta(minutes=15))

_TRIP_STOP_OUTCOME_COLUMNS = {
    "service_date",
    "trip_id",
    "stop_id",
    "vehicle_assigned",
    "trip_cancelled",
    "stop_skipped",
}
_PREDICTIONS_COLUMNS = {"service_date", "trip_id", "stop_id", "sampled_at", "predicted_arrival"}
_ID_DTYPES = {"route_id": str, "trip_id": str, "stop_id": str}


@dataclass(frozen=True)
class VehiclesInServicePoint:
    time_of_day: str  # "HH:MM"
    vehicle_count: int


@dataclass(frozen=True)
class TripsByDate:
    date: str  # ISO date
    trip_count: int


@dataclass(frozen=True)
class AccuracyBucket:
    label: str
    prediction_count: int
    accurate_count: int
    accuracy_percent: float | None  # None if prediction_count == 0


@dataclass(frozen=True)
class TidesBenchmarks:
    trips_performed: int
    realtime_completeness_percent: float | None
    realtime_completeness_note: str | None
    eta_accuracy_percent: float | None
    eta_accuracy_note: str | None
    eta_accuracy_buckets: list[AccuracyBucket]


@dataclass(frozen=True)
class DashboardData:
    agency: str
    feed_start_date: date
    feed_end_date: date
    route_count: int
    trip_count: int
    stop_count: int
    busiest_date: date
    peak_vehicles: int
    peak_time: str
    vehicles_time_series: list[VehiclesInServicePoint]
    trips_by_date: list[TripsByDate]
    tides: TidesBenchmarks | None


def _read_typed_csvs(tides_files: list[Path], required_columns: set[str]) -> pd.DataFrame:
    """Concatenate every fetched CSV whose columns are a superset of `required_columns`.

    Duck-typed by column presence, like every TIDES read in this project
    (a fetched TIDES directory may hold several distinct CSV shapes side
    by side) — see
    specs/data-model.md#tides-data-for-the-eta-benchmarks-assumed-separate-files.
    """
    frames = []
    for path in tides_files:
        if path.suffix.lower() != ".csv":
            continue
        df = pd.read_csv(path, dtype=_ID_DTYPES)
        if required_columns.issubset(df.columns):
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=sorted(required_columns))
    df = pd.concat(frames, ignore_index=True)
    df["service_date"] = pd.to_datetime(df["service_date"]).dt.date
    return df


def _read_trip_stop_outcomes(tides_files: list[Path]) -> pd.DataFrame:
    return _read_typed_csvs(tides_files, _TRIP_STOP_OUTCOME_COLUMNS)


def _read_predictions(tides_files: list[Path]) -> pd.DataFrame:
    return _read_typed_csvs(tides_files, _PREDICTIONS_COLUMNS)


def _scheduled_trip_stops(feed: gk.Feed, start: date, end: date) -> pd.DataFrame:
    """(date, trip_id, stop_id) rows for every trip actually scheduled on each date in [start, end].

    The GTFS-derived denominator for ETA completeness — deliberately
    independent of TIDES, so a trip-stop TIDES never reported at all is
    still counted (and correctly comes out incomplete).
    """
    stop_times = feed.stop_times[["trip_id", "stop_id"]].drop_duplicates()
    rows = []
    for n in range((end - start).days + 1):
        day = start + timedelta(days=n)
        day_trips = feed.get_trips(date=day.strftime("%Y%m%d"))
        if day_trips.empty:
            continue
        day_stops = stop_times[stop_times["trip_id"].isin(set(day_trips["trip_id"]))].copy()
        day_stops.insert(0, "date", day)
        rows.append(day_stops)
    if not rows:
        return pd.DataFrame(columns=["date", "trip_id", "stop_id"])
    return pd.concat(rows, ignore_index=True)


def _qualifying_prediction_keys(outcomes: pd.DataFrame, predictions: pd.DataFrame) -> set[tuple]:
    """(service_date, trip_id, stop_id) keys with >=1 prediction 0-15 min before actual arrival."""
    if predictions.empty or outcomes.empty:
        return set()
    actuals = outcomes[["service_date", "trip_id", "stop_id", "actual_arrival"]].dropna(subset=["actual_arrival"])
    if actuals.empty:
        return set()
    merged = predictions.merge(actuals, on=["service_date", "trip_id", "stop_id"], how="inner")
    time_to_actual = pd.to_datetime(merged["actual_arrival"]) - pd.to_datetime(merged["sampled_at"])
    low, high = _COMPLETENESS_PREDICTION_WINDOW
    qualifying = merged[(time_to_actual >= low) & (time_to_actual < high)]
    return set(zip(qualifying["service_date"], qualifying["trip_id"], qualifying["stop_id"]))


def _eta_completeness_percent(
    feed: gk.Feed, start: date, end: date, outcomes: pd.DataFrame, predictions: pd.DataFrame
) -> tuple[float | None, str | None]:
    """ETA Completeness Benchmark: https://github.com/SwiftlyInc/ETA-Completeness-Benchmark

    See specs/data-model.md#eta-completeness for how this maps onto this
    project's GTFS + TIDES inputs.
    """
    scheduled = _scheduled_trip_stops(feed, start, end)
    denominator = len(scheduled)
    if denominator == 0:
        return None, "no scheduled trip-stops in the configured date range"
    if outcomes.empty:
        return None, "no fetched TIDES file has a trip_stop_outcomes shape"

    in_range = outcomes[(outcomes["service_date"] >= start) & (outcomes["service_date"] <= end)]
    qualifying = _qualifying_prediction_keys(in_range, predictions)

    keys = list(zip(in_range["service_date"], in_range["trip_id"], in_range["stop_id"]))
    has_qualifying_prediction = pd.Series([k in qualifying for k in keys], index=in_range.index)
    scheduled_keys = set(zip(scheduled["date"], scheduled["trip_id"], scheduled["stop_id"]))
    in_scheduled = pd.Series([k in scheduled_keys for k in keys], index=in_range.index)

    vehicle_assigned = in_range["vehicle_assigned"].astype(bool)
    trip_cancelled = in_range["trip_cancelled"].astype(bool)
    stop_skipped = in_range["stop_skipped"].astype(bool)
    complete = (vehicle_assigned & has_qualifying_prediction) | trip_cancelled | stop_skipped

    numerator = int((complete & in_scheduled).sum())
    return 100 * numerator / denominator, None


def _eta_accuracy(
    outcomes: pd.DataFrame, predictions: pd.DataFrame, start: date, end: date
) -> tuple[float | None, str | None, list[AccuracyBucket]]:
    """ETA Accuracy Benchmark: https://github.com/TransitApp/ETA-Accuracy-Benchmark

    See specs/data-model.md#eta-accuracy for how this maps onto this
    project's GTFS + TIDES inputs.
    """
    if predictions.empty:
        return None, "no fetched TIDES file has a predictions shape", []
    if outcomes.empty:
        return None, "no fetched TIDES file has a trip_stop_outcomes shape (needed for actual_arrival)", []

    predictions_in_range = predictions[(predictions["service_date"] >= start) & (predictions["service_date"] <= end)]
    if predictions_in_range.empty:
        return None, "no predictions in the configured date range", []

    actuals = outcomes[["service_date", "trip_id", "stop_id", "actual_arrival"]].dropna(subset=["actual_arrival"])
    merged = predictions_in_range.merge(actuals, on=["service_date", "trip_id", "stop_id"], how="inner")
    if merged.empty:
        return None, "no predictions have a matching actual_arrival", []

    sampled_at = pd.to_datetime(merged["sampled_at"])
    actual_arrival = pd.to_datetime(merged["actual_arrival"])
    predicted_arrival = pd.to_datetime(merged["predicted_arrival"])
    time_to_actual = actual_arrival - sampled_at
    variance = actual_arrival - predicted_arrival

    buckets = []
    bucket_accuracies = []
    for label, low_min, high_min, early_tolerance, late_tolerance in _ACCURACY_BUCKETS:
        in_bucket = (time_to_actual >= timedelta(minutes=low_min)) & (time_to_actual < timedelta(minutes=high_min))
        bucket_variance = variance[in_bucket]
        count = len(bucket_variance)
        if count == 0:
            buckets.append(AccuracyBucket(label=label, prediction_count=0, accurate_count=0, accuracy_percent=None))
            continue
        accurate = int(((bucket_variance >= -early_tolerance) & (bucket_variance <= late_tolerance)).sum())
        accuracy_percent = 100 * accurate / count
        buckets.append(
            AccuracyBucket(label=label, prediction_count=count, accurate_count=accurate, accuracy_percent=accuracy_percent)
        )
        bucket_accuracies.append(accuracy_percent)

    if not bucket_accuracies:
        return None, "no predictions fell within any of the four accuracy time buckets", buckets
    return sum(bucket_accuracies) / len(bucket_accuracies), None, buckets


def _build_tides_benchmarks(feed: gk.Feed, tides_files: list[Path], start: date, end: date) -> TidesBenchmarks:
    performed = otp.read_tides_performed(tides_files)
    scheduled_dt = pd.to_datetime(performed["scheduled_departure"])
    in_range = (scheduled_dt.dt.date >= start) & (scheduled_dt.dt.date <= end)
    performed = performed[in_range]
    performed = performed[~performed["cancelled"].astype(bool)]
    trips_performed = len(performed)

    outcomes = _read_trip_stop_outcomes(tides_files)
    predictions = _read_predictions(tides_files)

    completeness_percent, completeness_note = _eta_completeness_percent(feed, start, end, outcomes, predictions)
    accuracy_percent, accuracy_note, accuracy_buckets = _eta_accuracy(outcomes, predictions, start, end)

    return TidesBenchmarks(
        trips_performed=trips_performed,
        realtime_completeness_percent=completeness_percent,
        realtime_completeness_note=completeness_note,
        eta_accuracy_percent=accuracy_percent,
        eta_accuracy_note=accuracy_note,
        eta_accuracy_buckets=accuracy_buckets,
    )


def build_dashboard_data(
    feed: gk.Feed,
    agency: str,
    *,
    tides_files: list[Path] | None = None,
    date_range: tuple[date, date] | None = None,
) -> DashboardData:
    """Build the dashboard's data, independent of how it's rendered.

    Schedule section is always computed (GTFS-only). The TIDES section is
    computed only when both `tides_files` and `date_range` are given —
    otherwise `data.tides` is None, per
    specs/data-model.md#static-html-dashboard-report-output.
    """
    feed_start, feed_end = schedule_stats.feed_date_range(feed)
    week_days = schedule_stats.representative_week(feed)
    week_day_strs = [d.strftime("%Y%m%d") for d in week_days]

    trip_stats = feed.compute_trip_stats()

    busiest_day_str = feed.compute_busiest_date(week_day_strs)
    busiest_date = datetime.strptime(busiest_day_str, "%Y%m%d").date()

    time_series = feed.compute_network_time_series([busiest_day_str], trip_stats=trip_stats, freq="15Min")
    vehicles_time_series = [
        VehiclesInServicePoint(time_of_day=row.datetime.strftime("%H:%M"), vehicle_count=int(row.num_trips))
        for row in time_series.itertuples()
    ]

    # peak_num_trips/peak_start_time come from compute_network_stats's own
    # exact calculation (trip start/end times), not derived by taking the
    # max of the 15-minute-binned time series above, which could
    # under-report a peak that falls inside a single bin boundary.
    busy_day_stats = feed.compute_network_stats([busiest_day_str], trip_stats=trip_stats)
    peak_row = busy_day_stats.iloc[0]
    peak_vehicles = int(peak_row["peak_num_trips"])
    peak_time = str(peak_row["peak_start_time"])[:5]  # HH:MM

    daily_stats = feed.compute_network_stats(feed.get_dates(), trip_stats=trip_stats)
    trips_by_date = [
        TripsByDate(
            date=datetime.strptime(row.date, "%Y%m%d").date().isoformat(),
            trip_count=int(row.num_trips),
        )
        for row in daily_stats.itertuples()
    ]

    route_count = 0 if feed.routes is None else len(feed.routes)
    trip_count = 0 if feed.trips is None else len(feed.trips)
    stop_count = 0 if feed.stops is None else len(feed.stops)

    tides_benchmarks = None
    if tides_files and date_range:
        tides_benchmarks = _build_tides_benchmarks(feed, tides_files, date_range[0], date_range[1])

    return DashboardData(
        agency=agency,
        feed_start_date=feed_start,
        feed_end_date=feed_end,
        route_count=route_count,
        trip_count=trip_count,
        stop_count=stop_count,
        busiest_date=busiest_date,
        peak_vehicles=peak_vehicles,
        peak_time=peak_time,
        vehicles_time_series=vehicles_time_series,
        trips_by_date=trips_by_date,
        tides=tides_benchmarks,
    )


def render_html(data: DashboardData) -> str:
    """Render the dashboard as a single self-contained HTML document (string)."""
    vehicles_points = [(p.time_of_day, p.vehicle_count) for p in data.vehicles_time_series]
    trips_points = [(t.date, t.trip_count) for t in data.trips_by_date]

    vehicles_chart = html_charts.area_chart_svg(chart_id="vehicles-chart", points=vehicles_points)
    trips_chart = html_charts.area_chart_svg(chart_id="trips-chart", points=trips_points, value_suffix=" trips")

    vehicles_table = html_charts.data_table(["Time of day", "Vehicles in service"], vehicles_points)
    trips_table = html_charts.data_table(["Date", "Scheduled trips"], trips_points)

    stat_tiles = [
        html_charts.stat_tile("Routes", str(data.route_count)),
        html_charts.stat_tile("Trips (whole feed)", str(data.trip_count)),
        html_charts.stat_tile("Stops", str(data.stop_count)),
        html_charts.stat_tile(
            "Peak vehicles in service",
            str(data.peak_vehicles),
            f"at {data.peak_time} on {data.busiest_date.isoformat()}",
        ),
    ]

    if data.tides is not None:
        stat_tiles.extend(
            [
                html_charts.stat_tile("Trips performed", str(data.tides.trips_performed)),
                html_charts.stat_tile(
                    "ETA completeness",
                    html_charts.percent(data.tides.realtime_completeness_percent),
                    data.tides.realtime_completeness_note,
                ),
                html_charts.stat_tile(
                    "ETA accuracy",
                    html_charts.percent(data.tides.eta_accuracy_percent),
                    data.tides.eta_accuracy_note,
                ),
            ]
        )
        bucket_rows = [
            (b.label, b.prediction_count, html_charts.percent(b.accuracy_percent))
            for b in data.tides.eta_accuracy_buckets
        ]
        bucket_table = html_charts.data_table(["Time bucket", "Predictions", "Accuracy"], bucket_rows)
        tides_section = f"""
<section class="section">
  <h2>TIDES benchmarks</h2>
  <p class="section-note">
    Trips performed, plus the
    <a href="https://github.com/SwiftlyInc/ETA-Completeness-Benchmark">ETA Completeness Benchmark</a>
    and
    <a href="https://github.com/TransitApp/ETA-Accuracy-Benchmark">ETA Accuracy Benchmark</a>
    scores over the configured date_range. Both rest on an
    <strong>unverified assumption</strong> about the TIDES CSV shape —
    see specs/data-model.md#tides-data-for-the-eta-benchmarks-assumed-separate-files.
  </p>
  <h3 class="subsection-title">ETA accuracy by time bucket</h3>
  {bucket_table}
</section>
""".strip()
    else:
        tides_section = """
<section class="section">
  <h2>TIDES benchmarks</h2>
  <p class="section-note">
    Not shown: this agency has no tides: + date_range: configured (or
    TIDES has not been fetched yet). See
    specs/data-model.md#static-html-dashboard-report-output.
  </p>
</section>
""".strip()

    agency_escaped = escape(data.agency)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{agency_escaped} — schedule &amp; TIDES dashboard</title>
<style>
{html_charts.BASE_CSS}
</style>
</head>
<body>
<main>
  <h1>{agency_escaped}</h1>
  <p class="subtitle">
    Schedule &amp; TIDES dashboard &middot; feed valid
    {data.feed_start_date.isoformat()} to {data.feed_end_date.isoformat()}
  </p>

  <div class="stat-row">
    {''.join(stat_tiles)}
  </div>

  <section class="section">
    <h2>Vehicles in service by time of day</h2>
    <p class="section-note">
      Concurrent scheduled trips on {data.busiest_date.isoformat()} — the
      busiest date within the feed's representative week.
    </p>
    {html_charts.chart_with_tooltip(vehicles_chart, chart_id="vehicles-chart")}
    {vehicles_table}
  </section>

  <section class="section">
    <h2>Scheduled trips per service day</h2>
    <p class="section-note">
      Every date in [{data.feed_start_date.isoformat()}, {data.feed_end_date.isoformat()}]
      on which the feed schedules at least one trip. Dates with no service
      are omitted.
    </p>
    {html_charts.chart_with_tooltip(trips_chart, chart_id="trips-chart")}
    {trips_table}
  </section>

  {tides_section}
</main>
<script>
{html_charts.HOVER_SCRIPT}
</script>
</body>
</html>
"""


def write_html(html: str, output_dir: Path, agency: str, feed_start: date, feed_end: date) -> Path:
    """Write the dashboard to <output_dir>/reports/<agency>/dashboard-<start>-<end>.html."""
    reports_dir = output_dir / "reports" / agency
    reports_dir.mkdir(parents=True, exist_ok=True)
    dest = reports_dir / f"dashboard-{feed_start.isoformat()}-{feed_end.isoformat()}.html"
    dest.write_text(html)
    return dest
