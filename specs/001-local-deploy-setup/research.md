# Research: Local Deployment Setup

## Decision: Use Docker Compose for end-to-end local deployment
- **Rationale**: Mirrors the consolidated compose stack (`compose.yaml`) and keeps backend/frontend parity with production-like networking. Simplifies port mapping and volume management for file-backed tree data.
- **Alternatives considered**: Standalone uvicorn + Vite dev servers (faster startup but diverges from composed stack networking); Kubernetes local (minikube/kind) adds overhead without need; pure mocks (no backend) fail to validate integration.

## Decision: Provide `.env.example`-driven configuration for local runs
- **Rationale**: Constitution requires env updates alongside behavior; a template ensures required variables and safe defaults are discoverable. Reduces setup errors for missing secrets and aligns with compose env loading.
- **Alternatives considered**: Inline env in docs (risks drift and secret leakage); interactive prompts (heavier UX, not needed for small variable set); bundling real secrets (disallowed).

## Decision: Refresh workflow uses `docker compose` rebuild/restart plus incremental frontend/backend commands when faster
- **Rationale**: Compose rebuild keeps parity; targeted `make dev-backend` / `make dev-frontend` pathways allow quicker iteration within 5-minute budget. Documenting both enables developers to choose speed vs fidelity.
- **Alternatives considered**: Always full rebuild (too slow); hot-reload only via dev servers (misses compose-specific config, risks mismatch).

## Decision: Health validation via smoke script and service endpoints
- **Rationale**: `./scripts/smoke_test.sh` already exercises core API; pairing with simple HTTP checks for frontend and backend ensures deterministic pass/fail and maps to success criteria.
- **Alternatives considered**: Manual browser-only checks (not repeatable); adding new bespoke probe scripts (duplicative with smoke test).

## Decision: Troubleshooting playbook prioritizes env conflicts and stale artifacts
- **Rationale**: Spec edge cases cite port conflicts, missing env, stale volumes/caches. Playbook will include port scan hints, volume/cache purge, and reset commands to restore known-good state.
- **Alternatives considered**: Assuming clean hosts (unrealistic); automated full teardown on every run (wastes time, not needed when incremental refresh works).
