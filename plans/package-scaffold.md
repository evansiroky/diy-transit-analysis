---
status: done
depends: []
specs:
  - specs/architecture.md
  - specs/data-model.md
  - specs/behaviors/config-validation.md
issues: []
pr: initial-scaffold-direct-to-main
---

# Plan: Python package scaffold, config loading, and CLI skeleton

## Scope

In scope: the installable Python package layout (`pyproject.toml`,
`src/diy_transit_analysis/`), the config loader + validator
(`config.py`), the `diy-transit-analysis` console-script entrypoint with
its three subcommands wired up as argparse stubs, `config/example.yaml`,
`requirements.txt`, `.gitignore`, and the repo-root `README.md`.

Out of scope (land in later plans): the actual GTFS fetch/parse logic
(`plans/data-fetch.md`), the actual TIDES fetch logic
(`plans/data-fetch.md`), and the on-time-performance report generation
(`plans/otp-report.md`). The `fetch-gtfs`, `fetch-tides`, and `report otp`
subcommands exist in this plan only as argparse-wired stubs that parse
their arguments and validate config, then raise `NotImplementedError` —
so subsequent plans only have to fill in a function body, not build CLI
plumbing.

## Implements

- `specs/architecture.md` — "Language & packaging", "Config file format",
  and "CLI entrypoint shape" sections.
- `specs/data-model.md#config-file` — the config schema.
- `specs/behaviors/config-validation.md` — validation rules, enforced by
  `config.load_config()`.

## Approach

1. `pyproject.toml`: PEP 621 metadata, `[project.scripts]` entry
   `diy-transit-analysis = "diy_transit_analysis.cli:main"`, dependencies
   (`gtfs-kit`, `google-cloud-storage`, `pandas`, `pyyaml`, `requests`),
   `[project.optional-dependencies].dev` with `pytest`.
2. `src/diy_transit_analysis/__init__.py`, `config.py` (dataclasses or
   plain dicts + a `load_config(path) -> Config` function implementing
   every rule in `specs/behaviors/config-validation.md`, raising a single
   `ConfigError` listing every problem found), `cli.py` (argparse
   subcommands `fetch-gtfs`, `fetch-tides`, `report otp`, each taking
   `--config` and `--agency`).
3. Stub out `gtfs/`, `tides/`, `report/` subpackages with `__init__.py`
   and empty-but-importable modules so later plans add functions, not
   new files/directories.
4. `config/example.yaml` per `specs/data-model.md#config-file`, using a
   real public California agency GTFS feed URL for realism (SacRT).
5. `requirements.txt` mirroring `pyproject.toml` deps (per
   `specs/architecture.md`).
6. `.gitignore` for Python (`__pycache__/`, `*.pyc`, `.venv/`, `build/`,
   `dist/`, `*.egg-info/`) plus this project's own `output/` (generated
   data/reports, per
   `specs/principles.md#local-files-as-the-unit-of-state`).
7. Repo-root `README.md`: what the project is, install instructions,
   the three-subcommand usage example (mirrors CLAUDE.md's "Running it"
   section, written for a human/GitHub reader rather than an agent).

## Validation

- [x] `pip install -e .` succeeds in a clean virtualenv (verified with a Python 3.11 venv).
- [x] `diy-transit-analysis --help` lists all three subcommands.
- [x] `diy-transit-analysis fetch-gtfs --config config/example.yaml --agency SacRT` loads and validates the example config without error. (Superseded in a good way — see Notes: this repo's initial scaffold implemented `gtfs/schedule.py` and `tides/historic.py` in the same working session as `plans/data-fetch.md`, so this command now fetches and parses the real SacRT feed end-to-end instead of stopping at a `NotImplementedError` stub.)
- [x] `diy-transit-analysis fetch-gtfs --config config/example.yaml --agency NotARealAgency` fails config validation with a message naming the unknown agency (per `specs/behaviors/config-validation.md`).
- [x] A config missing a required field fails with a message listing every missing field, not just the first.

## Risks / unknowns

- **Dependency pin drift**: `gtfs-kit` and `google-cloud-storage` are
  pulled at whatever their latest version is at scaffold time; no
  compatibility testing against a range of versions yet. Acceptable for
  an MVP scaffold; revisit if a later plan hits a breaking upstream
  change.

## Notes

- Sequencing deviation from the Approach: because this whole DAG was built
  as one solo initial-scaffold pass rather than across separate reviewed
  PRs, `gtfs/schedule.py` (from `plans/data-fetch.md`) and
  `report/on_time_performance.py` (from `plans/otp-report.md`) were
  implemented in the same working session as this plan's stub-only scope,
  rather than landing as later, separate stub-fill-in commits. The three
  plans still exist as separate scope/validation records — this note just
  explains why this plan's own validation runs against the finished
  binary rather than a stub.
- `config.load_config()` raises a single `ConfigError` aggregating every
  validation problem, verified against a config missing four required
  fields at once (all four appear in one error message).
- No PR/review gate for this initial scaffold, per the user's explicit
  instruction for this one-time solo bootstrap — `pr:` above records that
  rather than a real merged-PR number.

## Follow-ups

None beyond what's already tracked in `plans/data-fetch.md` and
`plans/otp-report.md`.
