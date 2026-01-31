# Feature Specification: Flexible Relation Linking

**Feature Branch**: `001-relation-linking-refactor`  
**Created**: 2025-12-20  
**Status**: Draft  
**Input**: User description: "Refactor the app. if there is Node1 < Node2 < node3 Node4 < node5 I can add relation node2 < node5 There is no node types like parent and child."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Link nodes across chains (Priority: P1)

Users want to create a directed relation between any two nodes in the same tree, even when they belong to different branches, without being blocked by parent/child labels.

**Why this priority**: Cross-branch relations are core to expressing causality; without them, trees stay fragmented and users cannot connect reasoning paths.

**Independent Test**: In an existing tree with two separate chains, add a directed relation from a node in chain A to a node in chain B and see it render with correct direction and labeling.

**Acceptance Scenarios**:

1. **Given** two existing chains (e.g., Node1 → Node2 → Node3 and Node4 → Node5), **When** the user links Node2 to Node5, **Then** the new relation is created with the expected direction and appears on the canvas.
2. **Given** nodes without parent/child labels, **When** the user initiates a link, **Then** the flow presents a clear source/target selection without referring to parent/child types.
3. **Given** a new cross-chain relation, **When** the user selects either endpoint, **Then** the relation highlights and remains editable like any other link.

---

### User Story 2 - Preserve new relations (Priority: P2)

Users need cross-chain relations to persist across saves, reloads, and export/import so reasoning stays intact.

**Why this priority**: Relations lose value if they disappear after a reload or when sharing a JSON export.

**Independent Test**: Create a cross-chain relation, save/reload the tree, and export/import the tree file to verify the relation and its direction survive all steps.

**Acceptance Scenarios**:

1. **Given** a tree with a cross-chain relation, **When** the user saves and reopens the tree, **Then** the relation is still present and oriented correctly.
2. **Given** a tree with cross-chain relations, **When** the user exports and re-imports it, **Then** all such relations are restored without duplication or loss.

---

### User Story 3 - Protect graph integrity (Priority: P3)

Users expect the app to block impossible or harmful links while keeping the graph responsive.

**Why this priority**: Preventing cycles, self-links, or duplicates avoids broken reasoning and keeps navigation fast.

**Independent Test**: Attempt to create self-links, duplicate links, or links that would introduce a cycle, and confirm the app prevents them with actionable feedback while keeping the canvas responsive.

**Acceptance Scenarios**:

1. **Given** a selected node, **When** the user tries to link it to itself, **Then** the app blocks the action with a clear message.
2. **Given** an existing relation between two nodes, **When** the user attempts the same relation again, **Then** the app prevents duplication and explains why.
3. **Given** a link that would close a cycle, **When** the user attempts it, **Then** the app blocks it and keeps the canvas responsive on a large (~200-node) tree.

---

### Edge Cases

- Link attempt between nodes in different chains that would introduce a cycle.
- Duplicate relation attempts between the same source and target.
- Self-link attempts (source and target identical).
- Import files missing relation definitions or containing malformed relation direction.
- Linking while offline/unsaved: relation creation must not risk data loss; autosave warns before exit if pending.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to create a directed relation between any two nodes in the same tree, regardless of branch, by selecting source and target explicitly, with direction consistently modeled as cause/lower → effect/upper.
- **FR-002**: Relation creation MUST avoid parent/child terminology; UI copy and prompts MUST use neutral language (e.g., source/target, from/to).
- **FR-003**: The system MUST validate and block self-links, duplicate links, and link attempts that would introduce cycles, providing user-facing reasons.
- **FR-004**: New relations MUST render with clear directionality, be selectable/editable, and participate in existing highlight/selection behaviors.
- **FR-005**: Cross-branch relations MUST persist across saves, reloads, and export/import with direction intact and without duplication.
- **FR-006**: Relation creation, validation, and rendering MUST remain responsive on trees of roughly 200 nodes, without freezing other interactions.
- **FR-007**: Errors during relation creation or persistence MUST produce actionable, inline, non-blocking feedback near the linking UI with retry guidance, expressed in human-readable language (no codes-only), include a copyable correlation/trace reference, shift focus to the inline message and announce it via a live region, and avoid data loss; local autosave protections remain in effect.

### Key Entities *(include if feature involves data)*

- **Tree**: Collection of nodes and directed relations.
- **Node**: Item in the tree that can participate in relations; not classified as parent/child for linking purposes.
- **Relation**: Directed link from a source node to a target node, including metadata for rendering and persistence.

## Assumptions & Dependencies

- All relations occur within a single tree; cross-tree linking is out of scope.
- Existing node types (cause/undesired effect/regular) remain; only parent/child terminology is removed from UI flows.
- Local-first autosave and consent guardrails stay in place; the feature does not require remote services.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 95% of attempts to link two existing nodes in separate chains succeed on the first try with confirmation visible within 2 seconds.
- **SC-002**: 100% of created cross-chain relations remain present and correctly oriented after save → reload and export → import round-trips in QA tests.
- **SC-003**: 98% of invalid link attempts (self, duplicate, cycle) are blocked with clear, user-readable reasons and no data loss.
- **SC-004**: Canvas remains responsive during relation creation/editing on a ~200-node tree, with navigation and highlighting actions responding within ~0.2 seconds.

## Clarifications

### Session 2025-12-20

- Q: Should direction semantics stay consistent when linking across chains? → A: Enforce cause-to-effect direction for all relations (source = cause/lower, target = effect/upper).
- Q: How should blocked link errors be presented? → A: Inline, non-blocking message near linking UI with retry guidance.
- Q: What should blocked link errors communicate? → A: Provide human understandable error.
- Q: Should relation failures include a support/diagnostic reference? → A: Log correlation ID and show a short reference inline.
- Q: How should inline errors behave for accessibility? → A: Shift focus to the inline message and announce via a live region.
