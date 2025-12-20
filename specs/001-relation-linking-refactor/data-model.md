# Data Model: Flexible Relation Linking

## Entities

### Tree
- **Fields**: id, name, nodes[], relations[], updated_at, version/meta for export/import.
- **Relationships**: Contains nodes and relations scoped to the same tree.
- **Constraints**: Cross-tree relations not allowed.

### Node
- **Fields**: id, label, type (undesired effect | cause | regular), position, styling metadata, upstream/downstream counts.
- **Relationships**: Participates in many relations as source or target.
- **Constraints**: Type does not determine parent/child semantics; direction uses cause (lower) → effect (upper).

### Relation
- **Fields**: id, source_node_id, target_node_id, created_at, direction (implicit source→target), optional label/metadata for rendering, correlation reference for error contexts.
- **Relationships**: Belongs to a Tree; references two Node ids.
- **Constraints**: No self-links (source != target); no duplicate source/target pairs; must not close cycles; direction is always cause→effect.

## Validation Rules
- Creating a relation must check: source/target exist in the same tree; not self-link; not duplicate; does not introduce a cycle.
- Relations must remain selectable/editable and highlight with endpoints.
- Export/import must preserve relation ids, source/target, and direction exactly.
