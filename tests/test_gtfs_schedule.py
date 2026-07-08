from pathlib import Path

from diy_transit_analysis.gtfs import schedule

FIXTURE = Path(__file__).parent / "fixtures" / "mini_gtfs.zip"


def test_load_schedule_parses_fixture_with_no_network_call():
    feed = schedule.load_schedule(FIXTURE)
    assert set(feed.routes["route_id"]) == {"R1", "R2"}
    assert len(feed.trips) == 3


def test_summarize_counts():
    feed = schedule.load_schedule(FIXTURE)
    summary = schedule.summarize(feed)
    assert summary == {"route_count": 2, "trip_count": 3, "stop_count": 2}
