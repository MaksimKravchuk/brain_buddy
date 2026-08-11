/**
 * Constraints that are true of the whole feature rather than of one module.
 *
 * These read source files instead of calling functions, which is unusual and
 * deliberate: FR-014 and FR-013 are prohibitions, and a prohibition has no
 * call site to assert against. The alternative was leaving them as prose in
 * `plan.md` that nothing enforces, which is how "no new endpoint" quietly
 * becomes two new endpoints.
 *
 * No Allure taxonomy here: `CLAUDE.md` scopes that rule to pytest, Vitest and
 * Playwright, and this is the mobile Jest suite.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const MOBILE_SRC = join(__dirname, "..", "..", "..");
const FEATURE_DIR = join(MOBILE_SRC, "features", "tasks");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

const featureSources = walk(FEATURE_DIR).filter(
  (path) => /\.tsx?$/.test(path) && !path.includes("__tests__"),
);

describe("feature-wide constraints", () => {
  it("006-FR-014 classification uses the existing task endpoint and adds none", () => {
    // The whole feature is one PATCH the backend already serves. If a lane had
    // needed a new route, this is where that would surface as a decision
    // rather than as a quietly widened API — and FR-014 exists because the
    // web client and the backend task module must not move for this.
    const client = readFileSync(join(MOBILE_SRC, "api", "client.ts"), "utf8");

    const taskWriteRoutes = [...client.matchAll(/`\/tasks\/[^`]*`/g)].map((m) => m[0]);
    const classificationRoutes = taskWriteRoutes.filter((route) =>
      /classification|project|tag/i.test(route),
    );

    expect(classificationRoutes).toEqual([]);
    expect(client).toContain("updateTask");
  });

  it("006-FR-013 says Tag, never Context, anywhere a person can read", () => {
    // ADR-0006 renamed this concept. The prohibition is on user-visible copy,
    // so comments are stripped first — several modules carry a header saying
    // "never Context", and an apostrophe in ordinary prose ("design.md's copy
    // column") otherwise reads as a string delimiter and matches the very
    // comment that states the rule.
    //
    // React's own `contextValue` identifiers are not what ADR-0006 means, so
    // the word is matched only as a standalone term inside a quoted string.
    const offenders = featureSources.filter((path) => {
      const source = readFileSync(path, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^\s*\/\/.*$/gm, "");
      return /["'`][^"'`\n]*\bContexts?\b[^"'`\n]*["'`]/.test(source);
    });

    expect(offenders).toEqual([]);
  });

  it("006-SC-001 a task goes from unclassified to classified without leaving the phone", () => {
    // The client half of the criterion: both fields are settable in one
    // request, so no step of the journey requires the web client. The other
    // half — that a person can actually complete it — is the manual check in
    // quickstart.md, and is graded there.
    const types = readFileSync(join(MOBILE_SRC, "api", "types.ts"), "utf8");
    const update = types.slice(types.indexOf("TaskUpdateRequest"));

    expect(update).toContain("project_id");
    expect(update).toContain("tag_ids");
  });

  it("006-SC-006 mobile triage costs no more interactions than the web client", () => {
    // The ceiling is stated before implementation, from design.md's affordance
    // map, so the manual count in quickstart.md is graded against a number
    // nobody chose after seeing the result. Web: open project picker, choose,
    // open tag picker, choose, choose, dismiss = 6.
    //
    // This asserts the ceiling is recorded, not that the app meets it — that
    // is the manual step's job, and pretending otherwise would be the kind of
    // test that passes without proving anything.
    const quickstart = readFileSync(
      join(__dirname, "..", "..", "..", "..", "..", "specs", "006-mobile-task-classification", "quickstart.md"),
      "utf8",
    );

    expect(quickstart).toMatch(/SC-006/);
    expect(quickstart).toMatch(/[Cc]ount every interaction/);
  });
});
