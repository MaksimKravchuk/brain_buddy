---
name: speckit-pipeline
description: The end-to-end BrainBuddy Spec Kit delivery chain — which stage runs when, which stages need a human, and how the assess front door gates an abstract ask. Use when planning or navigating a feature from idea through spec, design, plan, review, tasks, implementation and acceptance.
---

# The BrainBuddy delivery pipeline

Use GitHub Spec Kit v0.15.0 for every new or materially changed feature spec.
Install or refresh the CLI with isolated uv tooling, not inside application
backend/frontend environments:

```bash
uv tool install specify-cli --force --from git+https://github.com/github/spec-kit.git@v0.15.0
specify --version          # expect: specify 0.15.0
specify check              # verifies Claude Code and other agent prerequisites
specify integration list   # confirms claude is available/installed
```

## The chain

`.specify/extensions.yml` chains five BrainBuddy stages onto the Spec Kit core,
using the `hooks.before_*` / `hooks.after_*` keys the upstream skills already
read — no upstream skill is forked. Front door for an abstract ask:

```text
/speckit-assess-*    should this be built at all? -> decision.md         [human, optional]
/speckit-interview   business requirements from the human -> intake.md   [human]
/speckit-specify     what and why -> spec.md
/speckit-clarify     disambiguate                                        [human]
/speckit-design      screens + numbered state inventory -> design.md     [human sign-off]
/speckit-plan        how and architecture -> plan.md  (MUST cite design.md)
/speckit-review      five-lens review gate (ADR-0011) -> verdict         [human on product decisions]
/speckit-checklist   requirements quality
/speckit-tasks       -> tasks.md
/speckit-analyze     cross-artifact consistency
/speckit-implement   direct implementation in an isolated worktree
/speckit-accept      criterion -> test traceability -> accept | reject
/speckit-report      the end-to-end report for the human                 [human]
```

## Stage 0 — assess

Stage 0 is the `assess` Spec Kit extension (`spec-kit-core`, installed):
`/speckit-assess-intake` → `research` → `define` → `shape` → `decide`, writing
`.specify/assessments/<slug>/decision.md`. A **kill** verdict stops the
pipeline — `/speckit-interview` refuses to proceed past one without an explicit
human override. Killing an idea there costs one conversation; discovering the
same thing at acceptance costs the whole pipeline.

## Implementation and artifacts

`/speckit-implement` implements directly, matching `CLAUDE.md`, the constitution
and `docs/spec-kit-workflow.md`. Read `docs/spec-kit-workflow.md` before
authoring specs. Spec Kit maintains versioned artifacts under `specs/`.

Generated `tasks.md` is portable planning input: implement it directly when the
user's request includes implementation, while preserving worktree, TDD, review,
CI, landing, and release gates.
