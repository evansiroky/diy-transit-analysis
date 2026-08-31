"""Build the GTFS-only schedule stats report.

Spec: specs/data-model.md#gtfs-schedule-stats-report-output

Unlike the on-time-performance report, this needs only a fetched GTFS
Schedule feed — no TIDES data, no user-configured date_range. Per-route
trip/frequency stats are scoped to the feed's own "representative week"
(its first Monday-Sunday week of calendar validity) so the report stays
reproducible from the feed alone, per
specs/principles.md#reproducibility-over-cleverness.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import gtfs_kit as gk
import pandas as pd


def _time_to_seconds(value: str) -> int | None:
    """Parse a GTFS HH:MM:SS time (hours may exceed 24) to seconds past midnight."""
    if not isinstance(value, str) or not value:
        return None
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds)


def _seconds_to_time(value: int) -> str:
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def feed_date_range(feed: gk.Feed) -> tuple[date, date]:
    dates = feed.get_dates(as_date_obj=True)
    if not dates:
        raise ValueError(
            "GTFS feed has no calendar information (calendar.txt and "
            "calendar_dates.txt are both empty) — cannot compute a "
            "schedule stats report. See "
            "specs/data-model.md#gtfs-schedule-stats-report-output."
        )
    return min(dates), max(dates)


def representative_week(feed: gk.Feed) -> list[date]:
    week = feed.get_first_week(as_date_obj=True)
    if week:
        return week
    # No Monday within the feed's validity (rare, short/odd feeds) — fall
    # back to whatever dates the feed does cover.
    return feed.get_dates(as_date_obj=True)


def _route_trip_counts_by_day(feed: gk.Feed, days: list[date]) -> pd.DataFrame:
    """Per-route trip count for each day in `days`. Columns: route_id, date, trip_count."""
    rows = []
    for day in days:
        day_str = day.strftime("%Y%m%d")
        day_trips = feed.get_trips(date=day_str)
        if day_trips.empty:
            continue
        counts = day_trips.groupby("route_id")["trip_id"].nunique()
        for route_id, count in counts.items():
            rows.append({"route_id": route_id, "date": day, "trip_count": count})
    return pd.DataFrame(rows, columns=["route_id", "date", "trip_count"])


def _stop_and_time_stats_by_route(feed: gk.Feed) -> pd.DataFrame:
    """Structural (non-calendar-scoped) per-route stats: stop_count, first/last departure."""
    stop_times = feed.stop_times[["trip_id", "stop_id", "departure_time"]].copy()
    trip_routes = feed.trips[["trip_id", "route_id"]]
    merged = stop_times.merge(trip_routes, on="trip_id", how="inner")
    merged["departure_seconds"] = merged["departure_time"].map(_time_to_seconds)

    stop_counts = merged.groupby("route_id")["stop_id"].nunique().rename("stop_count")
    first_departure = merged.groupby("route_id")["departure_seconds"].min().rename("first_departure_seconds")
    last_departure = merged.groupby("route_id")["departure_seconds"].max().rename("last_departure_seconds")

    return pd.concat([stop_counts, first_departure, last_departure], axis=1)


def build_schedule_stats_report(feed: gk.Feed, agency: str) -> pd.DataFrame:
    """Build the route-level GTFS schedule stats report DataFrame.

    Columns match specs/data-model.md#gtfs-schedule-stats-report-output
    exactly. Deterministic given the same feed, per
    specs/principles.md#reproducibility-over-cleverness — it never
    depends on the wall-clock date the report is run.
    """
    feed_start, feed_end = feed_date_range(feed)
    week_days = representative_week(feed)
    week_start = min(week_days) if week_days else feed_start

    day_counts = _route_trip_counts_by_day(feed, week_days)
    trip_counts = day_counts.groupby("route_id")["trip_count"].sum().rename("trip_count")
    service_day_counts = day_counts.groupby("route_id")["date"].nunique().rename("service_day_count")

    structural = _stop_and_time_stats_by_route(feed)

    routes = feed.routes[["route_id", "route_short_name", "route_type"]].copy()
    routes["route_short_name"] = routes["route_short_name"].fillna(routes["route_id"])

    rows = []
    for _, route in routes.iterrows():
        route_id = route["route_id"]
        trip_count = int(trip_counts.get(route_id, 0))
        service_day_count = int(service_day_counts.get(route_id, 0))
        stop_count = int(structural["stop_count"].get(route_id, 0))
        first_seconds = structural["first_departure_seconds"].get(route_id)
        last_seconds = structural["last_departure_seconds"].get(route_id)

        rows.append(
            {
                "agency": agency,
                "feed_start_date": feed_start.isoformat(),
                "feed_end_date": feed_end.isoformat(),
                "route_id": route_id,
                "route_short_name": route["route_short_name"],
                "route_type": int(route["route_type"]),
                "stop_count": stop_count,
                "representative_week_start": week_start.isoformat(),
                "service_day_count": service_day_count,
                "trip_count": trip_count,
                "avg_trips_per_service_day": (trip_count / service_day_count) if service_day_count else None,
                "first_departure_time": _seconds_to_time(int(first_seconds)) if pd.notna(first_seconds) else None,
                "last_departure_time": _seconds_to_time(int(last_seconds)) if pd.notna(last_seconds) else None,
            }
        )

    return pd.DataFrame(rows)


def write_report(df: pd.DataFrame, output_dir: Path, agency: str, feed_start: date, feed_end: date) -> Path:
    """Write the report CSV to <output_dir>/reports/<agency>/schedule-stats-<start>-<end>.csv."""
    reports_dir = output_dir / "reports" / agency
    reports_dir.mkdir(parents=True, exist_ok=True)
    dest = reports_dir / f"schedule-stats-{feed_start.isoformat()}-{feed_end.isoformat()}.csv"
    df.to_csv(dest, index=False)
    return dest
