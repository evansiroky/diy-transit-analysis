"""Config loading and validation.

Schema and validation rules are specified in:
- specs/data-model.md#config-file
- specs/behaviors/config-validation.md

Validation is purely structural/local — it never makes a network call.
Every problem found is collected and raised together in one ConfigError,
per specs/behaviors/config-validation.md ("list every missing field
found, not just the first").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

_ALLOWED_URL_SCHEMES = ("http://", "https://")


class ConfigError(ValueError):
    """Raised when a config file fails validation.

    Message lists every problem found in one shot, per
    specs/behaviors/config-validation.md.
    """


@dataclass(frozen=True)
class TidesConfig:
    gcs_bucket: str
    gcp_billing_project: str
    agency_prefix: str | None = None


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date


@dataclass(frozen=True)
class AgencyConfig:
    name: str
    gtfs_schedule_url: str
    tides: TidesConfig
    date_range: DateRange


@dataclass(frozen=True)
class Config:
    output_dir: Path
    agencies: dict[str, AgencyConfig]


def _parse_date(raw: object, *, field: str, errors: list[str]) -> date | None:
    if not isinstance(raw, str):
        errors.append(f"{field}: expected a YYYY-MM-DD string, got {raw!r}")
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        errors.append(f"{field}: {raw!r} is not a valid YYYY-MM-DD date")
        return None


def _parse_tides(raw: object, *, field: str, errors: list[str]) -> TidesConfig | None:
    if not isinstance(raw, dict):
        errors.append(f"{field}: required mapping (gcs_bucket, gcp_billing_project) is missing")
        return None

    gcs_bucket = raw.get("gcs_bucket")
    gcp_billing_project = raw.get("gcp_billing_project")
    agency_prefix = raw.get("agency_prefix")

    if not isinstance(gcs_bucket, str) or not gcs_bucket:
        errors.append(f"{field}.gcs_bucket: required, must be a non-empty string")
        gcs_bucket = None
    if not isinstance(gcp_billing_project, str) or not gcp_billing_project:
        errors.append(f"{field}.gcp_billing_project: required, must be a non-empty string")
        gcp_billing_project = None
    if agency_prefix is not None and not isinstance(agency_prefix, str):
        errors.append(f"{field}.agency_prefix: must be a string if present")
        agency_prefix = None

    if gcs_bucket is None or gcp_billing_project is None:
        return None
    return TidesConfig(
        gcs_bucket=gcs_bucket,
        gcp_billing_project=gcp_billing_project,
        agency_prefix=agency_prefix,
    )


def _parse_date_range(raw: object, *, field: str, errors: list[str]) -> DateRange | None:
    if not isinstance(raw, dict):
        errors.append(f"{field}: required mapping (start, end) is missing")
        return None

    start = _parse_date(raw.get("start"), field=f"{field}.start", errors=errors)
    end = _parse_date(raw.get("end"), field=f"{field}.end", errors=errors)
    if start is None or end is None:
        return None
    if start > end:
        errors.append(f"{field}: start ({start}) must be <= end ({end})")
        return None
    return DateRange(start=start, end=end)


def _parse_agency(name: str, raw: object, *, errors: list[str]) -> AgencyConfig | None:
    field = f"agencies.{name}"
    if not isinstance(raw, dict):
        errors.append(f"{field}: must be a mapping")
        return None

    gtfs_schedule_url = raw.get("gtfs_schedule_url")
    if not isinstance(gtfs_schedule_url, str) or not gtfs_schedule_url:
        errors.append(f"{field}.gtfs_schedule_url: required, must be a non-empty string")
        gtfs_schedule_url = None
    elif not gtfs_schedule_url.startswith(_ALLOWED_URL_SCHEMES):
        errors.append(
            f"{field}.gtfs_schedule_url: must start with http:// or https:// "
            f"(public data only — see specs/principles.md#public-data-only), got {gtfs_schedule_url!r}"
        )
        gtfs_schedule_url = None

    tides = _parse_tides(raw.get("tides"), field=f"{field}.tides", errors=errors)
    date_range = _parse_date_range(raw.get("date_range"), field=f"{field}.date_range", errors=errors)

    if gtfs_schedule_url is None or tides is None or date_range is None:
        return None

    return AgencyConfig(
        name=name,
        gtfs_schedule_url=gtfs_schedule_url,
        tides=tides,
        date_range=date_range,
    )


def load_config(path: str | Path) -> Config:
    """Load and fully validate a config file. Raises ConfigError on any problem."""
    path = Path(path)
    errors: list[str] = []

    try:
        raw_text = path.read_text()
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from exc

    try:
        raw = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top-level document must be a mapping")

    output_dir_raw = raw.get("output_dir")
    if not isinstance(output_dir_raw, str) or not output_dir_raw:
        errors.append("output_dir: required, must be a non-empty string")
        output_dir_raw = None

    agencies_raw = raw.get("agencies")
    agencies: dict[str, AgencyConfig] = {}
    if not isinstance(agencies_raw, dict) or not agencies_raw:
        errors.append("agencies: required, must be a non-empty mapping of agency name -> config")
    else:
        for name, agency_raw in agencies_raw.items():
            parsed = _parse_agency(str(name), agency_raw, errors=errors)
            if parsed is not None:
                agencies[str(name)] = parsed

    if errors:
        raise ConfigError(
            f"{path}: {len(errors)} config validation error(s):\n" + "\n".join(f"  - {e}" for e in errors)
        )

    assert output_dir_raw is not None  # no errors means these are set
    output_dir = (path.parent / output_dir_raw).resolve() if not Path(output_dir_raw).is_absolute() else Path(output_dir_raw)

    return Config(output_dir=output_dir, agencies=agencies)


def get_agency(config: Config, agency_name: str) -> AgencyConfig:
    """Look up an agency by name, raising ConfigError if it's not in the config."""
    try:
        return config.agencies[agency_name]
    except KeyError:
        known = ", ".join(sorted(config.agencies)) or "(none configured)"
        raise ConfigError(
            f"unknown agency {agency_name!r} — not present in config. Known agencies: {known}"
        ) from None
