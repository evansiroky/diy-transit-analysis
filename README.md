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
agency's GTFS feed and TIDES bucket, then:

```sh
diy-transit-analysis fetch-gtfs  --config config/example.yaml --agency SacRT
diy-transit-analysis fetch-tides --config config/example.yaml --agency SacRT
diy-transit-analysis report otp  --config config/example.yaml --agency SacRT
```

This writes fetched data and the report CSV under `output/` (gitignored).
`fetch-tides` requires a Google Cloud project with billing enabled — the
TIDES bucket is requester-pays (see the Status section above).

## Development

```sh
pip install -e ".[dev]"
pytest
```

## License

MIT.
