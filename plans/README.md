# Plans

`plans/` is the work-in-flight micro-DAG that bridges `specs/` (timeless:
what should be true) to running code (motion: how we're getting there
next). Each file is one scope-bounded chunk of work: frontmatter declares
status, dependencies, and which specs it implements; the body has Scope,
Implements, Approach, Validation, Risks/unknowns, Notes, and Follow-ups.

Full protocol — frontmatter schema, body template, status lifecycle, the
closeout-commit ritual, and the Follow-ups taxonomy — lives in the specops
skill's [references/plans-protocol.md](../.agents/skills/specops/references/plans-protocol.md).
Read it before authoring or closing out a plan. This file intentionally
does not maintain a hand-drawn DAG or status table — both rot the moment
someone forgets to update them.

Query the live DAG instead:

```sh
.agents/skills/specops/scripts/specops next   # what's ready to work on
.agents/skills/specops/scripts/specops dag    # Mermaid graph
```
