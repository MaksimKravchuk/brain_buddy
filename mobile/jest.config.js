/** Unit tests only — the integration suite runs separately via `npm run integration`. */
module.exports = {
  preset: "jest-expo",
  testMatch: ["**/__tests__/**/*.test.ts", "**/__tests__/**/*.test.tsx"],
  testPathIgnorePatterns: ["/node_modules/", "/integration/"],
  clearMocks: true,
};
