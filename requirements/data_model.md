# Brain Buddy Data Model (MVP)

## Storage Overview
- Persistence layer uses filesystem-based JSON files under a root data directory (configurable; default `data/`).
- Each tree stored in its own folder: `data/{tree_id}/`.
- Files favor flat structures for easy migration to document or relational databases later.
- Operations should be atomic where possible (write temp file then rename) to reduce corruption risk.

## Directory Layout
```
data/
  tree_123/
    tree.json
    versions/
      2024-04-06T12:40:00Z.json
    validation/
      node_root.json
    config.json
```

## Tree File (`tree.json`)
```json
{
  "id": "tree_123",
  "title": "Supply Chain CRT",
  "description": "Exploring constraints in fulfillment process",
  "created_at": "2024-04-06T12:45:00Z",
  "updated_at": "2024-04-06T12:55:00Z",
  "nodes": [
    {
      "id": "node_root",
      "label": "Shipping delays increase costs",
      "position": {"x": 100, "y": 200},
      "metadata": {
        "created_at": "2024-04-06T12:45:00Z",
        "updated_at": "2024-04-06T12:50:00Z"
      },
      "visual": {
        "color": "#F4F4F5",
        "highlight": false
      },
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
      "notes": "node_weather explains node_root",
      "metadata": {
        "created_at": "2024-04-06T12:46:00Z",
        "updated_at": "2024-04-06T12:46:00Z"
      }
    }
  ],
  "version_refs": [
    {
      "id": "tree_123::2024-04-06T12:40:00Z",
      "label": "Before vendor change",
      "created_at": "2024-04-06T12:40:00Z"
    }
  ]
}
```

### Node Schema
- `id`: string (UUID or shortid).
- `label`: string (required).
- `position`: object with float `x`/`y` canvas coordinates.
- `metadata`: timestamps plus optional author.
- `visual`: optional hints for frontend (color, highlight status from validation).
- `validation`: latest validation results; may be `null` if never validated.

### Relation Schema
- `id`: string.
- `source_id`: string (effect node).
- `target_id`: string (cause node).
- `question_label`: string, default `WHY?`, editable by user.
- `notes`: optional explanation text.
- `metadata`: timestamps; store author info if available.

## Version Snapshots (`versions/{timestamp}.json`)
- Full copy of `tree.json` structure at snapshot time.
- Filename uses ISO timestamp (UTC) to ease chronological sorting.
- Example snippet:
```json
{
  "id": "tree_123",
  "label": "Supply Chain CRT",
  "captured_at": "2024-04-06T12:40:00Z",
  "nodes": [...],
  "relations": [...]
}
```

## Validation History (`validation/{node_id}.json`)
- Array of validation results per node to avoid bloating main tree file.
```json
[
  {
    "confidence": 78,
    "summary": "Chain consistent. Verify supplier data.",
    "provider": "openai",
    "prompt_hash": "abc123",
    "checked_at": "2024-04-06T12:55:00Z"
  }
]
```
- `prompt_hash` helps deduplicate requests with identical inputs.

## Provider Configuration (`config.json`)
```json
{
  "default_provider": "openai",
  "providers": {
    "openai": {
      "api_key_ref": "secrets/openai.key",
      "model": "gpt-4o-mini"
    }
  }
}
```
- `api_key_ref` points to file path or secret store. MVP may store encrypted key in same file if necessary.
- Additional provider-specific settings stored under their respective keys.

## Global Metadata
- Maintain `data/index.json` to map tree IDs to titles, descriptions, and last modified timestamps for quick listing.
```json
[
  {
    "id": "tree_123",
    "title": "Supply Chain CRT",
    "description": "Exploring constraints",
    "updated_at": "2024-04-06T12:55:00Z"
  }
]
```

## Logging
- Debug logs stored separately (e.g., `logs/app.log`) capturing API calls, validation requests/responses (with redacted keys).
- Include correlation IDs per request to trace workflows.

## Migration Considerations
- Keep schema definitions centralized (e.g., Pydantic models) to toggle between filesystem and future database storage.
- Use version field in files (`schema_version`) to support migrations as structures evolve.
