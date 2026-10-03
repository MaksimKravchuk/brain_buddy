# Local development

This is the smallest supported host-based setup for the backend and web frontend. It keeps dependencies inside the checkout and uses the same runtime versions as CI.

## Prerequisites

Install these with your preferred user-scoped runtime manager:

- Python 3.11 with the `venv` module (selected by the repository `.python-version`)
- Node.js 20.19.0 for `frontend/` (selected by `frontend/.nvmrc`)
- nvm, available to the shell
- npm
- GNU Make

The mobile client is optional and uses Node.js 22.13.1 from `mobile/.nvmrc`, because Expo SDK 57 requires Node.js 22.13.x or newer.

The version files are guidance, not installers. For example, `pyenv` reads `.python-version`, while the required `nvm use` reads the `.nvmrc` in the current directory.

## Install

From the repository root:

```bash
python3 --version  # 3.11.x
python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -e 'backend[dev]'

cd frontend
nvm use
npm ci
cd ..
```

Do not add provider keys for the default local path. AI providers and externally relayed agents stay disabled without credentials.

## Run the web stack

Use two terminals from the repository root.

Terminal 1:

```bash
source backend/.venv/bin/activate
make dev-backend
```

Terminal 2:

```bash
cd frontend
nvm use
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to the backend at `http://localhost:8000`, preserving the same-origin cookie flow.

Signup is invite-gated. In a third terminal with the backend environment active:

```bash
source backend/.venv/bin/activate
cd backend
python -m app.cli create-invite
```

The printed invite is local data. Do not commit it.

## Verify

Run the smallest checks for the stack you changed:

```bash
source backend/.venv/bin/activate
make lint-backend test-backend

cd frontend
nvm use
npm run lint
npm run typecheck
npm run test:coverage
npm run build
```

Before reporting a repository change done, follow `AGENTS.md`; its required gates are broader than this startup check.

## Optional mobile setup

```bash
cd mobile
nvm use
npm ci
npm start
```

Native iOS/Android execution still requires the corresponding Expo/device host prerequisites; this repository does not install or modify them.
