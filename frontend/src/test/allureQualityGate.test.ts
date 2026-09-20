// @ts-expect-error -- this Node-only CI-contract test intentionally sits outside
// the browser production type environment, which excludes Node ambient types.
import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";

const allure = "node_modules/.bin/allure";
const config = "../allurerc.mjs";
const fixtures = "../scripts/fixtures/allure-quality-gate";

// Stryker copies only `frontend/` into its sandbox (`.stryker-tmp/sandbox-*/`),
// so under mutation testing `..` is `.stryker-tmp/` and neither `../allurerc.mjs`
// nor the fixtures exist there; the initial test run failed on this test alone
// and the nightly campaign never got past its dry run. The canary exercises
// nothing in `stryker.config.json`'s `mutate` list, so it kills no mutants and
// skipping it there loses no evidence. Same switch as `vite.config.ts`.
// @ts-expect-error -- `process` is the same Node-only exception as the import above.
const underMutationTesting = process.env.STRYKER_MUTATOR_WORKER !== undefined;

describe("008-FR-005 aggregate quality-gate canary", () => {
  it.skipIf(underMutationTesting)("008-SC-001 passes clean results and rejects a failed result", () => {
    const clean = spawnSync(
      allure,
      ["quality-gate", `${fixtures}/passing`, "--config", config],
      { encoding: "utf8" },
    );
    const dirty = spawnSync(
      allure,
      ["quality-gate", `${fixtures}/failing`, "--config", config],
      { encoding: "utf8" },
    );

    expect(clean.error).toBeUndefined();
    expect(clean.status).toBe(0);
    expect(dirty.error).toBeUndefined();
    expect(dirty.status).not.toBe(0);
  });
});