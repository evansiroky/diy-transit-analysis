from pathlib import Path

import pytest

from diy_transit_analysis.config import ConfigError, NtdTimeSeriesSource, get_agency, load_config

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
    # tides: and date_range: are both present but incomplete here, so both
    # blocks' own required sub-fields must still be reported — even though
    # (per specs/behaviors/config-validation.md) omitting either block
    # entirely is now valid, an agency that opts into a block must still
    # fill it out.
    config_path = tmp_path / "config.yaml"
    config_path.write_text("agencies:\n  Foo:\n    tides:\n      gcs_bucket: x\n    date_range:\n      start: '2026-01-01'\n")

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_path)

    message = str(exc_info.value)
    assert "output_dir" in message
    assert "gtfs_schedule_url" in message
    assert "gcp_billing_project" in message
    assert "date_range.end" in message


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


def test_gtfs_only_agency_loads_with_no_tides_or_date_range(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "output_dir: output\n"
        "agencies:\n"
        "  Bar:\n"
        '    gtfs_schedule_url: "https://example.org/gtfs.zip"\n'
    )

    config = load_config(config_path)
    agency = get_agency(config, "Bar")

    assert agency.tides is None
    assert agency.date_range is None


def test_tides_block_still_validates_its_own_fields_when_present(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "output_dir: output\n"
        "agencies:\n"
        "  Bar:\n"
        '    gtfs_schedule_url: "https://example.org/gtfs.zip"\n'
        "    tides:\n"
        "      gcs_bucket: bucket\n"
    )

    with pytest.raises(ConfigError, match="gcp_billing_project"):
        load_config(config_path)


def test_agency_ntd_id_is_optional_and_independent_of_other_blocks(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GOOD_CONFIG.replace("gtfs_schedule_url:", 'ntd_id: "90019"\n    gtfs_schedule_url:'))

    config = load_config(config_path)

    assert get_agency(config, "Foo").ntd_id == "90019"
    assert config.ntd is None


def test_agency_ntd_id_must_be_non_empty_string(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GOOD_CONFIG.replace("gtfs_schedule_url:", "ntd_id: 90019\n    gtfs_schedule_url:"))

    with pytest.raises(ConfigError, match="ntd_id"):
        load_config(config_path)


_NTD_BLOCK = """
ntd:
  time_series:
    - name: "Unlinked Passenger Trips"
      category: service
      product_url: "https://www.transit.dot.gov/ntd/data-product/ts21-service-data"
      sheet: "UPT"
"""


def test_top_level_ntd_block_loads_when_valid(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GOOD_CONFIG + _NTD_BLOCK)

    config = load_config(config_path)

    assert config.ntd.time_series == [
        NtdTimeSeriesSource(
            name="Unlinked Passenger Trips",
            category="service",
            product_url="https://www.transit.dot.gov/ntd/data-product/ts21-service-data",
            sheet="UPT",
        )
    ]


def test_ntd_time_series_sheet_is_optional(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GOOD_CONFIG + _NTD_BLOCK.replace('      sheet: "UPT"\n', ""))

    config = load_config(config_path)

    assert config.ntd.time_series[0].sheet is None


def test_ntd_block_requires_non_empty_time_series(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GOOD_CONFIG + "\nntd:\n  time_series: []\n")

    with pytest.raises(ConfigError, match="time_series"):
        load_config(config_path)


def test_ntd_time_series_entry_rejects_unknown_category(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GOOD_CONFIG + _NTD_BLOCK.replace("category: service", "category: bogus"))

    with pytest.raises(ConfigError, match="category"):
        load_config(config_path)


def test_ntd_time_series_entry_rejects_non_http_url(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        GOOD_CONFIG
        + _NTD_BLOCK.replace(
            '"https://www.transit.dot.gov/ntd/data-product/ts21-service-data"', '"file:///etc/passwd"'
        )
    )

    with pytest.raises(ConfigError, match="http"):
        load_config(config_path)


def test_ntd_time_series_entry_requires_name(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(GOOD_CONFIG + _NTD_BLOCK.replace('name: "Unlinked Passenger Trips"\n      ', ""))

    with pytest.raises(ConfigError, match="name"):
        load_config(config_path)
