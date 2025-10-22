# Brain Buddy Implementation Plan

## Phase 0 – Project Setup
- **Backend scaffold**
  - Initialize FastAPI project (`backend/app`) with `pyproject.toml`, dependencies (fastapi, uvicorn, pydantic, httpx, python-dotenv, typer for scripts, pytest).
  - Configure linting/formatting (black, ruff, mypy minimal config).
- **Frontend scaffold**
  - Bootstrap Vite React + TypeScript app (`frontend/`).
  - Install core libraries (react-flow, zustand, @tanstack/react-query, tailwindcss, postcss/autoprefixer, class-variance-authority optional).
- **Repo infrastructure**
  - Add top-level README summarizing architecture.
  - Configure `.editorconfig`, `.gitignore`, pre-commit hooks (optional).
  - Set up root Makefile or npm scripts to run backend/frontend/dev server.

## Phase 1 – Backend MVP Foundations
1. **Configuration & core utilities**
   - Implement `core/config.py`, `core/logging.py`, `utils/file_ops.py`, `utils/time.py`.
   - Establish data directory structure (`data/`) with `schema_version`.
2. **Schema definitions**
   - Create Pydantic models for trees, nodes, relations, versions, validation DTOs, error responses.
3. **Repositories (filesystem)**
   - Implement `TreeRepository`, `VersionRepository`, `ValidationRepository`, `ProviderRepository`, `IndexRepository`.
   - Ensure atomic writes and index sync.
4. **Services**
   - Build `TreeService`, `NodeService`, `RelationService` with validation (e.g., no duplicate IDs, directional integrity).
   - Add `VersionService` for snapshot/save/restore.
5. **API routers**
   - Wire CRUD endpoints for trees, nodes, relations, versions using services.
   - Implement unified error handling middleware; return JSON per contract.
6. **Testing**
   - Unit tests for repositories/services using temp directories or pyfakefs.
   - API tests with FastAPI TestClient covering happy paths and validation errors.

## Phase 2 – Frontend MVP Foundations
1. **Design system & layout**
   - Configure Tailwind theme, global styles, base layout components (`Layout`, `TopBar`, `SidePanel`).
2. **State management**
   - Implement `treeStore` (Zustand) with initial node/relation structures, undo stack, selection state.
   - Add `uiStore` for panel toggles and modals.
3. **API client**
   - Create `api/client.ts` with base axios/http wrapper or Fetch helper.
   - Implement hooks via React Query (`useTrees`, `useMutateNode`, etc.) matching backend contracts.
4. **Canvas integration**
   - Set up React Flow provider (`CRTCanvas`), custom node and edge components with inline editing scaffolding.
   - Implement node creation, selection, drag, delete; relation creation and editing.
5. **Inspector panels**
   - Build `NodeInspector`, `RelationInspector` showing metadata, related nodes, counts.
   - Display highlight states based on relation density placeholders.
6. **Version/export UI**
   - Add `VersionPanel` listing snapshots (stub actions until backend ready).
7. **Notifications & error handling**
   - Integrate toast system; surface API errors from React Query.
8. **Testing**
   - Vitest component tests for stores and inspectors.
   - Cypress component/integration for canvas interactions (where feasible).

## Phase 3 – AI Validation Integration
1. **Prompt builder & provider adapters**
   - Implement `ai/prompts/validation_prompt.py` using template from requirements.
   - Build `OpenAIProvider`; add provider registry with fallback.
2. **Validation service flow**
   - Complete `ValidationService` to assemble chain, call provider, parse response, store results.
3. **API endpoints**
   - Implement `POST /trees/{id}/validate/{node_id}` and validation history route.
   - Add rate limiting throttle (simple in-memory counter for MVP).
4. **Frontend integration**
   - Hook validation button to call API; update node validation state, highlight node.
   - Show validation history timeline and suggested questions in inspector.
5. **Testing**
   - Mock provider responses to test service/endpoint behavior.
   - Frontend integration tests to ensure validation workflow updates UI.

## Phase 4 – Versioning & Export Completion
- Finalize backend version snapshot logic, restore endpoints, JSON export.
- Connect frontend version panel actions (create, restore, view notes).
- Implement export download flow with progress feedback.
- Add regression tests around version restore (ensuring nodes/relations restored accurately).

## Phase 5 – Hardening & Polish
- **Performance tuning**: profile large tree operations (100–200 nodes) on canvas and repository load times.
- **Error UX**: ensure friendly messages, add retry options, log correlation IDs.
- **Access control prep**: stub auth middleware to make future expansion easier.
- **Documentation**: update README, add API docs (OpenAPI link), developer setup steps, and contribution guide.

## Phase 6 – Deployment Readiness
- Create Dockerfiles for backend and frontend; docker-compose for local dev.
- Configure environment templates (`.env.example` for API keys, data paths).
- Set up CI pipelines (GitHub Actions) running lint, tests, build steps.
- Prepare initial release checklist (tag, changelog, deployment instructions).

## Risk & Dependency Notes
- **Graph library**: validate React Flow licensing/limits; keep Konva fallback in mind.
- **AI provider**: confirm API access/budget; design provider interface to handle offline mode gracefully.
- **Filesystem concurrency**: consider locking mechanism if multi-user backend access is expected; for MVP single-user assumption is acceptable.
- **Undo/redo vs backend sync**: ensure reconciliation logic handles failed API calls by rolling back state.

## Suggested Milestones
1. **M1 – CRUD Backbone**: Backend CRUD + Frontend canvas basic editing synced.  
2. **M2 – Validation Alpha**: AI validation end-to-end with mocked provider.  
3. **M3 – Versioning Beta**: Snapshot/restore/export functional, initial testers onboarded.  
4. **M4 – Release Candidate**: Performance tuned, docs complete, deployment pipeline ready.
