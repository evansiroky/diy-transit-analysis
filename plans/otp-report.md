---
status: done
depends: [data-fetch]
specs:
  - specs/data-model.md
issues: []
pr: initial-scaffold-direct-to-main
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
   - Deferred from [`data-fetch`](data-fetch.md): `fetch_historic()` does
     not filter by date range (the real TIDES bucket layout is still
     unverified, so there's no confirmed way to filter server-side yet).
     Until that lands, this report's GTFS-side `scheduled_trip_count`
     calculation is the de facto date filter for the whole report — the
     TIDES join must not assume `tides_files` only contains rows inside
     `date_range`, and should itself drop/ignore any performed-trip rows
     whose `scheduled_departure` falls outside `[start, end]` before
     counting, rather than trusting the fetch step to have pre-filtered.
2. `write_report(df, output_dir, agency, date_range) -> Path` writes to
   `<output_dir>/reports/<agency>/otp-<start>-<end>.csv`, per
   `specs/architecture.md#output-format`.
3. Wire into `cli.py`'s `report otp` subcommand, replacing its
   `NotImplementedError` stub.

## Validation

- [x] `diy-transit-analysis report otp --config config/example.yaml --agency SacRT` produces a CSV at `output/reports/SacRT/otp-<start>-<end>.csv` with exactly the columns listed in `specs/data-model.md#on-time-performance-report-output`, given previously-fetched GTFS + TIDES data. (Verified against the real fetched SacRT GTFS feed plus a small hand-built TIDES CSV sample, since real TIDES fetch is unverified — see `plans/data-fetch.md`.)
- [x] Running the same command twice with the same fetched inputs produces byte-identical CSV output (per `specs/principles.md#reproducibility-over-cleverness`). Verified with `diff` on two consecutive runs.
- [x] Unit test covers the null-safety rule: a route with `scheduled_trip_count == 0` reports `cancellation_percent` as `null`, not a divide-by-zero error.
- [x] Unit test covers the on-time window boundary (a trip exactly -1 or +5 minutes off counts as on-time; -1:01 or +5:01 does not).
- [x] Unit test covers the deferral from [`data-fetch`](data-fetch.md): a TIDES row whose `scheduled_departure` falls outside the configured `date_range` is excluded from `performed_trip_count`/`on_time_trip_count`, even though `fetch_historic()` itself does no date filtering.

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

- Absorbed the `data-fetch` deferral: the report now filters TIDES rows
  by `scheduled_departure` falling inside `[start, end]` before any
  counting, so it stays correct regardless of how much (or how little)
  `fetch_historic()` pre-filters in the future.
- TIDES CSV column-name assumptions (`route_id`, `trip_id`,
  `scheduled_departure`, `actual_departure`, `cancelled`) are the single
  biggest unverified surface in this report — see the module docstring in
  `report/on_time_performance.py`. Not resolvable until real TIDES data
  is fetchable (`plans/data-fetch.md` Follow-ups).
- route_id/trip_id are read from TIDES CSVs with `dtype=str` explicitly —
  without it, pandas infers numeric-looking agency IDs (e.g. `"001"`) as
  int64, which both loses leading zeros and breaks the join against
  gtfs-kit's string-typed route_id column. Found via the real SacRT
  manual end-to-end run, not by the unit tests (the fixture's IDs
  happened not to be numeric-looking).

## Follow-ups

- Tracked as: making the -1/+5 minute on-time threshold configurable, if
  a real agency's OTP convention turns out to differ once this is used
  for real reporting (currently a fixed constant, per this plan's Scope).
- Tracked as: confirming TIDES CSV column names/shape once real TIDES
  data is fetchable — same underlying blocker as `plans/data-fetch.md`'s
  bucket-verification follow-up.
