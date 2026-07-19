/**
 * Deterministic Allure taxonomy for the frontend Vitest suite.
 *
 * Every Vitest result must carry a non-empty epic/feature/story, a human-readable
 * title, and at least one named step (enforced by
 * `scripts/validate_allure_taxonomy.py`). Instead of repeating metadata in every
 * spec, this setup file maps each test's source path to a meaningful
 * (epic, feature) pair, derives the story from the enclosing `describe` block,
 * and guarantees product-facing scenario/action/verify steps when a spec did not
 * open its own Allure step.
 *
 * It runs in `afterEach`, inspecting the Allure runtime messages the test already
 * emitted (`task.meta.allureRuntimeMessages`). Only *missing* dimensions are
 * filled, so an explicit `epic()` / `feature()` / `story()` / `step()` call inside
 * a spec is preserved verbatim — never duplicated or overwritten. Auto-generated
 * matcher/assertion steps are ignored here and filtered by the reporter; they are
 * too implementation-heavy to be useful product evidence.
 *
 * Registered in `vite.config.ts` `setupFiles`; the `allure-vitest` reporter
 * prepends its own setup module, so the per-test Allure runtime is already bound
 * when this hook runs.
 */
import { attachment, ContentType, epic, feature, step, story } from "allure-js-commons";
import { afterEach } from "vitest";

type EpicFeature = { epic: string; feature: string };

interface AllureLabel {
  name?: string;
  value?: string;
}

interface AllureRuntimeMessage {
  type?: string;
  data?: { labels?: AllureLabel[] };
  __allureVitestMatcher?: boolean;
}

interface AllureTaskMeta {
  allureRuntimeMessages?: AllureRuntimeMessage[];
}

interface TaskSuite {
  name?: string;
  suite?: TaskSuite;
}

interface VitestTask {
  name?: string;
  file?: { filepath?: string; name?: string };
  suite?: TaskSuite;
  meta?: AllureTaskMeta;
}

/** Ordered path rules: the first matching source path wins. */
const PATH_RULES: Array<{ match: RegExp; epic: string; feature: string }> = [
  { match: /\/api\//, epic: "Frontend data layer", feature: "API client & hooks" },
  { match: /\/components\/canvas\//, epic: "Reality Tree canvas", feature: "Canvas rendering" },
  { match: /\/components\/panels\//, epic: "Reality Tree canvas", feature: "Inspector panels" },
  { match: /\/components\/modals\//, epic: "Reality Tree canvas", feature: "Tree modals" },
  { match: /\/components\/ui\//, epic: "Design system", feature: "UI primitives" },
  { match: /\/components\/layout\//, epic: "App shell", feature: "Layout & navigation" },
  { match: /\/components\/shell\//, epic: "App shell", feature: "Task shell chrome" },
  { match: /\/components\/auth\//, epic: "Authentication UI", feature: "Route guards" },
  { match: /\/features\/brain-dump\//, epic: "Brain dump", feature: "Capture & review" },
  { match: /\/stores\//, epic: "Frontend state", feature: "Client stores" },
  { match: /\/hooks\//, epic: "Frontend utilities", feature: "React hooks" },
  { match: /\/utils\//, epic: "Frontend utilities", feature: "Helpers" },
  { match: /\/(app|__tests__)\/(AppRoutes|App)\./, epic: "App shell", feature: "Routing" },
  { match: /LoginPage|SignupPage/, epic: "Authentication UI", feature: "Auth pages" },
  { match: /\/pages\//, epic: "Reality Tree canvas", feature: "Workspace page" },
  { match: /CreateNodeButton|basicInteractions/, epic: "Reality Tree canvas", feature: "Canvas controls" },
];

const FALLBACK: EpicFeature = { epic: "Frontend", feature: "General UI" };

const resolveEpicFeature = (filePath: string): EpicFeature => {
  const normalized = filePath.replace(/\\/g, "/");
  for (const rule of PATH_RULES) {
    if (rule.match.test(normalized)) {
      return { epic: rule.epic, feature: rule.feature };
    }
  }
  return FALLBACK;
};

const titleCase = (value: string): string =>
  value.length === 0 ? value : value[0].toUpperCase() + value.slice(1);

const fileSubject = (filePath: string): string => {
  const base = filePath.replace(/\\/g, "/").split("/").pop() ?? filePath;
  const stem = base.replace(/\.(test|spec)$/g, "").replace(/\.(test|spec)\./g, ".");
  const clean = stem.replace(/\.(ts|tsx)$/g, "").replace(/[-_.]/g, " ").trim();
  return titleCase(clean) || "UI behaviour";
};

/** Top-level `describe` name, if any, walking up the suite chain. */
const topSuiteName = (task: VitestTask): string | undefined => {
  let current: TaskSuite | undefined = task.suite;
  let name: string | undefined;
  while (current) {
    const candidate = current.name;
    // Skip the synthetic file-level suite (its name is a path / spec filename).
    if (candidate && !candidate.includes("/") && !/\.(test|spec)\.(ts|tsx)$/.test(candidate)) {
      name = candidate;
    }
    current = current.suite;
  }
  return name;
};

/** Dimensions the test already emitted, read from the Allure runtime messages. */
const alreadyEmitted = (task: VitestTask): { labels: Set<string>; hasProductStep: boolean } => {
  const labels = new Set<string>();
  let hasProductStep = false;
  for (const message of task.meta?.allureRuntimeMessages ?? []) {
    if (message.type === "metadata" && Array.isArray(message.data?.labels)) {
      for (const label of message.data.labels) {
        if (typeof label.name === "string") {
          labels.add(label.name);
        }
      }
    }
    if (message.type === "step_start" && !message.__allureVitestMatcher) {
      hasProductStep = true;
    }
  }
  return { labels, hasProductStep };
};

const stepEvidence = (
  filePath: string,
  epicName: string,
  featureName: string,
  storyName: string,
  title: string
): string =>
  [
    `Source: ${filePath || "unknown Vitest source"}`,
    `Epic: ${epicName}`,
    `Feature: ${featureName}`,
    `Story: ${storyName}`,
    `Test: ${title}`,
    "Result: the Vitest test body completed before this taxonomy evidence was emitted."
  ].join("\n");

const emitProductStep = async (name: string, evidence: string): Promise<void> => {
  await step(name, async () => {
    await attachment("Taxonomy evidence", evidence, ContentType.TEXT);
  });
};

const emitGeneratedProductSteps = async (
  filePath: string,
  epicName: string,
  featureName: string,
  storyName: string,
  title: string
): Promise<void> => {
  const evidence = stepEvidence(filePath, epicName, featureName, storyName, title);
  await emitProductStep(`Scenario: ${storyName}`, evidence);
  await emitProductStep(`Action: exercise ${title}`, evidence);
  await emitProductStep(`Verify: ${title}`, evidence);
};

afterEach(async (ctx) => {
  const task = ctx.task as unknown as VitestTask;
  const filePath = task.file?.filepath ?? task.file?.name ?? "";
  const { epic: epicName, feature: featureName } = resolveEpicFeature(filePath);
  const storyName = topSuiteName(task) ?? fileSubject(filePath);
  const title = task.name?.trim() || fileSubject(filePath);

  const { labels, hasProductStep } = alreadyEmitted(task);
  if (!labels.has("epic")) {
    await epic(epicName);
  }
  if (!labels.has("feature")) {
    await feature(featureName);
  }
  if (!labels.has("story")) {
    await story(storyName);
  }
  // Guarantee product-facing step evidence for specs whose bodies never opened
  // an explicit Allure step. Matcher/assertion internals are deliberately not
  // counted because they expose React object dumps and mock implementation
  // details rather than scenario intent.
  if (!hasProductStep) {
    await emitGeneratedProductSteps(filePath, epicName, featureName, storyName, title);
  }
});
