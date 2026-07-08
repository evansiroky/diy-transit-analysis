"""One-off script that generated tests/fixtures/mini_gtfs.zip.

Not part of the test suite itself (no test imports this module) — kept
alongside the fixture it produced so the fixture's provenance and shape
are easy to regenerate/audit rather than being an opaque binary blob.
Run with: python tests/fixtures/build_fixture_gtfs.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path

FIXTURE_PATH = Path(__file__).parent / "mini_gtfs.zip"

FILES = {
    "agency.txt": (
        "agency_id,agency_name,agency_url,agency_timezone\n"
        "AGY,Mini Transit,https://example.org,America/Los_Angeles\n"
    ),
    "routes.txt": (
        "route_id,agency_id,route_short_name,route_long_name,route_type\n"
        "R1,AGY,1,First Street Line,3\n"
        "R2,AGY,2,Second Street Line,3\n"
    ),
    "stops.txt": (
        "stop_id,stop_name,stop_lat,stop_lon\n"
        "S1,Start,38.58,-121.49\n"
        "S2,End,38.60,-121.47\n"
    ),
    "calendar.txt": (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
        "WEEKDAY,1,1,1,1,1,0,0,20260101,20260331\n"
    ),
    "trips.txt": (
        "route_id,service_id,trip_id\n"
        "R1,WEEKDAY,R1-T1\n"
        "R1,WEEKDAY,R1-T2\n"
        "R2,WEEKDAY,R2-T1\n"
    ),
    "stop_times.txt": (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "R1-T1,08:00:00,08:00:00,S1,1\n"
        "R1-T1,08:15:00,08:15:00,S2,2\n"
        "R1-T2,09:00:00,09:00:00,S1,1\n"
        "R1-T2,09:15:00,09:15:00,S2,2\n"
        "R2-T1,08:30:00,08:30:00,S1,1\n"
        "R2-T1,08:50:00,08:50:00,S2,2\n"
    ),
}


def main() -> None:
    with zipfile.ZipFile(FIXTURE_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in FILES.items():
            zf.writestr(name, content)
    print(f"wrote {FIXTURE_PATH}")


if __name__ == "__main__":
    main()
