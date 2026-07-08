from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from diy_transit_analysis.gtfs import schedule
from diy_transit_analysis.report import on_time_performance as otp

FIXTURE = Path(__file__).parent / "fixtures" / "mini_gtfs.zip"


def _write_tides_csv(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "tides_trips_performed.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_build_otp_report_basic_counts_and_null_safety(tmp_path: Path):
    feed = schedule.load_schedule(FIXTURE)
    day = date(2026, 1, 5)  # a Monday within the WEEKDAY calendar

    tides_csv = _write_tides_csv(
        tmp_path,
        [
            # R1-T1: on time (+1 min, within -1/+5 window)
            {
                "route_id": "R1",
                "trip_id": "R1-T1",
                "scheduled_departure": "2026-01-05 08:00:00",
                "actual_departure": "2026-01-05 08:01:00",
                "cancelled": False,
            },
            # R1-T2: cancelled -> excluded from performed/on-time counts
            {
                "route_id": "R1",
                "trip_id": "R1-T2",
                "scheduled_departure": "2026-01-05 09:00:00",
                "actual_departure": "",
                "cancelled": True,
            },
            # R2-T1: performed but late (+10 min, outside window)
            {
                "route_id": "R2",
                "trip_id": "R2-T1",
                "scheduled_departure": "2026-01-05 08:30:00",
                "actual_departure": "2026-01-05 08:40:00",
                "cancelled": False,
            },
        ],
    )

    df = otp.build_otp_report(feed, [tides_csv], agency="Mini", start=day, end=day)
    df = df.set_index("route_id")

    assert df.loc["R1", "scheduled_trip_count"] == 2
    assert df.loc["R1", "performed_trip_count"] == 1
    assert df.loc["R1", "on_time_trip_count"] == 1
    assert df.loc["R1", "on_time_percent"] == pytest.approx(1.0)
    assert df.loc["R1", "cancellation_percent"] == pytest.approx(0.5)

    assert df.loc["R2", "scheduled_trip_count"] == 1
    assert df.loc["R2", "performed_trip_count"] == 1
    assert df.loc["R2", "on_time_trip_count"] == 0
    assert df.loc["R2", "on_time_percent"] == pytest.approx(0.0)
    assert df.loc["R2", "cancellation_percent"] == pytest.approx(0.0)


def test_scheduled_zero_gives_null_cancellation_percent(tmp_path: Path):
    feed = schedule.load_schedule(FIXTURE)
    # A Sunday: WEEKDAY calendar has no service, so scheduled_trip_count == 0
    # for every route, but pretend TIDES still reports a performed trip.
    sunday = date(2026, 1, 4)

    tides_csv = _write_tides_csv(
        tmp_path,
        [
            {
                "route_id": "R1",
                "trip_id": "R1-T1",
                "scheduled_departure": "2026-01-04 08:00:00",
                "actual_departure": "2026-01-04 08:00:00",
                "cancelled": False,
            },
        ],
    )

    df = otp.build_otp_report(feed, [tides_csv], agency="Mini", start=sunday, end=sunday)
    row = df[df["route_id"] == "R1"].iloc[0]

    assert row["scheduled_trip_count"] == 0
    assert pd.isna(row["cancellation_percent"])


def test_tides_rows_outside_date_range_are_excluded(tmp_path: Path):
    # fetch_historic() does no date filtering itself (see
    # plans/data-fetch.md Follow-ups) — the report must filter.
    feed = schedule.load_schedule(FIXTURE)
    day = date(2026, 1, 5)

    tides_csv = _write_tides_csv(
        tmp_path,
        [
            # Inside the requested window.
            {
                "route_id": "R1",
                "trip_id": "R1-T1",
                "scheduled_departure": "2026-01-05 08:00:00",
                "actual_departure": "2026-01-05 08:00:00",
                "cancelled": False,
            },
            # Outside the requested window — fetch_historic() may have
            # pulled a whole prefix's worth of files; this row must not
            # count toward the report.
            {
                "route_id": "R1",
                "trip_id": "R1-T2",
                "scheduled_departure": "2026-02-01 09:00:00",
                "actual_departure": "2026-02-01 09:00:00",
                "cancelled": False,
            },
        ],
    )

    df = otp.build_otp_report(feed, [tides_csv], agency="Mini", start=day, end=day)
    row = df[df["route_id"] == "R1"].iloc[0]

    assert row["performed_trip_count"] == 1


def test_on_time_window_boundaries():
    scheduled = pd.Series(
        [
            "2026-01-05 08:00:00",  # exactly -1 min -> on time
            "2026-01-05 08:00:00",  # exactly +5 min -> on time
            "2026-01-05 08:00:00",  # -1:01 -> not on time
            "2026-01-05 08:00:00",  # +5:01 -> not on time
        ]
    )
    actual = pd.Series(
        [
            "2026-01-05 07:59:00",
            "2026-01-05 08:05:00",
            "2026-01-05 07:58:59",
            "2026-01-05 08:05:01",
        ]
    )

    result = otp._is_on_time(scheduled, actual)
    assert result.tolist() == [True, True, False, False]
