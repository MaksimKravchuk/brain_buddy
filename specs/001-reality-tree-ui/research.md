# Research – Current Reality Tree UI

## Decisions and Rationale

### Keyboard-first interactions
- **Decision**: Support quick actions for create node (typed), link selected to parent/child, zoom in/out, center on selection, and open save/import dialogs. Use modifier + key combos that do not conflict with browser defaults (e.g., Cmd/Ctrl+Shift+N for new node, Cmd/Ctrl+Shift+L to link, +/- for zoom, Cmd/Ctrl+Shift+C to center).
- **Rationale**: Mirrors xmind-like speed without breaking standard shortcuts; keeps flows accessible to keyboard users.
- **Alternatives considered**: Single-letter shortcuts (risk clashes with browser find/zoom); context-menu-only workflows (slower, mouse-dependent).

### Node coloring and highlighting
- **Decision**: Distinct colors per type (undesired effect, cause, regular) with intensity changes when a node has 3+ outgoing/upstream relations; brick-red highlight when its reachable set covers all undesired effects. De-emphasize non-path nodes via grayscale fade when a node is selected.
- **Rationale**: Encodes causality strength and scope coverage visually, helping users spot leverage points.
- **Alternatives considered**: Badges instead of colors (less scannable); size scaling (can harm readability).

### JSON import/export schema
- **Decision**: Export/import includes tree metadata (id, name, created/updated), nodes (id, label, type, position), relations (id, from_id, to_id, kind="why"), and styling cues (type-derived colors, highlight flags). Reject malformed/partial files with clear errors and without mutating the current canvas.
- **Rationale**: Ensures lossless round-trips and compatibility with backend storage; avoids silent corruption.
- **Alternatives considered**: Minimal schema without styling (would break color cues); binary/exporting screenshots (not editable).

### Persistence for signed-in users
- **Decision**: Reuse existing backend storage model (file-backed trees with LRU cache) keyed by user/session for cloud saves; signed-out users rely on local download/upload. Save action writes full tree state atomically.
- **Rationale**: Aligns with current infra and avoids introducing new persistence tech during this feature.
- **Alternatives considered**: Introducing database layer now (out of scope); client-only localStorage (insufficient for multi-device access).

### AI feedback flow
- **Decision**: Convert tree into ordered chains from causes to undesired effects, include node labels/types and relation directions, and send as a prompt for analysis; surface progress and error toasts; return summary plus recommendations.
- **Rationale**: Keeps AI guidance grounded in user-provided structure; matches spec expectation of chain-of-thought feedback.
- **Alternatives considered**: Per-node suggestions only (less holistic); free-form chat (adds scope without benefit).

### Docker Compose stack for local deploy
- **Decision**: Provide a compose file that builds backend and frontend images, runs backend on 8000 with data volume mount, serves frontend via dev server or nginx proxy, and wires optional API key/env variables from `.env`. Use `docker compose up --build` / `docker compose down --volumes` and reuse `./scripts/smoke_test.sh` for verification.
- **Rationale**: Keeps onboarding minimal while matching existing smoke workflow; preserves local data across runs via volume.
- **Alternatives considered**: Separate compose for prod vs dev (unneeded now); bundling frontend into nginx-only image (can be added later if required).
