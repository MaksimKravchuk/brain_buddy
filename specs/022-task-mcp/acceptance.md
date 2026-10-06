# Candidate acceptance

Implementation source is in `feat/task-mcp`, based on `afaa820`. This records
observed local evidence, not independent approval or production release.

## Passing evidence

- Targeted MCP suite: **18 passed**. The official SDK performs initialization,
  discovery, creation, reading, cancellation and active-list read-back. Other
  cases cover requirements 022-FR-002 through 022-FR-007.
- Real HTTP smoke: Uvicorn plus the official Streamable HTTP client passed
  create/cancel/list and logout revocation with a custom `/custom-api` prefix.
  Synthetic data lived in a temporary directory that was removed after shutdown.
- `make verify-all` completed repository/spec/CI validations and backend lint,
  Black, mypy and all five import-layer contracts.
- Backend: **3690 passed**; coverage **98.14%**, branch **95.97%**, line **98.65%**.
  Both the coverage-floor and Allure taxonomy gates passed.
- Frontend: **66 files / 1639 tests passed**; branch coverage **97.90%**, line
  **99.49%**. Lint, typecheck, production build, coverage-floor and Allure taxonomy
  gates passed. Frontend source is unchanged.
- Docker/nginx MCP smoke: the official SDK passed discovery, create/replay,
  cancellation, active-list cleanup and logout revocation through the existing
  frontend proxy. MCP was enabled alongside normal background maintenance.
- Compose/Playwright: **65 passed**, with the repository's one pre-existing
  `test.fixme` vNext proposal placeholder skipped. All executable journeys and
  Playwright product-result/Allure taxonomy gates passed. The temporary stack
  and its data volume were removed by the runner's cleanup trap.
- Requirement coverage: **10/10** feature requirements/success criteria traced.
  The 18 MCP tests were rerun after adding success-criterion trace labels; their
  separate Allure taxonomy check passed.

## Pending

- Independent review and authorized exact-SHA landing/release are deferred.
- Production MCP exposure, external GPT provider execution and authenticated
  production smoke have not been performed; the endpoint is not claimed live.

Rendered web/iOS/macOS design acceptance is N/A: this change adds backend MCP tools
without changing those clients. No database migration, irreversible task erasure
or new persistent credential is introduced. OFF removes exposure and preserves data.

## Environment adaptation

The initial `make verify-all` invocation reached Docker and stopped at PyPI TLS
verification: the nested containers did not inherit this managed environment's
proxy CA. Rebuilt the same source using temporary Dockerfiles outside the repo
with a BuildKit-mounted CA and pip/npm trust settings, retaining TLS verification.
The E2E runner uses those exact local image tags through its supported
`BRAIN_BUDDY_E2E_BUILD_IMAGES=0` path. Repository Dockerfiles/CI are unchanged.

The first browser run also hit the managed proxy when the existing A2A client
requested the local Hermes fixture's pinned IP (503 through the proxy versus 200
over the local Compose network). A temporary Compose override preserves inherited
proxy settings and adds only the fixture's local IP/isolated network to NO_PROXY.
The repeated Hermes discovery, hand-off and replay cases passed after this
environment correction. No relay/application networking code was changed.
