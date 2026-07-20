import * as allure from "allure-js-commons";

export type AllureTaxonomy = {
  epic: string;
  feature: string;
  story: string;
  title: string;
  steps: readonly string[];
};

/**
 * Single metadata source for mobile Jest scenarios. The adapter deliberately
 * contains no request bodies, credentials, paths, or product content.
 */
export function taxonomy(
  values: AllureTaxonomy,
): AllureTaxonomy {
  if (!values.epic || !values.feature || !values.story || !values.title) {
    throw new Error("Allure taxonomy requires epic, feature, story, and title.");
  }
  if (values.steps.length === 0 || values.steps.some((step) => !step.trim())) {
    throw new Error("Allure taxonomy requires a named product step.");
  }
  return values;
}

export const mobileAllure = {
  auth: (title: string) => taxonomy({
    epic: "Mobile foundation",
    feature: "Secure session",
    story: "Native authentication",
    title,
    steps: ["Exercise the mobile-safe session boundary"],
  }),
  tasks: (title: string) => taxonomy({
    epic: "Mobile GTD workspace",
    feature: "Canonical tasks",
    story: "Mobile list and detail navigation",
    title,
    steps: ["Render canonical server task data"],
  }),
  contract: (title: string) => taxonomy({
    epic: "Mobile foundation",
    feature: "Generated API contract",
    story: "Explicit operation allowlist",
    title,
    steps: ["Filter the pinned OpenAPI snapshot to the mobile allowlist"],
  }),
};

export async function withAllure<T>(
  values: AllureTaxonomy,
  exercise: () => Promise<T>,
): Promise<T> {
  await allure.epic(values.epic);
  await allure.feature(values.feature);
  await allure.story(values.story);
  return allure.step(values.steps[0], exercise);
}
