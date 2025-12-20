# API Contract: Relations

## POST /api/trees/{tree_id}/relations
- **Purpose**: Create a directed relation between two nodes in the same tree (cause/lower → effect/upper).
- **Request Body**:
  ```json
  {
    "source_node_id": "node-uuid",
    "target_node_id": "node-uuid"
  }
  ```
- **Responses**:
  - `201 Created`:  
    ```json
    {
      "id": "relation-uuid",
      "tree_id": "tree-uuid",
      "source_node_id": "node-uuid",
      "target_node_id": "node-uuid",
      "created_at": "2025-12-20T12:00:00Z"
    }
    ```
  - `400 Bad Request` (validation: self-link, duplicate, cycle, missing nodes) with human-readable message and correlation/reference id.
  - `404 Not Found` if tree or nodes missing.

## DELETE /api/trees/{tree_id}/relations/{relation_id}
- **Purpose**: Remove a relation.
- **Responses**:
  - `204 No Content`
  - `404 Not Found`

## Export/Import
- Relations MUST be included in tree export JSON with `id`, `source_node_id`, `target_node_id`, and restored exactly on import.

## Error Handling
- All error responses include human-readable detail and a correlation/reference id surfaced to the user inline.
