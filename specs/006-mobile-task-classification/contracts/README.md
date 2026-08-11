# Contracts: none change

This directory records a checked finding rather than an absence.

Phase 1 confirmed that feature 006 changes **no** interface contract:

| surface | status | evidence |
|---|---|---|
| `PATCH /tasks/{id}` | unchanged | `TaskUpdateRequest` already carries `project_id`, `tag_ids` and the required `expected_revision` |
| `POST /projects` | unchanged | `createProject` already exists in `mobile/src/api/client.ts` |
| `POST /tags` | unchanged | `createTag` already exists in the same client |
| `GET /auth/me` | unchanged | already returns `feature_flags: dict[str, bool]` |
| `KNOWN_FEATURE_FLAGS` | **widened** | one name added to an allow-list in `backend/app/core/config.py`. Additive; no existing caller changes |

The device-local pending-change record is not a contract: it never crosses a
process boundary. Its shape is in [`../data-model.md`](../data-model.md).

Recorded explicitly because "no contracts directory" and "contracts were checked
and none change" look identical from the outside, and only one of them is a
finding.
