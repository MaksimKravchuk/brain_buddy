# Brain Buddy Frontend Architecture

## Stack Summary
- **Framework**: React 18 + TypeScript for predictable component model and strong tooling.
- **Build Tooling**: Vite for fast dev server, HMR, and optimized builds.
- **State Management**: Zustand for lightweight global state and undo/redo history; React Query for server cache and mutations.
- **Styling**: Tailwind CSS with design tokens for colors/spacing; Radix UI primitives for accessibility when needed.
- **Graph Canvas**: React Flow to handle nodes/edges, zoom/pan, selection, and custom node/edge renderer.

## High-Level Component Map
```
App
├── Layout
│   ├── TopBar
│   ├── CanvasPanel
│   │   └── CRTCanvas (React Flow)
│   └── SidePanel
│       ├── NodeInspector
│       ├── RelationInspector
│       ├── ValidationPanel
│       └── VersionPanel
├── Modals
│   ├── TreeSelectorModal
│   └── VersionRestoreModal
└── ToastProvider
```

## Key Modules

### 1. State Layer
- **stores/treeStore.ts**  
  - Holds active tree data (nodes, relations, metadata).  
  - Provides actions for CRUD, selection, undo/redo, and autosave triggers.  
  - Uses Immer for immutable updates; includes derived selectors (e.g., related nodes).
- **stores/uiStore.ts**  
  - Manages UI state (panel visibility, modals, hotkey hints).
- **hooks/useTreeApi.ts**  
  - Wraps React Query for data fetching/mutations aligned with backend contracts.

### 2. Canvas Layer
- **components/canvas/CRTCanvas.tsx**  
  - Configures React Flow instance, node/edge types, and event handlers.  
  - Integrates keyboard shortcuts (using `react-hotkeys` or custom hook).  
  - Syncs selection state with store; handles relation creation gestures.
- **components/canvas/nodes/CRTNode.tsx**  
  - Custom node renderer showing label, validation badge, relation count.  
  - Inline edit support (contenteditable or controlled input).  
  - Action buttons (validate, add relation) appear on hover/focus.
- **components/canvas/edges/CRTEdge.tsx**  
  - Custom edge with arrow marker, editable question label, optional notes icon.  
  - Highlight states for upstream/downstream focus.

### 3. Inspector Panels
- **components/inspector/NodeInspector.tsx**  
  - Displays metadata, relations grouped by direction, quick navigation links.  
  - Hosts validation button and feedback area.
- **components/inspector/RelationInspector.tsx**  
  - Allows editing question label, notes, and viewing connected nodes.
- **components/inspector/ValidationPanel.tsx**  
  - Shows history timeline, provider used, confidence trend sparkline.
- **components/inspector/VersionPanel.tsx**  
  - Lists snapshots with restore/export controls.

### 4. Utilities
- **lib/pathUtils.ts**: derive chain root→node.  
- **lib/validationColors.ts**: map confidence to highlight colors.  
- **lib/hotkeys.ts**: centralize keyboard shortcuts and descriptions.  
- **lib/export.ts**: format tree for download using backend endpoint.

## Data Flow
1. User actions mutate Zustand store; optimistic updates show instantly.
2. React Query mutation sends change to backend API (from `api_contracts.md`); on success, store reconciles with authoritative response.
3. Canvas rerenders nodes/edges from store updates; inspector reacts to selection state.
4. AI validation triggers API call; response updates node validation data and history store.

## Undo/Redo Strategy
- `treeStore` maintains history stack sized (e.g., last 50 actions).  
- Each mutating action optionally records diff; undone changes also sync with backend via reload or patch endpoints.  
- Autosave runs after successful backend confirmation to keep file storage consistent.

## Keyboard Shortcuts (Draft)
- `Enter`: create node at cursor.  
- `Cmd/Ctrl + Enter`: trigger validation for selected node.  
- `Delete/Backspace`: delete selected node/relation (with confirm).  
- `Cmd/Ctrl + Z / Shift + Cmd/Ctrl + Z`: undo/redo.  
- `Space + drag`: pan canvas.  
- `Cmd/Ctrl + mouse wheel`: zoom.  
- `Tab`: move selection to next related node.

## Error Handling & Notifications
- Global `ToastProvider` surfaces success or failure messages.  
- API errors use standardized messages; network failures prompt retry with offline indicator.  
- Validation failures include link to logs view (future).

## Testing Approach
- Component tests with Vitest + Testing Library for inspectors and state logic.  
- Cypress component tests for complex canvas interactions (selection, inline edit).  
- Integration tests mocking backend to validate optimistic updates and rollback.
