.PHONY: install-backend install-frontend dev-backend dev-frontend test-backend test-frontend compose-up compose-down compose-logs compose-smoke-up compose-smoke-down compose-smoke-logs local-deploy local-deploy-down

install-backend:
	cd backend && python -m pip install -e .[dev]

install-frontend:
	cd frontend && npm install

dev-backend:
	uvicorn app.main:app --reload --app-dir backend

dev-frontend:
	cd frontend && npm run dev

test-backend:
	docker build --target tests -t brain-buddy-backend-tests -f backend/Dockerfile .
	docker run --rm brain-buddy-backend-tests

test-frontend:
	docker build --target tests -t brain-buddy-frontend-tests -f frontend/Dockerfile .
	docker run --rm brain-buddy-frontend-tests

compose-up:
	docker compose -f docker-compose.local.yml up --build

compose-down:
	docker compose -f docker-compose.local.yml down --volumes

compose-logs:
	docker compose -f docker-compose.local.yml logs -f

compose-smoke-up:
	docker compose -f docker-compose.smoke.yml up --build

compose-smoke-down:
	docker compose -f docker-compose.smoke.yml down --volumes

compose-smoke-logs:
	docker compose -f docker-compose.smoke.yml logs -f

# Local deployment shortcuts (uses smoke stack)
local-deploy:
	docker compose -f docker-compose.smoke.yml up --build

local-deploy-down:
	docker compose -f docker-compose.smoke.yml down --volumes
