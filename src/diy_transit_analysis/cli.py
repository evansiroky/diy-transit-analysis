"""CLI entrypoint. Spec: specs/architecture.md#cli-entrypoint-shape."""

from __future__ import annotations

import argparse
import sys

from diy_transit_analysis.config import Config, ConfigError, get_agency, load_config
from diy_transit_analysis.gtfs import schedule as gtfs_schedule
from diy_transit_analysis.report import on_time_performance as otp
from diy_transit_analysis.tides import historic as tides_historic
from diy_transit_analysis.tides.historic import TidesAccessError


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True, help="Path to the YAML config file.")
    parser.add_argument("--agency", required=True, help="Agency name, as configured under agencies:.")


def _load(args: argparse.Namespace) -> tuple[Config, str]:
    config = load_config(args.config)
    get_agency(config, args.agency)  # validates the --agency selector, per behaviors/config-validation.md
    return config, args.agency


def cmd_fetch_gtfs(args: argparse.Namespace) -> int:
    config, agency_name = _load(args)
    agency = get_agency(config, agency_name)

    dest_dir = config.output_dir / agency_name / "gtfs"
    print(f"Fetching GTFS Schedule feed for {agency_name} from {agency.gtfs_schedule_url} ...")
    zip_path = gtfs_schedule.fetch_schedule(agency.gtfs_schedule_url, dest_dir)
    feed = gtfs_schedule.load_schedule(zip_path)
    summary = gtfs_schedule.summarize(feed)
    print(
        f"Saved to {zip_path}. "
        f"{summary['route_count']} routes, {summary['trip_count']} trips, "
        f"{summary['stop_count']} stops."
    )
    return 0


def cmd_fetch_tides(args: argparse.Namespace) -> int:
    config, agency_name = _load(args)
    agency = get_agency(config, agency_name)

    dest_dir = config.output_dir / agency_name / "tides" / "raw"
    print(
        f"Fetching TIDES historic data for {agency_name} from "
        f"gs://{agency.tides.gcs_bucket} (billed to {agency.tides.gcp_billing_project}) ..."
    )
    written = tides_historic.fetch_historic(agency.tides, dest_dir)
    print(f"Saved {len(written)} file(s) to {dest_dir}.")
    return 0


def cmd_report_otp(args: argparse.Namespace) -> int:
    config, agency_name = _load(args)
    agency = get_agency(config, agency_name)

    gtfs_zip = config.output_dir / agency_name / "gtfs" / "gtfs.zip"
    tides_dir = config.output_dir / agency_name / "tides" / "raw"
    if not gtfs_zip.exists():
        raise SystemExit(
            f"error: {gtfs_zip} not found — run `fetch-gtfs --config {args.config} --agency {agency_name}` first."
        )
    if not tides_dir.is_dir():
        raise SystemExit(
            f"error: {tides_dir} not found — run `fetch-tides --config {args.config} --agency {agency_name}` first."
        )

    feed = gtfs_schedule.load_schedule(gtfs_zip)
    tides_files = sorted(tides_dir.glob("*.csv"))

    df = otp.build_otp_report(
        feed,
        tides_files,
        agency=agency_name,
        start=agency.date_range.start,
        end=agency.date_range.end,
    )
    dest = otp.write_report(df, config.output_dir, agency_name, agency.date_range.start, agency.date_range.end)
    print(f"Wrote {len(df)} row(s) to {dest}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diy-transit-analysis",
        description="Fetch GTFS Schedule + Caltrans TIDES data and report on transit on-time performance.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_gtfs = subparsers.add_parser("fetch-gtfs", help="Fetch and parse an agency's GTFS Schedule feed.")
    _add_common_args(fetch_gtfs)
    fetch_gtfs.set_defaults(func=cmd_fetch_gtfs)

    fetch_tides = subparsers.add_parser("fetch-tides", help="Fetch an agency's historic TIDES data.")
    _add_common_args(fetch_tides)
    fetch_tides.set_defaults(func=cmd_fetch_tides)

    report = subparsers.add_parser("report", help="Generate a report.")
    report_subparsers = report.add_subparsers(dest="report_type", required=True)
    report_otp = report_subparsers.add_parser("otp", help="On-time-performance / cancellation-rate report.")
    _add_common_args(report_otp)
    report_otp.set_defaults(func=cmd_report_otp)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, TidesAccessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
