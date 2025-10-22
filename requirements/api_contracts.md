# Brain Buddy API Contracts (MVP Draft)

Base URL: `/api`

## Authentication
- MVP runs without authentication; future versions can add token-based auth.
- API keys for AI providers managed via backend configuration endpoints.

## Trees

### Create Tree
- `POST /trees`
- Request:
```json
{
  "title": "Supply Chain CRT",
  "description": "Exploring constraints in fulfillment process"
}
```
- Response `201 Created`:
```json
{
  "id": "tree_123",
  "title": "Supply Chain CRT",
  "description": "Exploring constraints in fulfillment process",
  "created_at": "2024-04-06T12:45:00Z",
  "updated_at": "2024-04-06T12:45:00Z"
}
```

### List Trees
- `GET /trees`
- Response `200 OK`:
```json
[
  {
    "id": "tree_123",
    "title": "Supply Chain CRT",
    "description": "Exploring constraints in fulfillment process",
    "updated_at": "2024-04-06T12:45:00Z"
  }
]
```

### Retrieve Tree (with structure)
- `GET /trees/{tree_id}`
- Response `200 OK`:
```json
{
  "id": "tree_123",
  "title": "Supply Chain CRT",
  "description": "Exploring constraints in fulfillment process",
  "created_at": "2024-04-06T12:45:00Z",
  "updated_at": "2024-04-06T12:50:00Z",
  "nodes": [
    {
      "id": "node_root",
      "label": "Shipping delays increase costs",
      "position": {"x": 100, "y": 200},
      "incoming_count": 2,
      "outgoing_count": 0,
      "validation": {
        "confidence": 82,
        "last_checked": "2024-04-06T12:48:00Z",
        "provider": "openai"
      }
    }
  ],
  "relations": [
    {
      "id": "rel_456",
      "source_id": "node_root",
      "target_id": "node_weather",
      "question_label": "WHY?",
      "notes": "Weather events cause delay",
      "created_at": "2024-04-06T12:46:00Z"
    }
  ],
  "versions": [
    {
      "id": "tree_123::2024-04-06T12:40:00Z",
      "label": "Before vendor change",
      "created_at": "2024-04-06T12:40:00Z"
    }
  ]
}
```

### Delete Tree
- `DELETE /trees/{tree_id}`
- Response `204 No Content`

## Nodes

### Create Node
- `POST /trees/{tree_id}/nodes`
- Request:
```json
{
  "label": "Customers receive damaged goods",
  "position": {"x": 320, "y": 410}
}
```
- Response `201 Created`:
```json
{
  "id": "node_damaged",
  "label": "Customers receive damaged goods",
  "position": {"x": 320, "y": 410},
  "created_at": "2024-04-06T12:52:00Z",
  "updated_at": "2024-04-06T12:52:00Z"
}
```

### Update Node
- `PATCH /trees/{tree_id}/nodes/{node_id}`
- Request (any subset of fields):
```json
{
  "label": "Customers complain about damaged goods",
  "position": {"x": 350, "y": 420}
}
```
- Response `200 OK` returns updated node.

### Delete Node
- `DELETE /trees/{tree_id}/nodes/{node_id}`
- Optional query parameter `cascade=true` to confirm deletion of relations.
- Response `204 No Content`

## Relations

### Create Relation
- `POST /trees/{tree_id}/relations`
- Request:
```json
{
  "source_id": "node_effect",
  "target_id": "node_cause",
  "question_label": "WHY?",
  "notes": "node_cause explains node_effect"
}
```
- Response `201 Created` with relation payload.
- Relations are directional: `target_id` logically answers the `question_label` posed by `source_id`. Example: `node_umbrella <- node_raining`.

### Update Relation
- `PATCH /trees/{tree_id}/relations/{relation_id}`
- Request:
```json
{
  "question_label": "HOW COME?",
  "notes": "Unexpected storm pattern"
}
```
- Response `200 OK` returns updated relation.

### Delete Relation
- `DELETE /trees/{tree_id}/relations/{relation_id}`
- Response `204 No Content`

## AI Validation

### Trigger Validation
- `POST /trees/{tree_id}/validate/{node_id}`
- Request:
```json
{
  "provider": "openai",
  "prompt_overrides": {
    "temperature": 0.2
  }
}
```
- Response `202 Accepted` (async) or `200 OK` (sync):
```json
{
  "node_id": "node_effect",
  "provider": "openai",
  "confidence": 78,
  "summary": "The reasoning chain is mostly consistent; consider verifying supply data",
  "checked_at": "2024-04-06T12:55:00Z"
}
```
- Implementation choice: synchronous response for MVP; consider background jobs later.

### Validation History
- `GET /trees/{tree_id}/nodes/{node_id}/validation-history`
- Response `200 OK`:
```json
[
  {
    "confidence": 78,
    "summary": "Reasoning chain consistent.",
    "provider": "openai",
    "checked_at": "2024-04-06T12:55:00Z"
  }
]
```

## Versions

### Create Version Snapshot
- `POST /trees/{tree_id}/versions`
- Request:
```json
{
  "label": "Before restructuring",
  "notes": "Captured after management review"
}
```
- Response `201 Created` with version metadata.

### List Versions
- `GET /trees/{tree_id}/versions`
- Response `200 OK`:
```json
[
  {
    "id": "tree_123::2024-04-06T12:40:00Z",
    "label": "Before restructuring",
    "notes": "Captured after management review",
    "created_at": "2024-04-06T12:40:00Z"
  }
]
```

### Restore Version
- `POST /trees/{tree_id}/versions/{version_id}/restore`
- Response `200 OK` returns restored tree snapshot.

## Export
- `GET /trees/{tree_id}/export`
- Response `200 OK` with `application/json` download containing current tree, nodes, relations, validation metadata, and version references.

## Provider Configuration

### List Providers
- `GET /providers`
- Response `200 OK`:
```json
[
  {"id": "openai", "label": "OpenAI GPT-4o"},
  {"id": "anthropic", "label": "Anthropic Claude"}
]
```

### Set Provider Credentials
- `POST /providers/{provider_id}/credentials`
- Request:
```json
{
  "api_key": "sk-***",
  "default": true
}
```
- Response `204 No Content`
- Stored securely on backend (file-based secrets for MVP).

### Get Active Provider
- `GET /providers/active`
- Response `200 OK`:
```json
{
  "provider": "openai",
  "configured": true
}
```

## Error Format
- Errors return consistent JSON:
```json
{
  "error": "VALIDATION_FAILED",
  "message": "Node label must not be blank",
  "details": {
    "field": "label"
  }
}
```
- Standard HTTP status codes (400, 404, 409, 500) communicate failures.
