"""CLI entrypoint. Spec: specs/architecture.md#cli-entrypoint-shape."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from diy_transit_analysis.config import AgencyConfig, Config, ConfigError, get_agency, load_config
from diy_transit_analysis.gtfs import schedule as gtfs_schedule
from diy_transit_analysis.ntd import timeseries as ntd_timeseries
from diy_transit_analysis.ntd.timeseries import NtdDataError
from diy_transit_analysis.report import dashboard
from diy_transit_analysis.report import ntd as ntd_report
from diy_transit_analysis.report import on_time_performance as otp
from diy_transit_analysis.report import schedule_stats
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


def _require_tides(agency: AgencyConfig, config_path: str, command: str) -> None:
    if agency.tides is None:
        raise SystemExit(
            f"error: agencies.{agency.name}.tides is not configured in {config_path} — "
            f"{command} requires a tides: block (gcs_bucket, gcp_billing_project)."
        )


def _require_date_range(agency: AgencyConfig, config_path: str, command: str) -> None:
    if agency.date_range is None:
        raise SystemExit(
            f"error: agencies.{agency.name}.date_range is not configured in {config_path} — "
            f"{command} requires a date_range: block (start, end)."
        )


def _require_ntd_id(agency: AgencyConfig, config_path: str, command: str) -> None:
    if agency.ntd_id is None:
        raise SystemExit(
            f"error: agencies.{agency.name}.ntd_id is not configured in {config_path} — "
            f"{command} requires ntd_id: to be set for this agency."
        )


def cmd_fetch_tides(args: argparse.Namespace) -> int:
    config, agency_name = _load(args)
    agency = get_agency(config, agency_name)
    _require_tides(agency, args.config, "fetch-tides")

    dest_dir = config.output_dir / agency_name / "tides" / "raw"
    print(
        f"Fetching TIDES historic data for {agency_name} from "
        f"gs://{agency.tides.gcs_bucket} (billed to {agency.tides.gcp_billing_project}) ..."
    )
    written = tides_historic.fetch_historic(agency.tides, dest_dir)
    print(f"Saved {len(written)} file(s) to {dest_dir}.")
    return 0


def cmd_fetch_ntd(args: argparse.Namespace) -> int:
    # Agency-independent fetch against the built-in catalog (specs/
    # architecture.md#ntd-time-series-data-access) — --agency is still
    # validated for CLI-shape consistency, but ntd_id isn't required for
    # this command, and there's no NTD-related config to check at all.
    config, agency_name = _load(args)

    dest_dir = config.output_dir / "ntd" / "raw"
    print(f"Fetching {len(ntd_timeseries.DEFAULT_TIME_SERIES_SOURCES)} NTD Time Series source(s) to {dest_dir} ...")
    written = ntd_timeseries.fetch_time_series(ntd_timeseries.DEFAULT_TIME_SERIES_SOURCES, dest_dir)
    print(f"Saved {len(written)} file(s) to {dest_dir}.")
    return 0


def cmd_report_otp(args: argparse.Namespace) -> int:
    config, agency_name = _load(args)
    agency = get_agency(config, agency_name)
    _require_tides(agency, args.config, "report otp")
    _require_date_range(agency, args.config, "report otp")

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


def _write_schedule_stats(feed, config: Config, agency_name: str) -> None:
    """Build + write the schedule-stats report, printing the same summary line every caller wants."""
    df = schedule_stats.build_schedule_stats_report(feed, agency=agency_name)
    feed_start = date.fromisoformat(df["feed_start_date"].iloc[0])
    feed_end = date.fromisoformat(df["feed_end_date"].iloc[0])
    dest = schedule_stats.write_report(df, config.output_dir, agency_name, feed_start, feed_end)
    print(f"Wrote {len(df)} row(s) to {dest}.")


def cmd_report_schedule_stats(args: argparse.Namespace) -> int:
    config, agency_name = _load(args)

    gtfs_zip = config.output_dir / agency_name / "gtfs" / "gtfs.zip"
    if not gtfs_zip.exists():
        raise SystemExit(
            f"error: {gtfs_zip} not found — run `fetch-gtfs --config {args.config} --agency {agency_name}` first."
        )

    feed = gtfs_schedule.load_schedule(gtfs_zip)
    _write_schedule_stats(feed, config, agency_name)
    return 0


def _write_dashboard(
    feed,
    config: Config,
    agency_name: str,
    *,
    tides_files: list | None = None,
    date_range: tuple | None = None,
) -> None:
    data = dashboard.build_dashboard_data(
        feed, agency=agency_name, tides_files=tides_files, date_range=date_range
    )
    html = dashboard.render_html(data)
    dest = dashboard.write_html(html, config.output_dir, agency_name, data.feed_start_date, data.feed_end_date)
    print(f"Wrote dashboard to {dest}.")


def cmd_report_html(args: argparse.Namespace) -> int:
    config, agency_name = _load(args)
    agency = get_agency(config, agency_name)

    gtfs_zip = config.output_dir / agency_name / "gtfs" / "gtfs.zip"
    if not gtfs_zip.exists():
        raise SystemExit(
            f"error: {gtfs_zip} not found — run `fetch-gtfs --config {args.config} --agency {agency_name}` first."
        )
    feed = gtfs_schedule.load_schedule(gtfs_zip)

    tides_files = None
    date_range = None
    if agency.tides is not None:
        tides_dir = config.output_dir / agency_name / "tides" / "raw"
        if not tides_dir.is_dir():
            raise SystemExit(
                f"error: {tides_dir} not found — run `fetch-tides --config {args.config} --agency {agency_name}` first."
            )
        if agency.date_range is not None:
            tides_files = sorted(tides_dir.glob("*.csv"))
            date_range = (agency.date_range.start, agency.date_range.end)

    _write_dashboard(feed, config, agency_name, tides_files=tides_files, date_range=date_range)
    return 0


def _write_ntd_report(config: Config, agency_name: str, ntd_id: str) -> None:
    raw_dir = config.output_dir / "ntd" / "raw"
    data = ntd_report.build_ntd_report_data(
        ntd_timeseries.DEFAULT_TIME_SERIES_SOURCES, raw_dir, agency=agency_name, ntd_id=ntd_id
    )
    html = ntd_report.render_html(data)
    dest = ntd_report.write_html(html, config.output_dir, agency_name, data.min_year, data.max_year)
    print(f"Wrote NTD Time Series report to {dest}.")


def cmd_report_ntd(args: argparse.Namespace) -> int:
    config, agency_name = _load(args)
    agency = get_agency(config, agency_name)
    _require_ntd_id(agency, args.config, "report ntd")

    raw_dir = config.output_dir / "ntd" / "raw"
    if not raw_dir.is_dir():
        raise SystemExit(
            f"error: {raw_dir} not found — run `fetch-ntd --config {args.config} --agency {agency_name}` first."
        )

    _write_ntd_report(config, agency_name, agency.ntd_id)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Fetch everything and generate every report the selected agency's config supports.

    Always fetches GTFS and produces the schedule-stats report (GTFS-only,
    no tides/date_range needed). Fetches TIDES and produces the otp report
    only if the agency configured tides: (and, for otp, date_range: too).
    Fetches NTD Time Series data (against the built-in catalog — no
    NTD-related config to check) and produces the ntd report only if the
    agency's ntd_id: is configured — see
    specs/architecture.md#the-run-subcommand.
    """
    config, agency_name = _load(args)
    agency = get_agency(config, agency_name)

    gtfs_dest_dir = config.output_dir / agency_name / "gtfs"
    print(f"[run] Fetching GTFS Schedule feed for {agency_name} from {agency.gtfs_schedule_url} ...")
    zip_path = gtfs_schedule.fetch_schedule(agency.gtfs_schedule_url, gtfs_dest_dir)
    feed = gtfs_schedule.load_schedule(zip_path)
    summary = gtfs_schedule.summarize(feed)
    print(
        f"[run] Saved to {zip_path}. "
        f"{summary['route_count']} routes, {summary['trip_count']} trips, "
        f"{summary['stop_count']} stops."
    )

    print(f"[run] Generating schedule-stats report for {agency_name} ...")
    _write_schedule_stats(feed, config, agency_name)

    tides_files = None
    date_range = None

    if agency.tides is None:
        print(
            f"[run] Skipped TIDES fetch and the on-time-performance report: "
            f"agencies.{agency_name}.tides is not configured."
        )
    else:
        tides_dir = config.output_dir / agency_name / "tides" / "raw"
        print(
            f"[run] Fetching TIDES historic data for {agency_name} from "
            f"gs://{agency.tides.gcs_bucket} (billed to {agency.tides.gcp_billing_project}) ..."
        )
        written = tides_historic.fetch_historic(agency.tides, tides_dir)
        print(f"[run] Saved {len(written)} file(s) to {tides_dir}.")

        if agency.date_range is None:
            print(
                f"[run] Skipped the on-time-performance report: "
                f"agencies.{agency_name}.date_range is not configured."
            )
        else:
            print(f"[run] Generating on-time-performance report for {agency_name} ...")
            tides_files = sorted(tides_dir.glob("*.csv"))
            date_range = (agency.date_range.start, agency.date_range.end)
            otp_df = otp.build_otp_report(
                feed,
                tides_files,
                agency=agency_name,
                start=agency.date_range.start,
                end=agency.date_range.end,
            )
            otp_dest = otp.write_report(
                otp_df, config.output_dir, agency_name, agency.date_range.start, agency.date_range.end
            )
            print(f"[run] Wrote {len(otp_df)} row(s) to {otp_dest}.")

    print(f"[run] Generating dashboard report for {agency_name} ...")
    _write_dashboard(feed, config, agency_name, tides_files=tides_files, date_range=date_range)

    if agency.ntd_id is None:
        print(
            f"[run] Skipped NTD fetch and the NTD Time Series report: "
            f"agencies.{agency_name}.ntd_id is not configured."
        )
    else:
        ntd_dest_dir = config.output_dir / "ntd" / "raw"
        print(
            f"[run] Fetching {len(ntd_timeseries.DEFAULT_TIME_SERIES_SOURCES)} "
            f"NTD Time Series source(s) to {ntd_dest_dir} ..."
        )
        ntd_written = ntd_timeseries.fetch_time_series(ntd_timeseries.DEFAULT_TIME_SERIES_SOURCES, ntd_dest_dir)
        print(f"[run] Saved {len(ntd_written)} file(s) to {ntd_dest_dir}.")

        print(f"[run] Generating NTD Time Series report for {agency_name} ...")
        _write_ntd_report(config, agency_name, agency.ntd_id)

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

    fetch_ntd = subparsers.add_parser(
        "fetch-ntd", help="Fetch the built-in catalog of NTD Time Series source files (agency-independent)."
    )
    _add_common_args(fetch_ntd)
    fetch_ntd.set_defaults(func=cmd_fetch_ntd)

    report = subparsers.add_parser("report", help="Generate a report.")
    report_subparsers = report.add_subparsers(dest="report_type", required=True)
    report_otp = report_subparsers.add_parser("otp", help="On-time-performance / cancellation-rate report.")
    _add_common_args(report_otp)
    report_otp.set_defaults(func=cmd_report_otp)

    report_schedule_stats = report_subparsers.add_parser(
        "schedule-stats",
        help="GTFS-only scheduled-service stats report (no TIDES fetch, no date_range needed).",
    )
    _add_common_args(report_schedule_stats)
    report_schedule_stats.set_defaults(func=cmd_report_schedule_stats)

    report_html = report_subparsers.add_parser(
        "html",
        help="Static HTML dashboard combining schedule stats and (when available) TIDES benchmarks.",
    )
    _add_common_args(report_html)
    report_html.set_defaults(func=cmd_report_html)

    report_ntd = report_subparsers.add_parser(
        "ntd",
        help="Static HTML report of NTD Time Series trend charts (service, expenditure, funding, asset).",
    )
    _add_common_args(report_ntd)
    report_ntd.set_defaults(func=cmd_report_ntd)

    run = subparsers.add_parser(
        "run",
        help="Fetch GTFS (+ TIDES/NTD if configured) and generate every report the agency's config supports.",
    )
    _add_common_args(run)
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, TidesAccessError, NtdDataError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
