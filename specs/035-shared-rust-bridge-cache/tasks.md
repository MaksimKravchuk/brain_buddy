# Tasks: Shared Apple Rust bridge cache

Input: spec.md, plan.md, design.md. One bounded implementation PR, followed by serial verification documentation; no independent product slices.
Planning campaign 1: product-decision-required; campaign 2: technical-changes-required. Implementation is authorized by founder-acceptance.json, with the current owner reply recorded. All tests and protection settings remain untouched.

- [x] T001 Resolve the planning gate with the owner; explicit one-task founder acceptance recorded.
- [x] T002 Add a focused producer-contract regression to the existing required utility suite and observe failure against the missing workflow.
- [x] T003 Implement the trusted main-push producer with existing two variants and exact-key inputs; wire its utility assertion into workflow-lint without changing product checks.
- [x] T004 Run affected validators and complete exact-candidate required CI plus independent code review.
- [x] T005 Follow the owner-approved landing procedure; verify main and producer run, cache keys and main refs.
- [ ] T006 Add operational documentation under ios/README.md in an owned follow-up PR, correcting the native-lane explanation; verify an actual merge-group cache hit, full app/widget build, package test count and timings.
- [ ] T007 Record exact SHA, CI/release disposition, cache read-back and before/after timings; report remaining limits honestly.
