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
- There is deliberately **no** config surface for which NTD metrics get
  fetched/charted — that's a fixed, built-in catalog (see
  [../architecture.md#ntd-time-series-data-access](../architecture.md#ntd-time-series-data-access)),
  not something `load_config()` parses or validates. `ntd_id` above is
  the only NTD-related field this validator knows about.
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
  `date_range:`; `report ntd` without the agency's `ntd_id`) is **not** a
  config-validation failure — the config itself is valid. It's a
  command-level error, raised when that subcommand runs, naming exactly
  which field is missing and for which agency. `run` and `report
  html`/`report ntd` treat the same situation as a section/report to skip
  (with an explanation printed/shown), not an error — see
  [../architecture.md#the-run-subcommand](../architecture.md#the-run-subcommand),
  [../data-model.md#static-html-dashboard-report-output](../data-model.md#static-html-dashboard-report-output),
  and
  [../data-model.md#ntd-time-series-report-output](../data-model.md#ntd-time-series-report-output).
  `report html` still hard-fails, the same way `report otp` does, when
  `tides:`/`date_range:` *are* configured but TIDES hasn't been fetched
  yet — that's a setup step the user still needs to run, not a case to
  silently skip. `report ntd` is the same: `ntd_id:` configured but not
  yet fetched (`fetch-ntd`) is a hard failure telling the user to run
  `fetch-ntd` first, not a silent skip. `fetch-ntd` itself needs no
  agency-level config at all — it always fetches the built-in catalog,
  regardless of whether the selected agency has `ntd_id:` set (its fetch
  is agency-independent — see
  [../architecture.md#ntd-time-series-data-access](../architecture.md#ntd-time-series-data-access));
  a selected agency missing `ntd_id:` only blocks `report ntd` and the
  NTD portion of `run`.

## Principles

**Inherited** — project principles from `principles.md` that especially
bite here:
- [Config-driven agency onboarding](../principles.md#config-driven-agency-onboarding)
  — validation is what keeps a bad config from silently producing a
  bad-but-plausible report; it's the enforcement mechanism behind "adding
  an agency is a config change."
