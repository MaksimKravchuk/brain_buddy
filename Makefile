.PHONY: install-backend install-frontend dev-backend dev-frontend lint-backend lint-frontend test-backend ci-backend test-frontend test-e2e build-frontend ci-frontend validate-ci check-specs install-mobile typecheck-mobile test-mobile integration-mobile build-mobile ci-mobile \
	verify-all verify-backend verify-frontend verify-mobile typecheck-frontend lint-mobile format-backend format-check-backend mutation-backend

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
	python3 scripts/validate_coverage_floor.py --stack backend --format cobertura \
		--report backend/coverage.xml --floor backend/coverage-floor.json
	python3 scripts/validate_allure_taxonomy.py --path backend/allure-results --label backend-pytest

lint-backend:
	cd backend && ruff check app tests
	cd backend && black --check app tests
	cd backend && mypy app
	cd backend && lint-imports

# Black is the documented formatter (CLAUDE.md: "Black 88-col + Ruff"). The
# backlog that once kept it out of lint-backend is gone -- the tree was
# reformatted in one mechanical commit -- so `black --check` now gates there and
# in CI. Use format-backend to fix a file rather than hand-wrapping it.
format-backend:
	cd backend && black app tests

format-check-backend:
	cd backend && black --check app tests

ci-backend: lint-backend test-backend

test-frontend:
	cd frontend && npm run test:coverage
	python3 scripts/validate_coverage_floor.py --stack frontend --format istanbul-summary \
		--report frontend/coverage/coverage-summary.json --floor frontend/coverage-floor.json
	python3 scripts/validate_allure_taxonomy.py --path frontend/allure-results/vitest --label frontend-vitest

test-e2e:
	./scripts/run_playwright_e2e.sh
	python3 scripts/validate_ci_artifacts.py results --path frontend/allure-results/playwright --label playwright-e2e --since-file frontend/allure-results/playwright/.run-started-at
	python3 scripts/validate_allure_taxonomy.py --path frontend/allure-results/playwright --label playwright-e2e
	python3 scripts/validate_ci_artifacts.py product-e2e-results --path frontend/allure-results/playwright

lint-frontend:
	cd frontend && npm run lint

typecheck-frontend:
	cd frontend && npx tsc --noEmit

build-frontend:
	cd frontend && npm run build

ci-frontend: lint-frontend typecheck-frontend test-frontend build-frontend

mutation-backend:
	cd backend && rm -rf mutants mutation-artifacts
	cd backend && mutmut run || true
	cd backend && mutmut results

validate-ci:
	python3 -m unittest scripts/test_check_requirement_coverage.py -v
	python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py -v
	python3 -m unittest scripts/test_validate_ci_artifacts.py -v
	python3 -m unittest scripts/test_validate_allure_taxonomy.py -v
	python3 -m unittest scripts/test_validate_coverage_floor.py -v
	python3 -m unittest scripts/test_mutation_gate.py -v
	python3 -m unittest scripts/test_validate_trunk_delivery.py -v
	python3 -m unittest scripts/test_submit_to_trunk.py -v
	python3 -m unittest scripts/test_production_smoke.py -v
	python3 -m unittest scripts/test_capture_fly_release_image.py -v
	python3 -m unittest scripts/test_classify_path_risk.py -v
	python3 -m unittest scripts/test_check_smoke_identity_cohort.py -v
	python3 scripts/validate_ci_artifacts.py workflow --ci .github/workflows/ci.yml --frontend-vite-config frontend/vite.config.ts --disallow-workflow frontend/.github/workflows/playwright.yml
	python3 scripts/validate_ci_artifacts.py mutation-workflow --workflow .github/workflows/mutation-quality.yml
	python3 scripts/validate_trunk_delivery.py trunk-ci --ci .github/workflows/ci.yml
	python3 scripts/validate_trunk_delivery.py deploy --workflow .github/workflows/deploy-fly-production.yml

check-specs:
	python3 -m unittest scripts/test_check_spec_kit_specs.py -v
	python3 -m unittest scripts/test_check_speckit_manifests.py -v
	python3 -m unittest scripts/test_spec_kit_planning_review.py -v
	python3 scripts/check_spec_kit_specs.py
	python3 scripts/check_speckit_manifests.py

# --- Mobile (Expo / React Native, mobile/) ---

install-mobile:
	cd mobile && npm install

typecheck-mobile:
	cd mobile && npx tsc --noEmit

lint-mobile:
	cd mobile && npx eslint .

test-mobile:
	cd mobile && npx jest --coverage
	python3 scripts/validate_coverage_floor.py --stack mobile --format istanbul-summary \
		--report mobile/coverage/coverage-summary.json --floor mobile/coverage-floor.json

# Boots its own disposable backend (requires backend deps: make install-backend)
integration-mobile:
	cd mobile && npm run integration

build-mobile:
	cd mobile && npx expo export --platform ios

# Includes integration-mobile: the CI mobile job runs it, and omitting it here
# let a locally-green change still fail CI. Requires make install-backend —
# the integration harness boots its own disposable backend.
ci-mobile: typecheck-mobile lint-mobile test-mobile integration-mobile build-mobile

# --- Aggregate verification (mirrors the CI job graph) ---

verify-backend: ci-backend

verify-frontend: ci-frontend

verify-mobile: ci-mobile

# The chain an implementation or verification agent runs before reporting done.
# Prerequisites the individual targets do not install:
#   make install-backend                                       (integration-mobile)
#   cd frontend && npx playwright install --with-deps chromium (test-e2e)
verify-all: check-specs validate-ci verify-backend verify-frontend verify-mobile test-e2e
