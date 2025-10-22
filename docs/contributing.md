# Contributing Guide

We welcome enhancements and bug fixes that keep Brain Buddy reliable and fast. This document summarises expectations for pull requests and local workflows.

## Development Workflow
1. **Fork & branch**: create a feature branch from `main` using a descriptive name (`feature/perf-counters`).
2. **Sync requirements**: skim `requirements/implementation_plan.md` to stay aligned with current phase goals.
3. **Write tests early**: favour pytest for backend logic and React Testing Library/Jest for frontend interactions.
4. **Keep commits focused**: each commit should represent a reversible unit with a clear message (`fix: guard API key middleware`).

## Coding Standards
- **Backend**: adhere to Black formatting, Ruff lint rules, and type-check where possible with Mypy. Prefer pure functions for repository helpers and document non-trivial behaviour with succinct comments.
- **Frontend**: TypeScript strictness is enabled. Use hooks for side-effects, memoise expensive selectors, and avoid non-deterministic IDs outside helpers.
- **Docs**: keep Markdown ASCII-friendly; provide references to file paths when describing implementation details.

## Testing Checklist
- `cd backend && pytest`
- `cd frontend && npm test`
- If you touch API contracts, update fixtures and schemas in both backend and frontend.
- Run a manual smoke test through the UI to ensure the canvas loads, nodes can be created, and validation toasts appear.

## Pull Request Checklist
- [ ] Description explains the problem and approach.
- [ ] Tests cover key paths (or rationale provided when not practical).
- [ ] Docs updated (`README`, `docs/*.md`, or API contracts) when behaviour changes.
- [ ] No debug logging or experimental flags left behind.
- [ ] Linked issue / ticket referenced in the PR body.

## Review Expectations
- Reviewers focus on correctness, regressions, and clarity. Highlight risks or testing gaps explicitly.
- Authors should respond to feedback within two working days, or leave a status update if additional investigation is required.
- Once approved, squash merge unless the commit history adds value for future archaeologists.
