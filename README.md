# Brain Buddy

Brain Buddy is a knowledge graph workspace that helps learners map out complex topics, validate understanding with AI prompts, and capture versioned progress snapshots.

## Repository Layout

- `backend/` – FastAPI application exposing the Brain Buddy API.
- `frontend/` – Vite React client for the interactive canvas and inspector.
- `requirements/` – Product requirements, contracts, and implementation plan.

## Getting Started

### Backend

1. Create and activate a Python 3.11 virtual environment.
2. Install dependencies:

   ```bash
   cd backend
   pip install -e .[dev]
   ```

3. Run the development server:

   ```bash
   uvicorn app.main:app --reload
   ```

4. Execute tests:

   ```bash
   pytest
   ```

### Frontend

1. Install Node.js 18+.
2. Install dependencies:

   ```bash
   cd frontend
   npm install
   ```

3. Start the development server:

   ```bash
   npm run dev
   ```

The frontend dev server runs on `http://localhost:5173` and expects the backend to be available at `http://localhost:8000`.

## Development Tooling

- Formatting and linting are configured via Black, Ruff, and Mypy on the backend.
- Tailwind CSS powers the frontend design system, with class-variance-authority for primitives.
- React Query manages data fetching and caching.

Refer to `requirements/implementation_plan.md` for the phased delivery roadmap.
