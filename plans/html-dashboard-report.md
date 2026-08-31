---
status: done
depends: [run-and-schedule-stats]
specs:
  - specs/architecture.md
  - specs/data-model.md
  - specs/behaviors/config-validation.md
issues: []
pr: 2
---

# Plan: Static HTML dashboard report

## Scope

In scope:

- A new `report html` subcommand (and its inclusion in `run`, always)
  producing a self-contained static HTML file per
  `specs/data-model.md#static-html-dashboard-report-output`.
- Schedule-based stats: vehicles-in-service by time of day (+ peak
  vehicles/time) for the feed's representative-week busiest date, and
  scheduled trips per service day across the feed's whole valid date
  range.
- TIDES-based stats (when available): trips performed,
  `realtime_completeness_percent`, `eta_accuracy_percent`.
- Extending the TIDES CSV assumption with two new **optional** columns
  (`realtime_data_available`, `predicted_departure`) needed for the two
  new benchmarks, documented as unverified per
  `specs/data-model.md#tides-historic-data-on-disk-fetched`.
- Reusing `report/on_time_performance.py`'s TIDES-CSV reader (made
  public) and `report/schedule_stats.py`'s feed-date-range /
  representative-week helpers (made public) rather than duplicating
  either.

Out of scope: any interactivity beyond a minimal hover/crosshair
affordance on the two charts (no filtering UI, no client-side date-range
picker — the report is generated for one fixed window per run, matching
every other report in this project). Also out of scope: a per-route
breakdown in the HTML report (the existing `report schedule-stats` CSV
already covers that grain); verifying the two new TIDES benchmark columns
against a real fetched TIDES sample (tracked as a Follow-up, same
unresolved-until-live-bucket-access blocker as `plans/data-fetch.md`).

## Implements

- `specs/data-model.md#static-html-dashboard-report-output` — the
  report's content and file-naming.
- `specs/data-model.md#tides-historic-data-on-disk-fetched` — the two new
  optional assumed TIDES columns and their fail-soft (not fail-loud)
  handling.
- `specs/architecture.md#the-report-html-dashboards-rendering-approach`
  — inline-SVG, no-JS-framework, no-CDN rendering approach.
- `specs/behaviors/config-validation.md` — `report html`'s
  configured-but-not-fetched-yet vs. not-configured-at-all distinction.

## Approach

1. `report/schedule_stats.py`: rename `_feed_date_range` →
   `feed_date_range` and `_representative_week` → `representative_week`
   (drop the leading underscore, no behavior change) so
   `report/dashboard.py` can reuse them instead of recomputing the same
   thing a second way.
2. `report/on_time_performance.py`: rename `_read_tides_performed` →
   `read_tides_performed` (same reasoning) so `report/dashboard.py` can
   reuse the same required-5-column TIDES read instead of a second
   assumed-schema implementation.
3. `report/dashboard.py` (new module):
   - `build_dashboard_data(feed, agency, tides_files=None, date_range=None) -> DashboardData`
     (frozen dataclasses for the return shape):
     - Schedule section: `feed.compute_trip_stats()` once; representative
       week via `schedule_stats.representative_week(feed)`;
       `feed.compute_busiest_date(week)` for the busiest date;
       `feed.compute_network_time_series([busiest], trip_stats=...,
       freq="15Min")` for the vehicles-in-service curve;
       `feed.compute_network_stats([busiest], trip_stats=...)` for the
       exact `peak_num_trips`/`peak_start_time` (not derived from the
       15-minute-binned curve, to avoid binning-induced undercount);
       `feed.compute_network_stats(feed.get_dates(), trip_stats=...)` for
       the per-service-day trip counts across the whole feed.
     - TIDES section (only built when both `tides_files` and
       `date_range` are given): reuses
       `otp.read_tides_performed(tides_files)`, applies the same
       date-range + not-cancelled filtering `build_otp_report` already
       does, then computes the two benchmarks from the two optional
       columns (each independently `null` if its column is absent from
       every fetched file, or if its denominator is zero) using a fixed
       ETA tolerance constant (±3 minutes, same fixed-constant precedent
       as the OTP report's on-time window).
   - `render_html(data: DashboardData) -> str`: builds the full HTML
     document as an f-string — inline `<style>` (light/dark via
     `prefers-color-scheme`, palette per the dataviz skill's reference
     palette: chart surface `#fcfcfb`/`#1a1a19`, series-1 blue
     `#2a78d6`/`#3987e5`, text/gridline tokens from the same reference),
     two hand-rolled inline-SVG area+line charts (2px line, ~10%-opacity
     area fill, per-point `<title>` for a zero-JS tooltip fallback), a
     KPI stat-tile row, and a `<details>`-collapsed data table under each
     chart so every charted value is also plainly readable/copyable — no
     value is reachable only by hovering. A small inline `<script>` adds
     a mouse-following crosshair + tooltip on each chart; the page is
     fully readable with JavaScript disabled.
   - `write_html(html: str, output_dir, agency, feed_start, feed_end) -> Path`
     writes to
     `<output_dir>/reports/<agency>/dashboard-<feed_start>-<feed_end>.html`.
4. `cli.py`:
   - `report html` subcommand: same "fetch-gtfs first" precondition as
     `report schedule-stats`; if the agency has `tides:`+`date_range:`
     configured, also requires the TIDES raw dir to exist (same
     precondition `report otp` enforces) — hard error naming the missing
     step if not, per `specs/behaviors/config-validation.md`. Builds +
     writes the dashboard.
   - `run`: after the schedule-stats step (and, when it ran, the otp
     step), always builds + writes the dashboard too, passing
     `tides_files`/`date_range` only when the otp step actually ran.
5. Tests:
   - `tests/test_dashboard.py` (new): `build_dashboard_data` against
     `tests/fixtures/mini_gtfs.zip` (GTFS-only call, asserting
     `peak_vehicles`, `vehicles_time_series` length/shape, and
     `trips_by_date` coverage) and against a small hand-built TIDES CSV
     fixture covering: both benchmark columns present and computed
     correctly; both columns absent (both benchmarks `null`, no crash);
     zero performed trips in range (`trips_performed == 0`, benchmarks
     `null`, no divide-by-zero).
   - `render_html` smoke test: output contains expected KPI values and
     is parseable as HTML (well-formed enough that `xml.etree` or a
     simple substring/tag-balance check passes) with no unescaped
     agency-name injection (basic HTML-escaping check).
   - `tests/test_cli.py` additions: `report html` and `run` produce a
     `dashboard-*.html` file for a GTFS-only agency (TIDES section
     absent, page says why) and for a full agency (TIDES section
     present); `report html` on a `tides:`-configured-but-not-fetched
     agency fails with a clear command-level error.

## Validation

- [x] `diy-transit-analysis report html --config ... --agency <gtfs-only agency>` (after `fetch-gtfs`) writes a `dashboard-<start>-<end>.html` file containing the feed overview, the vehicles-in-service chart, and the trips-per-service-day chart, with the TIDES section replaced by a "not configured" note.
- [x] The same command against a `tides:`+`date_range:`-configured, already-fetched agency additionally shows `trips_performed`, `realtime_completeness_percent`, and `eta_accuracy_percent`.
- [x] `report html` against a `tides:`-configured-but-not-yet-fetched agency fails with a clear message to run `fetch-tides` first, not a silent omission.
- [x] `run` produces the dashboard HTML alongside `schedule-stats` (and `otp`, when applicable) in one invocation, for both a GTFS-only and a fully-configured agency.
- [x] Unit test: a TIDES CSV missing both benchmark columns still produces a dashboard with `trips_performed` populated and both benchmark percentages `null` — no crash.
- [x] Unit test: `peak_vehicles`/`peak_time` come from `compute_network_stats`'s exact calculation, not derived by taking the max of the (binned) time-series data — verified with a constructed fixture (two non-overlapping trips that both fall inside one 15-minute bin) where the binned max (2) and the true peak (1) actually disagree; taking the binned max would have reported the wrong number.
- [x] Full existing test suite (`pytest`) still passes.
- [x] The rendered HTML has no unescaped-agency-name injection risk (agency names are HTML-escaped before interpolation).

## Risks / unknowns

- **The two new TIDES benchmark columns are pure guesses** — `tides-transit.org`'s published spec suite reportedly defines something like "realtime completeness" and "prediction/ETA accuracy" benchmarks, but this plan does not have access to that spec's exact field names or formulas, and implements a best-effort, clearly-documented assumption instead (same posture as every other unverified TIDES assumption already in this project). If/when the real TIDES bucket and its schema are verified, this is one of the first things to re-check.
- **`compute_network_stats` over the whole feed's date range** could be slow for a feed with a very long calendar validity (e.g. multi-year). Mitigated by passing a precomputed `trip_stats` table (per gtfs-kit's own performance guidance) and accepted as an MVP risk otherwise — not verified against a real large multi-year feed in this plan (this sandboxed environment's outbound network access to a real feed URL currently returns `403`, same limitation noted in `plans/run-and-schedule-stats.md`'s Notes).

## Notes

- gtfs-kit's `compute_network_time_series`/`compute_network_stats` (both
  built-ins) turned out to cover the vehicles-in-service curve, the exact
  peak, and the per-service-day trip counts directly — no hand-rolled
  calendar-expansion or sweep-line concurrency code needed, consistent
  with this project's stated rationale for choosing gtfs-kit.
- Found and fixed a real bug while writing the peak-vehicles test: a
  15-minute time-series bin counts a trip as "in service" if it merely
  *overlaps* the bin, which can **overestimate** true instantaneous
  concurrency (two trips that never run at the same moment can still both
  land inside one bin) — the opposite direction from what the plan's
  Approach initially assumed ("avoid binning-induced *undercount*"). Both
  the code (already used `compute_network_stats`'s exact calculation, not
  the binned max) and the test (now uses a constructed fixture that
  actually demonstrates the disagreement) reflect the corrected
  understanding; the risk write-up above still describes the mitigation
  correctly, just not the direction of the original error.
- Also caught and fixed a related null-handling bug before it shipped:
  `pandas.Series.astype(bool)` on a column containing `NaN` (e.g. from
  `pd.concat`-ing a TIDES file that lacks the optional
  `realtime_data_available` column with one that has it) silently reads
  `NaN` as `True`. `realtime_completeness_percent` now excludes rows
  where the column is unset from both the numerator and denominator
  instead of miscounting them as "available" — covered by
  `test_tides_benchmarks_excludes_rows_with_unknown_realtime_status`.
- Visually verified the rendered HTML (light + dark, GTFS-only + full
  agency, and the hover/crosshair tooltip) with a real headless-Chromium
  screenshot in this sandbox rather than only trusting the generated
  markup — caught and fixed two real issues this way before they shipped:
  duplicate y-axis tick labels on small-integer charts (fixed with a
  proper `_nice_ticks` round-number algorithm) and a tooltip that
  positioned itself relative to the whole chart instead of the hovered
  point.
- Reused `report/on_time_performance.py`'s TIDES CSV reader and
  `report/schedule_stats.py`'s feed-date-range/representative-week
  helpers by making them public (dropping their leading underscore) —
  no behavior change, per the Approach.
- Pushed directly to this task's working branch with no PR opened, since
  none was requested — same no-PR-gate precedent as
  `plans/package-scaffold.md` and `plans/run-and-schedule-stats.md`.

## Follow-ups

- Tracked as: verify the two new TIDES benchmark columns
  (`realtime_data_available`, `predicted_departure`) — and their
  formulas — against a real fetched TIDES sample once the underlying
  bucket-access blocker in `plans/data-fetch.md` is resolved. Same
  unresolved dependency, not a new one.
- Tracked as: live-verify `report html`/`run`'s dashboard generation
  against a real, large public GTFS feed (this sandboxed environment's
  outbound network access to the SacRT feed URL used elsewhere in this
  project currently returns `403`, so this was validated against the
  local fixture plus a hand-built disagreement-case fixture instead) —
  same tracked gap as `plans/run-and-schedule-stats.md`'s Follow-ups.
