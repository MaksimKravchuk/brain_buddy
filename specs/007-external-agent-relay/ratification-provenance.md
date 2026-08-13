# External-agent relay ratification provenance

This record distinguishes immutable evidence, semantic approval, procedural deviation,
and release authority. It does not ratify itself or claim approval of its own bytes.

## 2026-08-09 baseline

- Source reconstruction: `92ff295:specs/006-external-agent-relay/spec.md`, with only
  ratification metadata reversed: status restored to `Draft`, and the later
  `Ratification receipt` paragraph plus its separating blank line removed.
- Durable artifact: `ratified-baseline-2026-08-09.md`.
- Exact SHA-256: `f3cf461ffa0340738b8d599d2c643a3979b7bea30fc08fabf90fa4c01299e384`.
- Approval scope: Max ratified those exact baseline bytes on 2026-08-09, including the
  Design Acceptance Gate then present.

## Later amendments and 2026-08-11 decision

Review-driven amendments after the immutable baseline remain visible in canonical
`spec.md`. The baseline required design approval before planning and implementation;
that sequence was not met and cannot be made true retroactively. No design-preview
approval is claimed.

On 2026-08-11 Max explicitly accepted this procedural deviation and semantically
approved the narrowly described amended specification. This is semantic approval of
that amendment scope, not approval of the exact bytes of this provenance record or the
post-edit canonical files.

This decision does not authorize merge, deploy, rollout, ruleset changes, workflow
changes, or release-floor changes. Landing still requires final independent dual review
of the actual web and iOS implementation on the exact candidate SHA, required CI on that
same SHA, and separate ASK merge authority. Deployment and rollout remain separately
governed after any authorized landing.
