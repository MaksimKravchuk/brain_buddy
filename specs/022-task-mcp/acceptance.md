# Candidate acceptance

Implementation source is in `feat/task-mcp`, based on `afaa820`. The initial
evidence below applies to `9f0d992`; follow-up evidence is recorded separately.
This records observed checks, not independent approval or production release.

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

Native iOS/macOS design acceptance is N/A. The follow-up adds the new row to the
existing generic web Admin Portal and updates the Privacy Policy's flag count;
their existing browser journeys are part of candidate validation. Production
rendering remains pending with release. No task-schema migration, irreversible
task erasure or new persistent credential is introduced. The runtime inventory
upgrade adds only a default-OFF row. OFF removes exposure and preserves data.

## PR babysitting follow-up

Existing review findings and the owner-directed review deferral are recorded in
[review-disposition.md](review-disposition.md).

- MCP wire suite plus the two changed aggregate-log contracts: **23 passed**;
  separate Allure taxonomy passed. Audience exclusion, selected-account admission,
  immediate removal, degraded-store denial, transport-disabled member projection
  and revocation between authentication and command execution are covered.
- Fresh/five-row runtime inventory upgrade is covered with preservation of earlier
  modes/cohorts; the full suite exercises earlier supported upgrades too.
- Clean Python 3.11 `uv sync --frozen` plus backend import passed. The same frozen
  environment completed a real HTTP SDK roundtrip with create replay, cancellation,
  native-list read-back, operator API cohort enable/remove and logout revocation.
  Synthetic state was removed after server shutdown.
- Frontend: **1639 passed**, with lint, types, build, coverage floor and Allure
  taxonomy passing. Branch **97.90%**, line **99.49%**.
- Full backend: **3699 passed**; total coverage **98.14%**, floor branch **95.97%**,
  line **98.65%**. Lint, formatting, types, all five architecture contracts,
  coverage floor and Allure taxonomy passed. Spec/repository/CI validations passed.
- Rebuilt current backend/frontend images and reran Compose/Playwright: **65
  passed**, one existing `test.fixme` skipped, product-result and Allure gates
  passed. The runner removed the isolated stack and volume. The same CA and
  local-fixture NO_PROXY adaptations described below were used outside the repo.
- Secret guardrail suite: **26 passed**. The pinned Gitleaks binary scans the
  original PR commit range with zero findings using the two exact fixture-line
  exceptions. No path/field-wide exemption was added.

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
