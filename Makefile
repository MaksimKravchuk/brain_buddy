.PHONY: install-backend install-frontend dev-backend dev-frontend test-backend

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
