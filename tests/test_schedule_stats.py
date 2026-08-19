import zipfile
from pathlib import Path

import pandas as pd
import pytest

from diy_transit_analysis.gtfs import schedule
from diy_transit_analysis.report import schedule_stats

FIXTURE = Path(__file__).parent / "fixtures" / "mini_gtfs.zip"

# mini_gtfs.zip's WEEKDAY calendar runs 2026-01-01..2026-03-31 (Mon-Fri
# only). The feed's first Monday-Sunday week is therefore 2026-01-05
# (Mon) .. 2026-01-11 (Sun), with 5 active weekdays (Jan 5-9).
_REPRESENTATIVE_WEEK_START = "2026-01-05"
_FEED_START = "2026-01-01"
_FEED_END = "2026-03-31"


def _build_fixture_with_never_active_route(tmp_path: Path) -> Path:
    """A second small fixture adding a route (R3) whose service never activates.

    Used to test that trip_count/service_day_count/avg_trips_per_service_day
    are null-safe for a route with zero active service days, while
    stop_count/first_departure_time/last_departure_time — which are
    calendar-independent — are still populated from the route's trips.
    """
    files = {
        "agency.txt": (
            "agency_id,agency_name,agency_url,agency_timezone\n"
            "AGY,Mini Transit,https://example.org,America/Los_Angeles\n"
        ),
        "routes.txt": (
            "route_id,agency_id,route_short_name,route_long_name,route_type\n"
            "R1,AGY,1,First Street Line,3\n"
            "R3,AGY,3,Third Street Line,3\n"
        ),
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\nS1,Start,38.58,-121.49\nS2,End,38.60,-121.47\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "WEEKDAY,1,1,1,1,1,0,0,20260101,20260331\n"
            "NEVER,0,0,0,0,0,0,0,20260101,20260331\n"
        ),
        "trips.txt": ("route_id,service_id,trip_id\nR1,WEEKDAY,R1-T1\nR3,NEVER,R3-T1\n"),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "R1-T1,08:00:00,08:00:00,S1,1\n"
            "R1-T1,08:15:00,08:15:00,S2,2\n"
            "R3-T1,07:00:00,07:00:00,S1,1\n"
            "R3-T1,07:20:00,07:20:00,S2,2\n"
        ),
    }
    path = tmp_path / "never_active.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


def test_build_schedule_stats_report_basic_counts():
    feed = schedule.load_schedule(FIXTURE)
    df = schedule_stats.build_schedule_stats_report(feed, agency="Mini").set_index("route_id")

    assert (df["feed_start_date"] == _FEED_START).all()
    assert (df["feed_end_date"] == _FEED_END).all()
    assert (df["representative_week_start"] == _REPRESENTATIVE_WEEK_START).all()

    assert df.loc["R1", "service_day_count"] == 5
    assert df.loc["R1", "trip_count"] == 10  # 2 trips/day * 5 weekdays
    assert df.loc["R1", "avg_trips_per_service_day"] == pytest.approx(2.0)
    assert df.loc["R1", "stop_count"] == 2
    assert df.loc["R1", "first_departure_time"] == "08:00:00"
    assert df.loc["R1", "last_departure_time"] == "09:15:00"

    assert df.loc["R2", "service_day_count"] == 5
    assert df.loc["R2", "trip_count"] == 5  # 1 trip/day * 5 weekdays
    assert df.loc["R2", "avg_trips_per_service_day"] == pytest.approx(1.0)
    assert df.loc["R2", "first_departure_time"] == "08:30:00"
    assert df.loc["R2", "last_departure_time"] == "08:50:00"


def test_route_with_no_active_service_days_is_null_safe(tmp_path: Path):
    fixture = _build_fixture_with_never_active_route(tmp_path)
    feed = schedule.load_schedule(fixture)
    df = schedule_stats.build_schedule_stats_report(feed, agency="Mini").set_index("route_id")

    assert df.loc["R3", "service_day_count"] == 0
    assert df.loc["R3", "trip_count"] == 0
    assert pd.isna(df.loc["R3", "avg_trips_per_service_day"])
    # Structural (calendar-independent) stats are still populated.
    assert df.loc["R3", "stop_count"] == 2
    assert df.loc["R3", "first_departure_time"] == "07:00:00"
    assert df.loc["R3", "last_departure_time"] == "07:20:00"
