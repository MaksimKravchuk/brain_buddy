/**
 * Deterministic Allure taxonomy for the mobile Jest suite.
 *
 * Every result must carry a non-empty epic/feature/story, a human-readable
 * title, and at least one meaningful step (enforced by
 * `scripts/validate_allure_taxonomy.py`). Rather than repeat metadata in 29
 * spec files, this hook maps each test's source path to an (epic, feature)
 * pair, derives the story from the enclosing `describe`, and emits
 * product-facing scenario/action/verify steps.
 *
 * Mirrors `frontend/src/test/allureTaxonomy.ts` so the aggregate report reads
 * as one taxonomy rather than two dialects. The step names are deliberately the
 * same shape: the validator treats a bare `Scenario:`/`Action:`/`Verify:` name
 * as an empty placeholder, so each step attaches its evidence — that is what
 * makes it count as meaningful rather than scaffolding.
 *
 * Registered in `jest.setup.js`. The per-test Allure runtime is bound by the
 * environment in `jest.allure-environment.js`, so it is already live in
 * `afterEach`.
 */
import { attachment, ContentType, epic, feature, step, story } from "allure-js-commons";

type EpicFeature = { epic: string; feature: string };

/**
 * First match wins, so narrower paths come before the directories that contain
 * them. Keyed on the test's own path, which is what Jest reports.
 */
const PATH_RULES: { match: RegExp; epic: string; feature: string }[] = [
  { match: /\/app\/brain-dump\//, epic: "Brain dump", feature: "Review & confirm" },
  { match: /\/braindump\//, epic: "Brain dump", feature: "Capture & upload protocol" },
  { match: /\/app\/task\//, epic: "Native GTD", feature: "Task detail" },
  { match: /\/features\/tasks\//, epic: "Native GTD", feature: "Task capture" },
  // Spec 014. These three must precede the broader `/lifecycle/`, `/api/` and
  // `/app/` rules below: first match wins, so `agentGuards.test.ts` would
  // otherwise be filed under "Native GTD / Lifecycle guards" and the SC-004 /
  // SC-005 agent suites would fall to the `Mobile / General behaviour`
  // fallback — neither of which names the capability under test.
  {
    match: /\/lifecycle\/__tests__\/agentGuards/,
    epic: "External agent relay",
    feature: "Hand-off lifecycle guards",
  },
  {
    match: /\/features\/agents\//,
    epic: "External agent relay",
    feature: "Agent screens",
  },
  { match: /\/agents\//, epic: "External agent relay", feature: "Agent state machine" },
  { match: /\/lifecycle\//, epic: "Native GTD", feature: "Lifecycle guards" },
  { match: /\/auth\//, epic: "Authentication", feature: "Session handling" },
  { match: /\/api\//, epic: "Mobile API client", feature: "Wire protocol" },
  { match: /\/components\//, epic: "Design system", feature: "UI primitives" },
  { match: /\/config\//, epic: "Mobile shell", feature: "Configuration" },
  { match: /\/utils\//, epic: "Mobile utilities", feature: "Helpers" },
  { match: /\/app\//, epic: "Mobile shell", feature: "Screens & navigation" },
];

const FALLBACK: EpicFeature = { epic: "Mobile", feature: "General behaviour" };

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

/** A readable subject for a spec file, used when a test has no `describe`. */
const fileSubject = (filePath: string): string => {
  const base = filePath.replace(/\\/g, "/").split("/").pop() ?? filePath;
  const clean = base
    .replace(/\.(test|spec)\.(ts|tsx)$/, "")
    .replace(/[-_.]/g, " ")
    .trim();
  return titleCase(clean) || "Mobile behaviour";
};

/**
 * Jest joins the suite chain and the test name with " > ". The first segment is
 * the outermost `describe`; a test declared at the top level of a file has none,
 * in which case the file itself names the story.
 */
const splitTestName = (
  currentTestName: string | undefined,
  filePath: string,
): { story: string; title: string } => {
  const segments = (currentTestName ?? "")
    .split(" > ")
    .map((segment) => segment.trim())
    .filter(Boolean);
  if (segments.length === 0) {
    return { story: fileSubject(filePath), title: fileSubject(filePath) };
  }
  const title = segments[segments.length - 1];
  const storyName = segments.length > 1 ? segments[0] : fileSubject(filePath);
  return { story: storyName, title };
};

const stepEvidence = (
  filePath: string,
  epicName: string,
  featureName: string,
  storyName: string,
  title: string,
): string =>
  [
    `Source: ${filePath || "unknown Jest source"}`,
    `Epic: ${epicName}`,
    `Feature: ${featureName}`,
    `Story: ${storyName}`,
    `Test: ${title}`,
    "Result: the Jest test body completed before this taxonomy evidence was emitted.",
  ].join("\n");

type TestBody = jest.ProvidesCallback;
type TestFn = jest.It;

/**
 * Run a test body inside a named Allure step.
 *
 * Steps follow the *executing* scope, and during a `beforeEach` that scope is
 * the fixture, not the test — labels set from a hook land on the result, but
 * steps do not. The only scope that belongs to the test is its own body, so the
 * body is what gets wrapped. The step therefore carries the test's real
 * duration and nests any step the spec opens itself.
 *
 * Evidence is attached inside the step because a zero-duration step with no
 * children and no evidence is rejected as a no-op, and a fast unit test can
 * legitimately run in 0ms.
 */
const wrapBody = (
  body: TestBody | undefined,
  /**
   * `it.each` bodies take the table row as parameters, so arity says nothing
   * about done-callback style there. For a plain `it`, a declared parameter IS
   * the done callback: wrapping would return a promise alongside it, which Jest
   * rejects outright, so such a body is left alone.
   */
  { fromEach }: { fromEach: boolean } = { fromEach: false },
): TestBody | undefined => {
  if (typeof body !== "function" || (!fromEach && body.length > 0)) {
    return body;
  }
  const wrapped = async function wrapped(this: unknown, ...args: unknown[]) {
    const state = expect.getState();
    const filePath = state.testPath ?? "";
    const { epic: epicName, feature: featureName } = resolveEpicFeature(filePath);
    const { story: storyName, title } = splitTestName(state.currentTestName, filePath);
    const evidence = stepEvidence(filePath, epicName, featureName, storyName, title);

    return step(`Action: exercise ${title}`, async () => {
      await attachment("Taxonomy evidence", evidence, ContentType.TEXT);
      return (body as (...callArgs: unknown[]) => unknown).apply(this, args);
    });
  };
  // Jest reads arity to decide how many table values to pass and whether a
  // trailing done callback was requested, so the wrapper must declare the same.
  Object.defineProperty(wrapped, "length", { value: body.length });
  return wrapped as TestBody;
};

/** Re-expose a Jest test global with every body routed through `wrapBody`. */
const wrapTestGlobal = (original: TestFn): TestFn => {
  const wrapped = ((name: string, body?: TestBody, timeout?: number) =>
    original(name, wrapBody(body), timeout)) as TestFn;

  // `it.each(table)` returns the real declarer; wrap the body it receives too.
  wrapped.each = ((...tableArgs: unknown[]) => {
    const declare = (original.each as (...a: unknown[]) => unknown)(...tableArgs);
    return (name: string, body?: TestBody, timeout?: number) =>
      (declare as (...a: unknown[]) => unknown)(
        name,
        wrapBody(body, { fromEach: true }),
        timeout,
      );
  }) as TestFn["each"];

  // Nothing in this suite uses these, but a future spec must not silently lose
  // its declarer just because this module forgot to carry it over.
  for (const key of ["only", "skip", "todo", "concurrent", "failing"] as const) {
    if (key in original) {
      (wrapped as unknown as Record<string, unknown>)[key] = (
        original as unknown as Record<string, unknown>
      )[key];
    }
  }
  return wrapped;
};

/**
 * Registered from `jest.setup.js`.
 *
 * Labels are set in `beforeEach` (they do bind to the result from a hook); the
 * step comes from wrapping the body, for the scope reason described above.
 */
export function registerAllureTaxonomy(): void {
  global.it = wrapTestGlobal(global.it);
  global.test = wrapTestGlobal(global.test);

  beforeEach(async () => {
    const state = expect.getState();
    const filePath = state.testPath ?? "";
    const { epic: epicName, feature: featureName } = resolveEpicFeature(filePath);
    const { story: storyName } = splitTestName(state.currentTestName, filePath);

    await epic(epicName);
    await feature(featureName);
    await story(storyName);
  });
}
