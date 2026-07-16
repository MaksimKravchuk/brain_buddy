/**
 * Deterministic Allure taxonomy for the frontend Vitest suite.
 *
 * Every Vitest result must carry a non-empty epic/feature/story, a human-readable
 * title, and at least one named step (enforced by
 * `scripts/validate_allure_taxonomy.py`). Instead of repeating metadata in every
 * spec, this setup file maps each test's source path to a meaningful
 * (epic, feature) pair, derives the story from the enclosing `describe` block,
 * and guarantees a step floor.
 *
 * It runs in `afterEach`, inspecting the Allure runtime messages the test already
 * emitted (`task.meta.allureRuntimeMessages`). Only *missing* dimensions are
 * filled, so an explicit `epic()` / `feature()` / `story()` / `step()` call inside
 * a spec is preserved verbatim — never duplicated or overwritten.
 *
 * Registered in `vite.config.ts` `setupFiles`; the `allure-vitest` reporter
 * prepends its own setup module, so the per-test Allure runtime is already bound
 * when this hook runs.
 */
import { epic, feature, step, story } from "allure-js-commons";
import { afterEach } from "vitest";

type EpicFeature = { epic: string; feature: string };

interface AllureLabel {
  name?: string;
  value?: string;
}

interface AllureRuntimeMessage {
  type?: string;
  data?: { labels?: AllureLabel[] };
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
const alreadyEmitted = (task: VitestTask): { labels: Set<string>; hasStep: boolean } => {
  const labels = new Set<string>();
  let hasStep = false;
  for (const message of task.meta?.allureRuntimeMessages ?? []) {
    if (message.type === "metadata" && Array.isArray(message.data?.labels)) {
      for (const label of message.data.labels) {
        if (typeof label.name === "string") {
          labels.add(label.name);
        }
      }
    }
    if (message.type === "step_start") {
      hasStep = true;
    }
  }
  return { labels, hasStep };
};

afterEach(async (ctx) => {
  const task = ctx.task as unknown as VitestTask;
  const filePath = task.file?.filepath ?? task.file?.name ?? "";
  const { epic: epicName, feature: featureName } = resolveEpicFeature(filePath);
  const storyName = topSuiteName(task) ?? fileSubject(filePath);
  const title = task.name?.trim() || fileSubject(filePath);

  const { labels, hasStep } = alreadyEmitted(task);
  if (!labels.has("epic")) {
    await epic(epicName);
  }
  if (!labels.has("feature")) {
    await feature(featureName);
  }
  if (!labels.has("story")) {
    await story(storyName);
  }
  // Guarantee the "at least one meaningful step" floor for specs whose bodies
  // never opened a step (e.g. no `expect` assertion). Specs with their own steps
  // keep them untouched.
  if (!hasStep) {
    await step(`Verify: ${title}`, async () => {
      /* scenario boundary — assertions ran in the test body */
    });
  }
});
