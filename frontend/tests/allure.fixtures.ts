/**
 * Centralized Allure taxonomy for the Playwright end-to-end suite.
 *
 * Import `test`/`expect` from this module instead of `@playwright/test`. An
 * auto-fixture applies a deterministic epic/feature/story derived from the spec
 * path plus one named step, so every emitted Allure result satisfies the
 * taxonomy gate (`scripts/validate_allure_taxonomy.py`) without per-test
 * boilerplate.
 *
 * A spec can override any dimension by calling `epic()`, `feature()`, `story()`,
 * `displayName()`, or `step()` from `allure-js-commons` inside the test body —
 * those run after this fixture, so the last write wins.
 */
import { expect, test as base } from "@playwright/test";
import { epic, feature, step, story } from "allure-js-commons";

type EpicFeatureStory = { epic: string; feature: string; story: string };

/** Ordered spec-path rules: the first match wins. */
const PATH_RULES: Array<{ match: RegExp } & EpicFeatureStory> = [
  {
    match: /claude-design-shell/,
    epic: "End-to-end journeys",
    feature: "Claude Design task shell",
    story: "Source-faithful task shell & brain dump",
  },
];

const FALLBACK: EpicFeatureStory = {
  epic: "End-to-end journeys",
  feature: "Application shell",
  story: "Critical user journey",
};

const resolveTaxonomy = (filePath: string): EpicFeatureStory => {
  const normalized = filePath.replace(/\\/g, "/");
  for (const rule of PATH_RULES) {
    if (rule.match.test(normalized)) {
      return { epic: rule.epic, feature: rule.feature, story: rule.story };
    }
  }
  return FALLBACK;
};

export const test = base.extend<{ allureTaxonomy: void }>({
  allureTaxonomy: [
    async ({}, use, testInfo) => {
      const meta = resolveTaxonomy(testInfo.file);
      await epic(meta.epic);
      await feature(meta.feature);
      await story(meta.story);
      await step(`Verify: ${testInfo.title}`, async () => {
        /* scenario boundary — assertions run in the test body */
      });
      await use();
    },
    { auto: true },
  ],
});

export { expect };
