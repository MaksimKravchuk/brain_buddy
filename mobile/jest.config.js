module.exports = {
  preset: "jest-expo",
  testEnvironment: "allure-jest/node",
  testMatch: ["**/__tests__/**/*.(test|spec).(ts|tsx)"],
  setupFilesAfterEnv: ["<rootDir>/src/test/setup.ts"],
  moduleNameMapper: { "^@/(.*)$": "<rootDir>/src/$1" },
};
