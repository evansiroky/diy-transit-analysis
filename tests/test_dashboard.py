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


def test_tides_benchmarks_with_both_optional_columns(tmp_path: Path):
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
                "realtime_data_available": True,
                "predicted_departure": "2026-01-05 08:00:30",  # 30s off -> accurate
            },
            {
                "route_id": "R2",
                "trip_id": "R2-T1",
                "scheduled_departure": "2026-01-05 08:30:00",
                "actual_departure": "2026-01-05 08:31:00",
                "cancelled": False,
                "realtime_data_available": False,
                "predicted_departure": "2026-01-05 08:35:00",  # 4 min off -> not accurate
            },
        ],
    )

    data = dashboard.build_dashboard_data(
        feed, agency="Mini", tides_files=[tides_csv], date_range=(date(2026, 1, 1), date(2026, 1, 31))
    )

    assert data.tides is not None
    assert data.tides.trips_performed == 2
    assert data.tides.realtime_completeness_percent == pytest.approx(50.0)
    assert data.tides.eta_accuracy_percent == pytest.approx(50.0)


def test_tides_benchmarks_excludes_rows_with_unknown_realtime_status(tmp_path: Path):
    # Simulate two fetched TIDES files where only one carries
    # realtime_data_available — pd.concat introduces NaN for the file
    # that lacks it. Those rows must be excluded from the completeness
    # calc, not silently counted as "available" (NaN.astype(bool) is
    # True) or "unavailable".
    feed = schedule.load_schedule(FIXTURE)
    with_column = _write_tides_csv(
        tmp_path,
        [
            {
                "route_id": "R1",
                "trip_id": "R1-T1",
                "scheduled_departure": "2026-01-05 08:00:00",
                "actual_departure": "2026-01-05 08:01:00",
                "cancelled": False,
                "realtime_data_available": True,
            },
        ],
    )
    without_column_path = tmp_path / "tides_no_column.csv"
    pd.DataFrame(
        [
            {
                "route_id": "R2",
                "trip_id": "R2-T1",
                "scheduled_departure": "2026-01-05 08:30:00",
                "actual_departure": "2026-01-05 08:31:00",
                "cancelled": False,
            }
        ]
    ).to_csv(without_column_path, index=False)

    data = dashboard.build_dashboard_data(
        feed,
        agency="Mini",
        tides_files=[with_column, without_column_path],
        date_range=(date(2026, 1, 1), date(2026, 1, 31)),
    )

    assert data.tides.trips_performed == 2
    # Only the one row with a known value counts -> 100%, not 50%.
    assert data.tides.realtime_completeness_percent == pytest.approx(100.0)


def test_tides_benchmarks_missing_optional_columns_are_null_not_a_crash(tmp_path: Path):
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
                "realtime_data_available": True,
                "predicted_departure": "2026-01-05 08:00:30",
            },
        ],
    )

    data = dashboard.build_dashboard_data(
        feed, agency="Mini", tides_files=[tides_csv], date_range=(date(2026, 1, 1), date(2026, 1, 31))
    )

    assert data.tides.trips_performed == 0
    assert data.tides.realtime_completeness_percent is None
    assert data.tides.eta_accuracy_percent is None


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
