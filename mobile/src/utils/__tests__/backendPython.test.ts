import path from "node:path";

import { resolveBackendPython } from "../../../integration/backend";

describe("resolveBackendPython", () => {
  const backendDir = path.join("repo", "backend");
  const venvPython = path.join(backendDir, ".venv", "bin", "python");

  it("uses an explicit executable override", () => {
    expect(resolveBackendPython(backendDir, "/ci/python", () => false)).toBe("/ci/python");
  });

  it("uses the repository virtualenv when it exists", () => {
    expect(resolveBackendPython(backendDir, undefined, (candidate) => candidate === venvPython)).toBe(
      venvPython,
    );
  });

  it("falls back to the Python on PATH when CI installed dependencies globally", () => {
    expect(resolveBackendPython(backendDir, undefined, () => false)).toBe("python3");
  });
});