.PHONY: install-backend install-frontend dev-backend dev-frontend test-backend compose-smoke-up compose-smoke-down compose-smoke-logs

install-backend:
	cd backend && python -m pip install -e .[dev]

install-frontend:
	cd frontend && npm install

dev-backend:
	uvicorn app.main:app --reload --app-dir backend

dev-frontend:
	cd frontend && npm run dev

test-backend:
	cd backend && pytest

compose-smoke-up:
	docker compose -f docker-compose.smoke.yml up --build

compose-smoke-down:
	docker compose -f docker-compose.smoke.yml down --volumes

compose-smoke-logs:
	docker compose -f docker-compose.smoke.yml logs -f
