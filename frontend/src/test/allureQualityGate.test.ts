// @ts-expect-error -- this Node-only CI-contract test intentionally sits outside
// the browser production type environment, which excludes Node ambient types.
import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";

const allure = "node_modules/.bin/allure";
const config = "../allurerc.mjs";
const fixtures = "../scripts/fixtures/allure-quality-gate";

describe("008-FR-005 aggregate quality-gate canary", () => {
  it("008-SC-001 passes clean results and rejects a failed result", () => {
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