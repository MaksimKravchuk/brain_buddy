# Brain Buddy Backend

FastAPI service providing CRUD, validation, and versioning APIs for the Brain Buddy knowledge graph. Refer to the project root README for setup instructions.

## Configuration

Environment variables allow you to tailor local behavior:

- `BRAIN_BUDDY_ENV` – runtime environment flag (`development`, `production`, or `test`). Defaults to `development`.
- `BRAIN_BUDDY_DATA_DIR` – filesystem location for tree data and metadata. Defaults to `<repo>/backend/data`.
- `BRAIN_BUDDY_LOG_LEVEL` – root log level (`INFO` by default).
- `BRAIN_BUDDY_API_PREFIX` – base path for the public API (`/api` by default).

Place these in a `.env` file or export them before starting the server. The active configuration is cached and exposed via `app.state.config`.

## Running Tests in Docker

Build the dedicated test image and execute the pytest suite from the repository root:

```bash
docker build --target tests -t brain-buddy-backend-tests -f backend/Dockerfile .
docker run --rm brain-buddy-backend-tests
```

The image installs the backend along with its development dependencies and sets `BRAIN_BUDDY_ENV=test` by default, so the container exits with the pytest status code.
