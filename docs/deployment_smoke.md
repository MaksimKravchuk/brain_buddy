# Local Smoke Test Deployment

Use this guide to spin up the Brain Buddy stack locally using Docker Compose for smoke testing or stakeholder demos.

## Prerequisites

- Docker Engine + Docker Compose Plugin (`docker compose version` should succeed).
- Python 3.11 and Node.js 18 remain required for local development, but not for the containerized stack.
- Optional: `jq` to pretty-print JSON when running the smoke test script.

## Setup

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```
   Adjust values as needed (leave `BRAIN_BUDDY_API_KEY` unset for open access, or set it alongside `VITE_API_KEY` for protected runs).

2. Build and start the containers:
   ```bash
   make compose-smoke-up
   ```
   This boots the FastAPI backend on `http://localhost:8000` and the frontend on `http://localhost:8080`. Docker will mount a named volume for persistence so your manual edits survive container restarts.

3. When you're done testing, stop the stack:
   ```bash
   make compose-smoke-down
   ```
   Include `--volumes` (already wired into the target) if you want to drop stored data and restart fresh later.

4. (Optional) Load the pilot dataset into the local volume:
   ```bash
   python scripts/load_dataset.py docs/pilot_dataset.json --data-dir backend/data
   ```
   This seeds a sample tree (`tree_pilot_onboarding`) so you can immediately explore canvas interactions.

## Smoke Test Script

Run the automated smoke probe once the stack is up to confirm the API is healthy:

```bash
scripts/smoke_test.sh
```

The script performs:

- `GET /health` to ensure the backend responds.
- `GET /trees` expecting an empty list on a clean volume.
- `POST /trees` to create a temporary graph.
- `DELETE /trees/{id}` to clean up.

If you enabled API key authentication, export `BRAIN_BUDDY_API_KEY` (and optionally `BRAIN_BUDDY_API_KEY_HEADER`) before invoking the script so it passes the header.

## Manual Verification Checklist

- Navigate to `http://localhost:8080` and create/edit a tree; confirm changes persist after page reload.
- Validate a node using the mock provider; check toast messaging and backend logs.
- Export a tree to confirm download flows through the frontend proxy.

## Troubleshooting

- **Health check failures**: run `make compose-smoke-logs` to tail service logs; restart with `make compose-smoke-down` followed by `make compose-smoke-up`.
- **Missing Docker**: install Docker Desktop or `docker` + `docker-compose-plugin` for your platform.
- **API key mismatches**: ensure both backend (`BRAIN_BUDDY_API_KEY`) and frontend (`VITE_API_KEY`) values match in `.env` before rebuilding.
