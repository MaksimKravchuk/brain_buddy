# Feature Specification: Current Reality Tree UI

**Feature Branch**: `001-reality-tree-ui`  
**Created**: 2025-12-03  
**Status**: Draft  
**Input**: User description: "Im workin on app to help people formalize their thinking. The core idea is Current reality trees from theory of constraints. 
User creates some initial nodes (undesired effects), then create lower level node, responding to WHY question. Nodes have relations to each other. relations have direction from lower to upper: N1 I took my umbrella with me <-why-- n2 its rainy. 
The app shold have web UI. UI shold be clean, MIRO with stickie notes is a good example. 
UI shold have keyboard based quick actions like xmidn does. 

UI: 
- should have simple tree managemet menu: new tree, save tree 
- navigation: zoom in, zoom out center, etc
Nodes: 
- different colors:
  - undesired effecr
  - regular node
  - cuase node (if node have 3 and more up relation we starting to change its color a bit). If node relations can be traced to all undesired effects we highlight it even more with brick red color Relation: have directions looks like arrow directed from bottom to up Animations: When user klicks on existing node, we should uprise upper related relations and nodes. Make other stuff a bit gray Data: - user can download his tree as json - import this json - If user sign in we can store tree (json) in our db AI: if user signed in we can provide AI based analisys for his chain of thoughts. Convert chain of nodes to chain of thoughts, mix it into base prompt and request ai to provide feedback."

## Clarifications

### Session 2025-12-03

- Q: Should AI feedback requests auto-send tree data or require user confirmation? → A: Prompt signed-in users to confirm sending the current tree for AI analysis each time.
- Q: How should unsaved work be protected against data loss? → A: Auto-save drafts locally (and to cloud if signed in) on a short interval and warn on exit if unsaved sync is pending.
- Q: What is the autosave cadence and exit warning rule? → A: Auto-save locally every ~5s after the last edit; cloud sync on the same cadence when signed in; warn on exit if any pending sync exists.

## User Scenarios & Testing *(mandatory)*

<!--
  IMPORTANT: User stories should be PRIORITIZED as user journeys ordered by importance.
  Each user story/journey must be INDEPENDENTLY TESTABLE - meaning if you implement just ONE of them,
  you should still have a viable MVP (Minimum Viable Product) that delivers value.
  
  Assign priorities (P1, P2, P3, etc.) to each story, where P1 is the most critical.
  Think of each story as a standalone slice of functionality that can be:
  - Developed independently
  - Tested independently
  - Deployed independently
  - Demonstrated to users independently
-->

### User Story 1 - Build and navigate a current reality tree (Priority: P1)

Users want to capture undesired effects and causes in a clean canvas and quickly link them into a current reality tree.

**Why this priority**: This is the core value of the app; without an easy way to add nodes and relations the tool provides no benefit.

**Independent Test**: Create a new tree, add nodes of each type, connect them with directional relations, and traverse via zoom/center controls without needing any other feature.

**Acceptance Scenarios**:

1. **Given** a blank tree, **When** the user adds undesired effect, cause, and regular nodes via keyboard quick actions or toolbar, **Then** the nodes appear on the canvas with the correct labels and type-specific colors.
2. **Given** two nodes, **When** the user connects a lower node to an upper undesired effect with a "why" relation, **Then** the relation renders bottom-to-top with an arrow and the path highlights when either node is selected.
3. **Given** a populated tree, **When** the user zooms in/out or recenters on a selected node, **Then** the canvas responds within a fraction of a second and keeps the selected path in view.
4. **Given** the user is editing a tree, **When** they make changes, **Then** the tree auto-saves to local draft (and cloud if signed in) at short intervals and warns before exit if pending sync remains.

---

### User Story 2 - Persist and share trees (Priority: P2)

Users want to save, re-open, and share their reasoning without losing structure or styling.

**Why this priority**: Saving and exporting keeps work portable and prevents loss; importing enables collaboration and retries.

**Independent Test**: Create a tree, save it, download the JSON, re-import it into a new session, and verify structure and colors without invoking AI analysis.

**Acceptance Scenarios**:

1. **Given** an open tree, **When** the user chooses to save, **Then** the latest node/relationship state is stored under the current tree name and confirmed to the user.
2. **Given** a completed tree, **When** the user downloads the JSON and re-imports it, **Then** all nodes, relation directions, and color cues reappear identically in a fresh canvas.
3. **Given** a signed-in user, **When** they save a tree and sign out/in again, **Then** the saved tree is available with its prior state intact.

---

### User Story 3 - Receive AI feedback on reasoning chains (Priority: P3)

Signed-in users want AI guidance on their chain of thought to spot gaps or suggest improvements.

**Why this priority**: AI feedback increases the value of the captured tree by turning structure into actionable insight.

**Independent Test**: With an existing signed-in session and populated tree, request AI feedback and review the returned summary and recommendations without needing export/import features.

**Acceptance Scenarios**:

1. **Given** a signed-in user with a populated tree, **When** they request AI analysis, **Then** the system summarizes the chain of causes/effects and returns at least one actionable recommendation within a few seconds.
2. **Given** a signed-in user, **When** they request AI analysis, **Then** the system asks for confirmation before sending tree data and proceeds only after consent.
2. **Given** a signed-in user, **When** AI analysis is unavailable or fails, **Then** the user sees a clear error and can retry without losing their tree.

---

[Add more user stories as needed, each with an assigned priority]

### Edge Cases

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right edge cases.
-->

- Import file is malformed JSON or missing required fields.
- A relation is attempted in the wrong direction (e.g., from effect to cause) or creates a cycle.
- A node exceeds the threshold for "cause" highlighting but is later disconnected.
- User attempts to leave or refresh with unsaved changes.
- AI feedback request times out or the user is not signed in.

## Requirements *(mandatory)*

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right functional requirements.
-->

### Functional Requirements

- **FR-001**: Users MUST be able to create, name, and switch between current reality trees from a simple tree management menu (new/save/open).
- **FR-002**: Users MUST be able to add and edit nodes of three types (undesired effect, cause, regular) with distinct visual styling.
- **FR-003**: Users MUST be able to create directional "why" relations from lower causes to upper effects, rendered with clear arrows and enforced directionality.
- **FR-004**: Keyboard quick actions MUST support core operations (create node, link nodes, zoom, center/pan) and be discoverable in-product.
- **FR-005**: Nodes with three or more upstream relations MUST change styling to indicate potential causes; nodes whose paths reach all undesired effects MUST highlight more prominently.
- **FR-006**: Selecting a node MUST animate and emphasize its upstream relations/nodes while de-emphasizing unrelated elements without hiding them.
- **FR-007**: Navigation controls MUST provide zoom in/out and recenter-on-selection behaviors without losing the current selection.
- **FR-008**: Users MUST be able to download the current tree as JSON (including node types, relations, and colors) and import a JSON file to fully restore structure; invalid files MUST produce clear errors without altering the canvas.
- **FR-009**: Signed-in users MUST be able to save trees to their account and retrieve the same state after signing back in.
- **FR-010**: Signed-in users MUST be able to request AI feedback that summarizes the chain of thought and returns recommendations; each request MUST prompt confirmation before sending tree data; failures MUST surface actionable errors and preserve the tree.
- **FR-011**: The app MUST auto-save drafts locally roughly every 5 seconds after the last edit and, when signed in, sync to cloud on the same cadence; the user MUST be warned before exit/navigation if any pending sync exists.

### Key Entities *(include if feature involves data)*

- **Tree**: Named collection of nodes and relations, with saved/unsaved status and ownership for signed-in users.
- **Node**: Item with label and type (undesired effect, cause, regular), tracked color state, and relation counts informing highlighting.
- **Relation**: Directed link from a lower node to an upper node capturing "why" causation and used for highlighting paths.
- **User Session**: Authenticated state enabling cloud saves and AI feedback eligibility.
- **AI Feedback Summary**: Generated text describing reasoning chains and offering recommendations tied to the current tree.

### Non-Functional Requirements (Quality, UX, Performance)

- **NFR-001**: Work MUST satisfy repository quality gates (lint/format/type checks) and include automated tests for new behaviors.
- **NFR-002**: UI/UX MUST remain consistent and accessible: keyboard-first flows, clear focus states, readable color contrast, and layouts that hold on tablet-sized viewports.
- **NFR-003**: Canvas interactions (zoom, select, highlight) on trees up to ~200 nodes SHOULD remain responsive (perceived under ~0.2s) without freezing the interface.
- **NFR-004**: AI feedback and save/load operations SHOULD complete within a few seconds and communicate progress/errors clearly; operations MUST avoid data loss.

## Success Criteria *(mandatory)*

<!--
  ACTION REQUIRED: Define measurable success criteria.
  These must be technology-agnostic and measurable.
-->

### Measurable Outcomes

- **SC-001**: 90% of first-time users can create and link at least five nodes (covering undesired effects and causes) in under 3 minutes using keyboard shortcuts or the toolbar during usability testing.
- **SC-002**: 95% of navigation actions (zoom, center, pan) respond within 0.2 seconds on a 200-node test tree.
- **SC-003**: 100% of export/import round-trips preserve node types, relation directions, and color cues in QA tests.
- **SC-004**: 90% of AI feedback requests for signed-in users return a summary plus at least one recommendation within 5 seconds; 100% of failures present a clear retry path without losing work.
