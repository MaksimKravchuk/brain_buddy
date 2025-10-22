# Troubleshooting

This guide captures common issues surfaced during Phase 5 hardening and how to resolve them quickly.

## 401 Unauthorized
- **Symptom**: Every request returns `401` with `Missing or invalid API key`.
- **Fix**: Ensure the backend exported `BRAIN_BUDDY_API_KEY` and the client sends the matching key. In local dev, set `VITE_API_KEY` (and `VITE_API_KEY_HEADER` if customised) before running `npm run dev`.
- **Verify**: Repeat the request with `curl -H "X-API-Key: <your-key>"`. The response should succeed and include the same `X-Correlation-ID`.

## 404 Tree Not Found
- **Symptom**: Canvas shows a fallback message with a correlation reference and the store stays empty.
- **Fix**: The tree may have been deleted on disk. Check `backend/data/<tree-id>/`. If missing, restore from backups or create a new tree.
- **Prevent**: Keep exports under version control with `GET /trees/{id}/export`.

## Canvas Feels Slow
- **Symptom**: Noticeable lag when manipulating 150+ nodes.
- **Fix**:
  1. Ensure you run the app in development mode so `useGraphProfiler` logs render timings. Profiling output shows `[perf] TreeCanvas: ...` entries in the console.
  2. Confirm the browser isn’t throttled and that React DevTools profiling is disabled.
  3. If degradation persists, capture timings and raise an issue with the export from DevTools Performance tab.

## Backend Error Messages Lack Detail
- **Symptom**: Toasts show `500: Internal Server Error` with no extra context.
- **Fix**: Copy the `ref: <correlation-id>` suffix from the toast and search backend logs for that ID. The log entry includes stack trace details.
- **Prevent**: Keep logging level at INFO or DEBUG when diagnosing issues.

## Tests Fail Locally
- Ensure the virtual environment is activated and run `pip install -e .[dev]` again.
- Clear cached config by deleting any lingering `BRAIN_BUDDY_*` environment variables before running pytest.
- For frontend tests, delete `frontend/node_modules` and reinstall dependencies if Jest fails to find `jsdom`.

## Reporting
- Capture the `X-Correlation-ID`, failing endpoint, payload, and reproduction steps.
- File issues in your team tracker or open a GitHub issue if the repository is public.
- Attach relevant logs and any exported snapshots to speed up triage.
