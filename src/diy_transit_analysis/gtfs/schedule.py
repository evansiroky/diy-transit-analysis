"""Fetch and parse a GTFS Schedule feed.

Spec: specs/architecture.md#gtfs-schedule-feed-fetch--parse
"""

from __future__ import annotations

from pathlib import Path

import gtfs_kit as gk
import requests


def fetch_schedule(url: str, dest_dir: Path, *, timeout: float = 60.0) -> Path:
    """Download a GTFS Schedule .zip to dest_dir/gtfs.zip and return its path.

    Plain HTTP GET, streamed to disk — no auth, matches
    specs/principles.md#public-data-only.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / "gtfs.zip"

    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with dest_path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 16):
                f.write(chunk)

    return dest_path


def load_schedule(zip_path: Path) -> gk.Feed:
    """Parse a GTFS Schedule .zip into a gtfs_kit.Feed.

    See specs/data-model.md#gtfs-schedule-in-memory — this project does not
    redefine gtfs-kit's own DataFrame schema.
    """
    return gk.read_feed(zip_path, dist_units="km")


def summarize(feed: gk.Feed) -> dict[str, int]:
    """A cheap sanity-check summary used by the CLI after a fetch (route/trip counts)."""
    return {
        "route_count": 0 if feed.routes is None else len(feed.routes),
        "trip_count": 0 if feed.trips is None else len(feed.trips),
        "stop_count": 0 if feed.stops is None else len(feed.stops),
    }
