"""Build the on-time-performance / cancellation-rate report.

Spec: specs/data-model.md#on-time-performance-report-output

ASSUMPTION, NOT VERIFIED: the TIDES "trips performed" CSV column names used
here (route_id, trip_id, scheduled_departure, actual_departure, cancelled)
follow the sibling gtfs-rt-to-tides project's own TIDES CSV output
convention as a best-effort stand-in, since the real tides.dds.dot.ca.gov
bucket layout/format has not been verified (see
diy_transit_analysis.tides.historic and
specs/architecture.md#tides-historic-data-access). Once real fetched TIDES
data is available, confirm these column names and adjust
_read_tides_performed accordingly.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import gtfs_kit as gk
import pandas as pd

# On-time window: -1 to +5 minutes vs. scheduled time, per
# specs/data-model.md#on-time-performance-report-output. Fixed constant for
# the MVP (not configurable yet).
ON_TIME_EARLY_TOLERANCE = timedelta(minutes=1)
ON_TIME_LATE_TOLERANCE = timedelta(minutes=5)

_ASSUMED_TIDES_COLUMNS = {
    "route_id",
    "trip_id",
    "scheduled_departure",
    "actual_departure",
    "cancelled",
}


def _read_tides_performed(tides_files: list[Path]) -> pd.DataFrame:
    """Read and concatenate the fetched TIDES "trips performed" CSV(s).

    See this module's docstring for the assumed column shape.
    """
    frames = []
    for path in tides_files:
        if path.suffix.lower() != ".csv":
            continue
        # route_id/trip_id are read as strings (not inferred as numeric) so
        # they compare correctly against gtfs-kit's own string-typed IDs and
        # so leading zeros in agency-assigned IDs (e.g. "001") aren't lost.
        df = pd.read_csv(path, dtype={"route_id": str, "trip_id": str})
        missing = _ASSUMED_TIDES_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(
                f"{path}: missing expected TIDES columns {sorted(missing)} — "
                "the assumed TIDES CSV shape in "
                "diy_transit_analysis.report.on_time_performance may be out "
                "of date; verify against a real fetched TIDES file."
            )
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=sorted(_ASSUMED_TIDES_COLUMNS))

    return pd.concat(frames, ignore_index=True)


def _scheduled_trip_counts(feed: gk.Feed, start: date, end: date) -> pd.Series:
    """Scheduled trip count per route_id across [start, end], service-calendar-aware."""
    dates = [
        (start + timedelta(days=n)).strftime("%Y%m%d")
        for n in range((end - start).days + 1)
    ]
    trip_ids: set[str] = set()
    for d in dates:
        trip_ids |= set(feed.get_trips(date=d)["trip_id"])

    trips = feed.trips[feed.trips["trip_id"].isin(trip_ids)]
    return trips.groupby("route_id")["trip_id"].nunique()


def _is_on_time(scheduled: pd.Series, actual: pd.Series) -> pd.Series:
    delta = pd.to_datetime(actual) - pd.to_datetime(scheduled)
    return (delta >= -ON_TIME_EARLY_TOLERANCE) & (delta <= ON_TIME_LATE_TOLERANCE)


def build_otp_report(
    feed: gk.Feed,
    tides_files: list[Path],
    agency: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Build the route-level on-time-performance report DataFrame.

    Columns match specs/data-model.md#on-time-performance-report-output
    exactly. Deterministic given the same feed + tides_files + date range,
    per specs/principles.md#reproducibility-over-cleverness.
    """
    scheduled_counts = _scheduled_trip_counts(feed, start, end)

    performed = _read_tides_performed(tides_files)

    # tides.historic.fetch_historic() does not itself filter by date range
    # (the real TIDES bucket layout is unverified — see
    # diy_transit_analysis.tides.historic and plans/data-fetch.md's
    # Follow-ups), so this report is the de facto date filter: drop any
    # row whose scheduled_departure falls outside [start, end] before
    # counting anything.
    scheduled_dt = pd.to_datetime(performed["scheduled_departure"])
    in_range = (scheduled_dt.dt.date >= start) & (scheduled_dt.dt.date <= end)
    performed = performed[in_range]

    performed = performed[~performed["cancelled"].astype(bool)]
    performed["on_time"] = _is_on_time(performed["scheduled_departure"], performed["actual_departure"])

    performed_counts = performed.groupby("route_id")["trip_id"].nunique()
    on_time_counts = performed.groupby("route_id")["on_time"].sum()

    routes = feed.routes[["route_id", "route_short_name"]].copy()
    routes["route_short_name"] = routes["route_short_name"].fillna(routes["route_id"])

    rows = []
    for route_id in sorted(set(scheduled_counts.index) | set(performed_counts.index)):
        short_name = routes.loc[routes["route_id"] == route_id, "route_short_name"]
        short_name = short_name.iloc[0] if not short_name.empty else route_id

        scheduled = int(scheduled_counts.get(route_id, 0))
        performed_n = int(performed_counts.get(route_id, 0))
        on_time_n = int(on_time_counts.get(route_id, 0))

        rows.append(
            {
                "agency": agency,
                "route_id": route_id,
                "route_short_name": short_name,
                "date_range_start": start.isoformat(),
                "date_range_end": end.isoformat(),
                "scheduled_trip_count": scheduled,
                "performed_trip_count": performed_n,
                "on_time_trip_count": on_time_n,
                "on_time_percent": (on_time_n / performed_n) if performed_n else None,
                "cancellation_percent": (1 - performed_n / scheduled) if scheduled else None,
            }
        )

    return pd.DataFrame(rows)


def write_report(df: pd.DataFrame, output_dir: Path, agency: str, start: date, end: date) -> Path:
    """Write the report CSV to <output_dir>/reports/<agency>/otp-<start>-<end>.csv."""
    reports_dir = output_dir / "reports" / agency
    reports_dir.mkdir(parents=True, exist_ok=True)
    dest = reports_dir / f"otp-{start.isoformat()}-{end.isoformat()}.csv"
    df.to_csv(dest, index=False)
    return dest
