.PHONY: install-backend install-frontend dev-backend dev-frontend test-backend test-frontend check-specs

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

check-specs:
	python3 scripts/check_spec_kit_specs.py
