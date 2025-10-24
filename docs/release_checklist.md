# Release Checklist

This checklist must be completed before tagging a Brain Buddy release candidate and inviting pilot users. Record the run in your PR or release notes.

## Pre-Flight
- [ ] Confirm the target commit is merged into `main` and the CI workflow (`CI`) is green.
- [ ] Review coverage artifacts (`backend-coverage`, `frontend-coverage`) from the latest CI run; investigate any sudden drops.
- [ ] Ensure `.env` contains the desired API key configuration and has been shared with the deployment owner.

## Automated Verification
- [ ] Run `make test-backend` locally (or via CI re-run) and confirm all tests pass.
- [ ] Run `make test-frontend` locally and confirm all tests pass.
- [ ] Execute `scripts/smoke_test.sh` against the compose stack and capture the output in the release notes.

## Build & Packaging
- [ ] Build backend image: `docker build -t brain-buddy-backend:release -f backend/Dockerfile .`
- [ ] Build frontend image: `docker build -t brain-buddy-frontend:release -f frontend/Dockerfile .`
- [ ] Tag images with the release version and push to the registry (if applicable).

## Pilot Dataset
- [ ] Load `docs/pilot_dataset.json` into the target environment:
  ```bash
  python scripts/load_dataset.py docs/pilot_dataset.json --data-dir /path/to/backend/data
  ```
- [ ] Verify `index.json` includes `tree_pilot_onboarding` and the tree appears in the UI.

## Manual QA
- [ ] Walk through the pilot tree: open each node, validate drag/drop, and trigger a mock validation.
- [ ] Export the pilot tree via the UI and confirm the download renders correctly.
- [ ] Toggle API key enforcement (if required) and confirm unauthorized requests return 401.

## Documentation & Comms
- [ ] Update `docs/troubleshooting.md` with any new known issues discovered during QA.
- [ ] Share release notes with stakeholders, including correlation IDs for any tracked issues.
- [ ] Announce availability in the pilot #channel with next steps for testers.

## Post-Release
- [ ] Monitor logs for 30 minutes after pilot sign-on; capture correlation IDs for any errors.
- [ ] Schedule a retro to review feedback and funnel insights into the backlog.
