const expoConfig = require("eslint-config-expo/flat");

module.exports = [
  ...expoConfig,
  {
    ignores: [
      "node_modules/", ".expo/", "coverage/", "allure-results/",
      "src/components/", "src/constants/", "src/hooks/", "src/global.css",
    ],
  },
];
