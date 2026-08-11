/** Unit tests only — the integration suite runs separately via `npm run integration`. */
module.exports = {
  preset: "jest-expo",
  // React Native's own environment, wrapped so every result lands in
  // allure-results/. See jest.allure-environment.js for why the stock
  // allure-jest environments cannot be used here.
  testEnvironment: "<rootDir>/jest.allure-environment.js",
  // Plain relative path on purpose: Jest does NOT interpolate <rootDir> inside
  // testEnvironmentOptions, and a token here is written out verbatim -- it
  // silently produced a directory literally named "<rootDir>". Resolved against
  // the working directory, which is mobile/ for every documented entry point.
  testEnvironmentOptions: { resultsDir: "allure-results" },
  testMatch: ["**/__tests__/**/*.test.ts", "**/__tests__/**/*.test.tsx"],
  testPathIgnorePatterns: ["/node_modules/", "/integration/"],
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
  clearMocks: true,
  // Jest's 5s default is too tight for the first test in a spec that mounts a
  // whole screen: on a cold transform cache that test absorbs the one-time
  // Babel/Metro transform of the React Native module graph. Measured on a
  // cleared cache, "shows a load failure with a retry that refetches" took
  // 5843ms while every other test in the same file took 5-42ms -- a one-time
  // cost, not product slowness. CI never restores a Jest cache, so it always
  // runs in exactly that condition and both retry specs were one slow runner
  // away from failing. A 20s ceiling absorbs the transform while still failing
  // a genuine hang.
  testTimeout: 20_000,
  // Opt-in via `--coverage` so the plain test run stays fast. Enumerated over src
  // so files no test imports still count against the total.
  collectCoverageFrom: ["src/**/*.{ts,tsx}", "!src/**/__tests__/**", "!src/test/**"],
  coverageReporters: ["json-summary", "lcov", "text"],
};
