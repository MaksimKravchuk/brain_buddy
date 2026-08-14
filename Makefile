.PHONY: install-backend install-frontend dev-backend dev-frontend lint-backend lint-frontend test-backend ci-backend test-frontend test-e2e build-frontend ci-frontend validate-ci check-specs install-mobile typecheck-mobile test-mobile integration-mobile build-mobile ci-mobile \
	verify-all verify-backend verify-frontend verify-mobile typecheck-frontend lint-mobile format-backend format-check-backend mutation-backend mutation-frontend \
	mutation-mobile mutation-gate-backend

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

# Report-only over the OBSERVED tier, and it prints the enforced-tier score
# from the same run: the observed scope is a superset, so the number that gates
# pull requests is a filter over these verdicts rather than a second campaign.
mutation-backend:
	cd backend && rm -rf mutants mutation-artifacts && mkdir -p mutation-artifacts
	cd backend && mutmut run || true
	cd backend && mutmut results
	cd backend && mutmut results --all true > mutation-artifacts/mutation-survivors.txt
	python3 scripts/mutation_gate.py summarize-mutmut \
		--results backend/mutation-artifacts/mutation-survivors.txt \
		--enforced backend/mutation-enforced-scope.txt \
		--summary-out backend/mutation-artifacts/enforced-summary.txt \
		--survivors-out backend/mutation-artifacts/enforced-survivors.txt

# Report-only, like mutation-backend: it prints the observed and enforced scores
# and never fails the build on either. Takes ~35 minutes; scope one module with
# `cd frontend && npx stryker run --mutate '<path>'` while iterating.
mutation-frontend:
	cd frontend && rm -rf mutation-artifacts .stryker-tmp reports
	cd frontend && npm run test:mutation || true
	python3 scripts/mutation_gate.py summarize-stryker \
		--report frontend/mutation-artifacts/mutation-report.json \
		--summary-out frontend/mutation-artifacts/observed-summary.txt \
		--survivors-out frontend/mutation-artifacts/observed-survivors.txt
	python3 scripts/mutation_gate.py summarize-stryker \
		--report frontend/mutation-artifacts/mutation-report.json \
		--enforced frontend/mutation-enforced-scope.txt \
		--summary-out frontend/mutation-artifacts/enforced-summary.txt \
		--survivors-out frontend/mutation-artifacts/enforced-survivors.txt

# The ENFORCED-tier measurement (ADR-0016). mutation-backend above measures the
# OBSERVED tier, which deliberately includes modules still under calibration, so
# its score must not be checked against ADR-0004's bar. This target narrows the
# scope to backend/mutation-enforced-scope.txt and asserts the bar with the
# gate's own validator, which is the only way to reproduce the recorded number
# without a hand-edited pyproject.toml.
#
# mutmut takes its scope from the config file rather than the command line, so
# backend/pyproject.toml is rewritten for the duration and restored on exit --
# including on failure or interrupt, hence the trap. mutmut has to run from
# backend/, and that `cd` stays inside a subshell: the trap's paths are relative
# to the repository root, so moving the trapped shell's own directory would make
# the restore silently fail and leave the narrowed scope behind.
mutation-gate-backend:
	@cp backend/pyproject.toml backend/pyproject.toml.mutation-bak
	@trap 'mv backend/pyproject.toml.mutation-bak backend/pyproject.toml; \
	       rm -f backend/.mutation-enforced-changed.txt' EXIT; \
	  sed 's/#.*//' backend/mutation-enforced-scope.txt \
	    | sed '/^[[:space:]]*$$/d' > backend/.mutation-enforced-changed.txt; \
	  python3 scripts/mutation_gate.py scope \
	    --enforced backend/mutation-enforced-scope.txt \
	    --changed backend/.mutation-enforced-changed.txt \
	    --apply-to backend/pyproject.toml; \
	  ( cd backend && rm -rf mutants && { mutmut run || true; } && mutmut export-cicd-stats )
	python3 scripts/mutation_gate.py check --stats backend/mutants/mutmut-cicd-stats.json

validate-ci:
	python3 -m unittest scripts/test_check_requirement_coverage.py -v
	python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py -v
	python3 -m unittest scripts/test_validate_ci_artifacts.py -v
	python3 -m unittest scripts/test_validate_allure_taxonomy.py -v
	python3 -m unittest scripts/test_validate_coverage_floor.py -v
	python3 -m unittest scripts/test_mutation_gate.py -v
	python3 -m unittest scripts/test_validate_trunk_delivery.py -v
	python3 -m unittest scripts/test_extract_staged_feature_flags.py -v
	python3 -m unittest scripts/test_submit_to_trunk.py -v
	python3 -m unittest scripts/test_production_smoke.py -v
	python3 -m unittest scripts/test_capture_fly_release_image.py -v
	python3 -m unittest scripts/test_classify_path_risk.py -v
	python3 -m unittest scripts/test_check_smoke_identity_cohort.py -v
	python3 scripts/validate_ci_artifacts.py workflow --ci .github/workflows/ci.yml --frontend-vite-config frontend/vite.config.ts --disallow-workflow frontend/.github/workflows/playwright.yml
	python3 scripts/validate_ci_artifacts.py mutation-workflow \
		--workflow .github/workflows/mutation-quality.yml \
		--frontend-stryker-config frontend/stryker.config.json \
		--mobile-stryker-config mobile/stryker.config.json
	python3 scripts/validate_ci_artifacts.py coverage-suppressions --path frontend/src --path mobile/src
	python3 scripts/validate_ci_artifacts.py mutation-scope --config frontend/stryker.config.json --enforced frontend/mutation-enforced-scope.txt
	python3 scripts/validate_trunk_delivery.py trunk-ci --ci .github/workflows/ci.yml
	python3 scripts/validate_trunk_delivery.py deploy --workflow .github/workflows/deploy-fly-production.yml

check-specs:
	python3 -m unittest scripts/test_check_spec_kit_specs.py -v
	python3 -m unittest scripts/test_check_speckit_manifests.py -v
	python3 -m unittest scripts/test_check_gate_integrity.py -v
	python3 -m unittest scripts/test_spec_kit_planning_review.py -v
	python3 -m unittest scripts/test_render_feature_report.py -v
	python3 scripts/check_spec_kit_specs.py
	python3 scripts/check_speckit_manifests.py
	python3 scripts/check_gate_integrity.py

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
	python3 scripts/validate_allure_taxonomy.py --path mobile/allure-results --label mobile-jest

# Report-only, like mutation-backend: the deterministic-core scope lives in
# mobile/stryker.config.json and is fixed by ADR-0015.
mutation-mobile:
	cd mobile && rm -rf mutation-artifacts .stryker-tmp reports
	cd mobile && npx stryker run || true
	python3 scripts/mutation_gate.py summarize-stryker \
		--report mobile/mutation-artifacts/mutation-report.json \
		--summary-out mobile/mutation-artifacts/observed-summary.txt \
		--survivors-out mobile/mutation-artifacts/observed-survivors.txt

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
