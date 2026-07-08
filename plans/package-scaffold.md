---
status: planned
depends: []
specs:
  - specs/architecture.md
  - specs/data-model.md
  - specs/behaviors/config-validation.md
issues: []
pr:
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

- [ ] `pip install -e .` succeeds in a clean virtualenv.
- [ ] `diy-transit-analysis --help` lists all three subcommands.
- [ ] `diy-transit-analysis fetch-gtfs --config config/example.yaml --agency SacRT` loads and validates the example config without error, then raises `NotImplementedError` at the point where fetch logic will land.
- [ ] `diy-transit-analysis fetch-gtfs --config config/example.yaml --agency NotARealAgency` fails config validation with a message naming the unknown agency (per `specs/behaviors/config-validation.md`).
- [ ] A config missing a required field fails with a message listing every missing field, not just the first.

## Risks / unknowns

- **Dependency pin drift**: `gtfs-kit` and `google-cloud-storage` are
  pulled at whatever their latest version is at scaffold time; no
  compatibility testing against a range of versions yet. Acceptable for
  an MVP scaffold; revisit if a later plan hits a breaking upstream
  change.

## Notes

(Populated at closeout.)

## Follow-ups

(Populated at closeout.)
