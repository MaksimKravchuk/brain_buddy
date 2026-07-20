.PHONY: install-backend install-frontend dev-backend dev-frontend lint-backend lint-frontend test-backend ci-backend test-frontend test-e2e build-frontend ci-frontend validate-ci check-specs generate-openapi check-api-contract generate-mobile-api

install-backend:
	cd backend && python -m pip install -e .[dev]

install-frontend:
	cd frontend && npm install

dev-backend:
	uvicorn app.main:app --reload --app-dir backend

dev-frontend:
	cd frontend && npm run dev

test-backend:
	cd backend && pytest --cov=app --cov-report=term --cov-report=xml --alluredir=allure-results
	python3 scripts/validate_backend_coverage.py backend/coverage.xml
	python3 scripts/validate_allure_taxonomy.py --path backend/allure-results --label backend-pytest

lint-backend:
	cd backend && ruff check app tests
	cd backend && mypy app

ci-backend: lint-backend test-backend

test-frontend:
	cd frontend && npm run test:coverage
	python3 scripts/validate_allure_taxonomy.py --path frontend/allure-results/vitest --label frontend-vitest

test-e2e:
	./scripts/run_playwright_e2e.sh
	python3 scripts/validate_ci_artifacts.py results --path frontend/allure-results/playwright --label playwright-e2e --since-file frontend/allure-results/playwright/.run-started-at
	python3 scripts/validate_allure_taxonomy.py --path frontend/allure-results/playwright --label playwright-e2e
	python3 scripts/validate_ci_artifacts.py product-e2e-results --path frontend/allure-results/playwright

lint-frontend:
	cd frontend && npm run lint

build-frontend:
	cd frontend && npm run build

ci-frontend: lint-frontend test-frontend build-frontend

validate-ci:
	python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py -v
	python3 -m unittest scripts/test_validate_ci_artifacts.py -v
	python3 -m unittest scripts/test_validate_allure_taxonomy.py -v
	python3 scripts/validate_ci_artifacts.py workflow --ci .github/workflows/ci.yml --frontend-vite-config frontend/vite.config.ts --disallow-workflow frontend/.github/workflows/playwright.yml
	python3 scripts/validate_ci_artifacts.py mutation-workflow --workflow .github/workflows/mutation-quality.yml

check-specs:
	python3 -m unittest scripts/test_check_spec_kit_specs.py -v
	python3 scripts/check_spec_kit_specs.py

generate-openapi:
	cd backend && uv run python3 ../scripts/generate_openapi.py

check-api-contract:
	cd backend && uv run python3 ../scripts/generate_openapi.py --check

generate-mobile-api:
	bash mobile/scripts/generate-api.sh
