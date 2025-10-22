# API Usage Guide

All endpoints live beneath the configured `BRAIN_BUDDY_API_PREFIX` (default `/api`). Responses include `X-Correlation-ID` for log tracing and follow a consistent JSON envelope.

## Authentication

If `BRAIN_BUDDY_API_KEY` is set on the backend, clients must send the matching key with each request:

```
X-API-Key: <your-key>
```

You can customise the header name via `BRAIN_BUDDY_API_KEY_HEADER`; mirror the value in the frontend using `VITE_API_KEY_HEADER`.

## Core Resources

### List Trees
```
GET /api/trees
```

Response (`200 OK`):
```json
[
  {
    "id": "tree_123",
    "title": "Discovery",
    "description": "Insights backlog",
    "updated_at": "2024-06-18T12:22:14Z"
  }
]
```

### Retrieve Tree Detail
```
GET /api/trees/{tree_id}
```

Response (`200 OK`):
```json
{
  "id": "tree_123",
  "title": "Discovery",
  "description": "Insights backlog",
  "created_at": "2024-06-01T08:15:00Z",
  "updated_at": "2024-06-18T12:22:14Z",
  "nodes": [
    {
      "id": "node_a",
      "label": "Problem statement",
      "position": { "x": 0, "y": 0 },
      "metadata": {
        "created_at": "2024-06-01T08:15:00Z",
        "updated_at": "2024-06-18T12:22:14Z",
        "author": null
      },
      "incoming_count": 0,
      "outgoing_count": 2
    }
  ],
  "relations": [
    {
      "id": "rel_ab",
      "source_id": "node_a",
      "target_id": "node_b",
      "question_label": "WHY?",
      "metadata": {
        "created_at": "2024-06-01T08:16:00Z",
        "updated_at": "2024-06-01T08:16:00Z",
        "author": null
      }
    }
  ],
  "versions": [
    {
      "id": "ver_001",
      "label": "Baseline",
      "created_at": "2024-06-18T12:22:14Z",
      "diff_summary": null,
      "conflict_count": 0
    }
  ]
}
```

### Create a Node
```
POST /api/trees/{tree_id}/nodes
Content-Type: application/json

{
  "label": "New idea",
  "position": { "x": 120, "y": 220 }
}
```

Response (`201 Created`): `NodeResponse` mirroring the created node with computed counts.

### Update a Relation
```
PATCH /api/trees/{tree_id}/relations/{relation_id}
Content-Type: application/json

{
  "question_label": "HOW?",
  "notes": "Linking to next hypothesis"
}
```

### Trigger Validation
```
POST /api/trees/{tree_id}/validate/{node_id}
Content-Type: application/json

{
  "provider_id": "mock",
  "prompt_overrides": {}
}
```

Response (`202 Accepted`):
```json
{
  "status": "pending",
  "node_id": "node_a",
  "provider": "mock"
}
```

### Export Tree Snapshot
```
GET /api/trees/{tree_id}/export?version_id=<optional-version>
```

Response: streamed JSON file with `Content-Disposition` filename such as `tree_123-latest.json`.

## Error Handling
- Errors return `ErrorResponse` payloads: `{ "message": "...", "detail": { ... } }`.
- `X-Correlation-ID` accompanies every response. Include the value when reporting issues so the backend logs can be filtered quickly.
- Authentication failures return `401` with `WWW-Authenticate: API-Key` when the static key is missing or incorrect.

Refer to `requirements/api_contracts.md` for the full schema catalogue.
