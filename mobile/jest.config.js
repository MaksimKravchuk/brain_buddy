/** Unit tests only — the integration suite runs separately via `npm run integration`. */
module.exports = {
  preset: "jest-expo",
  testMatch: ["**/__tests__/**/*.test.ts", "**/__tests__/**/*.test.tsx"],
  testPathIgnorePatterns: ["/node_modules/", "/integration/"],
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
  clearMocks: true,
  // Opt-in via `--coverage` so the plain test run stays fast. Enumerated over src
  // so files no test imports still count against the total.
  collectCoverageFrom: ["src/**/*.{ts,tsx}", "!src/**/__tests__/**", "!src/test/**"],
  coverageReporters: ["json-summary", "lcov", "text"],
};
