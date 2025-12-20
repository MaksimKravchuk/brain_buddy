# Quickstart: Flexible Relation Linking

## Setup
1. Copy `.env.example` to `.env` if using compose; set `BRAIN_BUDDY_API_KEY`/`VITE_API_KEY` together when enforcing keys.
2. Install backend deps:
   ```bash
   cd backend
   python -m venv .venv && source .venv/bin/activate
   pip install -e .[dev]
   ```
3. Install frontend deps:
   ```bash
   cd frontend
   npm install
   ```

## Run
- Backend: `make dev-backend` (FastAPI reload, local file storage under `backend/data`)
- Frontend: `make dev-frontend` (Vite dev server proxied to backend `/api`)

## Validate the Feature
1. Open the app, create two chains of nodes.
2. Link a node from chain A to chain B; confirm direction (cause→effect) and highlight behavior.
3. Attempt self-link/duplicate/cycle; verify inline human-readable error with copyable correlation reference, focus/announcement.
4. Save, reload, and export/import the tree; confirm relations persist with correct direction.
5. Run tests:
   ```bash
   make test-backend
   make test-frontend
   ```
