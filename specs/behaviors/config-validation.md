# Behavior: Config Validation

## Rule

Before any fetch or report command runs, the config file is fully
validated against the schema in
[../data-model.md#config-file](../data-model.md#config-file). Validation
failures abort the run with a message naming the offending field and
agency — the program never proceeds with a partially-valid config or
silently skips an invalid agency entry.

## Applies To

All CLI subcommands (`fetch-gtfs`, `fetch-tides`, `fetch-ntd`, `report
otp`, `report schedule-stats`, `report html`, `report ntd`, `run`) and the
`diy_transit_analysis.config.load_config()` function they share.

## Details

- Missing required fields (see the "Required" column in
  `data-model.md#config-file`) fail validation, listing every missing
  field found (not just the first) so a user can fix them all in one
  pass.
- `tides:` and `date_range:` are each **whole-block optional**, per
  agency, independently of each other — an agency may configure neither,
  either, or both. This is what makes a GTFS-only agency (just
  `gtfs_schedule_url:`) a valid config, per
  [../principles.md#config-driven-agency-onboarding](../principles.md#config-driven-agency-onboarding):
  no code change, and no unrelated config (a GCP project, a reporting
  window) is required just to fetch and describe a schedule. When a block
  *is* present, every field normally required within it is still required
  — e.g. a `tides:` block with `gcs_bucket` but no `gcp_billing_project`
  still fails validation.
- `date_range.start` must be `<= date_range.end` (when `date_range:` is
  present).
- `agencies.<name>.ntd_id` is optional and independent of every other
  per-agency block — a non-empty string if present, no format beyond that
  is enforced (NTD IDs are conventionally 5-digit numeric codes, but that
  convention isn't validated here — see
  [../architecture.md#ntd-time-series-data-access](../architecture.md#ntd-time-series-data-access)
  for why this project doesn't hard-code assumptions about NTD's exact
  formats beyond what's needed to use them).
- The top-level `ntd:` block is **whole-block optional**, same pattern as
  `tides:`/`date_range:` but at the document root rather than per-agency
  (it configures agency-independent shared source files, not one agency's
  own data — see
  [../architecture.md#ntd-time-series-data-access](../architecture.md#ntd-time-series-data-access)).
  When present, `ntd.time_series` must be a non-empty list, and every
  entry must have all three of `name` (non-empty string), `category` (one
  of `service`, `funding`, `expenditure`, `asset` — any other value fails
  validation, naming the allowed set), and `url` (`http://`/`https://`
  only, same rule as `gtfs_schedule_url`).
- `gtfs_schedule_url` and any URL field must be `http://` or `https://` —
  no local file paths, no other schemes (keeps the "public data only"
  principle mechanically enforced rather than just documented; see
  [../principles.md#public-data-only](../principles.md#public-data-only)).
- `--agency` selectors passed on the CLI must match a key under
  `agencies:` in the loaded config; an unknown agency name is a
  validation failure, not a silent no-op.
- Validation does not attempt to reach any network endpoint (no "does
  this URL 200" check) — that's the fetch step's job, not config
  validation's. Config validation is purely structural/local.
- A subcommand that needs a block the selected agency didn't configure
  (`fetch-tides` or `report otp` without `tides:`; `report otp` without
  `date_range:`; `report ntd` without the top-level `ntd:` block and/or
  the agency's `ntd_id`) is **not** a config-validation failure — the
  config itself is valid. It's a command-level error, raised when that
  subcommand runs, naming exactly which block is missing and for which
  agency. `run` and `report html`/`report ntd` treat the same situation
  as a section/report to skip (with an explanation printed/shown), not an
  error — see
  [../architecture.md#the-run-subcommand](../architecture.md#the-run-subcommand),
  [../data-model.md#static-html-dashboard-report-output](../data-model.md#static-html-dashboard-report-output),
  and
  [../data-model.md#ntd-time-series-report-output](../data-model.md#ntd-time-series-report-output).
  `report html` still hard-fails, the same way `report otp` does, when
  `tides:`/`date_range:` *are* configured but TIDES hasn't been fetched
  yet — that's a setup step the user still needs to run, not a case to
  silently skip. `report ntd` is the same: configured (`ntd:` +
  `ntd_id:`) but not yet fetched (`fetch-ntd`) is a hard failure telling
  the user to run `fetch-ntd` first, not a silent skip. `fetch-ntd`
  itself only needs the top-level `ntd:` block (its fetch is
  agency-independent — see
  [../architecture.md#ntd-time-series-data-access](../architecture.md#ntd-time-series-data-access));
  a selected agency missing `ntd_id:` doesn't block `fetch-ntd`, only
  `report ntd` and the NTD portion of `run`.

## Principles

**Inherited** — project principles from `principles.md` that especially
bite here:
- [Config-driven agency onboarding](../principles.md#config-driven-agency-onboarding)
  — validation is what keeps a bad config from silently producing a
  bad-but-plausible report; it's the enforcement mechanism behind "adding
  an agency is a config change."
