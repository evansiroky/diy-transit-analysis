---
status: done
depends: [data-fetch, otp-report]
specs:
  - specs/architecture.md
  - specs/data-model.md
  - specs/behaviors/config-validation.md
issues: []
pr: 1
---

# Plan: `run` command and GTFS-only schedule-stats report

## Scope

In scope:

- A new `run` CLI subcommand that composes `fetch-gtfs`, `fetch-tides`,
  `report otp`, and the new `report schedule-stats` into one command per
  `specs/architecture.md#the-run-subcommand`.
- A new `report schedule-stats` subcommand and
  `report/schedule_stats.py`, producing the report described in
  `specs/data-model.md#gtfs-schedule-stats-report-output` from a fetched
  GTFS feed alone — no TIDES fetch, no `date_range`.
- Making `agencies.<name>.tides` and `agencies.<name>.date_range` each
  independently optional in config, per
  `specs/behaviors/config-validation.md`'s updated rule, so a
  GTFS-only agency (just `gtfs_schedule_url`) is a valid config.
- Command-level (not config-validation-level) errors from `fetch-tides`
  and `report otp` when the selected agency didn't configure the block
  they need.

Out of scope: changing the on-time-performance report's own calculation
logic (`plans/otp-report.md`), changing the TIDES fetch's bucket-shape
assumptions (`plans/data-fetch.md`), and making the schedule-stats
report's representative-week columns configurable (fixed at "feed's own
first Monday–Sunday week" for this MVP, same fixed-constant precedent as
the OTP report's on-time threshold).

## Implements

- `specs/architecture.md` — "CLI entrypoint shape" and its new `run` /
  `report schedule-stats` subsections, and the GTFS-only config example.
- `specs/data-model.md#config-file` — optional `tides`/`date_range`
  blocks.
- `specs/data-model.md#gtfs-schedule-stats-report-output` — the new
  report's exact column set.
- `specs/behaviors/config-validation.md` — optional-block validation
  rule and the config-validation-vs-command-error distinction.

## Approach

1. `config.py`: change `AgencyConfig.tides` to `TidesConfig | None` and
   `AgencyConfig.date_range` to `DateRange | None`. `_parse_agency` calls
   `_parse_tides`/`_parse_date_range` only when the corresponding raw key
   is present in the agency mapping; each still validates fully (every
   required sub-field) when present. No changes to `_parse_tides`'s or
   `_parse_date_range`'s own internals.
2. `report/schedule_stats.py` (new module):
   - `build_schedule_stats_report(feed: gtfs_kit.Feed, agency: str) ->
     pandas.DataFrame` implementing every column in
     `specs/data-model.md#gtfs-schedule-stats-report-output`.
   - Feed date range: `feed.get_dates(as_date_obj=True)` → min/max for
     `feed_start_date`/`feed_end_date`. Raise `ValueError` if empty (no
     calendar info at all), per the spec's fail-loud rule.
   - Representative week: `feed.get_first_week(as_date_obj=True)`,
     falling back to `feed.get_dates(as_date_obj=True)` if that's empty
     (feed has no Monday within its validity — rare edge case). For each
     date in the representative week, `feed.get_trips(date=d)` (same
     gtfs-kit call already used in `report/on_time_performance.py`) gives
     that day's active trips; group by `route_id` to build per-route,
     per-day trip counts.
   - `stop_count`/`first_departure_time`/`last_departure_time`: derived
     from `stop_times` joined to `trips` (route_id), no date filtering —
     these are structural GTFS facts, not calendar-scoped. Departure
     times parsed as `HH:MM:SS` → total seconds (plain int split on `:`,
     not `pandas.to_timedelta`, since GTFS times can exceed 24:00:00) so
     min/max compare correctly, then formatted back to `HH:MM:SS`.
   - `write_report(df, output_dir, agency, feed_start, feed_end) -> Path`
     writes to
     `<output_dir>/reports/<agency>/schedule-stats-<feed_start>-<feed_end>.csv`,
     mirroring `on_time_performance.write_report`'s path convention.
3. `cli.py`:
   - `report schedule-stats` subcommand: loads the already-fetched GTFS
     zip (same "fetch first" precondition message as `report otp`), calls
     `build_schedule_stats_report` + `write_report`.
   - `fetch-tides` and `report otp`: at the top of each command function,
     check `agency.tides is None` (and `agency.date_range is None` for
     `report otp`) and raise a `SystemExit` naming exactly which
     `agencies.<name>.<block>` is missing and which command needs it —
     mirrors the existing "run fetch-gtfs first" `SystemExit` pattern
     already used for missing fetched-data preconditions.
   - `run` subcommand: for the selected agency, always fetch GTFS and
     always produce `schedule-stats`; fetch TIDES and produce `otp` only
     if `agency.tides`/`agency.date_range` are both set (checked once,
     since `report otp` needs both); print one line per step taken or
     skipped (skipped steps say why), matching
     `specs/architecture.md#the-run-subcommand`.
4. Tests:
   - `tests/test_config.py`: a GTFS-only config (no `tides:`, no
     `date_range:`) loads successfully with both fields `None`.
   - `tests/test_schedule_stats.py` (new): builds the report against
     `tests/fixtures/mini_gtfs.zip` and asserts `stop_count`, `trip_count`,
     `service_day_count`, `avg_trips_per_service_day`,
     `first_departure_time`/`last_departure_time`, and the
     zero-service-day null-safety case.
   - CLI-level test (or a light `cli.py` unit test, whichever the
     existing test suite's style favors once inspected) covering: `run`
     on a GTFS-only agency succeeds and produces only `schedule-stats`;
     `fetch-tides`/`report otp` on a GTFS-only agency raise a clear
     command-level error instead of an `AttributeError` on `None`.

## Validation

- [x] `agencies.<name>:` with only `gtfs_schedule_url` set loads
      successfully via `load_config`, with `tides is None` and
      `date_range is None`.
- [x] `diy-transit-analysis report schedule-stats --config ... --agency
      <gtfs-only agency>` (after `fetch-gtfs`) produces a CSV under
      `output/reports/<agency>/` with exactly the columns in
      `specs/data-model.md#gtfs-schedule-stats-report-output`, using only
      the fixture GTFS feed (no TIDES data, no configured `date_range`).
- [x] `diy-transit-analysis run --config ... --agency <gtfs-only agency>`
      succeeds, fetches GTFS, writes the schedule-stats report, and
      prints that it skipped TIDES fetch / the OTP report and why —
      without raising.
- [x] `diy-transit-analysis run --config ... --agency <full agency>`
      (tides + date_range both configured) fetches GTFS, fetches TIDES,
      and writes both reports.
- [x] `diy-transit-analysis fetch-tides` / `report otp` against a
      GTFS-only agency fail with a message naming the missing
      `agencies.<name>.tides` / `.date_range` block, not a raw
      `AttributeError`.
- [x] Unit test: a route with zero scheduled trips in the representative
      week reports `avg_trips_per_service_day` as `null`, not a
      divide-by-zero error.
- [x] Full existing test suite (`pytest`) still passes.

## Risks / unknowns

- **`get_first_week()` edge case** — gtfs-kit returns an empty list if
  the feed's calendar validity contains no Monday at all (a very short or
  oddly-bounded feed). Mitigated by falling back to `get_dates()`
  wholesale in that case; if the feed has *no* calendar info at all
  (`get_dates()` also empty), the report fails loudly per the spec rather
  than emitting nulls.
- **Representative-week choice** — using the feed's *first* week (rather
  than, say, its busiest week via gtfs-kit's `compute_busiest_date`)
  keeps the report reproducible without depending on today's date, but
  means a feed with a distinct "summer schedule" vs. "school-year
  schedule" reports whichever comes first chronologically. Acceptable for
  an MVP "various stats" report; revisit if this turns out to
  mischaracterize a real agency's typical service.

## Notes

- `feed.get_first_week()`/`feed.get_dates()` (gtfs-kit built-ins) turned
  out to cover exactly the "representative week" and "feed validity range"
  needs of this report, so no hand-rolled calendar expansion was needed —
  consistent with `specs/architecture.md`'s original rationale for
  choosing gtfs-kit (avoid re-implementing GTFS calendar logic).
- `run` reuses the single `feed` object it already fetched/parsed for both
  the schedule-stats report and (when applicable) the otp report, rather
  than each report step re-fetching/re-parsing the GTFS zip — a small
  efficiency `report otp` run standalone doesn't get (it re-loads from
  disk each time), acceptable since `report otp` run standalone is the
  less-common path once `run` exists.
- Verified against the real `gtfs-kit` 12.3.1 API (`get_dates`,
  `get_first_week`), not just assumed from documentation — installed the
  project in a scratch virtualenv and ran the full test suite plus a
  manual `run` invocation (GTFS fetch faked via monkeypatch to avoid a
  live network call — this sandboxed environment's outbound HTTP to the
  real SacRT feed URL used in `plans/data-fetch.md`'s original live
  verification now returns `403 Forbidden`, which looks like an
  environment/network-policy restriction rather than a code defect; not
  investigated further since this plan's validation doesn't depend on
  that specific live endpoint).
- Pushed directly to this task's working branch
  (`claude/gtfs-download-report-command-g46gjx`) with no PR opened, since
  none was requested — same no-PR-gate precedent as
  `plans/package-scaffold.md`. `pr:` records that rather than a real PR
  number; flip it to a real number if/when a PR is opened for this
  branch.

## Follow-ups

- Tracked as: live-verify `report schedule-stats` and `run` against a
  real, large public GTFS feed (e.g. the SacRT feed used in
  `plans/data-fetch.md`) once this environment's outbound network access
  allows it — same "implemented against a well-understood but not
  live-re-verified library API" gap already accepted for other parts of
  this project, not a blocker for closing this plan.
- Tracked as: revisit the "first week" representative-week choice (see
  Risks/unknowns above) if a real agency's schedule-stats report turns
  out to pick a chronologically-first week that's unrepresentative of
  their typical service (e.g. a summer-only opening week before the
  school-year schedule kicks in).
