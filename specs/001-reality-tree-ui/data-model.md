# Data Model – Current Reality Tree UI

## Entities

### Tree
- **Fields**: id, name, created_at, updated_at, owner_id (optional), nodes[], relations[], metadata (version, layout settings).
- **Relationships**: Contains nodes and relations; owned by user when signed in.
- **Validation**: name required; node and relation ids unique within tree.

### Node
- **Fields**: id, label, type (undesired_effect | cause | regular), position (x,y), highlight_state (cause_candidate | effect_spanning | none), relation_counts (up_count, down_count).
- **Relationships**: Linked via relations; belongs to one tree.
- **Validation**: label required; type constrained to enum; position required for canvas placement.

### Relation
- **Fields**: id, from_id (lower/cause), to_id (upper/effect), kind ("why"), created_at.
- **Relationships**: Connects two nodes in the same tree.
- **Validation**: Must not create cycles; direction enforced (from lower to upper); referenced nodes must exist.

### User Session
- **Fields**: user_id, session_token, permissions (can_save, can_request_ai), last_active_at.
- **Relationships**: Authorizes persistence and AI feedback requests.
- **Validation**: session must be valid for save/load/AI operations.

### AI Feedback Summary
- **Fields**: tree_id, generated_at, summary_text, recommendations[], status (success | failed | pending).
- **Relationships**: Tied to a specific tree/version.
- **Validation**: Requires signed-in user; status reflects latest request outcome.

## Derived States & Rules
- Cause highlighting triggers when a node has >=3 outgoing/upstream relations; effect-spanning highlight when its reachable paths cover all undesired effect nodes.
- Selecting a node sets highlight_state for its upstream path and applies canvas de-emphasis elsewhere (no deletion of off-path nodes).
- Import/export preserves ids, types, positions, relations, and highlight cues; invalid imports leave current tree untouched.
