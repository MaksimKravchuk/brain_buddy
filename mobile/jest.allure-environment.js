/**
 * The React Native test environment, wrapped so every Jest result is written as
 * Allure evidence.
 *
 * `allure-jest` ships ready-made `node` and `jsdom` environments, but neither is
 * usable here: the mobile suite must run inside React Native's own environment
 * (the one `jest-expo` selects), which sets up the RN globals the product code
 * and its native mocks expect. `allure-jest/factory` exists for exactly this —
 * it decorates an arbitrary base environment rather than replacing it, so the
 * RN setup is untouched and Allure is layered on top.
 *
 * Registered as `testEnvironment` in jest.config.js, which overrides the
 * preset's own value while keeping the same underlying base class.
 */
const { createJestEnvironment } = require("allure-jest/factory");
const ReactNativeEnvironment = require("@react-native/jest-preset/jest/react-native-env");

module.exports = createJestEnvironment(ReactNativeEnvironment);
