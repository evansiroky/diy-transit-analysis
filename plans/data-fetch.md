---
status: done
depends: [package-scaffold]
specs:
  - specs/architecture.md
  - specs/data-model.md
issues: []
pr: initial-scaffold-direct-to-main
---

# Plan: GTFS Schedule fetch/parse and TIDES historic data fetch

## Scope

In scope: filling in `gtfs/schedule.py` (fetch a GTFS Schedule `.zip` over
HTTP, parse it with `gtfs-kit`) and `tides/historic.py` (fetch an agency's
historic TIDES files from its configured GCS bucket), and wiring both into
the `fetch-gtfs` / `fetch-tides` CLI subcommands stubbed out in
`plans/package-scaffold.md`.

Out of scope: the on-time-performance report itself
(`plans/otp-report.md`, which consumes the outputs of this plan). Also out
of scope: verifying the TIDES bucket name/layout against the live
`tides.dds.dot.ca.gov` service with a real GCP project — that requires a
GCP account with billing, which is a manual one-time step for whoever runs
this for real; this plan implements against the documented assumption in
`specs/architecture.md#tides-historic-data-access` and fails loudly if the
assumption doesn't hold (e.g. bucket not found), rather than silently
returning nothing.

## Implements

- `specs/architecture.md` — "GTFS Schedule feed fetch + parse" and "TIDES
  historic data access" sections.
- `specs/data-model.md#gtfs-schedule-in-memory` and
  `specs/data-model.md#tides-historic-data-on-disk-fetched`.

## Approach

1. `gtfs/schedule.py`: `fetch_schedule(url: str, dest_dir: Path) -> Path`
   downloads to `<dest_dir>/gtfs.zip` via `requests` streaming GET;
   `load_schedule(zip_path: Path) -> gtfs_kit.Feed` wraps
   `gtfs_kit.read_feed(path, dist_units="km")`.
2. `tides/historic.py`: `fetch_historic(tides_config, date_range,
   dest_dir: Path) -> list[Path]` using `google.cloud.storage.Client()`
   and `bucket(gcs_bucket, user_project=gcp_billing_project)`, listing
   blobs under `agency_prefix` (if set) and downloading each to
   `dest_dir`. The function's docstring and an inline comment both state
   explicitly that the bucket name/layout is an assumption pending
   verification (per
   `specs/principles.md#fail-loud-on-unverified-assumptions`), and it
   raises a clearly-named `TidesAccessError` (wrapping the underlying GCS
   exception) rather than swallowing failures, so a wrong assumption is
   loud, not silent.
3. Wire both into `cli.py`'s `fetch-gtfs` / `fetch-tides` subcommands,
   replacing their `NotImplementedError` stubs; each writes into
   `<output_dir>/<agency>/gtfs/` or `<output_dir>/<agency>/tides/raw/`
   respectively, per `specs/data-model.md`.
4. Add a small local test fixture — a trimmed real GTFS zip (a handful of
   routes/trips/stops from a small agency, checked in under
   `tests/fixtures/`) — so `gtfs/schedule.py`'s parse path is tested
   without a live network call, per `specs/architecture.md#testing`.
   `tides/historic.py`'s GCS calls are mocked in tests (no live GCS
   fixture, since there is no verified-real bucket to fetch a fixture
   from yet).

## Validation

- [x] `diy-transit-analysis fetch-gtfs --config config/example.yaml --agency SacRT` downloads and parses the real SacRT GTFS feed end-to-end, writing the zip under `output/SacRT/gtfs/` and printing a summary (route/trip counts) without error. (Verified live: 47 routes, 4953 trips, 2534 stops from `http://iportal.sacrt.com/GTFS/SRTD/google_transit.zip`.)
- [x] `gtfs/schedule.py` has a passing unit test against the checked-in trimmed fixture (`tests/fixtures/mini_gtfs.zip`), with no live network call.
- [x] `tides/historic.py` raises `TidesAccessError` (not a raw/uncaught GCS exception) when the bucket doesn't exist or credentials are missing, verified with a mocked GCS client in a unit test, and manually confirmed against the real (unconfigured-credentials) environment — a raw `EnvironmentError` from `google.cloud.storage.Client()` surfaced through the first implementation; broadened the except clause to also catch that case and wrap it, so no un-wrapped exception reaches the CLI.
- [x] `tides/historic.py`'s docstring and `specs/architecture.md` both still say "assumed, verify against live endpoint" — no code comment silently drops that caveat.

## Risks / unknowns

- **TIDES bucket shape unverified** — the single largest unknown in this
  plan. If the real bucket layout differs meaningfully (e.g. it's a
  BigQuery dataset instead of flat GCS objects, or requires a signed URL
  flow instead of `user_project` billing), `tides/historic.py`'s
  implementation will need a follow-up plan once someone verifies the
  live endpoint with a real GCP project. Tracked as a Follow-up at
  closeout if not resolved within this plan.
- **No GCP project available during implementation** — this plan may
  close with the TIDES fetch path implemented-but-unverified against the
  live service; that's an acceptable, explicitly-flagged gap, not a
  blocker for closing the plan, per
  `specs/principles.md#fail-loud-on-unverified-assumptions`.

## Notes

- `fetch_historic()`'s actual signature dropped the `date_range` parameter
  sketched in Approach step 2 — with the bucket layout itself unverified,
  there's no confirmed way to filter server-side or client-side by date
  yet, so the MVP fetches everything under `agency_prefix` and leaves
  date filtering to the report step (which already scopes its GTFS-side
  calculation to the configured window). Tracked as a Follow-up below.
- An empty `list_blobs()` result is treated as a `TidesAccessError`, not a
  legitimate "no data for this window" case — reasonable for an
  unverified integration at MVP scale, but will need reconsidering once
  the real bucket is confirmed and genuinely-empty windows become
  possible.
- Verified GTFS fetch against the real, live SacRT feed rather than only
  a mock — this project's one real, working network integration so far.

## Follow-ups

- Deferred to [`otp-report`](otp-report.md) — once real TIDES data is
  fetchable, `fetch_historic` should accept the agency's `date_range` and
  either filter objects client-side by name/prefix or pass it through to
  whatever real query mechanism the live bucket turns out to support;
  until then, `otp-report`'s join logic is the de facto date filter via
  the GTFS side of the calculation.
- Tracked as: verifying the real TIDES bucket name, prefix/partitioning
  scheme, and file format against a live GCP project with billing enabled
  — no issue filed yet, this is a manual one-person step for whoever next
  has TIDES portal access.
