# Brain Buddy User Stories

## Tree Management
- **As a** user building a CRT  
  **I want** to create a new tree with a title and optional description  
  **So that** I can start mapping my problem space.  
  **Acceptance Criteria**:  
  - User can supply title (required) and description (optional).  
  - Application creates an empty canvas and persists metadata.  
  - Success confirmation appears; errors show descriptive message.

- **As a** user referencing an existing CRT  
  **I want** to open a previously saved tree  
  **So that** I can continue editing or reviewing it.  
  **Acceptance Criteria**:  
  - Trees listed with title, last modified date.  
  - Selecting a tree loads nodes, relations, validation states.  
  - Loading errors surface with retry guidance.

## Node Operations
- **As a** user capturing ideas  
  **I want** to create nodes inline on the canvas  
  **So that** I can quickly add observations or conditions.  
  **Acceptance Criteria**:  
  - Single hotkey or button creates a node at cursor.  
  - Node opens in edit mode for text entry.  
  - Empty confirmations are prevented with prompt to add text.

- **As a** user refining a node  
  **I want** to edit or delete node content  
  **So that** the tree remains accurate.  
  **Acceptance Criteria**:  
  - Double-click or inspector allows text edits with autosave.  
  - Delete requires confirmation to avoid accidental removal.  
  - Deleting a node also removes attached relations with warning.

## Relation Operations
- **As a** user connecting causes and effects  
  **I want** to draw directional relations between nodes  
  **So that** I can express the logic chain.  
  **Acceptance Criteria**:  
  - Drag connector from source node to target or use menu selection.  
  - Default label is `WHY?`; user can edit label text.  
  - Canvas visually shows direction (arrowhead) and label placement.

- **As a** user reviewing reasoning  
  **I want** to view, edit, or delete relations  
  **So that** the narrative stays precise.  
  **Acceptance Criteria**:  
  - Selecting relation displays properties in inspector (label, notes).  
  - Edits apply immediately and persist.  
  - Removing relation updates related node counts and highlights.

## Navigation & Visualization
- **As a** user understanding context  
  **I want** to select a node and see all related upstream/downstream nodes  
  **So that** I grasp dependencies quickly.  
  **Acceptance Criteria**:  
  - Selected node highlights; connected nodes use distinct styling.  
  - Inspector lists related nodes grouped by direction.  
  - Breadcrumb/path view presents chain from highest node to selected.

- **As a** user managing large trees  
  **I want** hotkeys for pan, zoom, undo/redo, and focus controls  
  **So that** I can navigate efficiently.  
  **Acceptance Criteria**:  
  - Keyboard shortcuts documented in help overlay.  
  - Actions operate without impacting text entry fields unexpectedly.

## AI Validation
- **As a** user checking logic  
  **I want** to validate a node’s reasoning chain via AI  
  **So that** I can spot weak links.  
  **Acceptance Criteria**:  
  - Validation button available on inspector and/or node UI.  
  - Application collects chain from root to node, sends to provider.  
  - Response displays confidence percentage and summary feedback; high confidence triggers highlight.

- **As a** user preferring specific AI services  
  **I want** to configure which provider validates my tree  
  **So that** I control costs and capabilities.  
  **Acceptance Criteria**:  
  - Settings view lists supported providers (OpenAI default).  
  - User can input API key/token securely.  
  - Validation requests honor chosen provider.

## Versioning & Export
- **As a** user capturing milestones  
  **I want** to save named versions of a tree  
  **So that** I can revisit earlier reasoning.  
  **Acceptance Criteria**:  
  - User can create version snapshots with optional note.  
  - Versions list shows timestamp, note, and restore action.  
  - Restoring replaces current working tree after confirmation.

- **As a** user sharing insights  
  **I want** to export a tree as JSON  
  **So that** I can archive or hand off the structure.  
  **Acceptance Criteria**:  
  - Export includes nodes, relations, validation metadata, and versions.  
  - Download triggers for supported browsers without extra auth.

## Persistence & Resilience
- **As a** user avoiding data loss  
  **I want** autosave or explicit save options  
  **So that** changes are preserved.  
  **Acceptance Criteria**:  
  - Autosave triggers on key interactions (node edit, relation update).  
  - Save status indicator communicates last sync time.  
  - Failures prompt retry and log error.

- **As a** user encountering issues  
  **I want** meaningful error feedback  
  **So that** I can take corrective action.  
  **Acceptance Criteria**:  
  - API errors show human-readable messages.  
  - Debug logs include request details without leaking secrets.
