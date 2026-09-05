/**
 * Centralized Allure taxonomy for the Playwright end-to-end suite.
 *
 * Import `test`/`expect` from this module instead of `@playwright/test`. An
 * auto-fixture applies a deterministic epic/feature/story derived from the spec
 * path, so every emitted Allure result has product taxonomy without per-test
 * boilerplate. It intentionally does not create a placeholder step: real
 * Playwright actions/assertions must provide the scenario evidence.
 *
 * A spec can override any dimension by calling `epic()`, `feature()`, `story()`,
 * `displayName()`, or `step()` from `allure-js-commons` inside the test body —
 * those run after this fixture, so the last write wins.
 */
import { expect, test as base } from "@playwright/test";
import { epic, feature, story } from "allure-js-commons";

type EpicFeatureStory = { epic: string; feature: string; story: string };

/** Ordered spec-path rules: the first match wins. */
const PATH_RULES: Array<{ match: RegExp } & EpicFeatureStory> = [
  {
    match: /e2e\/account/,
    epic: "End-to-end journeys",
    feature: "Account & data rights",
    story: "Profile, export, and deletion lifecycle",
  },
  {
    match: /e2e\/agents/,
    epic: "End-to-end journeys",
    feature: "External agent relay",
    story: "Connect an agent and gate the hand-off honestly",
  },
  {
    // Spec 014, quickstart.md §7. The `e2e/agents` rule above does not match
    // `agent-relay`, so without this line the compose spec would fall through
    // to the generic application-shell fallback and leave the A2A stories
    // outside their own epic in the aggregate report.
    match: /e2e\/agent-relay/,
    epic: "External agent relay",
    feature: "A2A wire contract",
    story: "Hand off to a real A2A agent end to end",
  },
  {
    match: /e2e\/auth/,
    epic: "End-to-end journeys",
    feature: "Authentication & access",
    story: "Invite signup and session routing",
  },
  {
    match: /claude-design-shell/,
    epic: "End-to-end journeys",
    feature: "Claude Design task shell",
    story: "Source-faithful task shell & brain dump",
  },
  {
    match: /e2e\/mobile/,
    epic: "End-to-end journeys",
    feature: "Responsive shell",
    story: "Mobile auth and navigation",
  },
  {
    match: /e2e\/security/,
    epic: "End-to-end journeys",
    feature: "Data isolation",
    story: "Cross-user access boundaries",
  },
  {
    match: /e2e\/tree-crud/,
    epic: "End-to-end journeys",
    feature: "Native task management",
    story: "Task lifecycle from browser",
  },
  {
    match: /e2e\/tree-relations/,
    epic: "End-to-end journeys",
    feature: "Native task organization",
    story: "Project and tag persistence",
  },
  {
    match: /e2e\/versioning/,
    epic: "End-to-end journeys",
    feature: "Optimistic concurrency",
    story: "Stale task write rejection",
  },
  {
    match: /e2e\/vnext/,
    epic: "End-to-end journeys",
    feature: "vNext operations",
    story: "Confirmation-gated proposals",
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
      await use();
    },
    { auto: true },
  ],
});

export { expect };
