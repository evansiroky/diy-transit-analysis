---
status: done
depends: [html-dashboard-report]
specs:
  - specs/data-model.md
issues: []
pr: 2
---

# Plan: Conform dashboard ETA benchmarks to the published methodologies

## Scope

In scope: replacing `report html`'s two ad-hoc TIDES benchmarks
(`realtime_completeness_percent`, `eta_accuracy_percent`) — invented for
`plans/html-dashboard-report.md` without a named source — with exact
implementations of two published, industry benchmarks:

- [SwiftlyInc/ETA-Completeness-Benchmark](https://github.com/SwiftlyInc/ETA-Completeness-Benchmark)
- [TransitApp/ETA-Accuracy-Benchmark](https://github.com/TransitApp/ETA-Accuracy-Benchmark)

Both operate at trip-*stop* grain with multiple timestamped prediction
samples per trip-stop — a shape the old single-row-per-trip TIDES
assumption (`realtime_data_available`, `predicted_departure`) could not
represent at all. This plan introduces two new assumed TIDES input
shapes (`trip_stop_outcomes`, `predictions`) to replace those two
columns; see `specs/data-model.md#tides-data-for-the-eta-benchmarks-assumed-separate-files`.

Out of scope: the `trips_performed` stat (unrelated data source, kept
as-is) and the on-time-performance report (`report otp`, unrelated —
different report, different grain, not a "benchmark" in the sense this
plan is conforming to an external spec). Also out of scope: verifying
either new assumed TIDES shape against a real fetched sample — same
unresolved bucket-access blocker as every other TIDES assumption in this
project.

## Implements

- `specs/data-model.md#tides-data-for-the-eta-benchmarks-assumed-separate-files`
  — the two new assumed TIDES CSV shapes.
- `specs/data-model.md#eta-completeness` and
  `specs/data-model.md#eta-accuracy` — the exact formulas, quoted from
  the two source specs, plus how they're applied to this project's data
  (calendar-derived denominator, bucket/threshold tables, the
  zero-sample-bucket edge case the source specs don't address).

## Approach

1. `report/dashboard.py`:
   - Remove the old `_build_tides_benchmarks` realtime/eta logic and the
     `ETA_ACCURACY_TOLERANCE` constant; keep `trips_performed`'s
     computation (still reads the existing "trips performed" CSV via
     `otp.read_tides_performed`).
   - New reader functions, duck-typed by column presence like every
     other TIDES read in this project: `_read_trip_stop_outcomes(files)`
     and `_read_predictions(files)`, each scanning all fetched `*.csv`
     files and concatenating the ones with the matching required
     columns.
   - `_scheduled_trip_stops(feed, start, end) -> pd.DataFrame`: for each
     date in `[start, end]`, `feed.get_trips(date=d)` joined to
     `stop_times` for that date's active trips, columns `(date, trip_id,
     stop_id)`. Reuses the same per-day calendar-expansion pattern
     `report/on_time_performance.py`'s `_scheduled_trip_counts` already
     uses.
   - `_eta_completeness_percent(scheduled, outcomes, predictions) ->
     tuple[float | None, str | None]`: implements the exact formula in
     the spec (denominator = len(scheduled); numerator = outcomes rows
     matched to scheduled where `trip_cancelled or stop_skipped or
     (vehicle_assigned and has a qualifying 0–15-min-out prediction)`).
   - `_eta_accuracy_percent(outcomes, predictions) -> tuple[float | None,
     str | None]`: implements the four time buckets and asymmetric
     thresholds as constant tables, buckets each prediction by
     `time_to_actual`, checks `variance` against the bucket's threshold,
     averages non-empty bucket accuracies.
   - `TidesBenchmarks` dataclass gains per-bucket breakdown fields (bucket
     label, prediction count, accuracy) for the accuracy benchmark, shown
     in a `<details>` table on the dashboard — same "don't gate a value
     behind hover-only" pattern the two charts already use.
2. `cli.py`: `report html` / `run` pass the same `tides_files`/`date_range`
   through unchanged — `build_dashboard_data`'s signature doesn't change,
   only what it does internally with the fetched TIDES files.
3. Tests: replace `tests/test_dashboard.py`'s old
   `test_tides_benchmarks_*` tests (built around the removed
   `realtime_data_available`/`predicted_departure` columns) with new
   tests against hand-built `trip_stop_outcomes`/`predictions` fixtures,
   covering: a straightforward complete/accurate case matching both
   source specs' worked examples; a trip-stop with no outcome row at all
   (counted incomplete, not skipped); a `CANCELED`/`SKIPPED` trip-stop
   (complete via condition 2 despite no prediction); a prediction outside
   all four accuracy buckets (excluded, not miscounted); a boundary case
   at each accuracy threshold's inclusive edge (30s early / 90s late on
   the 0–3 min bucket, per the source spec's own example); a bucket with
   zero predictions (excluded from the average, not counted as 0%).

## Validation

- [x] `realtime_completeness_percent` matches a hand-computed expected
      value against a small constructed fixture covering all four
      quadrants of the source spec's 2×2 table (delivered+communicated,
      undelivered+communicated via CANCELED, undelivered+communicated via
      SKIPPED, and both "uncommunicated" cases via a missing outcome row).
- [x] `eta_accuracy_percent` matches a hand-computed expected value
      against a fixture with predictions in multiple buckets, including
      one prediction exactly on each bucket's inclusive threshold
      boundary (accurate) and one just past it (inaccurate).
- [x] A prediction whose `time_to_actual` falls outside all four buckets
      (e.g. sampled >15 minutes before actual arrival) does not affect
      either benchmark.
- [x] A bucket with zero predictions is excluded from the accuracy
      average, not treated as a 0% bucket — verified with a fixture where
      including it as 0% would change the result.
- [x] `trips_performed` is unaffected by this plan — still computed from
      the existing "trips performed" CSV, unit test unchanged in intent.
- [x] Full existing test suite (`pytest`) passes.
- [x] Rendered HTML dashboard visually re-verified (screenshot) with the
      new benchmark values and bucket-breakdown detail table.

## Risks / unknowns

- **Both new TIDES shapes remain entirely unverified** — more so than
  before, since they're now more specific (trip-stop grain, multiple
  timestamped samples) about exactly what TIDES would need to expose.
  This is the most speculative part of this project's TIDES integration
  to date; flagged prominently in the spec and will need the first real
  correction once live TIDES access exists.
- **The source specs are silent on a few edge cases** this
  implementation has to resolve anyway (a bucket with zero predictions;
  a trip-stop present in `predictions` but entirely absent from
  `trip_stop_outcomes`). Each resolution is written down explicitly in
  the spec rather than left as an implicit code choice, per
  `specs/principles.md#reproducibility-over-cleverness`.

## Notes

- Fetched both source specs' READMEs verbatim (not just a paraphrase)
  before implementing, specifically to get exact field semantics right:
  the accuracy benchmark's bucket boundaries are half-open
  (`>= start < end`) while its accuracy thresholds are closed
  (inclusive on both ends) — an easy detail to get backwards, and one
  the boundary-inclusive test (`test_eta_accuracy_boundary_thresholds_are_inclusive`)
  locks in.
- Discovered and fixed a real blocking bug while implementing: `report
  otp`'s `on_time_performance.read_tides_performed` previously *raised*
  on any fetched `.csv` file that didn't have the "trips performed"
  shape. Once a TIDES fetch directory legitimately holds three distinct
  CSV shapes side by side (trips performed, trip_stop_outcomes,
  predictions), that would have broken `report otp` itself the moment
  an agency's TIDES bucket also published either of the two new shapes.
  Changed it to skip non-matching files instead — covered by
  `test_read_tides_performed_skips_files_of_a_different_shape` — and
  applied the same duck-typing convention to the two new readers.
  This is a real, non-cosmetic behavior change beyond this plan's
  original Scope, made because the original (raising) behavior would
  otherwise silently regress `report otp` for any agency adopting the
  new shapes.
- The source specs don't say what to do when an accuracy bucket has zero
  predictions, or when a trip-stop is missing from `trip_stop_outcomes`
  entirely — both resolved explicitly in the spec (exclude the bucket
  from the average; count as incomplete), each locked in by a dedicated
  test that would fail under the other plausible interpretation.
- Visually re-verified the rendered dashboard (screenshot) with real
  completeness/accuracy numbers and the new bucket-breakdown table —
  renders correctly, no layout issues from the added `<h3>` subsection.
- This work landed as additional commits on the same branch/PR (#2) as
  `plans/html-dashboard-report.md`, since that PR was still open when
  this plan started — not a new PR. Corrected that earlier plan's (and
  `plans/run-and-schedule-stats.md`'s) `pr:` placeholder to the real PR
  number now that both are known, since the placeholder text
  ("direct-to-branch-no-pr-requested") turned out to be factually wrong
  once PRs were opened after those plans closed.

## Follow-ups

- Tracked as: verify the two new TIDES shapes (`trip_stop_outcomes`,
  `predictions`) — and by extension both benchmark formulas — against a
  real fetched TIDES sample once the underlying bucket-access blocker in
  `plans/data-fetch.md` is resolved. Same unresolved dependency as
  `plans/html-dashboard-report.md`'s equivalent Follow-up, now sharpened
  to the new, more specific shapes.
- Tracked as: if a real TIDES sample turns out to report `actual_arrival`
  as a *departure* time instead (the source specs say "arrival (or
  departure)" without picking one), revisit which one this project
  standardizes on — currently arrival throughout, chosen for consistency
  with the source specs' own primary wording, not verified against real
  data.
