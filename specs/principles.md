# Principles

The project's philosophy, written down as principles. Each is decisive: it
picks a side of a real trade-off so an implementer can resolve an
unspecified case the way the author would.

## Public data only

This toolkit only ever fetches data a transit agency or Caltrans has
already published for public consumption (GTFS Schedule feeds, the TIDES
portal, other open transit data portals). It never scrapes pages that
require login, never stores agency credentials, and never asks an agency
for anything beyond what they already publish. When a data source requires
auth beyond a public API key or a requester-pays cloud bucket a user
provisions themselves, that source is out of scope until the agency
publishes it more openly.

> Why: the goal is public accountability reporting usable by journalists
> and advocates with no special relationship to the agency. Anything that
> needs privileged access defeats that purpose and creates legal/ethical
> risk this project isn't set up to carry.

## Config-driven agency onboarding

Adding a new agency (or a new GTFS feed, or a new TIDES submission window)
is a config-file change, never a code change. If supporting an agency
requires new Python, that's a sign the config schema is missing a knob —
fix the schema, not just the one agency.

> Why: this reuses the pattern from the sibling `gtfs-rt-to-tides` project
> (`config/example_download_config.json`, keyed by agency/feed name) for
> consistency across this user's transit tooling, and because the whole
> point of the project is to scale past a single hand-tuned agency.

## Reproducibility over cleverness

Given the same config and the same date range, a report run twice produces
byte-for-byte (or at minimum, value-for-value) identical output. Prefer
deterministic, auditable calculations — plain aggregation, documented
formulas — over statistical smoothing, imputation, or "smart" heuristics
that a reader can't reproduce by hand from the same inputs.

> Why: the audience is journalists and advocates who need to defend a
> number publicly. A number nobody can reproduce is a number nobody can
> trust or cite.

## Fail loud on unverified assumptions

Where this project's understanding of an external data source (especially
the TIDES portal's real download/API shape) is based on documentation
review rather than a working integration test, the code says so at the
point of use — an explicit comment, a clearly named "assumed" config
field, or a startup warning — rather than silently guessing and returning
data that looks legitimate.

> Why: a wrong on-time-performance number that looks confident is worse
> than a loud failure. This project's core deliverable is public trust in
> a number; false confidence is the single fastest way to lose it.

## Local files as the unit of state

All fetched data and generated reports land as files on disk (CSV/Parquet
inputs and outputs, no database). No implicit background service, no
long-running daemon, no hidden mutable state beyond what's on disk in the
configured output directory.

> Why: this is a toolkit run ad hoc by one person on a laptop or in a CI
> job, not a hosted service. Files are inspectable, diffable, and
> git-friendly for reproducibility, and they impose zero infra burden on
> an open-source, unmonetized project.
