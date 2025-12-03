# Quickstart – Current Reality Tree UI

1) Start services  
- Backend: `cd backend && uvicorn app.main:app --reload` (ensure env vars from `.env.example` are set as needed).  
- Frontend: `cd frontend && npm install && npm run dev`.

2) Create a tree  
- Use the tree menu to start a new tree and name it.  
- Add undesired effect, cause, and regular nodes via keyboard shortcuts or toolbar.  
- Link nodes with directional "why" relations (bottom-to-top); verify arrows render.

3) Navigate and highlight  
- Zoom in/out and center on the selected node; confirm selected paths highlight while others fade.  
- Add multiple upstream relations to a cause and observe color intensify; when it spans all undesired effects it highlights brick red.

4) Save and exchange  
- Save the tree (signed-in: stored in account; signed-out: download JSON).  
- Re-import the downloaded JSON into a fresh session and confirm structure/colors match.

5) AI feedback (signed-in)  
- With a populated tree, request AI analysis.  
- Confirm you receive a summary and recommendations; on failure, verify error/ retry messaging and no data loss.

6) Run via Docker Compose (local stack)  
- Copy `.env.example` to `.env` and set optional `BRAIN_BUDDY_API_KEY`/`VITE_API_KEY` if needed.  
- From repo root: `make compose-smoke-up` to build and start backend/frontend.  
- Access UI at `http://localhost:8080` and API at `http://localhost:8000/api`.  
- Run `./scripts/smoke_test.sh` to validate core endpoints.  
- Tear down with `make compose-smoke-down`; data persists in the mounted volume.
