from pathlib import Path

import pytest

from diy_transit_analysis.config import ConfigError, get_agency, load_config

GOOD_CONFIG = """
output_dir: output
agencies:
  Foo:
    gtfs_schedule_url: "https://example.org/gtfs.zip"
    tides:
      gcs_bucket: "bucket"
      gcp_billing_project: "proj"
    date_range:
      start: "2026-01-01"
      end: "2026-03-31"
"""


def test_load_config_success(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GOOD_CONFIG)

    config = load_config(config_path)

    assert "Foo" in config.agencies
    agency = get_agency(config, "Foo")
    assert agency.gtfs_schedule_url == "https://example.org/gtfs.zip"
    assert agency.tides.gcs_bucket == "bucket"


def test_load_config_reports_every_missing_field(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("agencies:\n  Foo:\n    tides:\n      gcs_bucket: x\n")

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_path)

    message = str(exc_info.value)
    assert "output_dir" in message
    assert "gtfs_schedule_url" in message
    assert "gcp_billing_project" in message
    assert "date_range" in message


def test_unknown_agency_selector_fails(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GOOD_CONFIG)
    config = load_config(config_path)

    with pytest.raises(ConfigError, match="unknown agency"):
        get_agency(config, "NotARealAgency")


def test_non_http_url_rejected(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GOOD_CONFIG.replace("https://example.org/gtfs.zip", "file:///etc/passwd"))

    with pytest.raises(ConfigError, match="http"):
        load_config(config_path)


def test_start_after_end_rejected(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GOOD_CONFIG.replace('start: "2026-01-01"', 'start: "2026-06-01"'))

    with pytest.raises(ConfigError, match="start"):
        load_config(config_path)
