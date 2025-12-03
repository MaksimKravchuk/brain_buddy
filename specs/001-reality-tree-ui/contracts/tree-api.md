# Contracts – Current Reality Tree UI

## REST Endpoints (proposed)

- **GET /api/trees**: List trees for signed-in user. Returns array of `{id, name, updated_at}`.
- **POST /api/trees**: Create a new tree. Body: `{name}`. Returns `{id, name, created_at, updated_at}`.
- **GET /api/trees/{id}**: Fetch full tree. Returns `{id, name, nodes: [], relations: [], metadata}`.
- **PUT /api/trees/{id}**: Save full tree state. Body mirrors export schema `{name, nodes, relations, metadata}`. Returns updated tree.
- **POST /api/trees/import**: Validate and import uploaded JSON. Body: tree export JSON. Returns stored tree with ids preserved when possible.
- **POST /api/trees/{id}/export**: Export current tree JSON. Returns `{tree}` payload suitable for download.
- **POST /api/trees/{id}/ai-feedback**: Request AI analysis. Body: `{tree_id, version?, request_id?}`. Returns `{status, summary, recommendations[]}` or `{status: "pending"}`; errors include actionable message.

## JSON Schema (export/import)

```json
{
  "id": "tree-123",
  "name": "My Current Reality Tree",
  "metadata": {
    "version": 1,
    "created_at": "2025-12-03T12:00:00Z",
    "updated_at": "2025-12-03T12:05:00Z"
  },
  "nodes": [
    {
      "id": "n1",
      "label": "Took umbrella",
      "type": "undesired_effect",
      "position": {"x": 100, "y": 200},
      "highlight_state": "none",
      "relation_counts": {"up_count": 0, "down_count": 1}
    }
  ],
  "relations": [
    {"id": "r1", "from_id": "n2", "to_id": "n1", "kind": "why"}
  ]
}
```

### Validation Rules
- `type` is one of `undesired_effect`, `cause`, `regular`.
- `kind` is `why`; `from_id` and `to_id` must exist and must not form cycles.
- Positions required; ids unique per tree.
- Invalid payloads return 400 with error details; tree state remains unchanged on failure.
