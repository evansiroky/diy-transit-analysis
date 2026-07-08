---
status: planned
depends: [data-fetch]
specs:
  - specs/data-model.md
issues: []
pr:
---

# Plan: On-time performance report

## Scope

In scope: `report/on_time_performance.py`, producing the CSV described in
`specs/data-model.md#on-time-performance-report-output`, and wiring it
into the `report otp` CLI subcommand.

Out of scope: any report type beyond on-time performance / cancellation
rate (e.g. NTD cost/ridership trend reporting from the original idea doc)
— those are future plans once this MVP's single report type is proven
out. Also out of scope: making the on-time threshold configurable (fixed
at -1/+5 minutes per `specs/data-model.md`, tracked as a Follow-up if it
turns out to matter before this ships for real).

## Implements

- `specs/data-model.md#on-time-performance-report-output` — the report's
  exact column set and calculations.

## Approach

1. `report/on_time_performance.py`: `build_otp_report(feed: gtfs_kit.Feed,
   tides_files: list[Path], date_range) -> pandas.DataFrame` that:
   - Derives `scheduled_trip_count` per route from the GTFS feed's
     `trips` + `calendar`/`calendar_dates`, restricted to the configured
     date range.
   - Parses the fetched TIDES CSV(s) for performed-trip records
     (`performed_trip_count`, on-time count using the -1/+5 minute
     window) per route, matching TIDES trip/route identifiers to GTFS
     `route_id`s — this join is the one place real TIDES sample data is
     needed to get right, so it's implemented against the documented CSV
     assumption and covered by a unit test using a small hand-built CSV
     fixture rather than live TIDES data.
   - Computes `on_time_percent` / `cancellation_percent`, `null`-safe per
     `specs/data-model.md`.
2. `write_report(df, output_dir, agency, date_range) -> Path` writes to
   `<output_dir>/reports/<agency>/otp-<start>-<end>.csv`, per
   `specs/architecture.md#output-format`.
3. Wire into `cli.py`'s `report otp` subcommand, replacing its
   `NotImplementedError` stub.

## Validation

- [ ] `diy-transit-analysis report otp --config config/example.yaml --agency SacRT` produces a CSV at `output/reports/SacRT/otp-<start>-<end>.csv` with exactly the columns listed in `specs/data-model.md#on-time-performance-report-output`, given previously-fetched GTFS + TIDES data.
- [ ] Running the same command twice with the same fetched inputs produces byte-identical CSV output (per `specs/principles.md#reproducibility-over-cleverness`).
- [ ] Unit test covers the null-safety rule: a route with `scheduled_trip_count == 0` reports `cancellation_percent` as `null`, not a divide-by-zero error.
- [ ] Unit test covers the on-time window boundary (a trip exactly -1 or +5 minutes off counts as on-time; -1:01 or +5:01 does not).

## Risks / unknowns

- **TIDES-to-GTFS route/trip matching** — TIDES records identify trips by
  whatever identifiers the agency submitted, which may not line up
  cleanly with GTFS `route_id`/`trip_id` without a documented mapping.
  This plan's join logic is a best-effort implementation against
  currently-understood TIDES field names (see
  `specs/data-model.md#tides-historic-data-on-disk-fetched`); if a real
  fetched TIDES sample (once `plans/data-fetch.md`'s unverified bucket
  assumption is confirmed) shows a different identifier scheme, this
  logic will need a follow-up fix.

## Notes

(Populated at closeout.)

## Follow-ups

(Populated at closeout.)
