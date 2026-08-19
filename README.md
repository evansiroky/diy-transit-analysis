# diy-transit-analysis

A Python toolkit that pulls a transit agency's **GTFS Schedule** feed and
historic performance data from Caltrans' **TIDES** data portal
(https://tides.dds.dot.ca.gov), and reports on on-time performance and
cancellations. Open source, not monetized — built for journalists,
advocates, board members, and agencies themselves who want an
independently-reproducible accountability number.

## Status

Early scaffold. GTFS Schedule fetch/parse is implemented and tested
against a real live feed. TIDES historic data fetch is implemented against
a **documented, not-yet-verified assumption** about how the TIDES portal's
Google Cloud Storage bucket is laid out — see
[`specs/architecture.md`](specs/architecture.md#tides-historic-data-access)
and the module docstring in
[`src/diy_transit_analysis/tides/historic.py`](src/diy_transit_analysis/tides/historic.py)
before relying on it.

This project follows [spec-driven development](CLAUDE.md) — `specs/` is
the source of truth for intended behavior, `plans/` tracks work in flight.

## Install

```sh
pip install -e ".[dev]"
```

## Usage

Copy [`config/example.yaml`](config/example.yaml), point it at your
agency's GTFS feed (and, optionally, its TIDES bucket + reporting window),
then run everything in one command:

```sh
diy-transit-analysis run --config config/example.yaml --agency SacRT
```

`run` fetches the GTFS Schedule feed, generates the GTFS-only
`schedule-stats` report, and — only if the agency's config includes a
`tides:` block and a `date_range:` block — also fetches TIDES data and
generates the `otp` (on-time-performance) report, printing what it did or
skipped (and why) as it goes.

An agency that only configures `gtfs_schedule_url` (no `tides:`, no
`date_range:` — see the commented-out `SmallTownTransit` example in
`config/example.yaml`) is a fully valid config: `run` fetches its GTFS
feed and produces `schedule-stats` (route-level trip counts, service
span, stop counts — no TIDES access or GCP project required).

The individual pipeline stages are also available standalone:

```sh
diy-transit-analysis fetch-gtfs            --config config/example.yaml --agency SacRT
diy-transit-analysis fetch-tides           --config config/example.yaml --agency SacRT
diy-transit-analysis report schedule-stats --config config/example.yaml --agency SacRT
diy-transit-analysis report otp            --config config/example.yaml --agency SacRT
```

This writes fetched data and report CSVs under `output/` (gitignored).
`fetch-tides` and `report otp` require a `tides:`/`date_range:`-configured
agency; `fetch-tides` also requires a Google Cloud project with billing
enabled, since the TIDES bucket is requester-pays (see the Status section
above).

## Development

```sh
pip install -e ".[dev]"
pytest
```

## License

MIT.
