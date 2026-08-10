/** CommonJS because the package is not `"type": "module"` — unlike frontend/eslint.config.js. */
const { defineConfig } = require("eslint/config");
const expoConfig = require("eslint-config-expo/flat");

module.exports = defineConfig([
  {
    ignores: ["coverage", "dist", ".expo", "android", "ios"]
  },
  ...expoConfig,
  {
    // Two React Compiler-era rules from eslint-config-expo 57 that the existing
    // code does not satisfy. Every other rule is enforced from day one; these
    // are deferred deliberately rather than by turning the linter down.
    //
    // react-hooks/refs (16 hits) is one idiom repeated:
    // `useRef(new Animated.Value(0)).current` read during render, which is how
    // React Native animation is written nearly everywhere. Satisfying it means
    // restructuring animation setup across the component tree, which needs a
    // device to validate.
    //
    // react-hooks/set-state-in-effect (4 hits) is real cascading-render
    // behaviour and worth fixing, also in product code rather than here.
    //
    // Turn these back on once those are addressed; do not add to this list.
    files: ["**/*.{ts,tsx}"],
    rules: {
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "off"
    },
    settings: {
      // eslint-config-expo's core config enables the tsconfig resolver, then its
      // own top-level object replaces `import/resolver` wholesale with a node-only
      // one. Restore it here or every `@/…` import reports import/no-unresolved.
      "import/resolver": {
        typescript: true,
        node: { extensions: [".js", ".jsx", ".ts", ".tsx", ".json"] }
      }
    }
  }
]);
