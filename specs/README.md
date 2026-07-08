# Specs

This directory is the source of truth for **what should be true** about
`diy-transit-analysis`. Implementation follows spec, not the other way
around. See the [specops skill](../.agents/skills/specops/SKILL.md) for the
full methodology; this file is just the local index and conventions.

## Directory layout

```
specs/
├── README.md              # this file
├── principles.md          # project-wide philosophy, written as decisive rules
├── architecture.md        # tech stack, project structure, foundational decisions
├── data-model.md          # config schema, GTFS/TIDES data shapes, report output shape
└── behaviors/             # cross-cutting rules that span multiple modules
    └── config-validation.md
```

This project is a CLI/library tool, not a web app, so there is no
`screens/` or `api/` directory — those directories are only added if a web
UI or HTTP API is ever built on top of this toolkit.

## Format conventions

- Specs are declarative: they say what must be true, not how to write the
  code. See the skill's "How to write specs" section for the detailed
  rubric and the too-vague / too-detailed examples.
- Every spec file is proofed by the [spec-drift auditor](../.claude/agents/spec-drift-auditor.md)
  (`/audit-spec-drift`) against the actual implementation and against
  `plans/*.md` `specs:` references.
- Principles that are local to one spec live in that spec's own
  `## Principles` section. Principles that are genuinely project-wide live
  in `principles.md`. Promote on duplication, not preemptively.
- When a data source's real-world shape can't be fully verified right now
  (this applies especially to the TIDES portal — see `architecture.md`),
  the spec says so explicitly rather than presenting a guess as settled
  fact. Look for "based on published TIDES documentation, verify against
  live endpoint before relying on it" markers.

## Workflow

1. Change the spec first, get it reviewed/accepted.
2. Author or update a plan in `plans/` that brings code into conformance.
3. Implement.
4. Verify the running code against the spec; close the plan out.

See `plans/README.md` for the plan protocol, and the specops CLAUDE.md hook
in this repo's root `CLAUDE.md` for the always-loaded reminder.
