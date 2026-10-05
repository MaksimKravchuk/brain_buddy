# Allure test taxonomy

BrainBuddy publishes Allure Report 3 evidence from every automated product-test layer:

- backend pytest results in `backend/allure-results`
- frontend Vitest results in `frontend/allure-results/vitest`
- Playwright product E2E results in `frontend/allure-results/playwright`

Every emitted Allure `*-result.json` must include:

1. a non-empty `epic` label,
2. a non-empty `feature` label,
3. a non-empty `story` label,
4. a human-readable result title, and
5. at least one named step.

`scripts/validate_allure_taxonomy.py` validates generated result JSON directly and fails CI when any result is missing this metadata. Run it after the relevant suite, for example:

```bash
python3 scripts/validate_allure_taxonomy.py --path backend/allure-results --label backend-pytest
python3 scripts/validate_allure_taxonomy.py --path frontend/allure-results/vitest --label frontend-vitest
python3 scripts/validate_allure_taxonomy.py --path frontend/allure-results/playwright --label frontend-playwright
```

## Backend pytest

Backend tests are tagged centrally by `backend/tests/allure_taxonomy.py`, applied from `backend/tests/conftest.py`. Add a module-level taxonomy rule there when adding a new backend test module so Allure groups by product capability rather than file mechanics.

Explicit overrides are allowed when a test needs a narrower classification:

```python
import allure

@allure.epic("Reality Tree")
@allure.feature("Tree API")
@allure.story("Import and export")
@allure.title("Export rejects another user's tree")
def test_export_rejects_foreign_tree(api_client):
    ...
```

The central hook fills any missing labels/title and wraps the test body in one named step, so explicit decorators only need to override the dimensions that differ.

## Frontend Vitest

Vitest taxonomy is centralized in `frontend/src/test/allureTaxonomy.ts` and registered in `frontend/vite.config.ts`. Path rules assign `epic`/`feature`, the top `describe` block becomes the `story`, and the test title remains the Allure title.

When a spec needs a more specific label or step, call `allure-js-commons` helpers inside the test body:

```ts
import { feature, story, step } from "allure-js-commons";

it("shows the selected version diff", async () => {
  await feature("Version panel");
  await story("Version diff review");
  await step("Select a historical version", async () => {
    // user-event and assertions
  });
});
```

## Playwright product E2E

Playwright specs must import from `frontend/tests/allure.fixtures.ts`:

```ts
import { expect, test } from "./allure.fixtures";
```

The fixture applies the suite taxonomy and a named scenario step. Add a path rule to that fixture for new product E2E specs; do not add generic sample tests such as Playwright starter examples. Overrides can use `epic()`, `feature()`, `story()`, `displayName()`, and `step()` from `allure-js-commons` inside the test body.
