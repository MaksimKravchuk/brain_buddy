# Brain Buddy Requirements

## Overview
- Build a web-first Current Reality Tree (CRT) application that supports large, complex trees without sacrificing clarity.
- Empower users who may have no background in Theory of Constraints with an intuitive, clutter-free interface inspired by tools like Miro.
- Augment reasoning by surfacing structural insights, AI-assisted validation, and visual cues instead of adding friction during diagramming.

## Target Users and Goals
- Users: knowledge workers, facilitators, or individuals mapping problems; no prior CRT expertise expected.
- Goals:
  - Capture problems as interconnected nodes and relations quickly.
  - Navigate, inspect, and validate reasoning paths with minimal friction.
  - Export and version trees for later review or collaboration hand-off.

## Platforms
- Initial release targets modern desktop web browsers with responsive behavior that remains usable on tablets.
- Future mobile or native clients can consume the same backend APIs.

## Frontend Requirements
- **Stack**: React + TypeScript + Vite for fast iteration, component modularity, and strong ecosystem support.
- **UI Library**: Tailwind CSS (or Chakra UI) for creating a clean, minimal interface reminiscent of Miro.
- **Graph Layer**: React Flow (preferred) or Konva to provide:
  - Panning/zooming canvas with smooth interactions.
  - Node creation, drag/drop repositioning, and connector drawing.
  - Hotkeys for common actions (node creation, delete, undo/redo, zoom).
- **Core Interactions**:
  - Create, update, and delete nodes with inline editing.
  - Create, update, and delete relations between nodes (directional edges with editable question labels; default `WHY?`).
  - Node inspector side panel with metadata, relation counts, related nodes list, and AI validation button.
  - Visual highlighting based on validation confidence and relation density.
  - Selecting a node highlights all upstream/downstream nodes and displays relation question context.
  - Breadcrumbs or path preview showing the chain from root to selected node.
- **Version & Export UI**:
  - History panel showing saved versions with timestamp and optional notes.
  - Export options for JSON (full tree + metadata).

## Backend Requirements
- **Stack**: Python FastAPI for async-friendly REST APIs and automatic documentation.
- **Responsibilities**:
  - CRUD for trees, nodes, relations, and version snapshots.
  - Trigger AI verification workflows; manage provider selection per user/tree.
  - File-based persistence (JSON files) for MVP stored under a structured directory.
  - Debug-level logging for API calls, validation events, and storage actions.
- **API Endpoints (initial)**:
  - `POST /trees` create tree; `GET /trees` list; `GET /trees/{id}` retrieve; `DELETE /trees/{id}` remove.
  - `POST /trees/{id}/nodes` create node; `PATCH /trees/{id}/nodes/{node_id}` update; `DELETE` remove.
  - `POST /trees/{id}/relations`; `PATCH /trees/{id}/relations/{relation_id}`; `DELETE`.
  - `POST /trees/{id}/validate/{node_id}` trigger AI validation chain.
  - `POST /trees/{id}/versions` snapshot tree; `GET /trees/{id}/versions` list; `GET /versions/{version_id}` retrieve.
  - `GET /trees/{id}/export` download JSON structure.

## AI Verification Workflow
- Collect the path from the highest/root node down to the selected node.
- Construct a prompt describing the chain of reasoning; send to configured AI provider.
- Allow user to choose provider (default OpenAI); store API keys securely (e.g., per-user configuration file or vault in later phases).
- Return:
  - Percentage representing confidence/correctness estimate.
  - Qualitative feedback or suggestions (optional for MVP).
- UI should highlight nodes with high confidence (or potential issues) and display validation history.

## Data Model & Storage
- File-based storage (JSON) organized by tree ID:
  - `tree.json`: nodes, relations, metadata (title, description).
  - `versions/{timestamp}.json`: snapshot history.
  - `config.json`: provider settings (per user or per tree).
- Ensure schema accommodates future migration to relational/graph DB without major API changes.
- Include fields for validation results (confidence, last run timestamp, provider used).
  - Relation structure includes `source_node_id`, `target_node_id`, `question_label` (default `WHY?`), and optional notes (e.g., `node1 <- node2` meaning “node2 explains why node1 happens”).

## Non-Functional Requirements
- **Performance**: Support trees with hundreds of nodes/edges; operations should remain responsive under 200ms latency for core actions on target hardware.
- **Reliability**: Basic error handling on both client and server; log all failed API calls; display meaningful feedback to the user.
- **Security**: Secure API keys in backend; ensure CORS configuration only exposes needed origins; anticipate auth layer integration later.
- **Extensibility**: Modular service layer to add future features (collaboration, analytics, alternative storage backends).
- **Testing & QA**:
  - Backend unit tests for tree operations and AI request formatting (mock providers).
  - Linting/formatting pipelines (ESLint/Prettier, black/ruff).

## Future Considerations (Post-MVP)
- Real-time collaboration (WebSocket layer) for multi-user editing.
- Authentication, user roles, and team spaces.
- Rich exports (PDF, image) using server-side rendering.
- Advanced analyses: automatic conflict detection, dependency suggestions.
- Guided onboarding and tutorials once core interactions are stable.
