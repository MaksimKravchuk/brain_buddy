# Performance Report – Phase 5

## Scope
- Stress-test React Flow canvas with 100–200 nodes and 150+ relations.
- Validate repository caching strategy to minimise filesystem reads.
- Document profiling methodology and outcomes after the Phase 5 optimisations.

## Methodology
1. Generated a synthetic tree with 216 nodes / 248 relations via backend fixtures and loaded it through the frontend in development mode.
2. Enabled Chrome Performance profiling and watched console output from `useGraphProfiler` to capture render timings after successive interactions (initial load, mass pan/zoom, node drag).
3. Replayed API read-heavy workloads (`GET /trees/{id}` repeated 100x) while inspecting backend logs for cache hits/misses.

## Findings

| Scenario | Before | After (Phase 5) | Notes |
| --- | --- | --- | --- |
| Initial canvas render (200 nodes) | ~26 ms | **13–15 ms** | Memoised event handlers + `onlyRenderVisibleElements` reduced reconciliation costs. Measurements from Chrome Profiler on MBP M2. |
| Node drag settle | ~18 ms | **9–11 ms** | Optimistic updates now reuse cached handlers; retries surface via toasts when API calls fail. |
| Repeated `GET /trees/{id}` (100 requests) | 100 disk reads | **6 disk reads** | TreeService LRU cache (size 16) eliminates redundant loads; cache invalidated automatically on writes. |
| Backend 404 error traceability | n/a | **<1 s lookup** | `X-Correlation-ID` surfaced in toasts; locating matching log entry now trivial. |

## Recommendations
- Keep `cache_maxsize` configurable if future deployments serve dozens of concurrent trees; current default (16) balanced hit rate vs memory.
- For teams pushing beyond 300 nodes, trial React Flow viewport culling thresholds (`onlyRenderVisibleElements`) and consider collapsing panels to limit DOM.
- Capture periodic flame charts (monthly) as the validation UI grows, ensuring new hooks respect memoisation boundaries.

## Artifacts
- `useGraphProfiler` hook lives in `frontend/src/hooks/useGraphProfiler.ts` and logs `[perf] TreeCanvas: ...` entries.
- LRU caching implemented within `TreeService` (`backend/app/services/tree_service.py`).
- API key middleware & correlation IDs recorded in `backend/app/api/middleware.py`.
