import shutil
from pathlib import Path

import pandas as pd
import pytest

from diy_transit_analysis import cli

FIXTURE = Path(__file__).parent / "fixtures" / "mini_gtfs.zip"

GTFS_ONLY_CONFIG = """
output_dir: output
agencies:
  Bar:
    gtfs_schedule_url: "https://example.org/gtfs.zip"
"""

FULL_CONFIG = """
output_dir: output
agencies:
  Bar:
    gtfs_schedule_url: "https://example.org/gtfs.zip"
    tides:
      gcs_bucket: bucket
      gcp_billing_project: proj
    date_range:
      start: "2026-01-05"
      end: "2026-01-05"
"""


def _fake_fetch_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real (network) fetch with a copy of the local fixture zip."""

    def _copy_fixture(url: str, dest_dir: Path, *, timeout: float = 60.0) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / "gtfs.zip"
        shutil.copyfile(FIXTURE, dest_path)
        return dest_path

    monkeypatch.setattr(cli.gtfs_schedule, "fetch_schedule", _copy_fixture)


def test_run_on_gtfs_only_agency_produces_schedule_stats_and_dashboard_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GTFS_ONLY_CONFIG)
    _fake_fetch_schedule(monkeypatch)

    exit_code = cli.main(["run", "--config", str(config_path), "--agency", "Bar"])

    assert exit_code == 0
    assert (tmp_path / "output" / "Bar" / "gtfs" / "gtfs.zip").exists()
    reports_dir = tmp_path / "output" / "reports" / "Bar"
    assert list(reports_dir.glob("schedule-stats-*.csv"))
    assert list(reports_dir.glob("dashboard-*.html"))
    assert not list(reports_dir.glob("otp-*.csv"))

    dashboard_html = next(reports_dir.glob("dashboard-*.html")).read_text()
    assert "Not shown" in dashboard_html  # TIDES section absent, with a note

    out = capsys.readouterr().out
    assert "Skipped TIDES fetch and the on-time-performance report" in out
    assert "agencies.Bar.tides is not configured" in out


def test_run_on_full_agency_produces_both_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(FULL_CONFIG)
    _fake_fetch_schedule(monkeypatch)

    def _fake_fetch_historic(tides_config, dest_dir: Path):
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / "trips_performed.csv"
        pd.DataFrame(
            [
                {
                    "route_id": "R1",
                    "trip_id": "R1-T1",
                    "scheduled_departure": "2026-01-05 08:00:00",
                    "actual_departure": "2026-01-05 08:00:00",
                    "cancelled": False,
                }
            ]
        ).to_csv(path, index=False)
        return [path]

    monkeypatch.setattr(cli.tides_historic, "fetch_historic", _fake_fetch_historic)

    exit_code = cli.main(["run", "--config", str(config_path), "--agency", "Bar"])

    assert exit_code == 0
    reports_dir = tmp_path / "output" / "reports" / "Bar"
    assert list(reports_dir.glob("schedule-stats-*.csv"))
    assert list(reports_dir.glob("otp-*.csv"))
    assert list(reports_dir.glob("dashboard-*.html"))

    dashboard_html = next(reports_dir.glob("dashboard-*.html")).read_text()
    assert "Trips performed" in dashboard_html


def test_report_html_standalone_on_gtfs_only_agency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GTFS_ONLY_CONFIG)
    _fake_fetch_schedule(monkeypatch)
    cli.main(["fetch-gtfs", "--config", str(config_path), "--agency", "Bar"])

    exit_code = cli.main(["report", "html", "--config", str(config_path), "--agency", "Bar"])

    assert exit_code == 0
    reports_dir = tmp_path / "output" / "reports" / "Bar"
    assert list(reports_dir.glob("dashboard-*.html"))


def test_report_html_on_configured_but_not_fetched_tides_fails_with_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(FULL_CONFIG)
    _fake_fetch_schedule(monkeypatch)
    cli.main(["fetch-gtfs", "--config", str(config_path), "--agency", "Bar"])

    with pytest.raises(SystemExit, match=r"tides.*raw.*not found"):
        cli.main(["report", "html", "--config", str(config_path), "--agency", "Bar"])


def test_fetch_tides_on_gtfs_only_agency_fails_with_clear_message(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GTFS_ONLY_CONFIG)

    with pytest.raises(SystemExit, match=r"agencies\.Bar\.tides is not configured"):
        cli.main(["fetch-tides", "--config", str(config_path), "--agency", "Bar"])


def test_report_otp_on_gtfs_only_agency_fails_with_clear_message(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GTFS_ONLY_CONFIG)

    with pytest.raises(SystemExit, match=r"agencies\.Bar\.tides is not configured"):
        cli.main(["report", "otp", "--config", str(config_path), "--agency", "Bar"])
