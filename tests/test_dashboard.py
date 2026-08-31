import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from diy_transit_analysis.gtfs import schedule
from diy_transit_analysis.report import dashboard

FIXTURE = Path(__file__).parent / "fixtures" / "mini_gtfs.zip"


def _write_tides_csv(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "tides_trips_performed.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _build_non_overlapping_but_same_bin_fixture(tmp_path: Path) -> Path:
    """Two trips that never truly overlap but both fall inside one 15-min bin.

    R1-T1 runs 08:00-08:05, R1-T2 runs 08:10-08:14 — never concurrent (true
    peak concurrency is 1), but compute_network_time_series's 08:00 bin
    (covering [08:00, 08:15)) counts both as "in service" during that
    period, reporting num_trips=2 for the bin. This is the concrete case
    that would make max(binned time series) disagree with the true peak.
    """
    files = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nAGY,T,https://example.org,America/Los_Angeles\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\nR1,AGY,1,L,3\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nS1,A,38.58,-121.49\nS2,B,38.60,-121.47\n",
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "WEEKDAY,1,1,1,1,1,0,0,20260101,20260107\n"
        ),
        "trips.txt": "route_id,service_id,trip_id\nR1,WEEKDAY,R1-T1\nR1,WEEKDAY,R1-T2\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "R1-T1,08:00:00,08:00:00,S1,1\n"
            "R1-T1,08:05:00,08:05:00,S2,2\n"
            "R1-T2,08:10:00,08:10:00,S1,1\n"
            "R1-T2,08:14:00,08:14:00,S2,2\n"
        ),
    }
    path = tmp_path / "non_overlapping.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


def test_build_dashboard_data_gtfs_only_schedule_section():
    feed = schedule.load_schedule(FIXTURE)

    data = dashboard.build_dashboard_data(feed, agency="Mini")

    assert data.route_count == 2
    assert data.trip_count == 3
    assert data.stop_count == 2
    assert data.feed_start_date == date(2026, 1, 1)
    assert data.feed_end_date == date(2026, 3, 31)
    # mini_gtfs.zip's trips never overlap (see tests/fixtures/build_fixture_gtfs.py).
    assert data.peak_vehicles == 1
    assert len(data.vehicles_time_series) == 96  # 24h at 15-minute resolution
    assert len(data.trips_by_date) == 64  # weekdays only, Jan 1 - Mar 31 2026
    assert data.tides is None


def test_build_dashboard_data_peak_not_derived_from_binned_time_series(tmp_path: Path):
    # A 15-minute bin counts a trip as "in service" if it overlaps the
    # bin at all, which can OVER-count relative to true instantaneous
    # concurrency: two trips that never run at the same moment can still
    # both fall inside one bin. peak_vehicles must come from
    # compute_network_stats's exact calculation, not max(binned series),
    # or this fixture's reported peak would be wrong (2 instead of 1).
    fixture = _build_non_overlapping_but_same_bin_fixture(tmp_path)
    feed = schedule.load_schedule(fixture)
    data = dashboard.build_dashboard_data(feed, agency="Mini")

    binned_max = max(p.vehicle_count for p in data.vehicles_time_series)
    assert binned_max == 2  # confirms the bin does over-count in this fixture
    assert data.peak_vehicles == 1  # the true, never-overlapping concurrency


_OUTCOME_COLUMNS = [
    "service_date",
    "trip_id",
    "stop_id",
    "vehicle_assigned",
    "trip_cancelled",
    "stop_skipped",
    "actual_arrival",
]
_PREDICTION_COLUMNS = ["service_date", "trip_id", "stop_id", "sampled_at", "predicted_arrival"]


def _write_outcomes_and_predictions(
    tmp_path: Path, outcomes: list[dict], predictions: list[dict]
) -> tuple[Path, Path]:
    # pd.DataFrame([]) has no columns at all, which writes a header-less
    # CSV that pandas can't even read back -- an empty list still needs
    # its shape's headers so the file is a valid (zero-row) CSV.
    outcomes_df = pd.DataFrame(outcomes, columns=_OUTCOME_COLUMNS) if outcomes else pd.DataFrame(columns=_OUTCOME_COLUMNS)
    predictions_df = (
        pd.DataFrame(predictions, columns=_PREDICTION_COLUMNS) if predictions else pd.DataFrame(columns=_PREDICTION_COLUMNS)
    )
    outcomes_path = tmp_path / "trip_stop_outcomes.csv"
    predictions_path = tmp_path / "predictions.csv"
    outcomes_df.to_csv(outcomes_path, index=False)
    predictions_df.to_csv(predictions_path, index=False)
    return outcomes_path, predictions_path


def test_eta_completeness_covers_all_four_quadrants(tmp_path: Path):
    # mini_gtfs.zip's 2026-01-05 (Monday) schedules 3 trips x 2 stops = 6
    # trip-stops: R1-T1@{S1,S2}, R1-T2@{S1,S2}, R2-T1@{S1,S2}.
    feed = schedule.load_schedule(FIXTURE)
    outcomes, predictions = _write_outcomes_and_predictions(
        tmp_path,
        outcomes=[
            # 1. Delivered + communicated: vehicle assigned, has a
            #    qualifying 0-15-min-out prediction -> complete (condition 1).
            {
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S1",
                "vehicle_assigned": True,
                "trip_cancelled": False,
                "stop_skipped": False,
                "actual_arrival": "2026-01-05 08:00:00",
            },
            # 2. Delivered + UNcommunicated: vehicle ran, but no
            #    prediction at all -> incomplete.
            {
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S2",
                "vehicle_assigned": True,
                "trip_cancelled": False,
                "stop_skipped": False,
                "actual_arrival": "2026-01-05 08:15:00",
            },
            # 3. Undelivered + communicated via CANCELED -> complete
            #    (condition 2), for both of this trip's stops.
            {
                "service_date": "2026-01-05",
                "trip_id": "R1-T2",
                "stop_id": "S1",
                "vehicle_assigned": False,
                "trip_cancelled": True,
                "stop_skipped": False,
                "actual_arrival": "",
            },
            {
                "service_date": "2026-01-05",
                "trip_id": "R1-T2",
                "stop_id": "S2",
                "vehicle_assigned": False,
                "trip_cancelled": True,
                "stop_skipped": False,
                "actual_arrival": "",
            },
            # 4. Undelivered + communicated via SKIPPED -> complete
            #    (condition 2).
            {
                "service_date": "2026-01-05",
                "trip_id": "R2-T1",
                "stop_id": "S1",
                "vehicle_assigned": False,
                "trip_cancelled": False,
                "stop_skipped": True,
                "actual_arrival": "",
            },
            # R2-T1@S2 has NO row at all: 5. Undelivered + UNcommunicated
            # — the trip-stop silently disappeared from TIDES entirely.
        ],
        predictions=[
            {
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S1",
                "sampled_at": "2026-01-05 07:50:00",  # 10 min before actual -> qualifies (0-15 out)
                "predicted_arrival": "2026-01-05 08:00:30",
            },
        ],
    )

    data = dashboard.build_dashboard_data(
        feed,
        agency="Mini",
        tides_files=[outcomes, predictions],
        date_range=(date(2026, 1, 5), date(2026, 1, 5)),
    )

    # 6 scheduled trip-stops total (the GTFS-derived denominator,
    # independent of TIDES: R2-T1@S2 has no outcome row at all and still
    # counts, correctly coming out incomplete). Complete: R1-T1@S1,
    # R1-T2@S1, R1-T2@S2, R2-T1@S1 = 4. Incomplete: R1-T1@S2, R2-T1@S2 = 2.
    assert data.tides.realtime_completeness_percent == pytest.approx(100 * 4 / 6)
    assert data.tides.realtime_completeness_note is None


def test_eta_completeness_null_when_no_outcomes_shape_fetched(tmp_path: Path):
    # No trip_stop_outcomes-shaped file was fetched at all (as opposed to
    # one being fetched with zero rows in range) -> null, not 0%, since
    # fetch_historic() itself already fails loudly on a truly empty
    # bucket (plans/data-fetch.md) -- reaching this code with fetched
    # TIDES data but no matching shape means the shape genuinely isn't
    # published, not that everything silently disappeared.
    feed = schedule.load_schedule(FIXTURE)
    predictions_only = _write_outcomes_and_predictions(tmp_path, outcomes=[], predictions=[])[1]

    data = dashboard.build_dashboard_data(
        feed,
        agency="Mini",
        tides_files=[predictions_only],
        date_range=(date(2026, 1, 5), date(2026, 1, 5)),
    )

    assert data.tides.realtime_completeness_percent is None
    assert data.tides.realtime_completeness_note is not None


def test_eta_accuracy_boundary_thresholds_are_inclusive(tmp_path: Path):
    # 0-3 minute bucket: accurate iff -0.5min <= variance <= +1.5min.
    # actual=08:00:00; predicted 08:00:30 -> variance -30s (exactly the
    # early boundary, inclusive -> accurate); predicted 07:58:29 ->
    # variance +91s (1 second past the late boundary -> inaccurate).
    feed = schedule.load_schedule(FIXTURE)
    outcomes, predictions = _write_outcomes_and_predictions(
        tmp_path,
        outcomes=[
            {
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S1",
                "vehicle_assigned": True,
                "trip_cancelled": False,
                "stop_skipped": False,
                "actual_arrival": "2026-01-05 08:00:00",
            },
        ],
        predictions=[
            {  # sampled 2 min before actual -> 0-3 min bucket; variance = -30s -> accurate (boundary)
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S1",
                "sampled_at": "2026-01-05 07:58:00",
                "predicted_arrival": "2026-01-05 08:00:30",
            },
            {  # sampled 1 min before actual -> 0-3 min bucket; variance = +91s -> inaccurate (1s past boundary)
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S1",
                "sampled_at": "2026-01-05 07:59:00",
                "predicted_arrival": "2026-01-05 07:58:29",
            },
        ],
    )

    data = dashboard.build_dashboard_data(
        feed,
        agency="Mini",
        tides_files=[outcomes, predictions],
        date_range=(date(2026, 1, 5), date(2026, 1, 5)),
    )

    bucket = next(b for b in data.tides.eta_accuracy_buckets if b.label == "0-3 min away")
    assert bucket.prediction_count == 2
    assert bucket.accurate_count == 1
    assert data.tides.eta_accuracy_percent == pytest.approx(50.0)  # only this one bucket has samples


def test_eta_accuracy_excludes_predictions_outside_all_buckets(tmp_path: Path):
    # Sampled 20 minutes before actual arrival -- outside the 0-15 minute
    # span all four buckets cover -- must not be counted anywhere.
    feed = schedule.load_schedule(FIXTURE)
    outcomes, predictions = _write_outcomes_and_predictions(
        tmp_path,
        outcomes=[
            {
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S1",
                "vehicle_assigned": True,
                "trip_cancelled": False,
                "stop_skipped": False,
                "actual_arrival": "2026-01-05 08:00:00",
            },
        ],
        predictions=[
            {
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S1",
                "sampled_at": "2026-01-05 07:40:00",  # 20 min before actual
                "predicted_arrival": "2026-01-05 08:00:00",
            },
        ],
    )

    data = dashboard.build_dashboard_data(
        feed,
        agency="Mini",
        tides_files=[outcomes, predictions],
        date_range=(date(2026, 1, 5), date(2026, 1, 5)),
    )

    assert all(b.prediction_count == 0 for b in data.tides.eta_accuracy_buckets)
    assert data.tides.eta_accuracy_percent is None
    assert data.tides.eta_accuracy_note is not None


def test_eta_accuracy_empty_buckets_excluded_from_average_not_counted_as_zero(tmp_path: Path):
    # One prediction in the 10-15 bucket (accurate -> 100%), one in the
    # 0-3 bucket (inaccurate -> 0%), the other two buckets empty. The
    # straight average of the two POPULATED buckets is 50%; treating the
    # two empty buckets as 0% would instead give 25%.
    feed = schedule.load_schedule(FIXTURE)
    outcomes, predictions = _write_outcomes_and_predictions(
        tmp_path,
        outcomes=[
            {
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S1",
                "vehicle_assigned": True,
                "trip_cancelled": False,
                "stop_skipped": False,
                "actual_arrival": "2026-01-05 08:00:00",
            },
        ],
        predictions=[
            {  # 10-15 min bucket, variance 0 -> accurate
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S1",
                "sampled_at": "2026-01-05 07:48:00",
                "predicted_arrival": "2026-01-05 08:00:00",
            },
            {  # 0-3 min bucket, variance +10min -> wildly inaccurate
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S1",
                "sampled_at": "2026-01-05 07:58:00",
                "predicted_arrival": "2026-01-05 07:50:00",
            },
        ],
    )

    data = dashboard.build_dashboard_data(
        feed,
        agency="Mini",
        tides_files=[outcomes, predictions],
        date_range=(date(2026, 1, 5), date(2026, 1, 5)),
    )

    populated = [b for b in data.tides.eta_accuracy_buckets if b.prediction_count > 0]
    assert len(populated) == 2
    assert data.tides.eta_accuracy_percent == pytest.approx(50.0)


def test_tides_benchmarks_missing_files_are_null_not_a_crash(tmp_path: Path):
    feed = schedule.load_schedule(FIXTURE)
    tides_csv = _write_tides_csv(
        tmp_path,
        [
            {
                "route_id": "R1",
                "trip_id": "R1-T1",
                "scheduled_departure": "2026-01-05 08:00:00",
                "actual_departure": "2026-01-05 08:01:00",
                "cancelled": False,
            },
        ],
    )

    data = dashboard.build_dashboard_data(
        feed, agency="Mini", tides_files=[tides_csv], date_range=(date(2026, 1, 1), date(2026, 1, 31))
    )

    assert data.tides.trips_performed == 1
    assert data.tides.realtime_completeness_percent is None
    assert data.tides.realtime_completeness_note is not None
    assert data.tides.eta_accuracy_percent is None
    assert data.tides.eta_accuracy_note is not None
    assert data.tides.eta_accuracy_buckets == []


def test_tides_benchmarks_zero_performed_trips_is_null_safe(tmp_path: Path):
    feed = schedule.load_schedule(FIXTURE)
    tides_csv = _write_tides_csv(
        tmp_path,
        [
            {
                "route_id": "R1",
                "trip_id": "R1-T1",
                "scheduled_departure": "2026-01-05 08:00:00",
                "actual_departure": "2026-01-05 08:01:00",
                "cancelled": True,
            },
        ],
    )

    data = dashboard.build_dashboard_data(
        feed, agency="Mini", tides_files=[tides_csv], date_range=(date(2026, 1, 1), date(2026, 1, 31))
    )

    assert data.tides.trips_performed == 0


def test_read_tides_performed_skips_files_of_a_different_shape(tmp_path: Path):
    # A tides/raw directory can hold all three CSV shapes at once; a
    # trip_stop_outcomes/predictions file must not break the "trips
    # performed" read (previously this raised; now it's skipped).
    from diy_transit_analysis.report import on_time_performance as otp

    performed_csv = _write_tides_csv(
        tmp_path,
        [
            {
                "route_id": "R1",
                "trip_id": "R1-T1",
                "scheduled_departure": "2026-01-05 08:00:00",
                "actual_departure": "2026-01-05 08:01:00",
                "cancelled": False,
            }
        ],
    )
    outcomes_csv, predictions_csv = _write_outcomes_and_predictions(
        tmp_path,
        outcomes=[
            {
                "service_date": "2026-01-05",
                "trip_id": "R1-T1",
                "stop_id": "S1",
                "vehicle_assigned": True,
                "trip_cancelled": False,
                "stop_skipped": False,
                "actual_arrival": "2026-01-05 08:00:00",
            }
        ],
        predictions=[],
    )

    df = otp.read_tides_performed([performed_csv, outcomes_csv, predictions_csv])

    assert len(df) == 1
    assert df.iloc[0]["trip_id"] == "R1-T1"


def test_render_html_is_well_formed_and_escapes_agency_name():
    feed = schedule.load_schedule(FIXTURE)
    data = dashboard.build_dashboard_data(feed, agency="<script>alert(1)</script>")

    html = dashboard.render_html(data)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html

    from html.parser import HTMLParser

    HTMLParser().feed(html)  # raises on catastrophic malformed markup


def test_render_html_shows_tides_section_only_when_data_present(tmp_path: Path):
    feed = schedule.load_schedule(FIXTURE)
    gtfs_only = dashboard.build_dashboard_data(feed, agency="Mini")
    assert "Not shown" in dashboard.render_html(gtfs_only)

    tides_csv = _write_tides_csv(
        tmp_path,
        [
            {
                "route_id": "R1",
                "trip_id": "R1-T1",
                "scheduled_departure": "2026-01-05 08:00:00",
                "actual_departure": "2026-01-05 08:01:00",
                "cancelled": False,
            },
        ],
    )
    with_tides = dashboard.build_dashboard_data(
        feed, agency="Mini", tides_files=[tides_csv], date_range=(date(2026, 1, 1), date(2026, 1, 31))
    )
    html = dashboard.render_html(with_tides)
    assert "Not shown" not in html
    assert "Trips performed" in html


def test_nice_ticks_never_produces_duplicate_labels():
    for max_value in [0, 1, 2, 3, 5, 7, 9, 42, 100, 4953]:
        ticks = dashboard._nice_ticks(max_value)
        assert len(ticks) == len(set(ticks))
        assert ticks[-1] >= max_value


def test_write_html(tmp_path: Path):
    feed = schedule.load_schedule(FIXTURE)
    data = dashboard.build_dashboard_data(feed, agency="Mini")
    html = dashboard.render_html(data)

    dest = dashboard.write_html(html, tmp_path, "Mini", data.feed_start_date, data.feed_end_date)

    assert dest == tmp_path / "reports" / "Mini" / "dashboard-2026-01-01-2026-03-31.html"
    assert dest.read_text() == html
