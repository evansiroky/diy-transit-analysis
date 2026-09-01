# diy-transit-analysis

A Python toolkit that pulls a transit agency's **GTFS Schedule** feed,
historic performance data from Caltrans' **TIDES** data portal
(https://tides.dds.dot.ca.gov), and multi-year trend data from the
**National Transit Database (NTD)** Time Series data products
(https://www.transit.dot.gov/ntd), and reports on on-time performance,
cancellations, and service/funding/expenditure/asset trends. Open source,
not monetized — built for journalists, advocates, board members, and
agencies themselves who want an independently-reproducible accountability
number.

## Status

Early scaffold. GTFS Schedule fetch/parse is implemented and tested
against a real live feed. TIDES historic data fetch is implemented against
a **documented, not-yet-verified assumption** about how the TIDES portal's
Google Cloud Storage bucket is laid out — see
[`specs/architecture.md`](specs/architecture.md#tides-historic-data-access)
and the module docstring in
[`src/diy_transit_analysis/tides/historic.py`](src/diy_transit_analysis/tides/historic.py)
before relying on it. The `report html` dashboard's two ETA benchmarks
implement the published
[ETA Completeness Benchmark](https://github.com/SwiftlyInc/ETA-Completeness-Benchmark)
and
[ETA Accuracy Benchmark](https://github.com/TransitApp/ETA-Accuracy-Benchmark)
methodologies exactly, but the trip-stop-level TIDES data they need is
an even newer, similarly **unverified** guess at two additional TIDES
CSV shapes — see
[`specs/data-model.md`](specs/data-model.md#tides-data-for-the-eta-benchmarks-assumed-separate-files).

NTD Time Series fetch/parsing (`fetch-ntd`, `report ntd`) fetches by
**scraping each data product's landing page** for its current `.xlsx`
download link — FTA doesn't publish a stable direct URL, and this
mirrors the same mechanism Caltrans' own
[cal-itp/data-infra](https://github.com/cal-itp/data-infra) uses in its
production NTD ingestion pipeline (confirmed by reading that project's
source, since `transit.dot.gov` itself was egress-blocked while building
this feature — see
[`specs/architecture.md`](specs/architecture.md#ntd-time-series-data-access)).
The four `product_url` landing pages in `config/example.yaml` are real,
confirmed-live URLs; the per-metric `sheet:` values are a best-guess
inferred from that same reference pipeline (not independently observed),
so sheet matching is deliberately resilient (case/punctuation-insensitive,
fails loudly listing the real sheet names on a miss) rather than pinned
to exact text — see the module docstring in
[`src/diy_transit_analysis/ntd/timeseries.py`](src/diy_transit_analysis/ntd/timeseries.py)
before relying on this for real reporting.

This project follows [spec-driven development](CLAUDE.md) — `specs/` is
the source of truth for intended behavior, `plans/` tracks work in flight.

## Install

```sh
pip install -e ".[dev]"
```

## Usage

Copy [`config/example.yaml`](config/example.yaml), point it at your
agency's GTFS feed (and, optionally, its TIDES bucket + reporting window,
and its NTD ID), then run everything in one command:

```sh
diy-transit-analysis run --config config/example.yaml --agency SacRT
```

`run` fetches the GTFS Schedule feed, generates the GTFS-only
`schedule-stats` and `html` (dashboard) reports, and — only if the
agency's config includes a `tides:` block and a `date_range:` block —
also fetches TIDES data and generates the `otp` (on-time-performance)
report; and — only if the config includes a top-level `ntd:` block and
the agency has `ntd_id:` configured — also fetches NTD Time Series data
and generates the `ntd` report, printing what it did or skipped (and why)
as it goes.

An agency that only configures `gtfs_schedule_url` (no `tides:`, no
`date_range:`, no `ntd_id:` — see the commented-out `SmallTownTransit`
example in `config/example.yaml`) is a fully valid config: `run` fetches
its GTFS feed and produces `schedule-stats` and `html` (route-level trip
counts, service span, stop counts, vehicles-in-service — no TIDES access,
GCP project, or NTD data required).

`report html` writes a single self-contained, offline-viewable HTML
dashboard — no external scripts/fonts/CDN — combining GTFS-only schedule
stats (vehicles in service by time of day + peak vehicles, scheduled
trips per service day) with, when TIDES is configured and fetched,
trips performed and the industry-standard
[ETA Completeness](https://github.com/SwiftlyInc/ETA-Completeness-Benchmark)
and [ETA Accuracy](https://github.com/TransitApp/ETA-Accuracy-Benchmark)
benchmark scores (see the Status section above on the TIDES assumptions
behind these two).

`report ntd` writes a second, similarly self-contained HTML report of
NTD Time Series trend charts for the agency — one chart per
`ntd.time_series[]` entry configured, grouped into Service, Expenditure,
Funding, and Asset sections (see the Status section above on the NTD
assumptions behind this one).

The individual pipeline stages are also available standalone:

```sh
diy-transit-analysis fetch-gtfs            --config config/example.yaml --agency SacRT
diy-transit-analysis fetch-tides           --config config/example.yaml --agency SacRT
diy-transit-analysis fetch-ntd             --config config/example.yaml --agency SacRT
diy-transit-analysis report schedule-stats --config config/example.yaml --agency SacRT
diy-transit-analysis report otp            --config config/example.yaml --agency SacRT
diy-transit-analysis report html           --config config/example.yaml --agency SacRT
diy-transit-analysis report ntd            --config config/example.yaml --agency SacRT
```

This writes fetched data and report files under `output/` (gitignored).
`fetch-tides` and `report otp` require a `tides:`/`date_range:`-configured
agency; `fetch-tides` also requires a Google Cloud project with billing
enabled, since the TIDES bucket is requester-pays (see the Status section
above). `report html` works for any agency, showing its TIDES benchmarks
section only when `tides:`/`date_range:` are configured and already
fetched. `fetch-ntd` requires only the top-level `ntd:` block (it fetches
files shared across every agency); `report ntd` additionally requires the
selected agency's `ntd_id:` and that `fetch-ntd` has already run.

## Development

```sh
pip install -e ".[dev]"
pytest
```

## License

MIT.
