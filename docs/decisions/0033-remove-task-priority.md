# ADR-0033: Remove task priority from the product

Date: 2026-10-15
Status: Accepted by the product owner, 2026-10-15
Supersedes in part: ADR-0006 (Priority as a baseline Task field, B-18, and the
priority parts of the filter and sort rules), ADR-0020 (its whole "Public Priority
contract" section; its List archive decision stands)
Related: feature 011 (`specs/011-rtm-task-parity/`), ADR-0030

## Context

Tasks carried a `priority` field (`none | low | medium | high`) on every surface:
the backend document, the HTTP and MCP contracts, the shared Rust domain and its
sync wire, the iOS, macOS and web clients, and the agent CLI. It drove a sort mode,
a list filter, smart-add `!` markers and a row badge.

On 2026-10-15 Max decided that BrainBuddy has no priorities at all: people can set
their own order, and anyone who still wants a priority can use a tag. Because there
are no real users and no valuable data (ADR-0030), the field is removed outright
rather than deprecated.

## Decision

- No Task has a priority. The `priority` field is gone from storage documents,
  request and response schemas, MCP tool parameters, the Rust domain and wire types,
  every client model, and the CLI.
- The `priority` sort mode is gone. List sorts are `manual`, `due` and `title`.
- The `priority` list filter is gone from the HTTP query, the Rust list options,
  the clients and the CLI.
- The `priority_required` domain error is gone.
- Smart add no longer reads `!` priority markers; such text stays in the title.
- Canonical content forms and content stamps no longer include priority.
- No UI replaces it. Tags are the answer for anyone who wants one.

## Consequences

- There is no data migration and no compatibility window. Python storage already
  ignores unknown fields, so stored task documents that still carry `priority`
  load unchanged and drop it on the next write.
- The Rust domain keeps `deny_unknown_fields`, so a command, outbox entry or local
  store written by an older client that still carries `priority` is rejected. An
  installed iOS or macOS build from before this change must be updated, and its
  local store may need to be reset. This is accepted while there are no real users.
- Feature 011's priority requirements (FR-006, SC-014, and the priority parts of
  FR-025, FR-028 and FR-039) are withdrawn; the feature's other requirements stand.
- Every other spec artifact that names a task priority field, value, filter, sort
  or control is superseded on that point by this record. That includes the
  `"priority": "none"` default in feature 003's Smart Add contract and feature 002's
  CO-11 default; neither field is accepted any more. Features 006, 020, 021, 024,
  026 and 027 carry a pointer to this record. Features 002 and 003 are completed,
  grandfathered packages, so they are superseded here rather than edited.
