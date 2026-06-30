---
name: project_example
description: The widget rewrite — goals, constraints, and current phase.
type: project
scope: example-project
---

Rewriting the legacy widget service into a smaller, testable module.

**Why:** the old one has no tests and a tangled config path that causes prod
surprises.

**How to apply / state:** auth and the data layer are done; the current phase is
pagination + the public API. Constraint: must stay backward-compatible with the v1
response shape until clients migrate. Decisions + reasoning live in the vault's
handoffs; this note is the durable "what & why." See [[reference_example]].
